#!/usr/bin/env bash
# Deja a Aquiles escuchando y hablando, sin necesitar sudo.
#
# `sudo apt install ffmpeg espeak-ng` es el camino obvio y es justo el que no
# sirve aquí: sudo exige una terminal interactiva, y un agente no la tiene.
# Todo lo que hace falta existe en pip:
#
#   faster-whisper   transcribe las notas de voz que llegan
#   piper-tts        sintetiza las respuestas, con voz neuronal
#   imageio-ffmpeg   trae su propio ffmpeg con libopus
#
# Uso:  make voz            (voz española por defecto)
#       make voz VOZ=es_MX-claude-high
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/whatsapp-responder"

VOZ="${VOZ:-${1:-es_ES-davefx-medium}}"
DESTINO="state/voces"

verde() { printf '\033[32m%s\033[0m\n' "$*"; }

echo "==> Instalando lo necesario (unos 400 MB, tarda un poco)"
uv sync --extra voice
verde "  ✓ faster-whisper, piper-tts y ffmpeg instalados"

echo
echo "==> Descargando la voz '$VOZ'"
mkdir -p "$DESTINO"
if ls "$DESTINO"/*.onnx >/dev/null 2>&1; then
  verde "  ✓ ya hay una voz descargada en $DESTINO"
else
  if ! uv run python -m piper.download_voices "$VOZ" --data-dir "$DESTINO" \
       2>"$DESTINO/.error"; then
    printf '\033[31m%s\033[0m\n' "  ✗ No se pudo descargar la voz '$VOZ'"
    echo "    Motivo: $(tail -1 "$DESTINO/.error" | cut -c1-120)"
    echo
    echo "    Suele ser la red (la voz se baja de huggingface.co)."
    echo "    Voces españolas disponibles:"
    echo "      es_ES-davefx-medium     hombre, España"
    echo "      es_ES-sharvard-medium   mujer, España"
    echo "      es_MX-claude-high       hombre, México (la mejor calidad)"
    echo
    echo "    Reintenta:  make voz VOZ=es_MX-claude-high"
    echo "    Mientras tanto Aquiles responde en texto, que sigue funcionando."
    rm -f "$DESTINO/.error"
    exit 1
  fi
  rm -f "$DESTINO/.error"
  verde "  ✓ voz descargada"
fi

echo
echo "==> Activando la respuesta en voz"
if grep -q '^reply_with_voice = false' config.toml 2>/dev/null; then
  sed -i 's/^reply_with_voice = false/reply_with_voice = true/' config.toml
  verde "  ✓ reply_with_voice = true"
else
  verde "  ✓ ya estaba activada"
fi

echo
echo "==> Comprobando"
uv run responder.py --check | sed -n '/Voz:/,$p'

echo
verde "Listo. Reinicia el respondedor y mándale una nota de voz:"
echo "    cd $ROOT && make responder"
