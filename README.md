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
| Go | **1.26+** (lo exige whatsmeow). Con una versión anterior, Go se descarga la cadena correcta solo si tiene red. |
| Compilador de C | `gcc`/`cc` — `go-sqlite3` es una extensión en C y se compila con CGO |
| Python | 3.11+ |
| [uv](https://docs.astral.sh/uv/) | gestor de paquetes de Python |
| ffmpeg | opcional, solo para `send_audio_message` con `.mp3`/`.wav` |

`make setup` comprueba las cuatro y te dice qué instalar si falta algo.

### Windows

Usa **WSL** y sigue las instrucciones de Linux; es con diferencia lo más
sencillo. En un WSL recién instalado te faltarán el compilador y las
herramientas:

```bash
sudo apt update && sudo apt install -y build-essential git
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -sSL https://go.dev/dl/go1.26.0.linux-amd64.tar.gz | sudo tar -C /usr/local -xz
echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/.local/bin' >> ~/.bashrc && source ~/.bashrc
```

Si prefieres Windows nativo, necesitas MSYS2 para el compilador de C y
`CGO_ENABLED=1`.

## Instalación

```bash
git clone https://github.com/aquilesagent/whasapp.git
cd whasapp
make setup          # comprueba requisitos, compila el bridge, instala deps
```

Todo lo que viene después se ejecuta **dentro de ese directorio**. Si
`make` responde `No targets specified`, es que no estás en él o el clonado
no llegó a hacerse.

### Vincular el móvil

```bash
make bridge
```

**El QR se dibuja en la propia terminal**, no en `web.whatsapp.com`. No hace
falta abrir ninguna página: el bridge *sustituye* a WhatsApp Web, se vincula
como un dispositivo más. Verás algo así:

```
Scan this QR code with your WhatsApp app:

▄▄▄▄▄▄▄ ▄▄  ▄ ▄▄▄▄▄▄▄
█ ▄▄▄ █ ▀█▄▀▀ █ ▄▄▄ █
█ ███ █ █ ▄▀█ █ ███ █
...
```

Con eso en pantalla, en el móvil: **WhatsApp → Ajustes → Dispositivos
vinculados → Vincular un dispositivo**, y apunta la cámara al QR de la
terminal.

#### Si el QR de la terminal no se lee

Es lo que más falla, y casi siempre por una de estas tres razones. Hay una
salida para cada una:

**1. Escanea la imagen en vez de la terminal.** El bridge guarda cada QR
también como PNG y te imprime la ruta:

```
whatsapp-bridge/store/qr.png
```

Ábrelo con cualquier visor de imágenes y escanea eso. Es el camino más
fiable: no depende de fuentes, colores ni tamaño de ventana.

**2. Terminal de fondo claro → el QR sale invertido.** Los bloques se dibujan
con el color de fondo de tu terminal, así que sobre fondo blanco los módulos
salen al revés y el móvil no lo reconoce. Dale la vuelta:

```bash
WHATSAPP_QR_INVERT=1 make bridge
```

**3. Olvídate del QR: vincula con un código.** WhatsApp permite vincular
tecleando un código de 8 caracteres. Pasa tu número con prefijo de país, sin
`+` ni espacios:

```bash
WHATSAPP_PHONE=34600111222 make bridge
```

El bridge imprime algo así:

```
 Numero: 34600111222
 Codigo: ABCD-EFGH
```

Y en el móvil: **Dispositivos vinculados → Vincular un dispositivo →
Vincular con el número de teléfono**, y tecleas el código.

**Otras dos cosas**: si el QR sale cortado, maximiza la ventana y reduce el
tamaño de letra (`Ctrl -` / `Cmd -`) — necesita unas 40 líneas. Y el QR se
renueva solo cada pocos segundos; el bridge espera 10 minutos antes de
rendirse.

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

## Aquiles — el respondedor automático

Además del MCP (donde tú preguntas y Claude responde), el repo trae un
**respondedor** que atiende WhatsApp solo, por dos caminos separados:

- **Cualquiera que te escriba** recibe un texto fijo de presentación. No pasa
  por ningún modelo, así que nadie puede manipularlo con lo que escriba.
- **Tú** conversas con Claude, que tiene herramientas para leer tus chats,
  buscar en tu historial, enviar mensajes en tu nombre y llevarte la agenda.

También transcribe las notas de voz que le manden, y puede responder en voz.

```bash
cd whatsapp-responder
cp config.example.toml config.toml   # pon tu número en owner.phone
export ANTHROPIC_API_KEY=sk-ant-...
cd .. && make responder
```

Detalles completos en [`whatsapp-responder/README.md`](./whatsapp-responder/README.md).
Para dejarlo arrancado al encender el equipo, [`systemd/README.md`](./systemd/README.md).

## Uso

Con el bridge corriendo, en Claude:

> Busca en mis chats de WhatsApp de qué hablé con Laura la semana pasada y hazme un resumen.

> Mándale a mi hermano por WhatsApp el PDF que hay en ~/Documentos/factura.pdf

## Comandos

```bash
make setup    # instala todo
make bridge   # arranca el bridge (QR la primera vez)
make doctor   # diagnostica qué falta o qué está fallando
make responder # arranca Aquiles, el respondedor automático
make build    # solo compila el bridge
make check    # verifica que bridge y servidor MCP cargan
make clean    # borra binarios y .venv (conserva la sesión de WhatsApp)
```

Variables que entiende el bridge:

| Variable | Efecto |
| --- | --- |
| `WHATSAPP_PHONE` | Vincula con código de 8 caracteres en vez de QR. Número con prefijo de país, sin `+`. |
| `WHATSAPP_QR_INVERT` | Invierte el QR de la terminal, para fondos claros. |

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
| No encuentro dónde escanear | El QR sale **en la terminal** donde corriste `make bridge`, no en web.whatsapp.com. |
| El QR no se lee | Abre `whatsapp-bridge/store/qr.png` y escanea la imagen. |
| El QR se ve invertido | Terminal de fondo claro: `WHATSAPP_QR_INVERT=1 make bridge`. |
| El QR no hay manera | Salta el QR: `WHATSAPP_PHONE=34600111222 make bridge`. |
| El QR sale cortado o deforme | Agranda la ventana y reduce el tamaño de letra hasta que quepa entero. |
| El QR no aparece | Borra `whatsapp-bridge/store/` y vuelve a arrancar el bridge. |
| `no such table: messages` | El bridge no ha corrido nunca o no terminó de sincronizar. |
| Claude dice que no puede enviar | El bridge no está corriendo. `make bridge`. |
| `undefined: ... sqlite3` al compilar | Falta el compilador de C: `sudo apt install build-essential`. |
| `make: No targets specified` | No estás dentro del directorio `whasapp`, o no lo has clonado. |
| `requires go >= 1.26.0` | Go demasiado viejo y sin red para autodescargarse. Instálalo desde [go.dev/dl](https://go.dev/dl/). |
| Dejó de conectar tras semanas | Sesión caducada: borra `whatsapp-bridge/store/` y reescanea. |
| Un contacto sale sin nombre | Si WhatsApp lo expone como `@lid`, el bridge lo traduce a número; si el mapeo aún no ha llegado, verás el identificador hasta que sincronice. |
| `Ya hay un bridge escuchando` | Correcto: solo puede haber uno. `make doctor` te dice cómo está el que corre. |

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
