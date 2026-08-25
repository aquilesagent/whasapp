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
    echo "  ✓ $1 ($($1 --version 2>&1 | head -1))"
  fi
}

echo "==> Comprobando requisitos"
need go "instálalo desde https://go.dev/dl/"
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
