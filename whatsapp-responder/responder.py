"""Respondedor automático de WhatsApp.

Dos caminos, deliberadamente separados:

  Terceros  ->  texto fijo de config.toml. No pasa por ningún modelo, así que
                nadie puede manipular la respuesta con lo que escriba.
  El dueño  ->  conversación con Claude, con herramientas sobre su WhatsApp.

Arranca con:  make responder
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
import tomllib
from datetime import datetime

import agent
import voice
import wa
from state import State

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.toml")
AUDIO_OUT_DIR = os.path.join(BASE_DIR, "state", "outgoing-audio")

log = logging.getLogger("responder")

_running = True


def _stop(signum, _frame):
    global _running
    log.info("Señal %s recibida, cerrando limpiamente...", signum)
    _running = False


def load_config(path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        raise SystemExit(
            f"No existe {path}.\n"
            "Copia config.example.toml a config.toml y rellena tu número."
        )
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)

    phone = str(cfg.get("owner", {}).get("phone", "")).strip()
    if not phone or not phone.isdigit():
        raise SystemExit(
            "config.toml: owner.phone debe ser tu número con prefijo de país, "
            "solo dígitos (ej. 584121234567)."
        )
    if not cfg.get("greeting", {}).get("text", "").strip():
        raise SystemExit("config.toml: greeting.text no puede estar vacío.")

    # El error mas facil de cometer: poner en owner.phone el numero del
    # asistente en vez del propio. Con esa config el dueño nunca se reconoce
    # (sus mensajes llegan desde SU numero, no desde el del bridge), asi que
    # el asistente le contesta el saludo de desconocido o, pasado el
    # enfriamiento, se queda callado. Se detecta y se para aqui.
    linked = wa.linked_number()
    if linked and linked == phone:
        raise SystemExit(
            f"config.toml: owner.phone es {phone}, que es el número al que está\n"
            f"vinculado el bridge — o sea, el número DEL ASISTENTE.\n\n"
            f"owner.phone tiene que ser TU número, el del teléfono desde el que\n"
            f"le escribes. Son dos números distintos."
        )
    return cfg


def is_owner(msg: wa.Message, owner_phone: str) -> bool:
    """El dueño escribiendo desde su móvil. Se compara solo el número: WhatsApp
    añade sufijos de dispositivo (:12) y servidores distintos según el caso."""
    return msg.sender_phone == owner_phone


def describe_incoming(msg: wa.Message, cfg: dict) -> str:
    """Texto del mensaje. Si es una nota de voz, la transcribe."""
    if msg.media_type in voice.AUDIO_MEDIA_TYPES:
        if not cfg.get("voice", {}).get("transcribe", True):
            return "[nota de voz recibida — transcripción desactivada]"
        path = wa.download_media(msg.id, msg.chat_jid)
        if not path:
            return "[nota de voz recibida — no se pudo descargar]"
        try:
            text = voice.transcribe(
                path,
                model_size=cfg.get("voice", {}).get("whisper_model", "base"),
                language=cfg.get("voice", {}).get("language", "es"),
            )
        except voice.VoiceUnavailable as e:
            log.warning("Transcripción no disponible: %s", e)
            return "[nota de voz recibida — transcripción no disponible]"
        return text or "[nota de voz vacía o inaudible]"
    return msg.content


def reply_to_owner(msg: wa.Message, cfg: dict, state: State) -> None:
    text = describe_incoming(msg, cfg)
    if not text.strip():
        return

    log.info("Dueño: %s", text[:120])
    try:
        answer = agent.reply(
            text,
            history_turns=cfg["assistant"].get("history_turns", 40),
            model=cfg["assistant"].get("model", "claude-opus-5"),
        )
    except Exception as e:  # la API puede fallar; el bucle no debe morir
        log.exception("Fallo hablando con Claude")
        answer = f"No pude procesar eso: {e}"

    # Si te llegó una nota de voz y la voz está activada, se responde en voz.
    voice_cfg = cfg.get("voice", {})
    wants_voice = (
        voice_cfg.get("reply_with_voice", False)
        and msg.media_type in voice.AUDIO_MEDIA_TYPES
    )
    if wants_voice:
        try:
            os.makedirs(AUDIO_OUT_DIR, exist_ok=True)
            out = os.path.join(AUDIO_OUT_DIR, f"{msg.id}.ogg")
            voice.synthesize(answer, out, piper_voice=voice_cfg.get("piper_voice"))
            ok, detail = wa.send_audio(msg.chat_jid, out)
            if ok:
                state.record_reply(msg.chat_jid)
                log.info("Respondido en voz")
                return
            log.warning("No se pudo enviar la nota de voz (%s), envío texto", detail)
        except voice.VoiceUnavailable as e:
            log.warning("Voz no disponible (%s), envío texto", e)

    ok, detail = wa.send_message(msg.chat_jid, answer)
    if ok:
        state.record_reply(msg.chat_jid)
    else:
        log.error("No se pudo responder al dueño: %s", detail)


def greet_stranger(msg: wa.Message, cfg: dict, state: State, owner_phone: str) -> None:
    greeting = cfg["greeting"]
    if not state.should_greet(msg.chat_jid, greeting.get("cooldown_hours", 12)):
        return

    ok, detail = wa.send_message(msg.chat_jid, greeting["text"])
    if not ok:
        log.error("No se pudo saludar a %s: %s", msg.chat_jid, detail)
        return

    state.mark_greeted(msg.chat_jid)
    state.record_reply(msg.chat_jid)
    log.info("Saludo enviado a %s", msg.chat_jid)

    if greeting.get("notify_owner", True):
        quien = msg.sender_phone or msg.chat_jid
        dijo = describe_incoming(msg, cfg)[:400]
        aviso = f"Le ha escrito {quien}:\n\n{dijo}\n\nYa le envié el saludo."
        wa.send_message(owner_phone, aviso)


def handle(msg: wa.Message, cfg: dict, state: State, owner_phone: str) -> None:
    limits = cfg.get("limits", {})
    log.info("Entrante de %s (chat %s): %s",
             msg.sender_phone or "?", msg.chat_jid, (msg.content or "")[:80])

    if msg.is_group and not limits.get("reply_in_groups", False):
        log.info("  -> es un grupo, lo ignoro (limits.reply_in_groups = false)")
        return

    cap = limits.get("max_replies_per_contact_per_hour", 6)
    if state.replies_last_hour(msg.chat_jid) >= cap:
        log.warning("  -> tope horario alcanzado (%d/h), no respondo", cap)
        return

    if is_owner(msg, owner_phone):
        log.info("  -> es el dueño, va al modelo")
        reply_to_owner(msg, cfg, state)
    else:
        log.info("  -> es un tercero (%s != %s), saludo fijo",
                 msg.sender_phone, owner_phone)
        greet_stranger(msg, cfg, state, owner_phone)


def run(cfg: dict, once: bool = False, replay_minutes: int | None = None) -> int:
    owner_phone = str(cfg["owner"]["phone"]).strip()
    state = State()
    agent.configure(
        state,
        owner_name=cfg["owner"].get("name", "el jefe"),
        assistant_name=cfg["assistant"].get("name", "Aquiles"),
    )

    watermark = state.get_watermark()
    if replay_minutes:
        from datetime import timedelta
        watermark = datetime.now() - timedelta(minutes=replay_minutes)
        state.set_watermark(watermark)
        log.info("Reproduciendo los últimos %d minutos desde %s",
                 replay_minutes, watermark)
    elif watermark is None:
        # Primer arranque: solo desde ahora. Responder al historial entero
        # sería enviar cientos de saludos a gente que escribió hace meses.
        watermark = wa.latest_timestamp()
        state.set_watermark(watermark)
        log.info("Primer arranque: atiendo mensajes posteriores a %s", watermark)

    poll = cfg.get("limits", {}).get("poll_seconds", 3)
    log.info("Escuchando. Dueño: %s. Ctrl-C para parar.", owner_phone)

    while _running:
        try:
            msgs = wa.fetch_incoming_since(watermark)
        except wa.BridgeUnavailable as e:
            log.error("%s", e)
            if once:
                return 1
            time.sleep(5)
            continue
        except Exception:
            log.exception("Error leyendo la base de mensajes")
            time.sleep(5)
            continue

        for m in msgs:
            try:
                handle(m, cfg, state, owner_phone)
            except Exception:
                log.exception("Error atendiendo el mensaje %s", m.id)
            # Se avanza la marca aunque falle: reintentar en bucle un mensaje
            # que siempre falla dejaría al asistente atascado para siempre.
            watermark = max(watermark, m.timestamp)
            state.set_watermark(watermark)

        if once:
            break
        time.sleep(poll)

    state.close()
    log.info("Parado.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Respondedor automático de WhatsApp")
    ap.add_argument("--once", action="store_true",
                    help="Procesa lo pendiente y sale (para pruebas)")
    ap.add_argument("--replay-minutes", type=int, metavar="N",
                    help="Retrocede la marca de agua N minutos y reprocesa "
                         "esos mensajes (para probar sin escribir de nuevo)")
    ap.add_argument("--check", action="store_true",
                    help="Valida la configuración y el entorno, sin responder nada")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    cfg = load_config()

    if args.check:
        print("Configuración válida.")
        linked = wa.linked_number()
        if linked:
            print(f"  Asistente:  {linked}  (número vinculado al bridge)")
        else:
            print("  Asistente:  SIN VINCULAR — ejecuta 'make bridge' primero")
        print(f"  Dueño:      {cfg['owner']['phone']} ({cfg['owner'].get('name')})")
        print(f"  Modelo:     {cfg['assistant'].get('name')} / {cfg['assistant'].get('model')}")
        print(f"  Saludo:     {cfg['greeting']['text'][:60]}...")
        print(f"  API key:    {'presente' if os.environ.get('ANTHROPIC_API_KEY') else 'AUSENTE (exporta ANTHROPIC_API_KEY)'}")
        print("  Voz:")
        for k, v in voice.diagnose().items():
            print(f"    {'sí' if v else 'no'}  {k}")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "ANTHROPIC_API_KEY no está definida: el saludo a terceros funcionará, "
            "pero la conversación contigo fallará."
        )

    return run(cfg, once=args.once, replay_minutes=args.replay_minutes)


if __name__ == "__main__":
    sys.exit(main())
