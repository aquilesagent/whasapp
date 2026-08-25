package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// El direct path que da WhatsApp trae su propia query string, y ahi van los
// parametros de autenticacion del CDN. whatsmeow los conserva porque une sus
// propios parametros con "&" en vez de "?", asi que un path sin query produce
// una URL sin autenticacion y el CDN responde 403.
const directPathReal = "/v/t62.7117-24/13812002_698058036224062_3424455886509161511_n.enc" +
	"?ccb=11-4&oh=01_Q5AaIQ&oe=66F3A1B2&_nc_sid=5e03e0"

func TestExtractDirectPathFromURLLosesTheAuthQuery(t *testing.T) {
	url := "https://mmg.whatsapp.net" + directPathReal
	got := extractDirectPathFromURL(url)

	if strings.Contains(got, "oh=") || strings.Contains(got, "oe=") {
		t.Fatalf("la funcion ya conserva la query; revisa si sigue haciendo falta guardar direct_path")
	}
	if got == directPathReal {
		t.Fatalf("se esperaba una version recortada, se obtuvo el path completo")
	}
	// Esto es exactamente lo que rompia: sin oh/oe, el CDN devuelve 403.
	t.Logf("derivado de la url: %s", got)
}

func TestWhatsmeowAppendsWithAmpersandSoThePathNeedsItsQuery(t *testing.T) {
	// whatsmeow construye: "https://" + host + directPath + "&hash=..."
	// Si directPath no lleva "?", la URL resultante no tiene query valida.
	sinQuery := "/v/t62.7117-24/foo.enc"
	construida := "https://host" + sinQuery + "&hash=abc&mms-type=WhatsAppAudio"
	if strings.Contains(construida, "?") {
		t.Fatal("una URL sin '?' no puede llevar parametros; ese es el fallo")
	}

	conQuery := "https://host" + directPathReal + "&hash=abc&mms-type=WhatsAppAudio"
	if !strings.Contains(conQuery, "?ccb=") || !strings.Contains(conQuery, "&hash=") {
		t.Fatal("con la query original, los parametros de whatsmeow encajan detras")
	}
}

// Una base creada antes de que existiera direct_path debe migrarse sola: dentro
// esta todo el historial ya sincronizado y borrarla no es una opcion.
func TestOpenAddsDirectPathToAnOlderDatabase(t *testing.T) {
	dir := t.TempDir()
	// NewMessageStore abre store/messages.db relativo al directorio actual.
	if err := os.MkdirAll(filepath.Join(dir, "store"), 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "store", "messages.db")

	viejo, err := sql.Open("sqlite3", "file:"+path+"?_foreign_keys=on")
	if err != nil {
		t.Fatal(err)
	}
	_, err = viejo.Exec(`
		CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
		CREATE TABLE messages (
			id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
			is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT,
			media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
			PRIMARY KEY (id, chat_jid));
		INSERT INTO chats VALUES ('x@s.whatsapp.net', 'X', NULL);
		INSERT INTO messages (id, chat_jid, content)
			VALUES ('m1', 'x@s.whatsapp.net', 'historial que no se debe perder');
	`)
	if err != nil {
		t.Fatal(err)
	}
	viejo.Close()

	anterior, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(anterior)

	store, err := NewMessageStore()
	if err != nil {
		t.Fatalf("abrir una base antigua debería migrarla, no fallar: %v", err)
	}
	defer store.Close()

	var contenido string
	if err := store.db.QueryRow(
		"SELECT content FROM messages WHERE id = 'm1'").Scan(&contenido); err != nil {
		t.Fatalf("el historial anterior debe seguir ahí: %v", err)
	}
	if contenido != "historial que no se debe perder" {
		t.Fatalf("contenido = %q", contenido)
	}

	if err := store.StoreMessage("m2", "x@s.whatsapp.net", "y", "hola",
		nowForTest(), false, "audio", "a.ogg", "https://u", directPathReal,
		nil, nil, nil, 0); err != nil {
		t.Fatalf("guardar con direct_path tras migrar: %v", err)
	}

	_, _, _, got, _, _, _, _, err := store.GetMediaInfo("m2", "x@s.whatsapp.net")
	if err != nil {
		t.Fatal(err)
	}
	if got != directPathReal {
		t.Fatalf("direct_path = %q, se esperaba el guardado intacto", got)
	}
}

func nowForTest() time.Time { return time.Unix(1756000000, 0) }
