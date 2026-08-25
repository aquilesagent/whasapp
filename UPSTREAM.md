# Origen del código y cambios locales

Este conector es un fork de **[lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)**
(MIT), el servidor MCP de WhatsApp más usado (~6.2k ★).

- Commit de origen: `7d6a06dcdce1f01dfb24f60e1030d5efba9f3b88` (2025-07-13)
- Licencia original conservada en [`LICENSE`](./LICENSE)

Se vendorizó en lugar de usarse como submódulo porque el upstream lleva sin
tocar el código desde abril de 2025 y necesitaba parches para seguir
conectando. Los cambios respecto al upstream son estos:

## 1. `whatsmeow` actualizado

El upstream fija `go.mau.fi/whatsmeow` en la versión del 2025-03-18. WhatsApp
rota el protocolo de WhatsApp Web con frecuencia y una versión vieja de
whatsmeow acaba fallando el handshake. Aquí está actualizado a
`v0.0.0-20260821141805-33cfac511629`.

La API nueva de whatsmeow exige `context.Context` en varias llamadas, así que
se añadió en los cinco puntos afectados de `whatsapp-bridge/main.go`:

| Llamada | Cambio |
| --- | --- |
| `client.Download` | `+ context.Background()` |
| `sqlstore.New` | `+ context.Background()` |
| `container.GetFirstDevice` | `+ context.Background()` |
| `client.GetGroupInfo` | `+ context.Background()` |
| `client.Store.Contacts.GetContact` | `+ context.Background()` |

## 2. Compatibilidad con el SDK de MCP 1.x y 2.x

El SDK de Python `mcp` 2.0 renombró `FastMCP` a `MCPServer` y movió el módulo,
lo que rompe el `import` del upstream. `whatsapp-mcp-server/main.py` ahora
intenta el import nuevo y cae al viejo si hace falta, así que funciona con
`mcp` 1.x y 2.x sin tocar nada.

## 3. Dependencias de Python actualizadas

`uv.lock` regenerado (`uv lock --upgrade`): `mcp` 1.6 → 2.1, más el resto de
transitivas.

## 4. El `direct_path` de los adjuntos

Descargar una nota de voz devolvía **403** desde `mmg.whatsapp.net`. La causa
está en cómo el upstream reconstruye la descarga: no guardaba el `direct_path`
que da WhatsApp, sino que lo derivaba de la URL cortando por `?`.

Ese corte es justo el problema. El `direct_path` real trae su propia query
string (`?ccb=…&oh=…&oe=…`), y ahí van los parámetros de autenticación del CDN.
Además whatsmeow une sus propios parámetros con `&`, no con `?`:

```go
mediaURL := fmt.Sprintf("https://%s%s&hash=%s&mms-type=%s…", host, directPath, …)
```

Con un path sin query, eso produce una URL sin `?` y sin autenticación. De ahí
el 403.

Ahora se guarda el `direct_path` tal cual lo entrega WhatsApp, en una columna
nueva. Las bases anteriores se migran con `ALTER TABLE` al abrirlas, en vez de
pedir que se borren: dentro está todo el historial sincronizado. Para los
mensajes viejos que no lo tengan se sigue derivando de la URL, con el fallo
conocido.

## 5. Añadidos de este repo

`scripts/setup.sh`, `scripts/bridge.sh`, `Makefile`, `.mcp.json` y `.gitignore`
(este último para que la sesión de WhatsApp y la base de mensajes nunca acaben
en un commit). Nada de esto existe en el upstream.

## Cómo traer cambios del upstream

```bash
git remote add upstream https://github.com/lharries/whatsapp-mcp.git
git fetch upstream
git diff HEAD upstream/main -- whatsapp-bridge whatsapp-mcp-server
```

Al integrar, revisa que los parches de arriba sigan aplicados.
