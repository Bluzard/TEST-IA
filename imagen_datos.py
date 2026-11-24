"""Datos del experto de prompts de imagen: entrada del usuario (texto mal redactado, JSON, YAML, viñetas, etiquetas, prompt flojo, español o inglés) + modelo destino -> prompt en inglés en el estilo del modelo.

Protocolo (igual que los otros expertos): el núcleo emite «B: <modelo>», la base local (imagen_fichas) devuelve la ficha del modelo y el núcleo responde «R: <prompt>». Sin modelo en el pedido pregunta para qué modelo.

Fuentes:
  · sintético: escenas bilingües (imagen_vocab) -> entradas en 6 formas y salidas por estilo de modelo (natural: Flux, Z-Image Turbo/Base, Qwen-Image; etiquetas: SDXL, SD 1.5, Pony, Illustrious)
  · real (descargado en datos/imagen/raw/, licencias abiertas): igor-im/flux_prompt_expander (MIT, 20 k pares corto -> largo), k-mktr/improved-flux-prompts (MIT), ChrisGoringe/flux_prompts (Apache-2.0),
    poloclub/diffusiondb (CC0, prompts reales de SD; solo para SDXL/SD 1.5)
Higiene mínima de datos reales: se normalizan artefactos de DiffusionDB («8 k» -> «8k»), se descartan enlaces/correos, duplicados, no-inglés y todo contenido sexual con menores. No hay otro filtro de contenido.
Evaluación: reserva por hash de la escena (sintético) o del prompt (real); nada de lo reservado entra en entrenamiento.

  python imagen_datos.py [--sinteticas 40000]   ->  datos/imagen/train.jsonl, datos/imagen/eval.jsonl
"""
import argparse
import collections
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

import imagen_vocab as V
from imagen_formato import formatear
from imagen_fichas import FICHAS_IMAGEN, NEGATIVO_ILL, NEGATIVO_NL, NEGATIVO_PONY, NEGATIVO_SD, ficha_linea

RAIZ = Path(__file__).parent
RAW = RAIZ / "datos" / "imagen" / "raw"
SALIDA = RAIZ / "datos" / "imagen"
NL = ("flux", "z-image-turbo", "z-image-base", "qwen-image")
TAGS = ("sdxl", "sd15", "pony", "illustrious")
PESO_MODELO = {"flux": 5, "z-image-turbo": 4, "z-image-base": 2, "qwen-image": 3, "sdxl": 4, "sd15": 2, "pony": 2, "illustrious": 2}
TOPE_FICHA = 330


def es_eval(clave):
    return int(hashlib.md5(clave.encode()).hexdigest(), 16) % 20 == 0  # 5 %


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def nombre_usuario(k, rng):
    n = rng.choice(FICHAS_IMAGEN[k]["nombres"])
    return rng.choice([n, n, n.title(), n.upper() if len(n) <= 5 else n])


# ----------------------------------------------------------------------------------------------------------- ensuciar
MULETILLAS = ["tipo", "como", "osea", "algo asi", "no se", "porfa", "bien bonito", "re lindo", "que se vea bien", "de calidad", "en 4k", "bien detallado", "algo epico"]
ERRATAS = [("que", "q"), ("para", "pa"), ("por", "x"), ("con", "c/"), ("muy", "mui"), ("imagen", "imajen"), ("ciudad", "siudad"), ("bosque", "bosqe"), ("atardecer", "atardeser"), ("fotografía", "fotografia")]


def ensuciar(t, rng, fuerza=1.0):
    """Hace que un texto parezca escrito sin cuidado: minúsculas, sin tildes ni comas, abreviaturas, muletillas y alguna errata."""
    if rng.random() < 0.55 * fuerza:
        t = t.lower()
    if rng.random() < 0.45 * fuerza:
        t = sin_tildes(t)
    if rng.random() < 0.35 * fuerza:
        t = t.replace(",", "")
    if rng.random() < 0.3 * fuerza:
        for a, b in ERRATAS:
            if rng.random() < 0.5:
                t = re.sub(rf"\b{a}\b", b, t)
    if rng.random() < 0.25 * fuerza:
        pal = t.split()
        pal.insert(rng.randrange(len(pal) + 1), rng.choice(MULETILLAS))
        t = " ".join(pal)
    if rng.random() < 0.12 * fuerza and len(t) > 12:
        i = rng.randrange(3, len(t) - 3)
        t = t[:i] + t[i + 1] + t[i] + t[i + 2:]  # transposición
    return t


