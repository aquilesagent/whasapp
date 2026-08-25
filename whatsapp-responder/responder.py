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
import public_agent
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


ENV_FILES = (
    os.path.expanduser("~/.config/aquiles/env"),
    os.path.join(BASE_DIR, ".env"),
)


def load_env_file() -> str | None:
    """Carga ANTHROPIC_API_KEY de disco si no está ya en el entorno.

    Sin esto, que funcione depende de si la variable llegó a *esta* terminal
    concreta — y no llega si se editó .bashrc y no se reabrió la shell, o si
    lo arranca un servicio. Leer el fichero directamente quita ese paso de
    en medio.

    Tolera las dos formas que se escriben en la práctica:
        ANTHROPIC_API_KEY=sk-ant-...
        export ANTHROPIC_API_KEY="sk-ant-..."
    La primera es la única que acepta systemd; la segunda es la que sale al
    copiar de una guía. Aquí valen ambas.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None

    for path in ENV_FILES:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            name, _, value = line.partition("=")
            if name.strip() != "ANTHROPIC_API_KEY":
                continue
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ["ANTHROPIC_API_KEY"] = value
                return path
    return None


def looks_like_placeholder(key: str) -> bool:
    """Detecta que se ha copiado el ejemplo de la documentacion en vez de la
    clave real.

    Pasa mas de lo que parece: el ejemplo se escribe `sk-ant-...` y se pega
    tal cual. La variable queda definida, asi que ninguna comprobacion de
    "¿existe?" lo detecta, y el fallo aparece mucho despues como un 401 raro.
    """
    k = key.strip()
    if not k:
        return False
    if k.endswith("...") or "…" in k:
        return True
    if not k.startswith("sk-ant-"):
        return True
    # Las de verdad rondan los 100 caracteres; nada corto es real.
    return len(k) < 40


def is_owner(msg: wa.Message, owner_phone: str) -> bool:
    """El dueño escribiendo desde su móvil.

    Se compara solo el número, porque WhatsApp añade sufijos de dispositivo
    (`:12`) y usa servidores distintos según el caso.

    Y si el remitente llega como LID —un identificador opaco que WhatsApp usa
    cada vez más en lugar del número— hay que traducirlo antes de comparar. Sin
    eso el dueño no se reconoce nunca: sus mensajes llegan como `67495…@lid`,
    que no se parece en nada a su número, y acaba recibiendo el saludo de
    desconocidos en su propia conversación.
    """
    if msg.sender_phone == owner_phone:
        return True
    if msg.is_lid:
        return wa.phone_for_lid(msg.sender) == owner_phone
    return False


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
            msg.chat_jid,
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


def attend_stranger(msg: wa.Message, cfg: dict, state: State,
                    owner_phone: str) -> None:
    """Atiende a un tercero.

    El primer contacto recibe el saludo literal de config.toml — son las
    palabras del dueño y no las reescribe ningún modelo. A partir de ahí, si
    [public] está activo, conversa; si no, se queda en el saludo.
    """
    greeting = cfg["greeting"]
    primera_vez = state.should_greet(msg.chat_jid,
                                     greeting.get("cooldown_hours", 12))

    if primera_vez:
        ok, detail = wa.send_message(msg.chat_jid, greeting["text"])
        if not ok:
            log.error("  -> no se pudo saludar: %s", detail)
            return
        state.mark_greeted(msg.chat_jid)
        state.record_reply(msg.chat_jid)
        # El saludo entra en su hilo para que la conversación siga con
        # coherencia: el modelo debe saber que ya se presentó.
        state.append_turn(msg.chat_jid, "user", describe_incoming(msg, cfg))
        state.append_turn(msg.chat_jid, "assistant", greeting["text"])
        log.info("  -> primer contacto, saludo enviado")

        if greeting.get("notify_owner", True):
            # Un LID crudo no le dice nada a nadie; se traduce si se puede.
            quien = (wa.phone_for_lid(msg.sender) if msg.is_lid else None) \
                or msg.sender_phone or msg.chat_jid
            dijo = describe_incoming(msg, cfg)[:400]
            wa.send_message(
                owner_phone,
                f"Le ha escrito {quien}:\n\n{dijo}\n\nYa le envié el saludo.",
            )
        return

    if not cfg.get("public", {}).get("enabled", False):
        log.info("  -> ya saludado y [public] desactivado, no respondo")
        return

    text = describe_incoming(msg, cfg)
    if not text.strip():
        return

    try:
        answer = public_agent.reply(
            msg.chat_jid,
            msg.sender_phone,
            text,
            history_turns=cfg["public"].get("history_turns", 20),
            model=cfg["public"].get(
                "model", cfg["assistant"].get("model", "claude-opus-5")),
        )
    except Exception:
        log.exception("  -> fallo atendiendo al tercero")
        # Nunca se filtra el error a un desconocido: no tiene por qué saber
        # qué hay detrás ni qué ha fallado.
        answer = ("Disculpe, ahora mismo no puedo atenderle bien. "
                  "Le paso el mensaje al Sr. y le responderá.")

    ok, detail = wa.send_message(msg.chat_jid, answer)
    if ok:
        state.record_reply(msg.chat_jid)
        log.info("  -> atendido por el agente público")
    else:
        log.error("  -> no se pudo responder: %s", detail)


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
        log.info("  -> es un tercero (%s != %s)", msg.sender_phone, owner_phone)
        attend_stranger(msg, cfg, state, owner_phone)


def run(cfg: dict, once: bool = False, replay_minutes: int | None = None) -> int:
    owner_phone = str(cfg["owner"]["phone"]).strip()
    state = State()
    agent.configure(
        state,
        owner_name=cfg["owner"].get("name", "el jefe"),
        assistant_name=cfg["assistant"].get("name", "Aquiles"),
    )
    public_agent.configure(
        state,
        owner_phone=owner_phone,
        owner_name=cfg["owner"].get("name", "el jefe"),
        assistant_name=cfg["assistant"].get("name", "Aquiles"),
        knowledge=cfg.get("public", {}).get("knowledge", ""),
    )
    if cfg.get("public", {}).get("enabled", False):
        log.info("Agente público ACTIVO: contesta a cualquiera (herramientas: %s)",
                 ", ".join(t.name for t in public_agent.TOOLS))
    else:
        log.info("Agente público desactivado: los terceros solo reciben el saludo")

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

    from_file = load_env_file()
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
        pub = cfg.get("public", {})
        if pub.get("enabled", False):
            saber = len(pub.get("knowledge", "").strip())
            print(f"  Terceros:   ATENDIDOS por el modelo "
                  f"({saber} caracteres de conocimiento)")
            print(f"              herramientas: "
                  f"{', '.join(t.name for t in public_agent.TOOLS)}")
            if saber < 50:
                print("              ! [public.knowledge] casi vacío — "
                      "Aquiles apenas sabrá qué contar")
        else:
            print("  Terceros:   solo saludo fijo ([public].enabled = false)")
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key and looks_like_placeholder(key):
            print(f"  API key:    NO ES UNA CLAVE — es el marcador '{key}'")
            print("              Copiaste el ejemplo literal. Pon la clave de")
            print("              verdad, la larga que empieza por sk-ant-api")
        elif key:
            origen = f"leída de {from_file}" if from_file else "del entorno"
            print(f"  API key:    presente ({origen})")
        else:
            print("  API key:    AUSENTE — SIN ESTO NO RESPONDE NADIE")
            print("              consíguela en https://console.anthropic.com")
            print("              (no es tu suscripción a Claude: es aparte)")
            print("              Escríbela en ~/.config/aquiles/env, una línea:")
            print("                ANTHROPIC_API_KEY=sk-ant-api03-...")
        if cfg["owner"].get("name") == cfg["assistant"].get("name"):
            print(f"  ! owner.name y assistant.name son ambos "
                  f"'{cfg['owner'].get('name')}'. En owner.name va TU nombre, "
                  f"no el del asistente.")
        print("  Voz:")
        for k, v in voice.diagnose().items():
            print(f"    {'sí' if v else 'no'}  {k}")
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key and looks_like_placeholder(key):
        raise SystemExit(
            f"ANTHROPIC_API_KEY vale '{key}', que es el marcador de la\n"
            "documentación, no una clave. Se copió el ejemplo literal.\n\n"
            "Pon la clave de verdad — la larga que empieza por 'sk-ant-api'.\n"
            "Si la dejas así, cada mensaje fallará con un error de "
            "autenticación."
        )

    if not key:
        log.error("=" * 60)
        log.error("ANTHROPIC_API_KEY no está definida. Sin ella no hay modelo.")
        log.error("  - Tu conversación con el asistente NO funcionará.")
        log.error("  - Consíguela en https://console.anthropic.com (no es tu")
        log.error("    suscripción a Claude: es una clave aparte, de pago por uso)")
        log.error("  - Luego:  export ANTHROPIC_API_KEY=sk-ant-...")
        log.error("=" * 60)
        if cfg.get("public", {}).get("enabled", False):
            # Dejarlo activo haría que cada desconocido recibiera un error de
            # disculpa en bucle. Mejor que se queden en el saludo, que sí sale.
            log.error("Desactivo el agente público mientras falte la clave: los "
                      "terceros recibirán solo el saludo, en vez de un error.")
            cfg.setdefault("public", {})["enabled"] = False

    return run(cfg, once=args.once, replay_minutes=args.replay_minutes)


if __name__ == "__main__":
    sys.exit(main())
