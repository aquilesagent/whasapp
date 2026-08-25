"""La conversacion con el dueño: Claude con herramientas sobre su WhatsApp.

Solo se invoca para mensajes del dueño. Los terceros nunca llegan aqui — su
respuesta es un texto fijo — asi que ningun desconocido puede inyectar
instrucciones a un modelo que tiene estas herramientas.
"""

from __future__ import annotations

import anthropic
from anthropic import beta_tool

import wa
from state import State

_state: State | None = None
_owner_name = "el jefe"
_assistant_name = "Aquiles"


def configure(state: State, owner_name: str, assistant_name: str) -> None:
    """Las herramientas son funciones de modulo (el decorador genera el esquema
    a partir de la firma), asi que el estado se comparte por modulo."""
    global _state, _owner_name, _assistant_name
    _state = state
    _owner_name = owner_name
    _assistant_name = assistant_name


# --------------------------------------------------------------------------
# Herramientas
# --------------------------------------------------------------------------


@beta_tool
def enviar_whatsapp(destinatario: str, mensaje: str) -> str:
    """Envía un mensaje de WhatsApp a un contacto.

    Args:
        destinatario: Número con prefijo de país sin '+' (ej. 584121234567) o JID completo.
        mensaje: Texto a enviar.
    """
    ok, detail = wa.send_message(destinatario, mensaje)
    return f"Enviado a {destinatario}." if ok else f"No se pudo enviar: {detail}"


@beta_tool
def listar_chats(limite: int = 15) -> str:
    """Lista los chats con actividad más reciente.

    Args:
        limite: Cuántos chats devolver.
    """
    chats = wa.recent_chats(limite)
    if not chats:
        return "No hay chats sincronizados todavía."
    return "\n".join(
        f"- {c.get('name') or c['jid']} ({c['jid']}) — último: {c['last_message_time']}"
        for c in chats
    )


@beta_tool
def buscar_mensajes(texto: str, limite: int = 15) -> str:
    """Busca mensajes que contengan un texto, en todos los chats.

    Args:
        texto: Qué buscar.
        limite: Máximo de resultados.
    """
    hits = wa.search_messages(texto, limite)
    if not hits:
        return f"Sin resultados para '{texto}'."
    out = []
    for h in hits:
        quien = "yo" if h["is_from_me"] else (h.get("sender") or "?")
        chat = h.get("chat_name") or h["chat_jid"]
        out.append(f"[{h['timestamp']}] {chat} — {quien}: {(h.get('content') or '')[:200]}")
    return "\n".join(out)


@beta_tool
def leer_chat(chat_jid: str, limite: int = 25) -> str:
    """Lee los mensajes recientes de un chat concreto.

    Args:
        chat_jid: JID del chat, tal y como lo devuelve listar_chats.
        limite: Cuántos mensajes leer.
    """
    msgs = wa.chat_history(chat_jid, limite)
    if not msgs:
        return f"No hay mensajes en {chat_jid}."
    return "\n".join(
        f"[{m['timestamp']}] {'yo' if m['is_from_me'] else (m.get('sender') or '?')}: "
        f"{(m.get('content') or '')[:300]}"
        for m in msgs
    )


@beta_tool
def agendar_reunion(titulo: str, cuando: str, con_quien: str, notas: str = "") -> str:
    """Registra una reunión en la agenda del asistente.

    Args:
        titulo: De qué es la reunión.
        cuando: Fecha y hora tal y como se acordó (ej. 'martes 3 de marzo, 15:00').
        con_quien: Nombre o número de la otra parte.
        notas: Detalles adicionales, opcional.
    """
    if _state is None:
        return "Error interno: el asistente no está configurado."
    mid = _state.add_meeting(titulo, cuando, con_quien, notas)
    return (
        f"Reunión #{mid} agendada: '{titulo}' con {con_quien}, {cuando}."
        + (f" Notas: {notas}" if notas else "")
    )


@beta_tool
def listar_reuniones(limite: int = 15) -> str:
    """Lista las reuniones agendadas, de la más reciente a la más antigua.

    Args:
        limite: Cuántas devolver.
    """
    if _state is None:
        return "Error interno: el asistente no está configurado."
    ms = _state.list_meetings(limite)
    if not ms:
        return "No hay reuniones agendadas."
    return "\n".join(
        f"#{m['id']} {m['title']} — con {m['with_whom']}, {m['when_text']}"
        + (f" ({m['notes']})" if m["notes"] else "")
        for m in ms
    )


TOOLS = [
    enviar_whatsapp,
    listar_chats,
    buscar_mensajes,
    leer_chat,
    agendar_reunion,
    listar_reuniones,
]


def system_prompt() -> str:
    return f"""Eres {_assistant_name}, el asistente personal de {_owner_name}.

Hablas con {_owner_name} por WhatsApp. Él es la única persona con la que
conversas: los desconocidos reciben un saludo fijo que tú no generas.

Cómo responder:
- Estás en WhatsApp. Sé breve y directo. Nada de markdown, listas con viñetas
  ni encabezados: aquí no se renderizan.
- Cuando te pida algo que puedas hacer con tus herramientas, hazlo y confirma
  con el resultado real. No prometas hacerlo "en un momento".
- Si te falta un dato imprescindible (a qué número enviar, qué día es la
  reunión), pregúntalo en una sola frase.
- Si una herramienta falla, di qué falló en lenguaje llano. No lo disimules.
- Trátalo de usted y llámalo {_owner_name}.

Tienes acceso a su WhatsApp: puedes leer sus chats, buscar en su historial,
enviar mensajes en su nombre y llevarle la agenda de reuniones. Envía mensajes
a terceros solo cuando te lo pida explícitamente."""


def reply(user_text: str, history_turns: int, model: str) -> str:
    """Procesa un mensaje del dueño y devuelve la respuesta.

    Persiste el turno del usuario antes de llamar a la API, para que un fallo
    de red no borre lo que dijo.
    """
    if _state is None:
        raise RuntimeError("agent.configure() no ha sido llamado")

    _state.append_turn("user", user_text)
    messages = _state.recent_turns(history_turns)

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=4096,
        system=system_prompt(),
        tools=TOOLS,
        messages=messages,
    )

    final = None
    for message in runner:
        final = message

    if final is None:
        return "No he podido procesar eso, inténtelo de nuevo."

    text = "\n".join(b.text for b in final.content if b.type == "text").strip()
    if not text:
        text = "Hecho."
    _state.append_turn("assistant", text)
    return text
