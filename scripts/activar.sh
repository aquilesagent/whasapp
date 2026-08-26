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
#
# Acepta las tres claves que usa Aquiles y distingue cuál es por el prefijo:
#   sk-ant-...   Anthropic   — la que le hace hablar. Sin ella no hay asistente.
#   sk-proj-...  OpenAI      — solo para generar imágenes.
#   sk_...       ElevenLabs  — solo para la voz realista.
# Guardar una no borra las otras.
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
# Se puede nombrar el proveedor delante:  activar.sh elevenlabs <clave>
# Sirve para cuando el prefijo no baste para saber de quién es.
FORZADO=""
case "${1:-}" in
  anthropic|claude)   FORZADO="ANTHROPIC_API_KEY";  shift ;;
  openai|imagenes)    FORZADO="OPENAI_API_KEY";     shift ;;
  elevenlabs|voz)     FORZADO="ELEVENLABS_API_KEY"; shift ;;
esac

CLAVE="${1:-}"
ORIGEN="el argumento"

if [ -z "$CLAVE" ] && [ ! -t 0 ]; then
  CLAVE="$(cat)"
  ORIGEN="la entrada estándar"
fi

if [ -z "$CLAVE" ]; then
  PEGADO="$(leer_portapapeles)"
  CLAVE="$(printf '%s' "$PEGADO" | grep -oE 'sk-(ant|proj|svcacct)-[A-Za-z0-9_-]*|sk_[A-Za-z0-9]{20,}' | head -1)"
  # Si no hay clave pero si una cadena hexadecimal suelta, casi seguro es el
  # ID de una clave de ElevenLabs copiado de la lista. Se recuerda para poder
  # decirlo, porque el error del proveedor es criptico y manda a mirar la
  # lista, que es justo de donde salio el ID.
  if [ -z "$CLAVE" ]; then
    IDPEGADO="$(printf '%s' "$PEGADO" | tr -d '[:space:]' | grep -xE '[0-9a-fA-F]{32,64}' || true)"
  fi
  ORIGEN="el portapapeles"
fi

CLAVE="$(printf '%s' "$CLAVE" | tr -d '[:space:]')"

if [ -z "$CLAVE" ] && [ -n "${IDPEGADO:-}" ]; then
  rojo "Eso es el ID de la clave, no la clave."
  echo
  echo "En la lista de ElevenLabs solo se ve el ID. La clave de verdad empieza"
  echo "por 'sk_' y SOLO se muestra una vez, al crearla o al rotarla."
  echo
  echo "Crea una nueva en https://elevenlabs.io/app/developers/api-keys,"
  echo "cópiala en ese momento, y pásala así:"
  echo "    ./scripts/activar.sh elevenlabs sk_loquesea"
  exit 1
fi

if [ -z "$CLAVE" ]; then
  rojo "No he encontrado ninguna clave."
  echo
  echo "Copia la clave desde https://console.anthropic.com (botón «Copiar"
  echo "clave») y vuelve a ejecutar esto. O pásala directamente:"
  echo "    ./scripts/activar.sh sk-ant-api03-loquesea"
  echo
  echo "Repite esto mismo con las otras dos claves si las quieres:"
  echo "  OpenAI     https://platform.openai.com/api-keys      (imágenes)"
  echo "  ElevenLabs https://elevenlabs.io/app/settings/api-keys (voz realista)"
  echo "Cada una es una cuenta aparte; guardar una no borra las otras."
  exit 1
fi

if [ -n "$FORZADO" ]; then
  VARIABLE="$FORZADO"
  case "$VARIABLE" in
    ANTHROPIC_API_KEY)  QUIEN="Anthropic (hablar)" ;;
    OPENAI_API_KEY)     QUIEN="OpenAI (imágenes)" ;;
    ELEVENLABS_API_KEY)
      QUIEN="ElevenLabs (voz realista)"
      # Nombrar el proveedor no convierte un ID en una clave; guardarlo solo
      # aplaza el fallo hasta la primera sintesis.
      case "$CLAVE" in
        sk_*) ;;
        *) rojo "Eso no es una clave de ElevenLabs: no empieza por 'sk_'."
           echo
           echo "Si son 64 caracteres hexadecimales, es el ID que se ve en la"
           echo "lista. La clave solo se muestra al crearla o al rotarla."
           echo "Crea una nueva en https://elevenlabs.io/app/developers/api-keys"
           exit 1 ;;
      esac ;;
  esac
