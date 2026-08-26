"""Búsqueda de imágenes reales en Google (Custom Search JSON API).

A diferencia de imagen.py (que genera una imagen nueva con OpenAI), esto
busca una foto real que ya existe en internet. Es la API oficial de Google,
gratis hasta 100 búsquedas al día — sin tarjeta de crédito — y de pago
($5 / 1000 búsquedas) a partir de ahí.

Hacen falta dos valores, ambos gratis de conseguir:
  GOOGLE_API_KEY  - de https://console.cloud.google.com/apis/credentials,
                    con la "Custom Search API" habilitada.
  GOOGLE_CX       - el ID de un motor de búsqueda programable, creado en
                    https://programmablesearchengine.google.com/ con
                    "Búsqueda de imágenes" activada y "Buscar en toda la web".

Si falta cualquiera de los dos, la herramienta ni se ofrece al modelo: igual
que con imagen.py, mejor decir que no se puede a intentarlo y fallar delante
de quien escribe.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import requests

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "state", "imagenes_google")

ENDPOINT = "https://www.googleapis.com/customsearch/v1"


class BusquedaNoDisponible(RuntimeError):
    """No se puede buscar: faltan claves o falló la llamada."""


def _sin_claves(texto: str) -> str:
    """Igual que en imagen.py: la clave de Google puede aparecer citada en un
    error de la API, y ese texto vuelve al chat."""
    return re.sub(r"AIza[A-Za-z0-9_\-]{10,}", "AIza***", texto)


def disponible() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CX"))


def buscar(consulta: str) -> str:
    """Busca una imagen y devuelve la ruta del fichero descargado.

    Devuelve una ruta y no los bytes por lo mismo que imagen.generar(): quien
    la usa la manda por WhatsApp, y el bridge recibe rutas.
    """
    if not consulta.strip():
        raise BusquedaNoDisponible("No hay qué buscar")
    api_key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CX")
    if not api_key or not cx:
        raise BusquedaNoDisponible(
            "Faltan GOOGLE_API_KEY y/o GOOGLE_CX. Son gratis: una API key de "
            "Google Cloud con la Custom Search API activada, y el ID de un "
            "motor de búsqueda programable con búsqueda de imágenes activada."
        )

    try:
        resp = requests.get(
            ENDPOINT,
            params={
                "key": api_key,
                "cx": cx,
                "q": consulta,
                "searchType": "image",
                "num": 1,
                "safe": "active",
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise BusquedaNoDisponible(f"Fallo de red buscando: {e}") from e

    if resp.status_code != 200:
        raise BusquedaNoDisponible(
            f"Google respondió {resp.status_code}: "
            f"{_sin_claves(resp.text[:300])}"
        )

    items = resp.json().get("items") or []
    if not items:
        raise BusquedaNoDisponible(f"Sin resultados de imagen para '{consulta}'")

    url_imagen = items[0].get("link")
    if not url_imagen:
        raise BusquedaNoDisponible("El primer resultado no traía enlace de imagen")

    try:
        img = requests.get(url_imagen, timeout=30)
        img.raise_for_status()
    except requests.RequestException as e:
        raise BusquedaNoDisponible(
            f"Encontré la imagen pero no se pudo descargar: {e}") from e

    ext = os.path.splitext(url_imagen.split("?", 1)[0])[1] or ".jpg"
    if len(ext) > 5:  # una extension rara indica que no era realmente una
        ext = ".jpg"
    os.makedirs(SALIDA, exist_ok=True)
    ruta = os.path.join(SALIDA, f"{datetime.now():%Y%m%d-%H%M%S}{ext}")
    with open(ruta, "wb") as fh:
        fh.write(img.content)
    return ruta
