"""Capa determinista del experto de prompts de imagen: añade lo que es TEXTO FIJO según la ficha del modelo (prefijo de calidad y línea de prompt negativo).

El núcleo escribe solo el CUERPO creativo del prompt (sujeto, entorno, luz, estilo…); esta capa lo completa. Así el formato es correcto por construcción, el modelo no gasta capacidad
memorizando listas y tokens raros («score_9, score_8_up…») y cambiar una regla de un modelo es editar una línea, no reentrenar.
"""
from imagen_fichas import NEGATIVO_ILL, NEGATIVO_NL, NEGATIVO_PONY, NEGATIVO_SD

NEGATIVO_TEXTO_QWEN = ", distorted text, misspelled letters"
MARCAS = ("masterpiece", "best quality", "score_9", "score_8_up", "newest", "absurdres")


def formatear(k, cuerpo, con_texto=False, limpiar=True):
    """Prompt final para el modelo `k` a partir del cuerpo escrito por el núcleo. Idempotente: si el cuerpo ya trae prefijo o negativo, no los duplica."""
    cuerpo = cuerpo.split("\nNegative prompt:")[0]
    cuerpo = limpiar_cuerpo(cuerpo) if limpiar else cuerpo.strip()
    bajo = cuerpo.lower()
    if k == "sdxl":
        pre, neg = ("" if bajo.startswith("masterpiece") else "masterpiece, best quality, "), NEGATIVO_SD
    elif k == "sd15":
        pre, neg = ("" if bajo.startswith("masterpiece") else "masterpiece, best quality, highly detailed, "), NEGATIVO_SD + ", lowres"
    elif k == "pony":
        pre, neg = ("" if bajo.startswith("score_9") else "score_9, score_8_up, score_7_up, "), NEGATIVO_PONY
    elif k == "illustrious":
        pre, neg = ("" if bajo.startswith("masterpiece") else "masterpiece, best quality, newest, absurdres, "), NEGATIVO_ILL
    elif k in ("z-image-base", "qwen-image"):
        pre, neg = "", NEGATIVO_NL + (NEGATIVO_TEXTO_QWEN if con_texto and k == "qwen-image" else "")
    else:  # flux, z-image-turbo: sin prompt negativo
        return cuerpo
    return f"{pre}{cuerpo}\nNegative prompt: {neg}"


def cuerpo_de(k, completo):
    """Inverso de `formatear`: el cuerpo creativo de un prompt completo (para construir los datos de entrenamiento)."""
    t = completo.split("\nNegative prompt:")[0].strip()
    for pre in ("masterpiece, best quality, highly detailed, ", "masterpiece, best quality, newest, absurdres, ", "masterpiece, best quality, ", "score_9, score_8_up, score_7_up, "):
        if t.startswith(pre):
            return t[len(pre):]
    return t


# ---------------------------------------------------------------------------------------------- limpieza determinista del cuerpo escrito por el núcleo
import re as _re

_ACENTUADA = _re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ¿¡]")


def limpiar_cuerpo(t):
    """Quita los defectos típicos de una generación voraz de un núcleo pequeño, sin cambiar lo que dice:
      · palabras con tilde/ñ FUERA de comillas (el prompt es en inglés: son fugas del español; el texto pedido para la imagen va entre comillas y se respeta)
      · palabras repetidas seguidas («biens biens») y oraciones repetidas
      · en prompts de etiquetas (con comas), etiquetas duplicadas («8k, 8k, 8k»; se conserva la primera) y una etiqueta final cortada a medias
    """
    t = t.strip()
    partes = _re.split(r'("[^"]*")', t)  # lo que está entre comillas se respeta tal cual
    for i in range(0, len(partes), 2):
        palabras = [w for w in partes[i].split(" ") if not _ACENTUADA.search(w)]
        salida = []
        for w in palabras:
            if salida and w.lower().strip(",.;") == salida[-1].lower().strip(",.;") and len(w.strip(",.;")) > 1:
                continue  # palabra repetida seguida
            salida.append(w)
        partes[i] = " ".join(salida)
    t = "".join(partes)
    t = _re.sub(r"\s+([,.;:])", r"\1", t)
    if t.count(",") >= 4 and "." not in t.replace("...", ""):  # estilo etiquetas
        vistas, tags = set(), []
        for tag in [x.strip() for x in t.split(",")]:
            clave = _re.sub(r"[\s()\d.:]+", " ", tag.lower()).strip()
            if tag and clave not in vistas:
                vistas.add(clave)
                tags.append(tag)
        if len(tags) > 3 and len(tags[-1]) < 4:
            tags.pop()  # etiqueta final cortada
        t = ", ".join(tags)
    else:  # lenguaje natural: sin oraciones repetidas
        oraciones, vistas = [], set()
        for o in _re.split(r"(?<=[.!?])\s+", t):
            c = _re.sub(r"\W+", " ", o.lower()).strip()
            if c and c not in vistas:
                vistas.add(c)
                oraciones.append(o)
        t = " ".join(oraciones)
    return t.strip(" ,")