else
  case "$CLAVE" in
    sk-ant-*)               VARIABLE="ANTHROPIC_API_KEY";  QUIEN="Anthropic (hablar)" ;;
    sk-proj-*|sk-svcacct-*) VARIABLE="OPENAI_API_KEY";     QUIEN="OpenAI (imágenes)" ;;
    sk_*)                   VARIABLE="ELEVENLABS_API_KEY"; QUIEN="ElevenLabs (voz realista)" ;;
    *)
      if printf '%s' "$CLAVE" | grep -qxE '[0-9a-fA-F]{32,64}'; then
        rojo "Eso es el ID de una clave de ElevenLabs, no la clave."
        echo
        echo "En la lista solo se ve el ID. La clave empieza por 'sk_' y SOLO"
        echo "se muestra una vez, al crearla o al rotarla."
        echo "Crea una nueva en https://elevenlabs.io/app/developers/api-keys"
      else
        rojo "Eso no parece una clave de ninguno de los tres proveedores."
        echo "Encontrado en $ORIGEN: ${CLAVE:0:12}..."
        echo
        echo "Las de Anthropic empiezan por 'sk-ant-', las de OpenAI por"
        echo "'sk-proj-' y las de ElevenLabs por 'sk_'."
      fi
      exit 1 ;;
  esac
fi

# 32 es el mínimo real: las de ElevenLabs sin prefijo tienen 64 y las de
# Anthropic pasan de 90.
if [ "${#CLAVE}" -lt 32 ]; then
  rojo "La clave es demasiado corta (${#CLAVE} caracteres)."
  echo "Puede que hayas copiado solo un trozo, o el ejemplo de la documentación."
  exit 1
fi

# --- 2. Guardarla ----------------------------------------------------------
mkdir -p "$ENV_DIR"
python3 "$ROOT/scripts/guardar_clave.py" "$ENV_FILE" "$VARIABLE" "$CLAVE" || exit 1
verde "✓ Clave de $QUIEN guardada en $ENV_FILE (desde $ORIGEN)"
echo "  $VARIABLE = ${CLAVE:0:16}…${CLAVE: -4}   ${#CLAVE} caracteres"

# El paquete de imágenes/voz solo se instala cuando hay clave para usarlo.
# --all-extras, no --extra "$EXTRA" solo: si otro extra ya estaba instalado
# (p.ej. voice), un sync que solo pide este lo desinstalaría.
# Guardar la clave y parar. Lo usan las pruebas, y sirve para cambiar una
# clave sin reinstalar paquetes ni arrancar comprobaciones.
if [ -n "${AQUILES_SOLO_CLAVE:-}" ]; then
  exit 0
fi

case "$VARIABLE" in
  OPENAI_API_KEY)     EXTRA=imagenes ;;
  ELEVENLABS_API_KEY) EXTRA=real ;;
  *)                  EXTRA="" ;;
esac
if [ -n "$EXTRA" ]; then
  echo "==> Instalando el paquete '$EXTRA'"
  ( cd "$ROOT/whatsapp-responder" && uv sync --all-extras ) || {
    rojo "No se pudo instalar. Hazlo a mano:"
    echo "    cd $ROOT/whatsapp-responder && uv sync --all-extras"
  }
fi
if [ "$VARIABLE" = "ELEVENLABS_API_KEY" ]; then
  echo
  echo "Elige la voz con la que quieres que hable:"
  echo "    make voces        ver las disponibles"
  echo "    make voz-real     poner la mejor voz neutra y probarla"
fi

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