# ----------------------------------------------------------------------------------------------------------- escenas sintéticas
ABSURDOS = {"persona": ("in deep space", "on the ocean floor", "on a floating island"), "animal": ("in deep space", "on the ocean floor", "in a busy bazaar", "on a moving train", "in a Tokyo back alley"),
            "objeto": ("in deep space", "on the ocean floor"), "criatura": ("in a busy bazaar", "on a moving train")}


def escena(rng):
    suj = rng.choice(V.SUJETOS)
    es, en, tipo, rasgos = suj
    e = dict(sujeto=(es, en), tipo=tipo, clave=en)
    if rasgos and rng.random() < 0.7:
        e["rasgo"] = rng.choice(rasgos)
    acc = V.ACCIONES[tipo]
    if rng.random() < 0.85:
        e["accion"] = rng.choice(acc)
    if tipo != "lugar" and rng.random() < 0.85:
        malos = ABSURDOS.get(tipo, ())
        e["entorno"] = rng.choice([x for x in V.ENTORNOS if x[1] not in malos])
    if rng.random() < 0.8:
        e["luz"] = rng.choice(V.LUCES)
    foto = rng.random() < 0.4
    fotos = V.ESTILOS_FOTO if tipo == "persona" else [x for x in V.ESTILOS_FOTO if "portrait" not in x[1]]  # «retrato» solo para personas
    if tipo in ("lugar", "criatura"):
        fotos = [x for x in fotos if "macro" not in x[1]]
    e["estilo"] = rng.choice(fotos if foto else V.ESTILOS_ARTE)
    e["foto"] = foto
    if rng.random() < 0.5:
        e["camara"] = rng.choice(V.CAMARAS)
    if rng.random() < 0.55:
        e["ambiente"] = rng.choice(V.AMBIENTES)
    if rng.random() < 0.45:
        e["paleta"] = rng.choice(V.PALETAS)
    if tipo == "objeto" and rng.random() < 0.0:
        pass
    if rng.random() < 0.2:
        e["texto"] = V.texto_aleatorio(rng) if rng.random() < 0.85 else rng.choice(V.TEXTOS)
    e["clave"] = e["sujeto"][1] + "|" + e.get("entorno", ("", ""))[1] + "|" + e["estilo"][1]
    return e


def _art(t):
    return t


def _cap(t):
    return t[:1].upper() + t[1:]


def salida_nl(e, k, rng):
    """Prompt en inglés, lenguaje natural, con la estructura típica (sujeto, acción, entorno, luz, cámara, ambiente)."""
    sujeto = e["sujeto"][1] + (" " + e["rasgo"][1] if "rasgo" in e else "")
    accion = e.get("accion", ("", ""))[1]
    entorno = e.get("entorno", ("", ""))[1]
    luz, cam = e.get("luz", ("", ""))[1], e.get("camara", ("", ""))[1]
    amb, pal = e.get("ambiente", ("", ""))[1], e.get("paleta", ("", ""))[1]
    estilo = e["estilo"][1]
    nucleo = " ".join(x for x in (sujeto, accion, entorno) if x)
    if "texto" in e:
        titulo, sub, _, objeto = e["texto"]
        t = f"{_cap(objeto)} in {estilo.replace('a ', '', 1) if estilo.startswith('a ') else estilo} style, showing {nucleo} as the main illustration, the title \"{titulo}\" in bold letters at the top"
        t += f" and the line \"{sub}\" in smaller text below" if sub else ""
        t += "".join(f", {x}" for x in (luz, pal, amb) if x) + "."
        return t
    v = rng.randrange(3)
    resto = [x for x in (luz, cam, amb, pal) if x]
    rng.shuffle(resto)
    if v == 0:
        t = f"{_cap(estilo)} of {nucleo}" + (f". {_cap(resto[0])}" + "".join(f", {x}" for x in resto[1:]) if resto else "") + "."
    elif v == 1:
        t = f"{_cap(nucleo)}" + (f", {resto[0]}" if resto else "") + f". Rendered as {estilo}" + "".join(f", {x}" for x in resto[1:]) + "."
    else:
        t = f"{_cap(estilo)}. {_cap(nucleo)}." + (f" The scene is lit by {luz}." if luz else "") + "".join(f" {_cap(x)}." for x in (cam, amb, pal) if x)
    if k == "z-image-turbo" or (k == "flux" and rng.random() < 0.3):
        t = t.rstrip(".") + ", " + rng.choice(V.CALIDAD_NL) + "."
    if e["foto"] and rng.random() < 0.4:
        t = t.rstrip(".") + ", natural skin and material textures."
    return re.sub(r"\s+", " ", t).replace(" ,", ",").replace("..", ".")


