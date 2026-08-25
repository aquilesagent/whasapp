#!/usr/bin/env bash
# Instala las dependencias del conector de WhatsApp y compila el bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "  ✗ falta '$1' — $2"
    fail=1
  else
    # go no entiende --version; usa el subcomando.
    if [ "$1" = go ]; then
      echo "  ✓ go ($(go version 2>&1 | head -1))"
    else
      echo "  ✓ $1 ($($1 --version 2>&1 | head -1))"
    fi
  fi
}

# El bridge necesita Go >= la version declarada en su go.mod. Las distros
# empaquetan una mas vieja, asi que comprobar que el binario existe no basta.
check_go_version() {
  command -v go >/dev/null 2>&1 || return 0
  need_v="$(awk '/^go /{print $2; exit}' whatsapp-bridge/go.mod)"
  have_v="$(go env GOVERSION 2>/dev/null | sed 's/^go//')"
  [ -n "$need_v" ] && [ -n "$have_v" ] || return 0
  if [ "$(printf '%s\n%s\n' "$need_v" "$have_v" | sort -V | head -1)" != "$need_v" ]; then
    echo "  ! Go $have_v es anterior a $need_v; Go descargara la cadena correcta sola"
    echo "    (necesita red). Si falla, instala la oficial desde https://go.dev/dl/"
  fi
}

# go-sqlite3 es una extension en C. Sin compilador el build falla con errores
# de enlazado que en ningun momento dicen que falta gcc.
check_c_compiler() {
  if command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1; then
    echo "  ✓ compilador de C"
    return 0
  fi
  echo "  ✗ falta un compilador de C (lo necesita go-sqlite3 via CGO)"
  echo "      Debian/Ubuntu/WSL:  sudo apt update && sudo apt install -y build-essential"
  echo "      Fedora:             sudo dnf install -y gcc"
  echo "      macOS:              xcode-select --install"
  fail=1
}

echo "==> Comprobando requisitos"
need go "instálalo desde https://go.dev/dl/"
check_go_version
check_c_compiler
need uv "instálalo con: curl -LsSf https://astral.sh/uv/install.sh | sh"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "  ! ffmpeg no encontrado (opcional: solo para send_audio_message con .mp3/.wav)"
else
  echo "  ✓ ffmpeg"
fi
[ "$fail" -eq 0 ] || { echo "Faltan requisitos, aborto."; exit 1; }

echo "==> Compilando el bridge de Go (CGO activado para sqlite3)"
( cd whatsapp-bridge && CGO_ENABLED=1 go build -o bin/whatsapp-bridge . )
echo "  ✓ whatsapp-bridge/bin/whatsapp-bridge"

echo "==> Instalando dependencias del servidor MCP"
( cd whatsapp-mcp-server && uv sync )
echo "  ✓ entorno de Python listo"

cat <<CONF

==> Listo.

Siguiente paso — arrancar el bridge y escanear el QR:

    ./scripts/bridge.sh

En Claude Code este repo ya trae .mcp.json, así que el servidor MCP
se detecta solo al abrir el proyecto.

Para Claude Desktop o Cursor, pega esto en tu config:

  Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json
  Cursor:         ~/.cursor/mcp.json

{
  "mcpServers": {
    "whatsapp": {
      "command": "$(command -v uv)",
      "args": ["--directory", "$ROOT/whatsapp-mcp-server", "run", "main.py"]
    }
  }
}
CONF
