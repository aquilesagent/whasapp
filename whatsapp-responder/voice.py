"""Notas de voz: transcribir las que llegan y sintetizar las que se envian.

Ambos motores son locales y opcionales. Si no estan instalados, el respondedor
sigue funcionando en texto — la voz nunca es un requisito para arrancar.

  Escuchar:  faster-whisper  (Whisper en CPU, sin servicio externo)
  Hablar:    ElevenLabs      (la voz mas realista; necesita clave, hay plan
                              gratuito)  o  piper-tts (local, sin clave)  o
                              espeak-ng (recurso, robotico)

Los tres motores de habla estan ordenados de mas a menos realista, y se cae al
siguiente en cuanto uno falla. Quedarse callado por un fallo de red seria peor
que sonar peor.

WhatsApp solo pinta la onda y el boton de reproducir si el audio es .ogg opus,
asi que todo lo sintetizado pasa por ffmpeg antes de enviarse.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

log = logging.getLogger(__name__)

AUDIO_MEDIA_TYPES = {"audio", "ptt", "voice"}


class VoiceUnavailable(RuntimeError):
    """El motor pedido no esta instalado o no se puede usar."""


def ffmpeg_path() -> str | None:
    """Ruta a ffmpeg: el del sistema, o el que trae imageio-ffmpeg.

    Instalar ffmpeg con apt necesita sudo, y sudo necesita una terminal
    interactiva que un agente no tiene. imageio-ffmpeg trae un binario
    estatico por pip —con libopus incluido— asi que la voz deja de depender
    de tener permisos de administrador.
    """
    del_sistema = shutil.which("ffmpeg")
    if del_sistema:
        return del_sistema
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


# --------------------------------------------------------------------------
# Escuchar
# --------------------------------------------------------------------------

_whisper_model = None


def transcribe(path: str, model_size: str = "base", language: str = "es") -> str:
    """Transcribe un audio a texto. Carga el modelo una sola vez por proceso:
    cargarlo en cada nota de voz costaria varios segundos cada vez."""
    global _whisper_model

    if not os.path.isfile(path):
        raise VoiceUnavailable(f"No existe el audio: {path}")

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceUnavailable(
            "faster-whisper no está instalado. Instálalo con: "
            "cd whatsapp-responder && uv sync --extra voice"
        ) from e

    if _whisper_model is None:
        # int8 en CPU: la unica combinacion que va fluida sin GPU.
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, _info = _whisper_model.transcribe(path, language=language, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


# --------------------------------------------------------------------------
# Hablar
# --------------------------------------------------------------------------


# Modelo de ElevenLabs. El multilingue v2 es el mas realista en español; el
# flash gasta la mitad de creditos y suena algo peor.
ELEVEN_MODELO = "eleven_multilingual_v2"


def elevenlabs_disponible() -> bool:
    if not os.environ.get("ELEVENLABS_API_KEY"):
        return False
    try:
        import elevenlabs  # noqa: F401
    except ImportError:
        return False
    return True


def _elevenlabs_to_mp3(text: str, destino: str, voice_id: str,
                       model_id: str = ELEVEN_MODELO) -> None:
    """Sintetiza con ElevenLabs y deja un mp3 en `destino`.

    Se pide mp3 y no opus porque el 'opus' de ElevenLabs no viene en el
    contenedor ogg que WhatsApp necesita; convertirlo con ffmpeg —que ya hace
    falta para el resto— sale mas barato que arriesgarse al formato.
    """
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError as e:
        raise VoiceUnavailable(
            "El paquete elevenlabs no esta instalado: uv sync --extra real"
        ) from e

    try:
        trozos = ElevenLabs().text_to_speech.convert(
            voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        datos = b"".join(trozos)
    except Exception as e:  # red, cuota, voz inexistente...
        raise VoiceUnavailable(_explicar_eleven(str(e))) from e

    if not datos:
        raise VoiceUnavailable("ElevenLabs no devolvio audio")
    with open(destino, "wb") as fh:
        fh.write(datos)


def _explicar_eleven(error: str) -> str:
    bajo = error.lower()
    if "quota" in bajo or "credit" in bajo or "429" in bajo:
        return ("la cuenta de ElevenLabs se quedo sin creditos este mes "
                "(el plan gratuito trae 10.000 caracteres)")
    if "401" in bajo or "invalid_api_key" in bajo or "unauthorized" in bajo:
        return "la clave de ElevenLabs no vale; vuelve a guardarla con 'make activar'"
    if "voice_not_found" in bajo or "404" in bajo:
        return ("esa voz no esta en tu cuenta de ElevenLabs. Anadela desde "
                "elevenlabs.io/app/voice-library y vuelve a intentarlo")
    return f"ElevenLabs fallo: {error[:200]}"


def synthesize(text: str, out_ogg: str, piper_voice: str | None = None,
               eleven_voice: str | None = None,
               eleven_model: str = ELEVEN_MODELO) -> str:
    """Convierte texto en una nota de voz .ogg opus lista para WhatsApp.

    Prueba los motores de mas a menos realista. Que ElevenLabs falle no debe
    dejar mudo a Aquiles: se sigue con la voz local, que no depende de la red.
    """
    if not text.strip():
        raise VoiceUnavailable("No hay texto que sintetizar")
    if not ffmpeg_available():
        raise VoiceUnavailable(
            "Falta ffmpeg, necesario para el formato que WhatsApp acepta. "
            "Sin sudo:  uv sync --extra voice   (trae un ffmpeg propio)"
        )

    with tempfile.TemporaryDirectory() as tmp:
        fuente = None

        if eleven_voice and elevenlabs_disponible():
            fuente = os.path.join(tmp, "speech.mp3")
            try:
                _elevenlabs_to_mp3(text, fuente, eleven_voice, eleven_model)
            except VoiceUnavailable as e:
                log.warning("ElevenLabs no pudo hablar (%s); uso la voz local", e)
                fuente = None

        if fuente is None:
            fuente = os.path.join(tmp, "speech.wav")
            modelo = piper_voice or _piper_model_por_defecto()
            if modelo:
                _piper_to_wav(text, fuente, modelo)
            elif shutil.which("espeak-ng"):
                _espeak_to_wav(text, fuente)
            else:
                raise VoiceUnavailable(
                    "No hay motor de voz. Instala piper, que no necesita sudo:\n"
                    "  uv sync --extra voice\n"
                    "  uv run python -m piper.download_voices es_MX-claude-high"
                )

        _a_opus_ogg(fuente, out_ogg)
    return out_ogg


PIPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "voces")
_piper_cargada = None


def _piper_model_por_defecto() -> str | None:
    """Primer modelo .onnx descargado, si no se configuro ninguno."""
    for carpeta in (PIPER_DIR, os.getcwd()):
        if not os.path.isdir(carpeta):
            continue
        for f in sorted(os.listdir(carpeta)):
            if f.endswith(".onnx"):
                return os.path.join(carpeta, f)
    return None


def _piper_to_wav(text: str, wav: str, voice_model: str) -> None:
    """Sintetiza con piper usando su API de Python.

    Se usa la API y no el binario porque `piper-tts` se instala por pip y no
    deja necesariamente un ejecutable en el PATH. El modelo se carga una sola
    vez: recargarlo en cada nota de voz costaria segundos cada vez.
    """
    global _piper_cargada

    if not os.path.isfile(voice_model):
        raise VoiceUnavailable(
            f"No existe el modelo de voz: {voice_model}\n"
            "Descarga uno con:\n"
            "  uv run python -m piper.download_voices es_MX-claude-high"
        )
    try:
        from piper import PiperVoice
    except ImportError as e:
        raise VoiceUnavailable(
            "piper-tts no esta instalado. Instalalo con: uv sync --extra voice"
        ) from e

    if _piper_cargada is None or _piper_cargada[0] != voice_model:
        _piper_cargada = (voice_model, PiperVoice.load(voice_model))

    import wave
    with wave.open(wav, "wb") as fh:
        _piper_cargada[1].synthesize_wav(text, fh)

    if not os.path.isfile(wav) or os.path.getsize(wav) == 0:
        raise VoiceUnavailable("piper no genero audio")


def _espeak_to_wav(text: str, wav: str) -> None:
    proc = subprocess.run(
        ["espeak-ng", "-v", "es", "-s", "150", "-w", wav, text],
        capture_output=True,
    )
    if proc.returncode != 0 or not os.path.isfile(wav):
        raise VoiceUnavailable(f"espeak-ng falló: {proc.stderr.decode()[:300]}")


def _a_opus_ogg(fuente: str, out_ogg: str) -> None:
    """Reencoda a ogg/opus, que es lo unico que WhatsApp pinta como nota de voz.

    Acepta wav o mp3: ffmpeg deduce el formato de entrada del propio fichero.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_ogg)), exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg_path(), "-y", "-i", fuente,
            "-c:a", "libopus", "-b:a", "32k", "-ar", "24000", "-ac", "1",
            out_ogg,
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not os.path.isfile(out_ogg):
        raise VoiceUnavailable(f"ffmpeg falló: {proc.stderr.decode()[:300]}")


def _piper_disponible() -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return _piper_model_por_defecto() is not None


def diagnose() -> dict[str, bool]:
    """Que piezas de voz hay disponibles. Lo usa `make doctor`."""
    try:
        import faster_whisper  # noqa: F401
        stt = True
    except ImportError:
        stt = False
    return {
        "transcripcion (faster-whisper)": stt,
        "voz ElevenLabs (la mas real)": elevenlabs_disponible(),
        "voz piper (con modelo)": _piper_disponible(),
        "voz espeak-ng": shutil.which("espeak-ng") is not None,
        "ffmpeg": ffmpeg_available(),
    }
