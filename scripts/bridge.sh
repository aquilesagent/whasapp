#!/usr/bin/env bash
# Arranca el bridge de WhatsApp. La primera vez muestra un QR para vincular
# el dispositivo; la sesión queda guardada en whatsapp-bridge/store/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/whatsapp-bridge"

if [ ! -x bin/whatsapp-bridge ]; then
  echo "==> Binario no encontrado, compilando..."
  CGO_ENABLED=1 go build -o bin/whatsapp-bridge .
fi

echo "==> Bridge escuchando en http://localhost:8080/api"
echo "    (Ctrl-C para parar. Déjalo corriendo mientras uses el MCP.)"
exec ./bin/whatsapp-bridge
