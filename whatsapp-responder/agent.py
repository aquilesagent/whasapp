"""La conversacion con el dueño: Claude con herramientas sobre su WhatsApp.

Solo se invoca para mensajes del dueño. Los terceros nunca llegan aqui — su
respuesta es un texto fijo — asi que ningun desconocido puede inyectar
instrucciones a un modelo que tiene estas herramientas.
"""

from __future__ import annotations

import anthropic
from anthropic import beta_tool

import buscar_imagen
import imagen
import wa
from state import State

_state: State | None = None
_owner_name = "el jefe"
_owner_address = "jefe"
_assistant_name = "Aquiles"
# Chat que se esta atendiendo ahora. Lo necesita generar_imagen: la imagen no
# cabe en el texto de una respuesta, hay que enviarla como fichero al mismo
# chat del que vino la peticion.
_chat_jid: str | None = None


def configure(state: State, owner_name: str, assistant_name: str,
              owner_address: str | None = None) -> None:
    """Las herramientas son funciones de modulo (el decorador genera el esquema
    a partir de la firma), asi que el estado se comparte por modulo.

    owner_address es como se dirige a el (p.ej. "jefe"); owner_name es su
    nombre real, que el modelo conoce pero no usa para hablarle. Si no se
    especifica, se dirige a el por su nombre (comportamiento anterior).
    """
    global _state, _owner_name, _owner_address, _assistant_name
    _state = state
    _owner_name = owner_name
    _owner_address = owner_address or owner_name
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


@beta_tool
def generar_imagen(descripcion: str, forma: str = "cuadrada") -> str:
    """Genera una imagen a partir de una descripción y la envía a este chat.

    Args:
        descripcion: Qué debe aparecer en la imagen, con detalle. En español o inglés.
        forma: 'cuadrada', 'horizontal' o 'vertical'.
    """
    if _chat_jid is None:
        return "Error interno: no sé a qué chat enviar la imagen."
    try:
        ruta = imagen.generar(descripcion, forma)
    except imagen.ImagenNoDisponible as e:
        return f"No pude generar la imagen: {e}"

    ok, detail = wa.send_file(_chat_jid, ruta)
    if not ok:
        return f"La imagen se generó pero no se pudo enviar: {detail}"
    # El modelo tiende a describir de nuevo lo que ya se ve; se le dice que no.
    return ("Imagen generada y enviada al chat. Ya la está viendo: no la "
            "describas, solo pregunta si quiere cambios.")


@beta_tool
def buscar_imagen_real(consulta: str) -> str:
    """Busca una foto real que ya existe en internet (Google) y la envía a
    este chat. Úsala cuando pidan una foto real de algo concreto, no un
    dibujo o una imagen inventada — para eso está generar_imagen.

    Args:
        consulta: Qué buscar, como lo escribirías en el buscador de Google.
    """
    if _chat_jid is None:
        return "Error interno: no sé a qué chat enviar la imagen."
    try:
        ruta = buscar_imagen.buscar(consulta)
    except buscar_imagen.BusquedaNoDisponible as e:
        return f"No pude buscar la imagen: {e}"

    ok, detail = wa.send_file(_chat_jid, ruta)
    if not ok:
        return f"Encontré la imagen pero no se pudo enviar: {detail}"
    return ("Imagen encontrada y enviada al chat. Ya la está viendo: no la "
            "describas, solo pregunta si quiere otra.")


TOOLS = [
    enviar_whatsapp,
    listar_chats,
    buscar_mensajes,
    leer_chat,
    agendar_reunion,
    listar_reuniones,
]

# Buscar en internet lo ejecuta Anthropic en sus servidores: no hay funcion
# que implementar, ni proveedor aparte, ni otra clave. Se pasa el diccionario
# tal cual junto a las demas herramientas.
BUSQUEDA_WEB = {
    "type": "web_search_20260209",
    "name": "web_search",
    # Sin tope, una sola pregunta puede encadenar muchas busquedas, y cada
    # una se factura. Cinco cubre de sobra una consulta por WhatsApp.
    "max_uses": 5,
}


