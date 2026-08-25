package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/mdp/qrterminal"
	waLog "go.mau.fi/whatsmeow/util/log"
	"rsc.io/qr"
)

// Payload con la forma de un QR real de WhatsApp: cuatro campos separados por
// comas, suficientemente largo para forzar una version alta del codigo.
const samplePayload = "2@aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789+/=,AbCdEf0123456789ghIJKL=,MnOpQr0123456789stUVWX=,1"

func TestWriteQRPNGProducesAScannableImage(t *testing.T) {
	dir := t.TempDir()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(cwd)

	if err := os.MkdirAll("store", 0755); err != nil {
		t.Fatal(err)
	}

	path, err := writeQRPNG(samplePayload)
	if err != nil {
		t.Fatalf("writeQRPNG: %v", err)
	}
	if !filepath.IsAbs(path) {
		t.Errorf("se esperaba una ruta absoluta para poder abrirla, se obtuvo %q", path)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("no se pudo leer el PNG escrito: %v", err)
	}
	if got, want := string(data[:8]), "\x89PNG\r\n\x1a\n"; got != want {
		t.Errorf("cabecera PNG = %q, se esperaba %q", got, want)
	}
	// A escala 8 la imagen debe ser lo bastante grande para escanearse desde
	// un visor; un QR minusculo es tan inutil como uno invertido.
	if len(data) < 1000 {
		t.Errorf("PNG de %d bytes, demasiado pequeno para escanear", len(data))
	}
}

// La polaridad es justo lo que rompe el escaneo en terminales de fondo claro,
// asi que ambas variantes deben ser opuestas modulo a modulo.
func TestTerminalQRConfigInvertsPolarity(t *testing.T) {
	t.Setenv("WHATSAPP_QR_INVERT", "")
	normal := terminalQRConfig()
	t.Setenv("WHATSAPP_QR_INVERT", "1")
	inverted := terminalQRConfig()

	if normal.BlackChar != qrterminal.BLACK_BLACK {
		t.Errorf("por defecto los modulos oscuros deben ir al fondo del terminal, se obtuvo %q", normal.BlackChar)
	}
	if inverted.BlackChar != qrterminal.WHITE_WHITE {
		t.Errorf("invertido los modulos oscuros deben dibujarse, se obtuvo %q", inverted.BlackChar)
	}
	if normal.BlackChar == inverted.BlackChar || normal.WhiteChar == inverted.WhiteChar {
		t.Error("las dos variantes deben ser opuestas, no iguales")
	}
	if normal.BlackWhiteChar == inverted.BlackWhiteChar || normal.WhiteBlackChar == inverted.WhiteBlackChar {
		t.Error("los medios bloques tambien deben invertirse, si no el QR sale mezclado")
	}
}

func TestEnvEnabled(t *testing.T) {
	for _, v := range []string{"1", "true", "TRUE", "yes", "si", " 1 "} {
		t.Setenv("WHATSAPP_QR_INVERT", v)
		if !envEnabled("WHATSAPP_QR_INVERT") {
			t.Errorf("envEnabled(%q) = false, se esperaba true", v)
		}
	}
	for _, v := range []string{"", "0", "false", "no"} {
		t.Setenv("WHATSAPP_QR_INVERT", v)
		if envEnabled("WHATSAPP_QR_INVERT") {
			t.Errorf("envEnabled(%q) = true, se esperaba false", v)
		}
	}
}

// El QR de WhatsApp es grande; comprobamos que cabe en una terminal normal
// con medios bloques, que es la razon de usarlos en vez de bloques enteros.
func TestSamplePayloadFitsInATerminal(t *testing.T) {
	c, err := qr.Encode(samplePayload, qr.L)
	if err != nil {
		t.Fatal(err)
	}
	rows := (c.Size+1)/2 + qrterminal.QUIET_ZONE
	if rows > 45 {
		t.Errorf("el QR ocupa %d filas; no cabe en una terminal tipica", rows)
	}
	t.Logf("QR de %d modulos -> %d filas en medios bloques", c.Size, rows)
}

var _ = waLog.Noop
