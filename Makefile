.PHONY: setup activar voz bridge responder responder-check build check doctor clean

setup:   ## Instala dependencias y compila todo
	./scripts/setup.sh

bridge:  ## Arranca el bridge de WhatsApp (muestra el QR la primera vez)
	./scripts/bridge.sh

activar:         ## Guarda la clave de la API y deja el respondedor listo
	./scripts/activar.sh

voz:             ## Instala escucha y habla (sin sudo) y descarga una voz
	./scripts/voz.sh

responder:       ## Arranca el respondedor automatico (Aquiles)
	cd whatsapp-responder && uv run responder.py

responder-check: ## Valida la config del respondedor y su entorno
	cd whatsapp-responder && uv run responder.py --check

build:   ## Solo compila el bridge de Go
	cd whatsapp-bridge && CGO_ENABLED=1 go build -o bin/whatsapp-bridge .

check:   ## Verifica que bridge, servidor MCP y respondedor funcionan
	cd whatsapp-bridge && go vet ./... && go test ./...
	cd whatsapp-mcp-server && uv run python -c "import main; print('MCP OK:', len(main.mcp._tool_manager.list_tools()), 'tools')"
	cd whatsapp-responder && uv run pytest -q

doctor:  ## Diagnostica requisitos, build, sesion y bridge en ejecucion
	@./scripts/doctor.sh || true

clean:   ## Borra binarios y entornos de Python (NO borra sesión ni estado)
	rm -rf whatsapp-bridge/bin whatsapp-mcp-server/.venv whatsapp-responder/.venv
