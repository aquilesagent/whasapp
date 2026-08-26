"""Comprueba que el servidor MCP carga y expone exactamente las 12 herramientas.

Se ejecuta contra varias versiones del SDK `mcp` para detectar de inmediato
cualquier ruptura de API como la de FastMCP -> MCPServer en la 2.0.
"""

import os
import sys

# Se invoca como `uv run python ../.github/scripts/check_tools.py` desde
# whatsapp-mcp-server/, asi que sys.path[0] apunta a este directorio y no al
# del servidor. Anadimos el cwd para poder importar main.
sys.path.insert(0, os.getcwd())

EXPECTED = {
    "search_contacts",
    "list_messages",
    "list_chats",
    "get_chat",
    "get_direct_chat_by_contact",
    "get_contact_chats",
    "get_last_interaction",
    "get_message_context",
    "send_message",
    "send_file",
    "send_audio_message",
    "download_media",
}


def main() -> int:
    import main as server

    found = {tool.name for tool in server.mcp._tool_manager.list_tools()}

    missing = EXPECTED - found
    extra = found - EXPECTED
    if missing:
        print(f"FALLO: faltan herramientas: {sorted(missing)}", file=sys.stderr)
    if extra:
        print(f"FALLO: herramientas inesperadas: {sorted(extra)}", file=sys.stderr)
    if missing or extra:
        return 1

    from importlib.metadata import version as pkg_version

    print(f"OK: {len(found)} herramientas cargadas con el SDK mcp {pkg_version('mcp')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
