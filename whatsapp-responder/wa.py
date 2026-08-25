"""Acceso a WhatsApp a través del bridge: leer mensajes nuevos y enviar.

El bridge no tiene webhook — al recibir un mensaje solo lo escribe en SQLite.
Asi que aqui se sondea esa base. Es mas robusto que un webhook: si el
respondedor se cae y vuelve, retoma donde estaba sin perder nada, porque el
estado vive en el disco y no en memoria.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MESSAGES_DB = os.path.join(BASE_DIR, "..", "whatsapp-bridge", "store", "messages.db")
API_BASE = os.environ.get("WHATSAPP_API_BASE_URL", "http://localhost:8080/api")

GROUP_SUFFIX = "@g.us"
LID_SUFFIX = "@lid"


@dataclass(frozen=True)
class Message:
    id: str
    chat_jid: str
    sender: str
    content: str
    timestamp: datetime
    media_type: str | None

    @property
    def is_group(self) -> bool:
        return self.chat_jid.endswith(GROUP_SUFFIX)

    @property
    def sender_phone(self) -> str:
        """Numero del remitente, sin sufijo de servidor ni sufijo de dispositivo.

        Ojo: si el remitente viene como LID, esto devuelve el LID, no un
        numero. Usa phone_for_lid() para traducirlo.
        """
        return self.sender.split("@", 1)[0].split(":", 1)[0]

    @property
    def is_lid(self) -> bool:
        """El remitente viene identificado por LID en vez de por numero."""
        return self.sender.endswith(LID_SUFFIX)


class BridgeUnavailable(RuntimeError):
    pass


def _connect() -> sqlite3.Connection:
    if not os.path.exists(MESSAGES_DB):
        raise BridgeUnavailable(
            f"No existe {MESSAGES_DB}. Arranca el bridge primero: make bridge"
        )
    # Solo lectura: el bridge es el unico que escribe aqui.
    conn = sqlite3.connect(f"file:{MESSAGES_DB}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_incoming_since(after: datetime, limit: int = 50) -> list[Message]:
    """Mensajes entrantes posteriores a `after`, del mas antiguo al mas reciente.

    Excluye los propios (is_from_me) para no responderse a si mismo, que seria
    un bucle infinito con el primer mensaje que enviara.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, chat_jid, sender, content, timestamp, media_type
            FROM messages
            WHERE is_from_me = 0 AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (after, limit),
        ).fetchall()

    out: list[Message] = []
    for r in rows:
        ts = r["timestamp"]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        out.append(
            Message(
                id=r["id"],
                chat_jid=r["chat_jid"],
                sender=r["sender"] or "",
                content=r["content"] or "",
                timestamp=ts,
                media_type=r["media_type"],
            )
        )
    return out


def latest_timestamp() -> datetime:
    """Marca de agua inicial: solo se responde a lo que llegue de ahora en
    adelante, nunca al historial ya sincronizado."""
    with _connect() as conn:
        row = conn.execute("SELECT MAX(timestamp) AS t FROM messages").fetchone()
    t = row["t"] if row else None
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t)
        except ValueError:
            pass
    if isinstance(t, datetime):
        return t
    return datetime.now()


def send_message(recipient: str, text: str) -> tuple[bool, str]:
    """Envia por el bridge. `recipient` puede ser un numero o un JID completo."""
    try:
        resp = requests.post(
            f"{API_BASE}/send",
            json={"recipient": recipient, "message": text},
            timeout=30,
        )
    except requests.RequestException as e:
        return False, f"El bridge no responde ({e}). ¿Está corriendo?"

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        body = resp.json()
    except ValueError:
        return False, f"Respuesta no válida del bridge: {resp.text[:200]}"
    return bool(body.get("success")), str(body.get("message", ""))


def recent_chats(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT jid, name, last_message_time FROM chats
            WHERE last_message_time IS NOT NULL
            ORDER BY last_message_time DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_messages(query: str, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT m.chat_jid, c.name AS chat_name, m.sender, m.content,
                   m.timestamp, m.is_from_me
            FROM messages m LEFT JOIN chats c ON c.jid = m.chat_jid
            WHERE m.content LIKE ?
            ORDER BY m.timestamp DESC LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def chat_history(chat_jid: str, limit: int = 30) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sender, content, timestamp, is_from_me
            FROM messages WHERE chat_jid = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (chat_jid, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def download_media(message_id: str, chat_jid: str) -> str | None:
    """Descarga el adjunto de un mensaje y devuelve su ruta local."""
    try:
        resp = requests.post(
            f"{API_BASE}/download",
            json={"message_id": message_id, "chat_jid": chat_jid},
            timeout=120,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body.get("path") if body.get("success") else None


def send_audio(recipient: str, ogg_path: str) -> tuple[bool, str]:
    """Envia una nota de voz. El fichero debe ser .ogg opus: WhatsApp solo
    muestra la onda y el boton de reproducir con ese formato."""
    if not os.path.isfile(ogg_path):
        return False, f"No existe el fichero de audio: {ogg_path}"
    try:
        resp = requests.post(
            f"{API_BASE}/send",
            json={"recipient": recipient, "media_path": ogg_path},
            timeout=120,
        )
    except requests.RequestException as e:
        return False, f"El bridge no responde ({e})"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        body = resp.json()
    except ValueError:
        return False, f"Respuesta no válida: {resp.text[:200]}"
    return bool(body.get("success")), str(body.get("message", ""))


SESSION_DB = os.path.join(BASE_DIR, "..", "whatsapp-bridge", "store", "whatsapp.db")


def linked_number() -> str | None:
    """Numero al que esta vinculado el bridge, o None si no hay sesion.

    Es el numero DEL ASISTENTE. Nunca puede ser el del dueño: los mensajes
    propios no llegan como entrantes, asi que si alguien pone este numero en
    owner.phone, la conversacion con el dueño no se activa jamas.
    """
    if not os.path.exists(SESSION_DB):
        return None
    try:
        conn = sqlite3.connect(f"file:{SESSION_DB}?mode=ro", uri=True, timeout=5)
        row = conn.execute("SELECT jid FROM whatsmeow_device LIMIT 1").fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    return str(row[0]).split("@", 1)[0].split(":", 1)[0]


def phone_for_lid(lid: str) -> str | None:
    """Traduce un LID al numero de telefono, con el mapeo de whatsmeow.

    WhatsApp identifica cada vez a mas remitentes por LID (un identificador
    opaco) en vez de por numero. Sin traducirlo, comparar el remitente con el
    numero del dueño falla siempre y el dueño acaba tratado como un
    desconocido.
    """
    if not lid or not os.path.exists(SESSION_DB):
        return None
    bare = lid.split("@", 1)[0].split(":", 1)[0]
    try:
        conn = sqlite3.connect(f"file:{SESSION_DB}?mode=ro", uri=True, timeout=5)
        row = conn.execute(
            "SELECT pn FROM whatsmeow_lid_map WHERE lid = ? OR lid = ?",
            (lid, f"{bare}@lid"),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    return str(row[0]).split("@", 1)[0].split(":", 1)[0]
