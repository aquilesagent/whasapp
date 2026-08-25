"""Estado persistente del respondedor.

Vive en su propia base, separada de la del bridge, para no escribir jamas en
la que el bridge considera suya. Guarda tres cosas: hasta donde se ha leido,
a quien se ha saludado y cuando, y la conversacion con el dueño.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DB = os.path.join(BASE_DIR, "state", "responder.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS watermark (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS greeted (
    chat_jid TEXT PRIMARY KEY,
    last_greeted TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replies (
    chat_jid TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replies ON replies (chat_jid, sent_at);
CREATE TABLE IF NOT EXISTS conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_jid TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation ON conversation (chat_jid, id);
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_by TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    when_text TEXT NOT NULL,
    with_whom TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""


class State:
    def __init__(self, path: str = STATE_DB) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Una base creada antes de que hubiera conversaciones por contacto no
        tiene estas columnas. Se añaden en vez de pedir que se borre: dentro
        hay el historial con el dueño y sus reuniones."""
        for table, column, ddl in (
            ("conversation", "chat_jid", "ALTER TABLE conversation ADD COLUMN chat_jid TEXT NOT NULL DEFAULT ''"),
            ("meetings", "requested_by", "ALTER TABLE meetings ADD COLUMN requested_by TEXT NOT NULL DEFAULT ''"),
        ):
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.conn.execute(ddl)

    def close(self) -> None:
        self.conn.close()

    # --- marca de agua -------------------------------------------------
    def get_watermark(self) -> datetime | None:
        row = self.conn.execute("SELECT last_timestamp FROM watermark WHERE id = 1").fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["last_timestamp"])
        except ValueError:
            return None

    def set_watermark(self, ts: datetime) -> None:
        self.conn.execute(
            "INSERT INTO watermark (id, last_timestamp) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_timestamp = excluded.last_timestamp",
            (ts.isoformat(),),
        )
        self.conn.commit()

    # --- saludos -------------------------------------------------------
    def should_greet(self, chat_jid: str, cooldown_hours: int) -> bool:
        row = self.conn.execute(
            "SELECT last_greeted FROM greeted WHERE chat_jid = ?", (chat_jid,)
        ).fetchone()
        if not row:
            return True
        try:
            last = datetime.fromisoformat(row["last_greeted"])
        except ValueError:
            return True
        return datetime.now() - last >= timedelta(hours=cooldown_hours)

    def mark_greeted(self, chat_jid: str) -> None:
        self.conn.execute(
            "INSERT INTO greeted (chat_jid, last_greeted) VALUES (?, ?) "
            "ON CONFLICT(chat_jid) DO UPDATE SET last_greeted = excluded.last_greeted",
            (chat_jid, datetime.now().isoformat()),
        )
        self.conn.commit()

    # --- freno anti-bucle ----------------------------------------------
    def record_reply(self, chat_jid: str) -> None:
        self.conn.execute(
            "INSERT INTO replies (chat_jid, sent_at) VALUES (?, ?)",
            (chat_jid, datetime.now().isoformat()),
        )
        self.conn.commit()

    def replies_last_hour(self, chat_jid: str) -> int:
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM replies WHERE chat_jid = ? AND sent_at > ?",
            (chat_jid, cutoff),
        ).fetchone()
        return int(row["n"]) if row else 0

    # --- conversacion con el dueño -------------------------------------
    def append_turn(self, chat_jid: str, role: str, content) -> None:
        self.conn.execute(
            "INSERT INTO conversation (chat_jid, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_jid, role, json.dumps(content, ensure_ascii=False),
             datetime.now().isoformat()),
        )
        self.conn.commit()

    def recent_turns(self, chat_jid: str, limit: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversation WHERE chat_jid = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_jid, limit),
        ).fetchall()
        out = []
        for r in reversed(rows):
            try:
                out.append({"role": r["role"], "content": json.loads(r["content"])})
            except json.JSONDecodeError:
                continue
        # Una conversacion no puede empezar por el asistente: la API lo rechaza.
        while out and out[0]["role"] != "user":
            out.pop(0)
        return out

    # --- reuniones ------------------------------------------------------
    def add_meeting(self, title: str, when_text: str, with_whom: str,
                    notes: str = "", requested_by: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO meetings (requested_by, title, when_text, with_whom, "
            "notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (requested_by, title, when_text, with_whom, notes,
             datetime.now().isoformat()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_meetings(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, when_text, with_whom, notes, requested_by FROM meetings "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