def herramientas(con_busqueda: bool, con_imagenes: bool | None = None,
                  con_busqueda_imagen: bool | None = None) -> list:
    """La lista que ve el modelo.

    generar_imagen y buscar_imagen_real solo aparecen si de verdad se pueden
    usar. Ofrecer una herramienta que va a fallar es peor que no ofrecerla: el
    modelo la promete, la llama, y el fallo sale en mitad de la conversacion.
    """
    if con_imagenes is None:
        con_imagenes = imagen.disponible()
    if con_busqueda_imagen is None:
        con_busqueda_imagen = buscar_imagen.disponible()
    tools = list(TOOLS)
    if con_imagenes:
        tools.append(generar_imagen)
    if con_busqueda_imagen:
        tools.append(buscar_imagen_real)
    if con_busqueda:
        tools.append(BUSQUEDA_WEB)
    return tools


def system_prompt() -> str:
    return f"""Eres {_assistant_name}, el asistente personal de {_owner_name}.

Hablas con él por WhatsApp. Es la única persona con la que conversas: los
desconocidos reciben un saludo fijo que tú no generas. Sabes que se llama
{_owner_name}, pero te diriges a él como "{_owner_address}" — nunca lo llames
por su nombre.

Cómo responder:
- Estás en WhatsApp. Sé breve y directo. Nada de markdown, listas con viñetas
  ni encabezados: aquí no se renderizan.
- Cuando te pida algo que puedas hacer con tus herramientas, hazlo y confirma
  con el resultado real. No prometas hacerlo "en un momento".
- Si te falta un dato imprescindible (a qué número enviar, qué día es la
  reunión), pregúntalo en una sola frase.
- Si una herramienta falla, di qué falló en lenguaje llano. No lo disimules.
- Trátalo de usted y llámalo {_owner_address}, nunca por su nombre.

Tienes acceso a su WhatsApp: puedes leer sus chats, buscar en su historial,
enviar mensajes en su nombre y llevarle la agenda de reuniones. Envía mensajes
a terceros solo cuando te lo pida explícitamente.

Si tienes generar_imagen, úsala cuando te pidan una imagen, un dibujo, un
logo o una idea visual que no existe todavía. Si tienes buscar_imagen_real,
úsala cuando pidan una foto real de algo concreto (una persona, un lugar, un
animal, un producto) en vez de algo inventado. Ante la duda de cuál usar,
pregunta o usa la de búsqueda: casi siempre "una foto de X" pide algo real.
La imagen llega sola al chat en ambos casos: no describas lo que acabas de
mandar. Si no tienes la que hace falta, dilo claro: "no tengo generación de
imágenes activada" o "no tengo búsqueda de imágenes activada", según cuál
falte.

Si tienes búsqueda web, úsala cuando la respuesta dependa de algo actual —
precios, noticias, horarios, disponibilidad— o cuando no estés seguro. No la
uses para lo que ya sabes. Di siempre de dónde sacaste el dato."""


def reply(chat_jid: str, user_text: str, history_turns: int, model: str,
          buscar_en_web: bool = False, con_imagenes: bool | None = None,
          con_busqueda_imagen: bool | None = None) -> str:
    """Procesa un mensaje del dueño y devuelve la respuesta.

    Persiste el turno del usuario antes de llamar a la API, para que un fallo
    de red no borre lo que dijo.
    """
    if _state is None:
        raise RuntimeError("agent.configure() no ha sido llamado")

    global _chat_jid
    _chat_jid = chat_jid

    _state.append_turn(chat_jid, "user", user_text)
    messages = _state.recent_turns(chat_jid, history_turns)

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=4096,
        system=system_prompt(),
        tools=herramientas(buscar_en_web, con_imagenes, con_busqueda_imagen),
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
    _state.append_turn(chat_jid, "assistant", text)
    return text
