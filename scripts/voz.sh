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
# Uso:  make voz            (voz latina neutra, la de mejor calidad)
#       make voz VOZ=es_ES-davefx-medium
#
# Esta es la voz LOCAL: gratis, sin clave y sin limite, pero se nota que es
# sintetica. Para una voz indistinguible de una persona:  make voz-real
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/whatsapp-responder"

# es_MX-claude-high es la unica voz masculina "high" del catalogo en español
# de America, y el acento mexicano es el que se usa como neutro en doblaje.
VOZ="${VOZ:-${1:-es_MX-claude-high}}"
DESTINO="state/voces"

verde() { printf '\033[32m%s\033[0m\n' "$*"; }

echo "==> Instalando lo necesario (unos 400 MB, tarda un poco)"
# --all-extras, no solo --extra voice: si imagenes ya estaba instalada, un
# sync que solo pide voice la desinstala.
uv sync --all-extras
verde "  ✓ faster-whisper, piper-tts y ffmpeg instalados"

echo
echo "==> Descargando la voz '$VOZ'"
mkdir -p "$DESTINO"
# Se busca ESTA voz, no "alguna voz": comprobar si hay cualquier .onnx haría
# que pedir una voz distinta no hiciera nada, porque la anterior ya estaba.
# Ruta absoluta: config.toml lo lee tambien un servicio de systemd, que no
# arranca desde este directorio.
YA="$(find "$PWD/$DESTINO" -name "*${VOZ}*.onnx" -print -quit 2>/dev/null || true)"
if [ -n "$YA" ]; then
  verde "  ✓ ya estaba descargada: $YA"
else
  if ! uv run python -m piper.download_voices "$VOZ" --data-dir "$DESTINO" \
       2>"$DESTINO/.error"; then
    printf '\033[31m%s\033[0m\n' "  ✗ No se pudo descargar la voz '$VOZ'"
    echo "    Motivo: $(tail -1 "$DESTINO/.error" | cut -c1-120)"
    echo
    echo "    Suele ser la red (la voz se baja de huggingface.co)."
    echo "    Voces en español disponibles:"
    echo "      es_MX-claude-high       hombre, México — neutra, mejor calidad"
    echo "      es_MX-ald-medium        hombre, México"
    echo "      es_AR-daniela-high      mujer, Argentina"
    echo "      es_ES-davefx-medium     hombre, España"
    echo "      es_ES-sharvard-medium   mujer, España"
    echo
    echo "    Reintenta:  make voz VOZ=es_MX-ald-medium"
    echo "    Mientras tanto Aquiles responde en texto, que sigue funcionando."
    rm -f "$DESTINO/.error"
    exit 1
  fi
  rm -f "$DESTINO/.error"
  verde "  ✓ voz descargada"
  YA="$(find "$PWD/$DESTINO" -name "*${VOZ}*.onnx" -print -quit 2>/dev/null || true)"
fi

# Se apunta la ruta exacta en config.toml. Sin esto, con dos voces descargadas
# se usaria la primera por orden alfabetico, que no tiene por que ser la que
# se acaba de pedir.
if [ -n "$YA" ]; then
  python3 - "$PWD/config.toml" "$YA" <<'PYEOF'
import re, sys
path, ruta = sys.argv[1], sys.argv[2]
try:
    s = open(path, encoding="utf-8").read()
except FileNotFoundError:
    raise SystemExit(0)
linea = f'piper_voice = "{ruta}"'
if re.search(r'(?m)^\s*piper_voice\s*=', s):
    s = re.sub(r'(?m)^\s*piper_voice\s*=.*$', linea, s, count=1)
else:
    s = s.rstrip() + "\n" + linea + "\n"
open(path, "w", encoding="utf-8").write(s)
PYEOF
  verde "  ✓ config.toml apunta a esa voz"
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
