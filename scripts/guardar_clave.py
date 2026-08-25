"""Guarda una clave en el fichero de entorno sin borrar las demás.

Aquiles usa dos claves de proveedores distintos: la de Anthropic para hablar y
la de OpenAI solo para generar imágenes. Escribir el fichero entero cada vez
haría que guardar la segunda borrase la primera y lo dejase mudo, así que aquí
se reemplaza únicamente la línea de la variable que toca.

    python3 scripts/guardar_clave.py ~/.config/aquiles/env OPENAI_API_KEY sk-...
"""

from __future__ import annotations

import os
import sys


def upsert(path: str, nombre: str, valor: str) -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            lineas = fh.read().splitlines()
    except FileNotFoundError:
        lineas = []

    salida: list[str] = []
    puesta = False
    for linea in lineas:
        limpia = linea.strip()
        if limpia.startswith("export "):
            limpia = limpia[len("export "):].lstrip()
        if limpia.split("=", 1)[0].strip() == nombre:
            # Se conserva una sola línea por variable: si el fichero traía
            # duplicados, el respondedor se quedaría con el primero y no con
            # el que se acaba de guardar.
            if not puesta:
                salida.append(f"{nombre}={valor}")
                puesta = True
            continue
        salida.append(linea)
    if not puesta:
        salida.append(f"{nombre}={valor}")

    texto = "\n".join(salida).strip()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    os.chmod(path, 0o600)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    upsert(sys.argv[1], sys.argv[2], sys.argv[3])
