#!/usr/bin/env bash
# Diagnostica el estado del conector: requisitos, build, sesión y bridge vivo.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

problemas=0
ok()   { echo "  ✓ $1"; }
warn() { echo "  ! $1"; }
bad()  { echo "  ✗ $1"; problemas=$((problemas + 1)); }

echo "==> Requisitos"
for cmd in go uv; do
  if command -v "$cmd" >/dev/null 2>&1; then ok "$cmd"; else bad "falta '$cmd'"; fi
done
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg"
else
  warn "sin ffmpeg — send_audio_message solo aceptará .ogg opus"
fi

echo "==> Build"
if [ -x whatsapp-bridge/bin/whatsapp-bridge ]; then
  ok "bridge compilado"
else
  bad "bridge sin compilar — ejecuta 'make build'"
fi
if [ -d whatsapp-mcp-server/.venv ]; then
  ok "entorno de Python creado"
else
  bad "sin .venv — ejecuta 'make setup'"
fi

echo "==> Sesión de WhatsApp"
if [ -f whatsapp-bridge/store/whatsapp.db ]; then
  ok "dispositivo vinculado (whatsapp-bridge/store/whatsapp.db)"
else
  bad "sin vincular — ejecuta 'make bridge' y escanea el QR"
fi

DB=whatsapp-bridge/store/messages.db
if [ -f "$DB" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    msgs=$(sqlite3 "$DB" "SELECT COUNT(*) FROM messages;" 2>/dev/null || echo "?")
    chats=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chats;" 2>/dev/null || echo "?")
    ok "mensajes sincronizados: $msgs en $chats chats"
    [ "$msgs" = "0" ] && warn "la base está vacía — la primera sincronización puede tardar"
  else
    ok "base de mensajes presente ($(du -h "$DB" | cut -f1))"
  fi
else
  bad "sin base de mensajes — el bridge no ha llegado a sincronizar"
fi

echo "==> Bridge en ejecución"
if curl -fsS --max-time 3 -o /dev/null http://localhost:8080/api/send -X POST -d '{}' 2>/dev/null \
   || curl -sS --max-time 3 -o /dev/null -w '%{http_code}' http://localhost:8080/api/send 2>/dev/null | grep -qE '^[2-5]'; then
  ok "respondiendo en http://localhost:8080/api"
else
  bad "no responde en localhost:8080 — arráncalo con 'make bridge'"
fi

echo
if [ "$problemas" -eq 0 ]; then
  echo "Todo correcto. El conector está listo para usarse desde Claude."
else
  echo "$problemas problema(s) encontrados — mira el detalle arriba."
  echo "Guía de resolución: sección 'Problemas comunes' del README."
  exit 1
fi
