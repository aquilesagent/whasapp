# Arrancar Aquiles solo, al encender

Servicios de usuario: no hacen falta permisos de root y arrancan con tu sesión.

```bash
# 1. La clave de la API, fuera del repositorio.
#    Escríbela con un editor, no con echo: así no queda en el historial
#    de bash y no te arriesgas a copiar el ejemplo literal.
mkdir -p ~/.config/aquiles
nano ~/.config/aquiles/env      # una línea: ANTHROPIC_API_KEY=sk-ant-api03-...
chmod 600 ~/.config/aquiles/env
#    Sin "export": systemd solo entiende CLAVE=valor.

# 2. Instalar los servicios
mkdir -p ~/.config/systemd/user
cp ~/whasapp/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now whatsapp-bridge whatsapp-responder

# 3. Que sigan corriendo aunque cierres la sesión
sudo loginctl enable-linger "$USER"
```

Comprobar y seguir:

```bash
systemctl --user status whatsapp-bridge whatsapp-responder
journalctl --user -u whatsapp-responder -f
```

Los servicios suponen que el repositorio está en `~/whasapp` y `uv` en
`~/.local/bin/uv`. Si no, ajusta `WorkingDirectory` y `ExecStart`.

**La primera vinculación no se puede hacer como servicio**: necesita que veas
el QR o el código. Vincula a mano una vez (`make bridge`, o
`WHATSAPP_PHONE=... make bridge`), y ya luego habilita los servicios — la
sesión queda guardada en `whatsapp-bridge/store/`.

## En WSL

WSL arranca systemd solo si lo activas. En `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

y luego `wsl --shutdown` desde PowerShell. Si prefieres no usar systemd, deja
`make bridge` y `make responder` en dos terminales abiertas.
