"""Notas de voz: transcribir las que llegan y sintetizar las que se envian.

Ambos motores son locales y opcionales. Si no estan instalados, el respondedor
sigue funcionando en texto — la voz nunca es un requisito para arrancar.

  Escuchar:  faster-whisper  (Whisper en CPU, sin servicio externo)
  Hablar:    piper-tts       (voces neuronales locales)  o  espeak-ng (recurso)

WhatsApp solo pinta la onda y el boton de reproducir si el audio es .ogg opus,
asi que todo lo sintetizado pasa por ffmpeg antes de enviarse.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

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


def synthesize(text: str, out_ogg: str, piper_voice: str | None = None) -> str:
    """Convierte texto en una nota de voz .ogg opus lista para WhatsApp."""
    if not text.strip():
        raise VoiceUnavailable("No hay texto que sintetizar")
    if not ffmpeg_available():
        raise VoiceUnavailable(
            "Falta ffmpeg, necesario para el formato que WhatsApp acepta. "
            "Sin sudo:  uv sync --extra voice   (trae un ffmpeg propio)"
        )

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "speech.wav")
        modelo = piper_voice or _piper_model_por_defecto()
        if modelo:
            _piper_to_wav(text, wav, modelo)
        elif shutil.which("espeak-ng"):
            _espeak_to_wav(text, wav)
        else:
            raise VoiceUnavailable(
                "No hay motor de voz. Instala piper, que no necesita sudo:\n"
                "  uv sync --extra voice\n"
                "  uv run python -m piper.download_voices es_ES-davefx-medium"
            )
        _wav_to_opus_ogg(wav, out_ogg)
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
            "  uv run python -m piper.download_voices es_ES-davefx-medium"
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


def _wav_to_opus_ogg(wav: str, out_ogg: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_ogg)), exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg_path(), "-y", "-i", wav,
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
        "voz piper (con modelo)": _piper_disponible(),
        "voz espeak-ng": shutil.which("espeak-ng") is not None,
        "ffmpeg": ffmpeg_available(),
    }
