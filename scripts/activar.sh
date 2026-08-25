#!/usr/bin/env bash
# Deja a Aquiles listo para arrancar sin tener que teclear nada.
#
# La clave de la API se toma, en este orden:
#   1. el argumento:            ./scripts/activar.sh sk-ant-api03-...
#   2. el portapapeles:         copia la clave en el navegador y ejecuta esto
#   3. lo que llegue por stdin: pbpaste | ./scripts/activar.sh
#
# El portapapeles es la vía preferida: la clave no pasa por el historial de
# bash ni por ninguna conversación.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_DIR="$HOME/.config/aquiles"
ENV_FILE="$ENV_DIR/env"
CONFIG="$ROOT/whatsapp-responder/config.toml"
EJEMPLO="$ROOT/whatsapp-responder/config.example.toml"

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }

leer_portapapeles() {
  # WSL: la forma fiable de llegar al portapapeles de Windows.
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command Get-Clipboard 2>/dev/null | tr -d '\r'
    return
  fi
  command -v wl-paste >/dev/null 2>&1 && { wl-paste 2>/dev/null; return; }
  command -v xclip   >/dev/null 2>&1 && { xclip -o -selection clipboard 2>/dev/null; return; }
  command -v pbpaste >/dev/null 2>&1 && { pbpaste 2>/dev/null; return; }
}

# --- 1. Conseguir la clave -------------------------------------------------
CLAVE="${1:-}"
ORIGEN="el argumento"

if [ -z "$CLAVE" ] && [ ! -t 0 ]; then
  CLAVE="$(cat)"
  ORIGEN="la entrada estándar"
fi

if [ -z "$CLAVE" ]; then
  CLAVE="$(leer_portapapeles | grep -o 'sk-ant-[A-Za-z0-9_-]*' | head -1)"
  ORIGEN="el portapapeles"
fi

CLAVE="$(printf '%s' "$CLAVE" | tr -d '[:space:]')"

if [ -z "$CLAVE" ]; then
  rojo "No he encontrado ninguna clave."
  echo
  echo "Copia la clave desde https://console.anthropic.com (botón «Copiar"
  echo "clave») y vuelve a ejecutar esto. O pásala directamente:"
  echo "    ./scripts/activar.sh sk-ant-api03-loquesea"
  exit 1
fi

case "$CLAVE" in
  sk-ant-*) ;;
  *) rojo "Eso no parece una clave de Anthropic: no empieza por 'sk-ant-'."
     echo "Encontrado en $ORIGEN: ${CLAVE:0:12}..."
     exit 1 ;;
esac

if [ "${#CLAVE}" -lt 40 ]; then
  rojo "La clave es demasiado corta (${#CLAVE} caracteres); las reales pasan de 90."
  echo "Puede que hayas copiado solo un trozo, o el ejemplo de la documentación."
  exit 1
fi

# --- 2. Guardarla ----------------------------------------------------------
mkdir -p "$ENV_DIR"
printf 'ANTHROPIC_API_KEY=%s\n' "$CLAVE" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
verde "✓ Clave guardada en $ENV_FILE (desde $ORIGEN)"
echo "  ${CLAVE:0:16}…${CLAVE: -4}   ${#CLAVE} caracteres"

# --- 3. La configuración del respondedor -----------------------------------
if [ ! -f "$CONFIG" ]; then
  cp "$EJEMPLO" "$CONFIG"
  verde "✓ config.toml creado desde el ejemplo"
  rojo  "  ! Falta poner tu número en owner.phone"
fi

# owner.name con el nombre del asistente deja al asistente llamándote a ti por
# su propio nombre. Si pasa, se toma el nombre que ya aparece en el saludo.
ASIST="$(sed -n '/^\[assistant\]/,/^\[/p' "$CONFIG" | sed -n 's/^name *= *"\(.*\)"/\1/p' | head -1)"
DUENO="$(sed -n '/^\[owner\]/,/^\[/p'     "$CONFIG" | sed -n 's/^name *= *"\(.*\)"/\1/p' | head -1)"
if [ -n "$ASIST" ] && [ "$ASIST" = "$DUENO" ]; then
  DEL_SALUDO="$(grep -o 'asistente del [A-ZÁÉÍÓÚÑ][^.,]*' "$CONFIG" | head -1 | sed 's/^asistente del //')"
  NUEVO="${DEL_SALUDO:-jefe}"
  python3 - "$CONFIG" "$NUEVO" <<'PY'
import re, sys
path, nuevo = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
def fix(m):
    return m.group(0).replace(m.group(1), nuevo, 1)
s = re.sub(r'(?s)(?<=\[owner\])(.*?)(?=\n\[)',
           lambda m: re.sub(r'name = "[^"]*"', f'name = "{nuevo}"', m.group(0)), s, count=1)
open(path, "w", encoding="utf-8").write(s)
PY
  verde "✓ owner.name corregido: era '$ASIST' (el del asistente), ahora '$NUEVO'"
fi

# --- 4. Comprobar ----------------------------------------------------------
echo
echo "==> Comprobando"
( cd whatsapp-responder && uv run responder.py --check ) || exit 1

echo
verde "Listo. Arranca el respondedor con:"
echo "    cd $ROOT && make responder"
