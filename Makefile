.PHONY: setup bridge build check doctor clean

setup:   ## Instala dependencias y compila todo
	./scripts/setup.sh

bridge:  ## Arranca el bridge de WhatsApp (muestra el QR la primera vez)
	./scripts/bridge.sh

build:   ## Solo compila el bridge de Go
	cd whatsapp-bridge && CGO_ENABLED=1 go build -o bin/whatsapp-bridge .

check:   ## Verifica que bridge y servidor MCP cargan correctamente
	cd whatsapp-bridge && go vet ./...
	cd whatsapp-mcp-server && uv run python -c "import main; print('MCP OK:', len(main.mcp._tool_manager.list_tools()), 'tools')"

doctor:  ## Diagnostica requisitos, build, sesion y bridge en ejecucion
	@./scripts/doctor.sh || true

clean:   ## Borra binarios y entorno de Python (NO borra la sesión de WhatsApp)
	rm -rf whatsapp-bridge/bin whatsapp-mcp-server/.venv
