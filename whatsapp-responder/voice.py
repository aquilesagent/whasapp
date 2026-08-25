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


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


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
            "Instálalo con: sudo apt install -y ffmpeg"
        )

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "speech.wav")
        if shutil.which("piper") and piper_voice:
            _piper_to_wav(text, wav, piper_voice)
        elif shutil.which("espeak-ng"):
            _espeak_to_wav(text, wav)
        else:
            raise VoiceUnavailable(
                "No hay motor de voz. Instala piper-tts (recomendado, voz "
                "natural) o espeak-ng (sudo apt install -y espeak-ng)."
            )
        _wav_to_opus_ogg(wav, out_ogg)
    return out_ogg


def _piper_to_wav(text: str, wav: str, voice_model: str) -> None:
    proc = subprocess.run(
        ["piper", "--model", voice_model, "--output_file", wav],
        input=text.encode("utf-8"),
        capture_output=True,
    )
    if proc.returncode != 0 or not os.path.isfile(wav):
        raise VoiceUnavailable(f"piper falló: {proc.stderr.decode()[:300]}")


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
            "ffmpeg", "-y", "-i", wav,
            "-c:a", "libopus", "-b:a", "32k", "-ar", "24000", "-ac", "1",
            out_ogg,
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not os.path.isfile(out_ogg):
        raise VoiceUnavailable(f"ffmpeg falló: {proc.stderr.decode()[:300]}")


def diagnose() -> dict[str, bool]:
    """Que piezas de voz hay disponibles. Lo usa `make doctor`."""
    try:
        import faster_whisper  # noqa: F401
        stt = True
    except ImportError:
        stt = False
    return {
        "transcripcion (faster-whisper)": stt,
        "voz piper": shutil.which("piper") is not None,
        "voz espeak-ng": shutil.which("espeak-ng") is not None,
        "ffmpeg": ffmpeg_available(),
    }
