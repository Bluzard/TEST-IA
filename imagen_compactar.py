"""Entradas LARGAS o ESTRUCTURADAS para el experto de prompts de imagen: compactación y composición determinista.

El núcleo v2c lee 1.024 tokens en total (ficha del modelo ≈ 330 + respuesta ≈ 150): la entrada debe caber en ≈ 430. Una especificación real (el JSON de una escena con «bindings / scene /
sourceAuthority / proposedPlan») mide miles de tokens, repite lo mismo en varios campos y mezcla datos visuales con instrucciones para OTRO modelo («Omit…», «Do not…», «Unspecified»).
Medido (imagen_d): con entradas largas y detalladas el núcleo ignora casi todo el contenido (ganancia de pérdida por usar la entrada: 0,1-0,3 nats frente a 0,8-1,4 en entradas cortas), así que
para una especificación completa NO se genera con el modelo: se COMPONE el prompt de forma determinista con sus propios campos (fidelidad total) y se aplica el formato del modelo destino.

Pasos, sin cambiar el significado visual:
  · aplana el JSON a frases y sustituye los identificadores de personaje por su sustantivo («MAIN_ADULT» -> «the woman»; con su edad la primera vez: «the 19-year-old woman»)
  · descarta valores vacíos o «Not specified / Unspecified / null» y las frases que son instrucciones o reglas para otro sistema («Omit…», «Do not…», «Never…», claves *Rule / *Authority)
  · si hay «visibleParticipants», no describe a quien no es visible
  · elimina frases repetidas o casi repetidas (la misma ropa en 4 campos queda una vez)
  · ordena por categoría visual: cámara, sujeto y ropa, acción y postura, entorno y luz, estilo
"""
import json
import re

CATEGORIAS = [r"camera|framing|vantage|pov|shot|angle|lens", r"outfit|wardrobe|clothing|attire|wearing", r"subject|appearance|description|hair|eyes", r"action|pose|posture|situation|seated|geometry|contact",
              r"light|lighting|atmosphere|ambient|environment|setting|location|office|room", r"style|palette|color|texture"]
ORDEN_CAT = {0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 4}  # cámara, (ropa y sujeto), acción, entorno y luz, estilo; lo demás va al final
META = re.compile(r"^\s*(?:unspecified|not specified|not separately visible|n/?a|none|null|omit|do not|don't|never|only |preserve|always|ignore|avoid|must|should|rule)\b", re.I)
CLAVE_META = re.compile(r"rule|authority|instruction|policy|constraint|guideline|schema|version|id$|pronouns?$", re.I)
VACIO = re.compile(r"^\s*(?:|null|none|n/?a|not specified|unspecified)\s*$", re.I)
EDAD = re.compile(r"(\d{1,3})\s*(?:years?|años)\s*old|(\d{1,3})\s*años", re.I)


