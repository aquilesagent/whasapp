#!/usr/bin/env bash
# Dice por que una nota de voz no se pudo escuchar.
#
# Hay tres puntos donde se rompe, y el mensaje del asistente no distingue
# entre ellos: que el bridge no guardara el direct_path (binario viejo), que
# la descarga del CDN falle, o que falte el motor de transcripcion.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/whatsapp-responder"

uv run python - <<'PY'
import os
import sqlite3
import sys

import voice
import wa

DB = wa.MESSAGES_DB
if not os.path.exists(DB):
    sys.exit("No hay base de mensajes. ¿Ha corrido el bridge?")

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
fila = con.execute(
    """SELECT id, chat_jid, timestamp, COALESCE(direct_path, '') AS dp
       FROM messages
       WHERE media_type IN ('audio', 'ptt') AND is_from_me = 0
       ORDER BY timestamp DESC LIMIT 1"""
).fetchone()

if fila is None:
    sys.exit("No ha llegado ninguna nota de voz todavía.")

print(f"Última nota de voz: {fila['timestamp']}")
print()

if fila["dp"]:
    print("  1. direct_path guardado ....... SÍ")
else:
    print("  1. direct_path guardado ....... NO")
    print()
    print("     Este audio llegó con el bridge ANTIGUO, que no lo guardaba.")
    print("     Recompila y reinicia el bridge, y manda una nota NUEVA:")
    print("       cd .. && make build && make bridge")
    sys.exit(1)

ruta = wa.download_media(fila["id"], fila["chat_jid"])
if ruta:
    print(f"  2. descarga del audio ......... SÍ  ({ruta})")
else:
    print("  2. descarga del audio ......... NO")
    print()
    print("     El bridge no pudo bajar el audio del CDN de WhatsApp.")
    print("     Mira el log del bridge: la línea con 'download' dice el motivo.")
    sys.exit(1)

try:
    texto = voice.transcribe(ruta, model_size="base", language="es")
    print("  3. transcripción .............. SÍ")
    print()
    print(f"     Dice: {texto[:200]}")
except voice.VoiceUnavailable as e:
    print("  3. transcripción .............. NO")
    print()
    print(f"     {e}")
    sys.exit(1)

print()
print("Todo el camino funciona. Si el asistente dice que no puede escucharte,")
print("reinícialo para que tome estos cambios.")
PY
