"""Elegir la voz de ElevenLabs con la que habla Aquiles.

Dos operaciones, y las dos existen para no tener que teclear un identificador
de 20 caracteres copiado de una web:

    python voces.py listar            qué voces hay, con su número
    python voces.py elegir [qué]      la deja puesta en config.toml y la prueba

`qué` puede ser un número de la lista, un trozo del nombre, o nada — sin nada
se queda con la primera, que es la mejor valorada de las que sirven.

Las voces del catálogo público hay que añadirlas a la cuenta antes de poder
usarlas; si no, la síntesis responde "voice_not_found". Eso lo hace `elegir`.
"""

from __future__ import annotations

import os
import re
import sys

import voice

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.toml")
MUESTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "state", "muestra-voz.ogg")

# Lo que dice la voz al probarla. Sirve para juzgarla: tiene números, una
# pregunta y palabras con acento, que es donde se delatan las voces malas.
FRASE = ("Hola, soy Aquiles, el asistente del señor Marcos. Tengo una reunión "
         "apuntada para el martes 3 a las cuatro y media. ¿Le confirmo?")


class SinClave(RuntimeError):
    pass


def _cliente():
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise SinClave(
            "Falta ELEVENLABS_API_KEY.\n"
            "  1. Crea una cuenta gratis en elevenlabs.io (10.000 caracteres al mes)\n"
            "  2. Copia la clave de elevenlabs.io/app/settings/api-keys\n"
            "  3. Ejecuta:  make activar"
        )
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError as e:
        raise SinClave(
            "El paquete elevenlabs no está instalado:  uv sync --extra real"
        ) from e
    return ElevenLabs()


def _propias(cliente) -> list[dict]:
    """Voces que la cuenta ya tiene. Estas se pueden usar directamente."""
    try:
        r = cliente.voices.search(page_size=100)
    except Exception as e:
        raise SinClave(f"No se pudo consultar ElevenLabs: {e}") from e
    return [
        {
            "voice_id": v.voice_id,
            "name": v.name or "",
            "accent": (v.labels or {}).get("accent", ""),
            "language": (v.labels or {}).get("language", ""),
            "propia": True,
            "public_owner_id": None,
        }
        for v in (r.voices or [])
    ]


def _catalogo(cliente, cuantas: int = 12) -> list[dict]:
    """Voces españolas del catálogo público, las mejor valoradas primero.

    Se filtran las que el plan gratuito no puede usar: ofrecer una voz que
    devolvería un error de permisos no ayuda a nadie.
    """
    try:
        r = cliente.voices.get_shared(language="es", page_size=cuantas * 3)
    except Exception as e:
        raise SinClave(f"No se pudo consultar el catálogo: {e}") from e

    fuera = []
    for v in (r.voices or []):
        if getattr(v, "free_users_allowed", True) is False:
            continue
        fuera.append({
            "voice_id": v.voice_id,
            "name": v.name or "",
            "accent": v.accent or "",
            "language": v.language or "",
            "descripcion": (v.description or "")[:100],
            "propia": False,
            "public_owner_id": v.public_owner_id,
        })
        if len(fuera) >= cuantas:
            break
    return fuera


def _neutra_primero(voces: list[dict]) -> list[dict]:
    """Ordena poniendo delante lo que suena neutro en Latinoamérica.

    "Neutro" no es un acento real sino la ausencia de marcas regionales; en las
    etiquetas de ElevenLabs eso aparece como es-latin-american, y en la
    descripción como la palabra 'neutro'. Un acento peninsular o muy marcado
    baja al final.
    """
    def puntos(v: dict) -> int:
        texto = f"{v.get('name','')} {v.get('descripcion','')}".lower()
        acento = (v.get("accent") or "").lower()
        p = 0
        if "latin-american" in acento or "latin american" in acento:
            p += 4
        if "neutr" in texto:
            p += 3
        if acento in ("es-mexican", "es-colombian"):
            p += 2          # los dos que más se usan como neutro de doblaje
        if acento in ("es-castilian", "es-spain", "es-peninsular"):
            p -= 3
        return -p           # negativo: menor va primero
    return sorted(voces, key=puntos)


