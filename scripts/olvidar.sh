#!/usr/bin/env bash
# Borra la memoria de conversación de Aquiles.
#
# Hace falta cuando el historial guarda avisos de fallos ya arreglados —
# "[nota de voz recibida — no se pudo descargar]" y similares. El modelo es
# coherente con lo que recuerda, así que sigue diciendo que no puede oírte
# aunque ya pueda. Borrar el hilo lo devuelve a la realidad.
#
# No toca la sesión de WhatsApp, ni tus mensajes, ni las reuniones apuntadas:
# solo lo que Aquiles recuerda haber hablado.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/whatsapp-responder"

# Se usa Python y no el cliente sqlite3: el binario no viene instalado en
# muchas máquinas, y aquí ya hay un Python con todo lo necesario.
uv run python - "${1:-todo}" <<'PY'
import os
import sqlite3
import sys

DB = os.path.join("state", "responder.db")
quien = sys.argv[1] if len(sys.argv) > 1 else "todo"

if not os.path.exists(DB):
    print("No hay nada que olvidar todavía.")
    raise SystemExit(0)

con = sqlite3.connect(DB)
if quien == "todo":
    n = con.execute("SELECT COUNT(*) FROM conversation").fetchone()[0]
    con.execute("DELETE FROM conversation")
    print(f"Olvidadas {n} líneas de conversación, de todos los contactos.")
else:
    patron = f"%{quien}%"
    n = con.execute(
        "SELECT COUNT(*) FROM conversation WHERE chat_jid LIKE ?", (patron,)
    ).fetchone()[0]
    con.execute("DELETE FROM conversation WHERE chat_jid LIKE ?", (patron,))
    print(f"Olvidadas {n} líneas de la conversación con {quien}.")
con.commit()
con.close()

print("Aquiles empieza de cero en el próximo mensaje.")
print("Las reuniones apuntadas y tu historial de WhatsApp no se han tocado.")
PY