def _etiqueta(t):
    t = re.sub(r"^(a|an|the)\s+", "", t.strip(), flags=re.I)
    return t.strip(" .")


def _peso(t, rng):
    return f"({t}:{rng.choice(['1.1', '1.2', '1.3', '1.4'])})"


def salida_tags(e, k, rng):
    suj = _etiqueta(e["sujeto"][1])
    partes = []
    if k in ("pony", "illustrious") and e["tipo"] == "persona":
        ms = e["sujeto"][1]
        partes.append("1girl, solo" if re.search(r"woman|girl|ballerina|elven|fairy|mermaid", ms) else "1boy, solo")
    partes.append(suj)
    if "rasgo" in e:
        partes.append(_etiqueta(e["rasgo"][1]))
    if "accion" in e:
        partes.append(e["accion"][1])
    if "entorno" in e:
        partes.append(_etiqueta(re.sub(r"^(in|on|among|beside|inside)\s+", "", e["entorno"][1])))
    for c in ("luz", "camara", "ambiente", "paleta"):
        if c in e:
            partes.append(_etiqueta(e[c][1]))
    partes.append(_etiqueta(e["estilo"][1]))
    partes = [p for p in partes if p]
    if k in ("sdxl", "sd15") and partes and rng.random() < 0.6:
        i = rng.randrange(1, len(partes))
        partes[i] = _peso(partes[i], rng)
    if k in ("sdxl", "sd15") and rng.random() < 0.5:
        partes.append(rng.choice(["highly detailed", "sharp focus", "8k", "intricate details", "cinematic composition"]))
    return ", ".join(partes)


def con_calidad_y_negativo(cuerpo, k, rng, texto=False):
    """Aplica la regla de la ficha del modelo: prefijo de calidad y línea de prompt negativo (o nada, según el modelo)."""
    if k == "sdxl":
        return f"masterpiece, best quality, {cuerpo}\nNegative prompt: {NEGATIVO_SD}"
    if k == "sd15":
        return f"masterpiece, best quality, highly detailed, {cuerpo}\nNegative prompt: {NEGATIVO_SD}, lowres"
    if k == "pony":
        return f"score_9, score_8_up, score_7_up, {cuerpo}\nNegative prompt: {NEGATIVO_PONY}"
    if k == "illustrious":
        return f"masterpiece, best quality, newest, absurdres, {cuerpo}\nNegative prompt: {NEGATIVO_ILL}"
    if k in ("z-image-base", "qwen-image"):
        neg = NEGATIVO_NL + (", distorted text, misspelled letters" if texto and k == "qwen-image" else "")
        return f"{cuerpo}\nNegative prompt: {neg}"
    return cuerpo  # flux y z-image-turbo: sin negativo


# ----------------------------------------------------------------------------------------------------------- entradas del usuario
def pedazos(e, idioma):
    i = 0 if idioma == "es" else 1
    sujeto = e["sujeto"][i] + (" " + e["rasgo"][i] if "rasgo" in e else "")
    p = {"sujeto": sujeto}
    for c in ("accion", "entorno", "luz", "camara", "ambiente", "paleta"):
        if c in e:
            p[c] = e[c][i]
    p["estilo"] = e["estilo"][i]
    if "texto" in e:
        p["objeto"] = e["texto"][2] if idioma == "es" else e["texto"][3]
        p["texto"] = e["texto"][0]
        if e["texto"][1]:
            p["subtexto"] = e["texto"][1]
    return p


def forma_libre(p, rng, idioma):
    orden = ([p["objeto"] + ("" if idioma == "en" else " con")] if "objeto" in p else []) + [p["sujeto"]] + [p[c] for c in ("accion", "entorno") if c in p] + [p[c] for c in ("luz", "estilo", "camara", "ambiente", "paleta") if c in p]
    if rng.random() < 0.4:
        i = rng.randrange(1, len(orden))
        orden.insert(0, orden.pop(i))
    sep = rng.choice([", ", ", ", " ", " y ", ". "]) if idioma == "es" else rng.choice([", ", ", ", " "])
    t = sep.join(orden)
    if "texto" in p:
        t += (", con el texto '" if idioma == "es" else ", with the text '") + p["texto"] + "'"
        if "subtexto" in p:
            t += (" y debajo '" if idioma == "es" else " and below '") + p["subtexto"] + "'"
    return t


