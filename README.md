# Conector de WhatsApp para Claude (MCP)

Conecta tu WhatsApp personal a Claude Code / Claude Desktop / Cursor mediante
el **Model Context Protocol**. Claude puede buscar contactos, leer tu historial
de chats y enviar mensajes, archivos y notas de voz.

Todo corre en local: los mensajes se guardan en un SQLite tuyo y solo salen de
tu máquina los que Claude lee explícitamente para responderte.

Fork de [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) con
las dependencias puestas al día — ver [UPSTREAM.md](./UPSTREAM.md).

---

## Cómo funciona

```
WhatsApp  ──websocket──►  whatsapp-bridge (Go, whatsmeow)  ──►  store/messages.db
                                    │                                  │
                            REST :8080/api                       lectura SQL
                                    │                                  │
                                    └──►  whatsapp-mcp-server (Python)  ◄┘
                                                    │
                                                   MCP
                                                    ▼
                                                 Claude
```

Son dos procesos:

- **`whatsapp-bridge/`** — cliente Go sobre [whatsmeow](https://github.com/tulir/whatsmeow).
  Se vincula a tu cuenta como un dispositivo más (igual que WhatsApp Web),
  sincroniza los mensajes a SQLite y expone una API REST en `localhost:8080`
  para enviar.
- **`whatsapp-mcp-server/`** — servidor MCP en Python. Lee la base directamente
  y llama al bridge para enviar.

El bridge tiene que estar corriendo para que el MCP funcione.

## Requisitos

| | |
| --- | --- |
| Go | 1.24+ (con CGO — `go-sqlite3` es una extensión en C) |
| Python | 3.11+ |
| [uv](https://docs.astral.sh/uv/) | gestor de paquetes de Python |
| ffmpeg | opcional, solo para `send_audio_message` con `.mp3`/`.wav` |

En Windows hace falta un compilador de C (MSYS2) y `CGO_ENABLED=1`.

## Instalación

```bash
git clone https://github.com/aquilesagent/whasapp.git
cd whasapp
make setup          # comprueba requisitos, compila el bridge, instala deps
```

Después, arranca el bridge y escanea el QR con el móvil
(**WhatsApp → Ajustes → Dispositivos vinculados → Vincular dispositivo**):

```bash
make bridge
```

La primera sincronización tarda un rato según tu historial. La sesión queda
guardada en `whatsapp-bridge/store/`, así que solo escaneas una vez —
WhatsApp la caduca cada ~20 días y entonces toca repetir el QR.

### Conectarlo a Claude

**Claude Code** — nada que hacer: el repo trae [`.mcp.json`](./.mcp.json) y se
detecta al abrir el proyecto. Confírmalo con `/mcp`.

**Claude Desktop / Cursor** — `make setup` imprime al final el bloque JSON con
las rutas absolutas ya rellenadas. Pégalo en:

- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Cursor: `~/.cursor/mcp.json`

y reinicia la app.

## Herramientas disponibles

| Herramienta | Qué hace |
| --- | --- |
| `search_contacts` | Busca contactos por nombre o número |
| `list_chats` | Lista chats con filtros y orden |
| `get_chat` | Metadatos de un chat concreto |
| `get_direct_chat_by_contact` | Chat directo con un contacto |
| `get_contact_chats` | Todos los chats donde aparece un contacto |
| `list_messages` | Mensajes con filtros de fecha, remitente y texto |
| `get_message_context` | Mensajes anteriores y posteriores a uno dado |
| `get_last_interaction` | Último mensaje con un contacto |
| `send_message` | Envía texto a un contacto o grupo |
| `send_file` | Envía imagen, vídeo, audio o documento |
| `send_audio_message` | Envía nota de voz (`.ogg opus`, o cualquier formato si hay ffmpeg) |
| `download_media` | Descarga el adjunto de un mensaje y devuelve la ruta |

## Uso

Con el bridge corriendo, en Claude:

> Busca en mis chats de WhatsApp de qué hablé con Laura la semana pasada y hazme un resumen.

> Mándale a mi hermano por WhatsApp el PDF que hay en ~/Documentos/factura.pdf

## Comandos

```bash
make setup    # instala todo
make bridge   # arranca el bridge (QR la primera vez)
make doctor   # diagnostica qué falta o qué está fallando
make build    # solo compila el bridge
make check    # verifica que bridge y servidor MCP cargan
make clean    # borra binarios y .venv (conserva la sesión de WhatsApp)
```

## Privacidad y riesgos

- **Tus mensajes se guardan sin cifrar** en `whatsapp-bridge/store/messages.db`.
  Está en `.gitignore`, pero es un fichero con todo tu historial: trátalo como
  tal y cifra el disco.
- **Claude solo ve lo que pide.** Los mensajes van a la API de Anthropic
  únicamente cuando una herramienta los devuelve como respuesta a algo que le
  preguntaste.
- **Es un cliente no oficial.** Usa el mismo protocolo que WhatsApp Web vía
  ingeniería inversa, no la API de negocio de Meta. Va contra los Términos de
  Servicio de WhatsApp y **existe riesgo de que baneen la cuenta**, sobre todo
  con envío masivo o automatizado. Para un caso comercial, lo correcto es la
  [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api)
  de Meta.

## Problemas comunes

| Síntoma | Solución |
| --- | --- |
| `Failed to connect: ... Forbidden` | Sin salida a `web.whatsapp.com` (proxy/firewall/sandbox). Comprueba la red. |
| El QR no aparece | Borra `whatsapp-bridge/store/` y vuelve a arrancar el bridge. |
| `no such table: messages` | El bridge no ha corrido nunca o no terminó de sincronizar. |
| Claude dice que no puede enviar | El bridge no está corriendo. `make bridge`. |
| `undefined: ... sqlite3` al compilar | Falta CGO o un compilador de C. Exporta `CGO_ENABLED=1`. |
| Dejó de conectar tras semanas | Sesión caducada: borra `whatsapp-bridge/store/` y reescanea. |

Ante cualquier duda, `make doctor` revisa requisitos, build, sesión vinculada,
mensajes sincronizados y si el bridge está escuchando, y te dice qué arreglar.

## Mantenimiento

El upstream se quedó atrás porque nadie notó que sus dependencias habían
dejado de funcionar. Para que no se repita, [`.github/workflows/ci.yml`](./.github/workflows/ci.yml)
corre en cada push **y todos los lunes**:

- compila el bridge con CGO, pasa `go vet` y comprueba que el binario arranca
  y llega a llamar a whatsmeow;
- carga el servidor MCP contra tres versiones del SDK (`uv.lock`, `mcp` 1.6.0
  y la última) y verifica que las 12 herramientas siguen ahí.

Si un lunes CI se pone en rojo sin que hayas tocado nada, es que una
dependencia rompió algo — y te enteras entonces, no el día que lo necesitas.

## Licencia

MIT — ver [LICENSE](./LICENSE). Código original de
[lharries](https://github.com/lharries/whatsapp-mcp).