def _hojas(obj, ruta=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _hojas(v, ruta + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _hojas(v, ruta + (str(i),))
    elif obj is not None:
        yield ruta, str(obj)


def _sustantivos(obj):
    """{«MAIN_ADULT»: «woman», …} a partir de diccionarios con «noun» (p. ej. bindings.MAIN_ADULT.noun)."""
    out = {}

    def rec(o, nombre=None):
        if isinstance(o, dict):
            if nombre and isinstance(o.get("noun"), str):
                out[nombre] = o["noun"].strip()
            for k, v in o.items():
                rec(v, k)
        elif isinstance(o, list):
            for v in o:
                rec(v, nombre)

    rec(obj)
    return out


def _oraciones(t):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", t.strip()) if x.strip()]


def _norm(t):
    return re.sub(r"[^a-z0-9 ]+", "", t.lower()).strip()


def _casi_igual(a, b):
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not (ta and tb):
        return False
    umbral = 0.5 if min(len(ta), len(tb)) >= 8 else 0.8  # frases largas que dicen lo mismo con otras palabras (la misma ropa en 3 campos)
    return len(ta & tb) / min(len(ta), len(tb)) >= umbral


def _categoria(ruta_txt, s):
    for i, pat in enumerate(CATEGORIAS):
        if re.search(pat, ruta_txt) or re.search(pat, s.lower().split(":")[0]):
            return i
    return 99


def _extraer(obj):
    """[(orden, categoría, frase)] visuales, deduplicadas y sin instrucciones; más {nombre: edad}."""
    nombres = _sustantivos(obj)
    visibles = None
    for ruta, v in _hojas(obj):
        if ruta[-1].lower() in ("visibleparticipants", "visible_participants", "visible"):
            visibles = {x.strip() for x in re.split(r"[,;/]| and ", v) if x.strip()}
    ocultos = {n for n in nombres if visibles is not None and n not in visibles}
    edades = {}
    for ruta, v in _hojas(obj):
        m = EDAD.search(v)
        if m and len(v.split()) <= 4:
            for n in nombres:
                if n in ruta and n not in ocultos:
                    edades[n] = m.group(1) or m.group(2)
    usados_edad = set()
    # Cámara en primera persona + un participante que no es visible = ese participante ES el espectador (la cámara son sus ojos). Si no se dice, un generador de imágenes lee «the man's desk»
    # o «the man» como un segundo personaje en escena. Solo si el sustantivo del oculto no coincide con el de ningún visible (con dos mujeres sería ambiguo).
    pov = any(re.search(r"first[- ]person|\bpov\b", v, re.I) for _, v in _hojas(obj))
    sust_ocultos = {nombres[o] for o in ocultos if o in nombres}
    sust_visibles = {nombres[n] for n in nombres if n not in ocultos}
    espectador = sust_ocultos if (pov and sust_ocultos and not (sust_ocultos & sust_visibles)) else set()

    def a_espectador(t):
        for n in espectador:
            t = re.sub(rf"\bthe {n}'s\b", "the viewer's", t, flags=re.I)
            t = re.sub(rf"\bthe {n}\b", "the viewer", t, flags=re.I)
        return t

    def sustituir(v):
        for ph, sust in nombres.items():
            while ph in v:
                if ph in edades and ph not in usados_edad:
                    v = v.replace(ph, f"the {edades[ph]}-year-old {sust}", 1)
                    usados_edad.add(ph)
                else:
                    v = v.replace(ph, f"the {sust}", 1)
        return v

    frases, vistas = [], []
    for orden, (ruta, v) in enumerate(_hojas(obj)):
        clave = ruta[-1]
        ruta_plana = re.sub(r"[_\s]", "", ".".join(ruta).lower())  # «partnerAdultPermanentAppearance» y «bindings.PARTNER_ADULT.…» son el mismo participante oculto
        if (VACIO.match(v) or CLAVE_META.search(clave) or META.match(v) or any(o in ruta for o in ocultos) or any(re.sub(r"_", "", o).lower() in ruta_plana for o in ocultos)
                or clave in ("noun",) or clave.lower() == "visibleparticipants"):
            continue
        if EDAD.search(v) and len(v.split()) <= 4:  # la edad ya se incorporó al sustantivo
            continue
        v = a_espectador(sustituir(v))
        corto = len(v.split()) <= 5
        for s in ([v] if corto else _oraciones(v)):
            if META.match(s) or any(o in s for o in ocultos) or any(_casi_igual(s, x) for x in vistas):
                continue
            vistas.append(s)
            cat = _categoria(".".join(ruta).lower(), f"{clave}: {s}")
            if espectador and cat == 0 and re.search(r"first[- ]person|\bpov\b", s, re.I):  # la frase de cámara dice de quién son los ojos
                quien = " and ".join(sorted(espectador))
                s = s.rstrip(" .") + f", seen through the eyes of the {quien} (the viewer), who is not visible in the frame"
            frases.append((orden, cat, s[:1].upper() + s[1:], clave))
    return frases


def componer_json(obj, tok=None, max_tokens=420):
    """(texto, resumen): el prompt en inglés compuesto con los campos visuales del JSON, en orden cámara -> sujeto/ropa -> acción -> entorno/luz -> estilo."""
    frases = _extraer(obj)
    ordenadas = sorted(frases, key=lambda f: (ORDEN_CAT.get(f[1], 9), f[0]))
    elegidas, usados = [], 0
    for orden, cat, s, clave in ordenadas:
        n = len(tok.encode(s).ids) + 1 if tok else len(s.split())
        if usados + n <= max_tokens:
            elegidas.append((orden, cat, s))
            usados += n
    elegidas.sort(key=lambda f: (ORDEN_CAT.get(f[1], 9), f[0]))
    texto = " ".join(s if s[-1] in ".!?" else s + "." for _, _, s in elegidas)
    return texto, f"{len(frases)} frases visuales únicas; {len(elegidas)} usadas ({usados} tokens)"


def a_etiquetas(texto):
    """Convierte una composición en lenguaje natural a etiquetas separadas por comas (SD/SDXL/Pony/Illustrious): fragmentos sin sujeto/verbo auxiliar, en minúsculas, sin repetidos."""
    frag, vistos = [], set()
    for f in re.split(r"[.;,]\s+|\.$", texto):
        f = re.sub(r"^\s*(?:and\s+|with\s+|she\s+|he\s+|they\s+)?(?:the\s+)?(?:\d+-year-old\s+)?(?:woman|man|girl|boy)?\s*(?:is|are|was|wears|wearing|has|have|remains?)?\s*", "", f.strip(), flags=re.I)
        f = re.sub(r"\b(?:her|his|their)\b", "", f, flags=re.I)
        f = re.split(r"\b(?:that|which|as|while|creating|interrupted|ideal|contrasting|focusing|providing|where)\b", f, maxsplit=1)[0]  # se corta la cláusula subordinada: en etiquetas pesa más lo breve
        f = re.sub(r"\s+", " ", f).strip(" .,;").lower()
        if re.search(r"\d{1,2}:\d{2}", f) or len(f.split()) < 2 or len(f.split()) > 12 or f in vistos:
            continue
        vistos.add(f)
        frag.append(f)
    return ", ".join(frag[:30])


def preparar_entrada(texto, tok, max_tokens=430):
    """Devuelve (texto_para_el_núcleo, resumen, objeto_json_o_None). Si la entrada cabe y no es un JSON voluminoso, (texto, None, None).
    Para un JSON voluminoso devuelve además el objeto para que el llamador componga el prompt de forma determinista."""
    n = len(tok.encode(texto).ids)
    ini = texto.find("{")
    es_json = ini >= 0 and texto.rstrip().endswith("}")
    if n <= max_tokens and not (es_json and n > 260):
        return texto, None, None
    if es_json:
        try:
            obj = json.loads(texto[ini:])
        except ValueError:
            obj = None
        if obj is not None:
            prefijo = texto[:ini].strip()
            comp, resumen = componer_json(obj, tok, max_tokens - len(tok.encode(prefijo).ids) - 2)
            return (prefijo + "\n" if prefijo else "") + comp, f"entrada estructurada de {n} tokens: {resumen}", obj
    frases, vistas, usados, salida = _oraciones(texto), [], 0, []
    for s in frases:
        if any(_casi_igual(s, x) for x in vistas):
            continue
        vistas.append(s)
        k = len(tok.encode(s).ids) + 1
        if usados + k > max_tokens:
            break
        salida.append(s)
        usados += k
    return " ".join(salida), f"entrada recortada: {n} -> {usados} tokens", None