def forma_json(p, rng, idioma, modelo_nombre):
    claves_en = dict(sujeto="subject", accion="action", entorno="setting", luz="lighting", estilo="style", camara="camera", ambiente="mood", paleta="palette", texto="text", subtexto="subtext", objeto="type")
    claves_es = dict(sujeto="sujeto", accion="accion", entorno="entorno", luz="luz", estilo="estilo", camara="camara", ambiente="ambiente", paleta="paleta", texto="texto", subtexto="subtexto", objeto="tipo")
    usar = claves_en if (idioma == "en" or rng.random() < 0.55) else claves_es
    d = {usar[c]: v for c, v in p.items() if c in usar and (c in ("sujeto", "estilo") or rng.random() < 0.9)}
    if rng.random() < 0.5:
        d["aspect_ratio"] = rng.choice(["16:9", "1:1", "9:16", "4:3", "3:2"])
    if rng.random() < 0.7:
        d["model"] = modelo_nombre
    return json.dumps(d, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 2]))


def forma_yaml(p, rng, idioma, modelo_nombre):
    nombres = dict(sujeto="sujeto", accion="accion", entorno="entorno", luz="luz", estilo="estilo", camara="camara", ambiente="ambiente", paleta="paleta", texto="texto", subtexto="subtexto", objeto="tipo") \
        if idioma == "es" else dict(sujeto="subject", accion="action", entorno="setting", luz="lighting", estilo="style", camara="camera", ambiente="mood", paleta="palette", texto="text", subtexto="subtext", objeto="type")
    lineas = [f"{nombres[c]}: {v}" for c, v in p.items() if c in nombres]
    lineas.append(("modelo" if idioma == "es" else "model") + f": {modelo_nombre}")
    return "\n".join(lineas)


def forma_vinetas(p, rng, idioma):
    bullet = rng.choice(["- ", "* ", "• "])
    return "\n".join(bullet + (f"'{v}'" if c in ("texto", "subtexto") else v) for c, v in p.items())


def forma_etiquetas(p, rng, idioma):
    return ", ".join((f"'{v}'" if c in ("texto", "subtexto") else v) for c, v in p.items())


def forma_floja(p, rng, idioma):
    """Pedido mínimo y flojo («gato durmiendo bonito 4k»): el experto tiene que enriquecerlo."""
    t = p["sujeto"] + (" " + p["accion"] if "accion" in p else "")
    return t + " " + rng.choice(["bonito", "bien hecho", "4k", "hd", "realista", "que se vea bien", "pro", "épico" if idioma == "es" else "epic", "masterpiece"] if idioma == "es" else ["nice", "good quality", "4k", "hd", "realistic", "pls", "epic", "masterpiece"])


def construir_fila(e, k, rng, forma=None):
    if k in TAGS and "texto" in e:  # SD casi no renderiza texto: esos modelos no se entrenan con texto en la imagen
        e = {c: v for c, v in e.items() if c != "texto"}
    idioma = rng.choices(["es", "en"], [0.78, 0.22])[0]
    p = pedazos(e, idioma)
    nombre = nombre_usuario(k, rng)
    forma = forma or rng.choices(["libre", "json", "yaml", "vinetas", "etiquetas", "floja"], [0.34, 0.17, 0.09, 0.13, 0.13, 0.14])[0]
    cuerpo_in = {"libre": lambda: forma_libre(p, rng, idioma), "json": lambda: forma_json(p, rng, idioma, nombre), "yaml": lambda: forma_yaml(p, rng, idioma, nombre),
                 "vinetas": lambda: forma_vinetas(p, rng, idioma), "etiquetas": lambda: forma_etiquetas(p, rng, idioma), "floja": lambda: forma_floja(p, rng, idioma)}[forma]()
    estructurada = forma in ("json", "yaml") and ("model" in cuerpo_in or "modelo" in cuerpo_in)
    if forma in ("libre", "floja", "etiquetas", "vinetas") or not estructurada:
        cuerpo_in = ensuciar(cuerpo_in, rng) if forma in ("libre", "floja") else cuerpo_in
        plantilla = rng.choice(V.PEDIDOS_ES if idioma == "es" else V.PEDIDOS_EN)
        pregunta = plantilla.format(m=nombre, x=cuerpo_in) if forma != "vinetas" else f"{nombre}\n{cuerpo_in}"
    else:
        pregunta = cuerpo_in
    texto = "texto" in e
    cuerpo_out = salida_nl(e, k, rng) if k in NL else salida_tags(e, k, rng)
    return dict(tipo=f"img_{forma}" + ("_texto" if texto else ""), pregunta=pregunta, consulta=k, resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA,
                respuesta=cuerpo_out, completo=formatear(k, cuerpo_out, texto), modelo=k, fuente="sintetico")


