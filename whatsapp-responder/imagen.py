"""Generacion de imagenes.

Claude no genera imagenes, asi que esto sale de otro proveedor —OpenAI— con
su propia cuenta y su propia clave, facturada aparte de la de Anthropic. Es
la unica pieza del asistente que no depende de Claude.

Si no hay OPENAI_API_KEY, la herramienta ni se ofrece al modelo: es mejor que
Aquiles diga que no puede a que lo intente y falle delante de quien le
escribe.
"""

from __future__ import annotations

import base64
import os
import re
from datetime import datetime

# Tamaños que acepta la API. Se limita a estos tres para que el modelo no
# invente uno y la llamada falle a mitad de conversacion.
TAMANOS = {
    "cuadrada": "1024x1024",
    "horizontal": "1536x1024",
    "vertical": "1024x1536",
}

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "state", "imagenes")


class ImagenNoDisponible(RuntimeError):
    """No se puede generar: falta la clave, el paquete o falló la llamada."""


def _cliente():
    """Aislado para poder sustituirlo en las pruebas sin tocar la red."""
    from openai import OpenAI
    return OpenAI()


def _sin_claves(texto: str) -> str:
    """Quita cualquier cosa con forma de clave del mensaje de error.

    Este texto vuelve al modelo y de ahí al chat. Los proveedores citan la
    clave enviada en los errores de autenticación, así que sin esto una clave
    mal escrita acabaría enviada por WhatsApp.
    """
    return re.sub(r"\bsk-[A-Za-z0-9_\-]{6,}", "sk-***", texto)


def disponible() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


def generar(descripcion: str, forma: str = "cuadrada",
            modelo: str = "gpt-image-1") -> str:
    """Genera una imagen y devuelve la ruta del fichero.

    Devuelve una ruta y no los bytes porque quien la usa la envia por
    WhatsApp, y el bridge recibe rutas.
    """
    if not descripcion.strip():
        raise ImagenNoDisponible("No hay nada que dibujar")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ImagenNoDisponible(
            "Falta OPENAI_API_KEY. Es una clave de platform.openai.com, "
            "distinta de la de Anthropic y con su propia facturación."
        )
    tamano = TAMANOS.get(forma, TAMANOS["cuadrada"])

    try:
        cliente = _cliente()
    except ImportError as e:
        raise ImagenNoDisponible(
            "El paquete openai no está instalado: uv sync --extra imagenes"
        ) from e

    try:
        respuesta = cliente.images.generate(
            model=modelo,
            prompt=descripcion,
            size=tamano,
            n=1,
        )
    except Exception as e:  # la red y la API fallan de muchas formas
        raise ImagenNoDisponible(
            f"El proveedor de imágenes falló: {_sin_claves(str(e))}") from e

    if not respuesta.data:
        raise ImagenNoDisponible("El proveedor no devolvió ninguna imagen")

    imagen = respuesta.data[0]
    if imagen.b64_json:
        datos = base64.b64decode(imagen.b64_json)
    elif imagen.url:
        # Algunos modelos devuelven un enlace en vez de los bytes.
        import urllib.request
        with urllib.request.urlopen(imagen.url, timeout=120) as r:
            datos = r.read()
    else:
        raise ImagenNoDisponible("La respuesta no traía ni imagen ni enlace")

    os.makedirs(SALIDA, exist_ok=True)
    ruta = os.path.join(SALIDA, f"{datetime.now():%Y%m%d-%H%M%S}.png")
    with open(ruta, "wb") as fh:
        fh.write(datos)
    return ruta
