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

# Un segundo bridge no solo falla al abrir el puerto: los dos procesos
# escribirian sobre la misma sesion de WhatsApp. Mejor pararlo aqui.
if curl -sS --max-time 2 -o /dev/null "http://localhost:8080/api/send" 2>/dev/null \
   || curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "http://localhost:8080/api/send" 2>/dev/null | grep -qE '^[2-5]'; then
  echo "==> Ya hay un bridge escuchando en localhost:8080."
  echo "    No arranco un segundo: compartirian la sesion y se pisarian."
  echo "    Para ver su estado:   make doctor"
  echo "    Para reemplazarlo:    para el otro proceso y vuelve a lanzar esto."
  exit 0
fi

echo "==> Bridge escuchando en http://localhost:8080/api"
echo "    (Ctrl-C para parar. Déjalo corriendo mientras uses el MCP.)"
exec ./bin/whatsapp-bridge