def fila_sin_modelo(e, rng):
    p = pedazos(e, rng.choice(["es", "es", "en"]))
    x = ensuciar(forma_libre(p, rng, "es"), rng, 0.6)
    return dict(tipo="img_sin_modelo", pregunta=rng.choice(V.PEDIDOS_SIN_MODELO).format(x=x), respuesta=rng.choice(V.PREGUNTA_MODELO), fuente="sintetico")


# ----------------------------------------------------------------------------------------------------------- datos reales
URL = re.compile(r"https?://|www\.|@\w+\.\w+|\.com\b")
MENORES = re.compile(r"\b(child|children|kid|kids|loli|lolita|shota|underage|minor|toddler|infant|schoolgirl|school girl|preteen|teen|teenage|young girl|little girl|little boy|baby|niña|niño)\b", re.I)
SEXUAL = re.compile(r"\b(nsfw|nude|naked|sex|sexual|porn|erotic|topless|nipples?|genitals?|lingerie|explicit|hentai|cum|fetish)\b", re.I)


def higiene(t):
    if URL.search(t):
        return False
    if MENORES.search(t) and SEXUAL.search(t):  # siempre fuera: contenido sexual con menores
        return False
    return sum(ord(c) < 128 for c in t) / max(1, len(t)) > 0.97


def normalizar_dd(t):
    t = re.sub(r"(?<=\d) (?=\d)", "", t)
    t = re.sub(r"\b(\d+) ?k\b", r"\1k", t)
    return re.sub(r"\s+", " ", t).strip(" ,")


def primera_idea(t, rng, maxpal=22):
    """Entrada corta derivada de un prompt largo: su primera cláusula, recortada."""
    c = re.split(r"(?<=[.!?])\s|,\s", t.strip())[0]
    pal = c.split()
    return " ".join(pal[:maxpal]) if len(pal) >= 3 else None


def cargar_traducciones():
    """{texto en inglés: traducción al español} generado con imagen_traducir.py (opus-mt-en-es); vacío si no existe."""
    mapa = {}
    for nombre in ("es_traducidos.jsonl", "es_traducidos_sd.jsonl"):
        ruta = RAW / nombre
        if ruta.exists():
            for l in open(ruta, encoding="utf-8"):
                r = json.loads(l)
                mapa[r["en"]] = r["es"]
    return mapa


def pregunta_real(texto_en, mapa, k, rng, p_es=0.65):
    """Entrada del usuario a partir de una descripción REAL: en español (traducida) o inglés, y en distintas formas (texto libre, JSON, YAML, viñetas)."""
    es = texto_en in mapa and rng.random() < p_es
    t = mapa[texto_en] if es else texto_en
    nombre = nombre_usuario(k, rng)
    f = rng.random()
    if f < 0.62:
        pedido = rng.choice(V.PEDIDOS_ES if es else V.PEDIDOS_EN + V.PEDIDOS_ES)
        return pedido.format(m=nombre, x=ensuciar(t, rng, 0.5))
    if f < 0.76:
        d = {("descripcion" if es else "description"): t}
        if rng.random() < 0.5:
            d["aspect_ratio"] = rng.choice(["16:9", "1:1", "9:16", "4:3"])
        d["model" if rng.random() < 0.6 else "modelo"] = nombre
        return json.dumps(d, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 2]))
    if f < 0.85:
        return f"{'descripcion' if es else 'description'}: {t}\n{'modelo' if es else 'model'}: {nombre}"
    trozos = [x.strip() for x in re.split(r",\s*| con | with | and | y ", t) if x.strip()]
    if len(trozos) < 2:
        return rng.choice(V.PEDIDOS_ES).format(m=nombre, x=ensuciar(t, rng, 0.5))
    return nombre + "\n" + "\n".join(rng.choice(["- ", "* ", "• "]) + x for x in trozos)