def listar() -> list[dict]:
    cliente = _cliente()
    voces = _neutra_primero(_catalogo(cliente)) + _propias(cliente)
    for i, v in enumerate(voces, 1):
        marca = "ya en tu cuenta" if v["propia"] else "del catálogo"
        print(f"{i:2}. {v['name'][:44]:<44}  {v['accent'] or '?':<18} {marca}")
        if v.get("descripcion"):
            print(f"    {v['descripcion']}")
    print()
    print("Para dejar puesta una:  make voz-real VOZ=2")
    print("                        make voz-real VOZ=Carlos")
    return voces


def _escoger(voces: list[dict], que: str | None) -> dict:
    if not voces:
        raise SinClave("ElevenLabs no devolvió ninguna voz utilizable.")
    if not que:
        return voces[0]
    if que.isdigit():
        i = int(que)
        if not 1 <= i <= len(voces):
            raise SinClave(f"No hay una voz número {i}; hay {len(voces)}.")
        return voces[i - 1]
    for v in voces:
        if que.lower() in v["name"].lower():
            return v
    raise SinClave(f"Ninguna voz se llama algo parecido a '{que}'. "
                   f"Mira la lista con:  make voces")


def _anadir(cliente, v: dict) -> str:
    """Añade a la cuenta una voz del catálogo y devuelve su id definitivo.

    Al añadirla, ElevenLabs da un id nuevo: el del catálogo no sirve para
    sintetizar.
    """
    if v["propia"]:
        return v["voice_id"]
    nombre = re.sub(r"[^\w áéíóúñÁÉÍÓÚÑ-]", "", v["name"])[:40] or "Aquiles"
    try:
        r = cliente.voices.share(v["public_owner_id"], v["voice_id"],
                                 new_name=nombre)
    except Exception as e:
        if "already" in str(e).lower():
            return v["voice_id"]
        raise SinClave(f"No se pudo añadir la voz a tu cuenta: {e}") from e
    return getattr(r, "voice_id", v["voice_id"])


def _guardar_en_config(voice_id: str) -> None:
    """Escribe elevenlabs_voice en [voice] sin tocar el resto del fichero.

    Se hace con una expresión regular y no reescribiendo el TOML entero porque
    el fichero lleva comentarios que explican cada opción, y volcarlo desde un
    diccionario los borraría todos.
    """
    if not os.path.isfile(CONFIG):
        raise SinClave("No existe config.toml. Ejecuta antes:  make activar")
    src = open(CONFIG, encoding="utf-8").read()

    linea = f'elevenlabs_voice = "{voice_id}"'
    if re.search(r'(?m)^\s*elevenlabs_voice\s*=', src):
        src = re.sub(r'(?m)^\s*elevenlabs_voice\s*=.*$', linea, src, count=1)
    elif re.search(r'(?m)^\[voice\]', src):
        src = re.sub(r'(?m)^\[voice\]', f"[voice]\n{linea}", src, count=1)
    else:
        src = src.rstrip() + f"\n\n[voice]\n{linea}\n"

    # Sin esto la voz queda configurada pero nunca se usa.
    src = re.sub(r'(?m)^\s*reply_with_voice\s*=\s*false\s*$',
                 "reply_with_voice = true", src, count=1)

    open(CONFIG, "w", encoding="utf-8").write(src)


def elegir(que: str | None) -> int:
    cliente = _cliente()
    voces = _neutra_primero(_catalogo(cliente)) + _propias(cliente)
    v = _escoger(voces, que)

    print(f"==> Voz elegida: {v['name']}  ({v['accent'] or 'sin etiqueta'})")
    voice_id = _anadir(cliente, v)
    if not v["propia"]:
        print("    añadida a tu cuenta de ElevenLabs")

    _guardar_en_config(voice_id)
    print(f"    guardada en config.toml  (elevenlabs_voice = {voice_id})")

    print("==> Probándola")
    try:
        voice.synthesize(FRASE, MUESTRA, eleven_voice=voice_id)
    except voice.VoiceUnavailable as e:
        print(f"    ✗ no se pudo sintetizar: {e}")
        return 1
    print(f"    ✓ muestra en {MUESTRA}")
    print()
    print("Reinicia el respondedor y mándale una nota de voz:")
    print("    make responder")
    return 0


def main(argv: list[str]) -> int:
    accion = argv[1] if len(argv) > 1 else "listar"
    que = argv[2] if len(argv) > 2 else None
    try:
        if accion == "listar":
            listar()
            return 0
        if accion == "elegir":
            return elegir(que)
    except SinClave as e:
        print(e)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