def cargar_reales(rng, max_exp, max_imp, max_flux, max_dd, max_civitai=6500):
    import pandas as pd

    mapa = cargar_traducciones()
    filas = []
    exp = pd.read_parquet(RAW / "igor-im__flux_prompt_expander" / "data" / "train-00000-of-00001.parquet")
    imp = [json.loads(l)["prompt"] for l in open(RAW / "k-mktr__improved-flux-prompts" / "20240927_flux_improved_prompts_final_cleaned.jsonl", encoding="utf-8")]
    fl = pd.read_parquet(RAW / "ChrisGoringe__flux_prompts" / "data" / "train-00000-of-00001.parquet")["prompt"].tolist()
    dd = pd.read_parquet(RAW / "poloclub__diffusiondb" / "metadata.parquet", columns=["prompt", "prompt_nsfw"])
    vistos = set()

    def nuevo(t):
        c = re.sub(r"\W+", " ", t.lower()).strip()[:160]
        if c in vistos:
            return False
        vistos.add(c)
        return True

    def modelo_nl():
        return rng.choices(NL, [PESO_MODELO[m] for m in NL])[0]

    # 1) expander: corto -> largo (Flux y familia natural)
    pares = [(r.gen_p.strip(), r.prompt.strip()) for r in exp.itertuples() if isinstance(r.gen_p, str) and isinstance(r.prompt, str)]
    rng.shuffle(pares)
    for corto, largo in pares:
        if len([1 for f in filas if f["tipo"] == "img_real_expandir"]) >= max_exp:
            break
        if not (20 <= len(corto) <= 260 and 200 <= len(largo) <= 1400 and higiene(largo) and nuevo(largo)):
            continue
        k = modelo_nl()
        filas.append(dict(tipo="img_real_expandir", pregunta=pregunta_real(corto, mapa, k, rng), consulta=k,
                          resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA, respuesta=largo, completo=formatear(k, largo), modelo=k, fuente="flux_prompt_expander", clave=largo))
    # 2) improved-flux-prompts y flux_prompts (solo los de lenguaje natural): primera idea -> prompt completo
    for fuente, lista, tope in (("improved_flux_prompts", imp, max_imp), ("flux_prompts", [t for t in fl if t.count(",") < 9 and "." in t], max_flux)):
        rng.shuffle(lista)
        n = 0
        for t in lista:
            if n >= tope:
                break
            t = t.strip()
            if not (200 <= len(t) <= 1400 and higiene(t) and nuevo(t)):
                continue
            idea = primera_idea(t, rng)
            if not idea:
                continue
            k = modelo_nl()
            filas.append(dict(tipo="img_real_idea", pregunta=pregunta_real(idea, mapa, k, rng), consulta=k,
                              resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA, respuesta=t, completo=formatear(k, t), modelo=k, fuente=fuente, clave=t))
            n += 1
    # 2b) Aconexx/CivitAI-Flux-Prompts (Apache-2.0): prompts reales de usuarios de Flux con temas variados (descripción corta -> prompt). Se descartan los que empiezan por un disparador de LoRA.
    ruta_cv = RAW / "Aconexx__CivitAI-Flux-Prompts" / "Flux_Prompts_Dataset_v1.1.0.jsonl"
    if ruta_cv.exists():
        n = 0
        filas_cv = [json.loads(l) for l in open(ruta_cv, encoding="utf-8")]
        rng.shuffle(filas_cv)
        for r in filas_cv:
            if n >= max_civitai:
                break
            entrada, t = (r.get("input") or "").strip(), (r.get("output") or "").strip()
            primero = t.split(",")[0].strip()
            if not (20 <= len(entrada) <= 260 and 120 <= len(t) <= 1400 and higiene(t) and nuevo(t)):
                continue
            if len(primero.split()) == 1 and re.search(r"\d", primero):  # «4si4n», «IMG1018»: disparador de un LoRA concreto
                continue
            k = modelo_nl()
            filas.append(dict(tipo="img_real_civitai", pregunta=pregunta_real(entrada, mapa, k, rng), consulta=k, resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA,
                              respuesta=t, completo=formatear(k, t), modelo=k, fuente="civitai_flux", clave=t))
            n += 1
    # 3) DiffusionDB: prompts reales de SD con etiquetas -> SDXL / SD 1.5 (con las entradas ya traducidas por imagen_traducir.py, si existen)
    sd_ruta = RAW / "es_traducidos_sd.jsonl"
    if sd_ruta.exists():
        n = 0
        for l in open(sd_ruta, encoding="utf-8"):
            r = json.loads(l)
            t = r["largo"]
            if n >= max_dd:
                break
            if not nuevo(t):
                continue
            k = rng.choices(["sdxl", "sd15"], [0.6, 0.4])[0]
            filas.append(dict(tipo="img_real_sd", pregunta=pregunta_real(r["en"], mapa, k, rng), consulta=k, resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA,
                              respuesta=t, completo=formatear(k, t), modelo=k, fuente="diffusiondb", clave=t))
            n += 1
        return filas
    dd = dd[(dd.prompt_nsfw < 0.5) & dd.prompt.notna()]
    cand = dd.prompt.sample(min(len(dd), max_dd * 6), random_state=3).tolist()
    n = 0
    for t in cand:
        if n >= max_dd:
            break
        t = normalizar_dd(t)
        if not (40 <= len(t) <= 380 and t.count(",") >= 3 and higiene(t) and nuevo(t)):
            continue
        trozos = [c.strip() for c in t.split(",") if c.strip()]
        elegidos = trozos[: rng.randint(1, 2)] + rng.sample(trozos[2:], min(len(trozos) - 2, rng.randint(0, 2)))
        if len(" ".join(elegidos).split()) < 3:
            continue
        k = rng.choices(["sdxl", "sd15"], [0.6, 0.4])[0]
        en_in = ", ".join(elegidos)  # misma forma que la traducida por imagen_traducir.pares_sd, para que la traducción exista
        filas.append(dict(tipo="img_real_sd", pregunta=pregunta_real(en_in, mapa, k, rng), consulta=k,
                          resultados=f"1. {k} - base local: {ficha_linea(k)}", pref="B", tope=TOPE_FICHA, respuesta=t, completo=formatear(k, t), modelo=k, fuente="diffusiondb", clave=t))
        n += 1
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sinteticas", type=int, default=40000)
    ap.add_argument("--sin_modelo", type=int, default=8000)
    ap.add_argument("--expander", type=int, default=12000)
    ap.add_argument("--improved", type=int, default=6000)
    ap.add_argument("--flux", type=int, default=2500)
    ap.add_argument("--diffusiondb", type=int, default=12000)
    ap.add_argument("--civitai", type=int, default=6500)
    ap.add_argument("--semilla", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.semilla)
    filas = []
    for _ in range(a.sinteticas):
        e = escena(rng)
        k = rng.choices(list(PESO_MODELO), list(PESO_MODELO.values()))[0]
        f = construir_fila(e, k, rng)
        f["clave"] = e["clave"]
        filas.append(f)
    for _ in range(a.sin_modelo):
        e = escena(rng)
        f = fila_sin_modelo(e, rng)
        f["clave"] = e["clave"]
        filas.append(f)
    filas += cargar_reales(rng, a.expander, a.improved, a.flux, a.diffusiondb, a.civitai)
    SALIDA.mkdir(parents=True, exist_ok=True)
    train, ev = [], []
    for f in filas:
        (ev if es_eval(f["clave"]) else train).append(f)
    # que la evaluación nunca comparta clave (escena/prompt) con el entrenamiento
    claves_ev = {f["clave"] for f in ev}
    train = [f for f in train if f["clave"] not in claves_ev]
    rng.shuffle(train)
    for nombre, lista in (("train", train), ("eval", ev)):
        with open(SALIDA / f"{nombre}.jsonl", "w", encoding="utf-8") as fh:
            for f in lista:
                fh.write(json.dumps({k: v for k, v in f.items() if k != "clave"}, ensure_ascii=False) + "\n")
    print(f"train {len(train):,} | eval {len(ev):,}")
    print("tipos train:", dict(collections.Counter(f["tipo"] for f in train).most_common()))
    print("modelos train:", dict(collections.Counter(f.get("modelo", "-") for f in train).most_common()))
    print("fuentes train:", dict(collections.Counter(f["fuente"] for f in train).most_common()))


if __name__ == "__main__":
    main()
