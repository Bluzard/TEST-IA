"""Redactor DETERMINISTA del prompt de imagen de una escena de chat (sustituto del «redactor final» con LLM de b_chat), sin generación libre: no puede perder ni inventar hechos.

Entrada (misma estructura que `generateSceneImagePrompt` de b_chat):
  {camera, main:{person, wardrobe}, partner?:{person, wardrobe}, location, time, lighting, photography:{viewpoint, framing, canvas, style, gaze}, situation}
La situación viene en español con MAIN_ADULT / PARTNER_ADULT. Pasos:
  1. se parte en cláusulas (misma regla que lib/facts-prompt.cjs: comas, punto y coma, «y» + gerundio)
  2. se descarta lo que NO es un hecho actual: pasado («antes estaba de pie»), intenciones sin ejecutar («quiere levantarse»), pedidos y órdenes («le pide que se levante»)
  3. se traduce cada cláusula al inglés con opus-mt-es-en (en lote, CPU) y se limpia («the observer» -> «the viewer»)
  4. se ensambla la prosa con plantillas: punto de vista, persona principal con su ropa, hechos actuales, lugar, hora, luz y mirada (solo si la situación la establece)
En primera persona (POV) el observador no sale en el cuadro: es «the viewer» y no se describe su cuerpo.
"""
import re
import unicodedata

from escena_comprimir import LUZ, UMBRAL, comprimir_momento, comprimir_visual, prendas
from imagen_idea import traducir_es_en

PERSONA_ES = {"woman": "la mujer", "man": "el hombre", "girl": "la joven", "boy": "el joven"}
PASADO = re.compile(r"^\W*(?:antes|previamente|anteriormente|hace\s+un\s+(?:momento|rato)|mas\s+temprano|más\s+temprano)\b|\b(?:antes\s+(?:estaba|miró|miro|había)|ya\s+no\s+(?:est[aá]|tiene))\b", re.I)
IMPERFECTO = re.compile(r"\b(?:estaba|tenía|tenia|había|habia|sostenía|sostenia|llevaba)\b", re.I)
INTENCION = re.compile(r"\b(?:quiere|quería|queria|desea|deseaba|pretende|intenta|piensa|planea|le\s+gustaría|le\s+gustaria|va\s+a\s+(?:levantarse|salir|irse)|está\s+a\s+punto|esta\s+a\s+punto)\b(?!\s+(?:de\s+)?\w+ando\b)", re.I)
PEDIDO = re.compile(r"\b(?:le\s+pide|le\s+pidió|le\s+pidio|le\s+dice\s+que|le\s+ordena|le\s+sugiere|le\s+ruega|le\s+propone|le\s+invita\s+a)\b", re.I)
NEGADO = re.compile(r"^\W*(?:[^\W\d_]+\s+){0,3}no\s+(?:est[aá]|se\s+encuentra|tiene|lleva|usa|es)\b", re.I)
CONTINUACION = re.compile(r"^\s*(?:pero|aunque|sin\s+embargo|y)\s+", re.I)


# Glosario previo a la traducción: palabras de escena que el traductor automático confunde («regadera» -> «shower»). El traductor conserva las palabras en inglés insertadas en la frase,
# así que se sustituye el término español por su equivalente correcto. Crece con los errores que se vayan viendo.
GLOSARIO_ES = [
    (r"\bregaderas?\b", "watering can"), (r"\bpinzas\s+(?:de|para)\s+(?:la\s+)?ropa\b", "clothespins"), (r"\bpinzas\b", "clothespins"), (r"\bsobre\s+(?:su|sus)\s+regazo\b", "en su lap"), (r"\bregazo\b", "lap"),
    (r"\bse\s+arremanga\b", "se rolls up"), (r"\bse\s+peina(?!\s+el\s+pelo|\s+el\s+cabello)\b", "se peina el pelo"), (r"\bmaceta\b", "flower pot"), (r"\bmesita\s+de\s+noche\b", "bedside table"),
    (r"\b(?:lentes|anteojos|gafas)\b", "glasses"), (r"\brecargad([ao])s?\b", r"apoyad\1"), (r"\bat[aá]ndose\b", "tying"), (r"\bsuelo\b(?=.*\b(?:sala|cuarto|habitaci[oó]n|casa|living|dormitorio)\b)", "floor"),
    (r"\bllave\s+inglesa\b", "wrench"), (r"\bcómoda\b", "dresser"), (r"\bbuhardilla\b", "attic"), (r"\bporche\b", "porch"), (r"\bhamaca\b", "hammock"), (r"\bmecedora\b", "rocking chair"),
    (r"\bmedias\b(?!\s+de\s+(?:algod[oó]n|lana|deporte))", "stockings"), (r"\bzapatillas\b", "sneakers"), (r"\bpolera\b", "camiseta"), (r"\btiro\s+alto\b", "high-waisted"), (r"\bnoche\s+avanzada\b", "late at night"),
    (r"\bperchero\b", "coat rack"), (r"\bescritorio\b", "desk"), (r"\bsillón\b", "armchair"), (r"\bbanco\b", "bench"),
]
OBSERVADOR_POSTURA = re.compile(r"^\W*(?:el\s+observador|el\s+espectador)\s+(?:est[aá]\s+|se\s+encuentra\s+)?(?:sentad|de\s+pie|par[ae]d|acostad|recostad|arrodillad|inclinad|agachad)", re.I)


def aplicar_glosario(t):
    for patron, ingles in GLOSARIO_ES:
        t = re.sub(patron, ingles, t, flags=re.I)
    return t


def dividir_oraciones(t):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=\S)", str(t or "").strip()) if x.strip()]


def dividir_clausulas(texto):
    """Port de splitClauses (lib/facts-prompt.cjs): una cláusula por hecho; los encabezados preposicionales cortos se pegan a la siguiente."""
    clausulas = []
    for oracion in dividir_oraciones(texto):
        # además de «y + gerundio» (regla de b_chat) se parte antes de un verbo de intención: «camina por la calle y quiere cruzar» son dos hechos distintos
        partes = [p.strip() for p in re.split(r"\s*[,;]\s*|\s+y\s+(?=[^\W\d_]+(?:ando|iendo|yendo)\b|(?:quiere|desea|piensa|planea|intenta|pretende)\b)", oracion)]
        partes = [re.sub(r"[.!?\s]+$", "", p).strip() for p in partes if p and re.sub(r"[.!?\s]+$", "", p).strip()]
        lead = ""
        for i, limpia in enumerate(partes):
            con_lead = f"{lead}, {limpia}" if lead else limpia
            lead = ""
            preposicional = len(limpia) < 20 and re.match(r"^(?:en|con|sin|sobre|de|del|al|bajo|junto|alrededor|entre|por|para)\b", limpia, re.I)
            if not preposicional and len(limpia) >= 7:
                clausulas.append(con_lead)
            elif preposicional and i < len(partes) - 1:
                lead = con_lead
            elif clausulas:
                clausulas[-1] += f", {con_lead}"
            else:
                clausulas.append(con_lead)
    return clausulas


def hechos_actuales(situacion):
    """Cláusulas que son hechos de AHORA. Devuelve (hechos, descartadas con su motivo) para poder auditar."""
    hechos, fuera = [], []
    previa_descartada = False
    for c in dividir_clausulas(situacion):
        if PASADO.search(c) or (IMPERFECTO.search(c) and not re.search(r"\b(?:ahora|actualmente|en\s+este\s+momento)\b", c, re.I)):
            fuera.append((c, "pasado")); previa_descartada = True; continue
        if INTENCION.search(c):
            fuera.append((c, "intención sin ejecutar")); previa_descartada = True; continue
        if PEDIDO.search(c):
            fuera.append((c, "pedido u orden")); previa_descartada = True; continue
        if NEGADO.search(c):  # «no está sentada»: una negación no es algo que se vea (y su palabra clave colaría la postura prohibida)
            fuera.append((c, "estado negado")); previa_descartada = False; continue
        if OBSERVADOR_POSTURA.search(c):  # en primera persona el observador está detrás de la cámara: su postura no es un hecho de la imagen (regla de b_chat)
            fuera.append((c, "postura del observador (detrás de la cámara)")); previa_descartada = False; continue
        c = re.sub(r"^\s*(?:ahora|actualmente|en\s+este\s+momento)\s*,?\s*", "", c, flags=re.I)
        if previa_descartada and CONTINUACION.match(c):  # «…, pero ella sigue regando»: lo que sigue a lo descartado sí es actual
            c = CONTINUACION.sub("", c)
        previa_descartada = False
        hechos.append(c)
    return hechos, fuera


_CONTACTO = re.compile(r"\b(?:apoya|apoyan|pone|coloca|posa|toca|acaricia|sujeta|agarra|aprieta|empuja|sostiene|besa|abraza|rodea|masajea|recorre|desliza|lleva)\b", re.I)
_PARTE_F = r"cintura|espalda|cara|cabeza|boca|mejillas?|piernas?|manos?|nalgas|rodillas?|caderas?"
_PARTE = rf"(?:{_PARTE_F}|pecho|cuello|hombros?|brazos?|muslos?|rostro|pelo|cabello|dedos|labios|vientre|abdomen|torso)"


def resolver_posesivo(clausula, es_main, es_par, hay_otro):
    """«La mujer apoya las manos en su pecho» (con otra persona en la escena): sin reflexivo («se»), «su» es de la OTRA persona, no de quien actúa.
    Solo cuando el sujeto es explícito (el nombre de una de las dos personas) y el verbo es de contacto; cualquier duda deja la frase como está."""
    if not hay_otro or re.search(r"\b(?:se|propi[oa]s?)\b", clausula, re.I) or not _CONTACTO.search(clausula):
        return clausula
    if re.match(rf"^\W*{re.escape(es_main)}\b", clausula, re.I):
        otro = es_par
    elif re.match(rf"^\W*{re.escape(es_par)}\b", clausula, re.I):
        otro = es_main
    else:
        return clausula
    de = re.sub(r"^el\b", "del", otro, flags=re.I) if otro.lower().startswith("el ") else f"de {otro}"

    def sustituir(m):
        plural = m.group(1).lower() == "sus"
        parte = m.group(2)
        fem = re.fullmatch(_PARTE_F, parte, re.I) is not None
        art = ("las" if fem else "los") if plural else ("la" if fem else "el")
        return f"{art} {parte} {de}"
    return re.sub(rf"\b(sus?)\s+({_PARTE})\b", sustituir, clausula, count=1, flags=re.I)


def _limpiar_ingles(t, pov):
    t = t.strip().rstrip(".")
    t = re.sub(r"^(?:but|although|however|and)\s+", "", t, flags=re.I)
    t = re.sub(r"\bhigh-waited\b", "high-waisted", t, flags=re.I)  # el traductor «corrige» la palabra del glosario
    t = re.sub(r"\b(?:the\s+)?(?:observer|watcher|onlooker|spectator)(?=['’]s\b|\b)", "the viewer", t, flags=re.I) if pov else t
    t = re.sub(r"^(?:the\s+)?one\s+(?=[a-z]+\b)", "", t, flags=re.I) if re.match(r"^(?:the\s+)?one\s+(?:bedroom|room|kitchen|bathroom|office|garden|street)\b", t, re.I) else t
    return t[:1].upper() + t[1:] if t else t


def _nfc(obj):
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        return {k: _nfc(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nfc(v) for v in obj]
    return obj


def _lista_ropa(frases):
    """Prendas ya traducidas -> «a blouse, a vest and boots». Con una sola prenda es la misma frase de siempre (sin artículo si ya lo trae)."""
    p = [x.strip().lower().rstrip(".") for x in frases if x and x.strip()]
    if len(p) <= 1:
        return _articulo(p[0]) if p else ""
    p = [_articulo(x) for x in p]
    return ", ".join(p[:-1]) + " and " + p[-1]


def _articulo(w):
    w = w.strip()
    if re.search(r"\b(?:jeans|pants|trousers|shorts|boots|shoes|heels|stockings|glasses|socks|leggings)\b", w, re.I) or w.lower().startswith(("a ", "an ", "the ")):
        return w
    return ("an " if re.match(r"[aeiou]", w, re.I) else "a ") + w


def componer(fuente, cuerpo=False):
    """(prompt en inglés, traza). `traza` lista lo descartado y la traducción, para auditoría.
    cuerpo=True: sin la apertura de cámara ni el estilo fotográfico (b_chat los añade él mismo): empieza por «One woman in …» y sigue con los hechos."""
    fuente = _nfc(fuente)  # «á» como una sola letra: las expresiones regulares no reconocen la tilde combinada («a» + U+0301)
    cam = fuente.get("camera", "")
    pov = cam == "pov"
    foto = fuente.get("photography", {}) or {}
    main = fuente.get("main", {}) or {}
    partner = fuente.get("partner") or {}
    n_main = main.get("person", "person")
    n_par = partner.get("person", "")
    es_main = PERSONA_ES.get(n_main, "la persona")
    es_par = "el observador" if pov else PERSONA_ES.get(n_par, "la otra persona")
    situacion = str(fuente.get("situation", "")).replace("MAIN_ADULT", es_main).replace("PARTNER_ADULT", es_par)
    hechos, fuera = hechos_actuales(situacion)
    hechos = [resolver_posesivo(h, es_main, es_par, pov or bool(n_par)) for h in hechos]
    vacias = [h for h in hechos if re.fullmatch(r"\W*\S+(?:\s+\S+)?\s+est[aá]\s+(?:apoyad|inclinad)[ao]\W*", h, re.I)]  # «está apoyada» a secas no dice sobre qué: no es un hecho dibujable
    hechos = [h for h in hechos if h not in vacias]
    fuera += [(h, "sin contenido dibujable") for h in vacias]
    # hora: solo la hora del día («Son las diez de la noche»); la narración vieja («antes miró su reloj») no es un hecho visual
    hora = [o for o in dividir_oraciones(fuente.get("time", "")) if re.match(r"^\s*(?:son|es|ya\s+es|amanece|atardece|anochece)\b", o, re.I) and not re.search(r"reloj|miró|miro|antes", o, re.I)]
    # textos largos de escenas reales (prosa literaria con sonidos, olores y ánimo): se queda solo lo dibujable; los cortos pasan intactos
    quitar_ids = lambda t: str(t or "").replace("MAIN_ADULT", es_main).replace("PARTNER_ADULT", es_par)
    if len(str(fuente.get("time", ""))) > UMBRAL and not hora:
        hora = [h for h in [comprimir_momento(fuente.get("time", ""))] if h]
    lugar_t = quitar_ids(comprimir_visual(fuente.get("location", ""), 36))
    luz_t = quitar_ids(comprimir_visual(fuente.get("lighting", ""), 26, exigir=LUZ))
    ropas_main = prendas(quitar_ids(main.get("wardrobe", ""))) or [""]
    ropas_par = prendas(quitar_ids(partner.get("wardrobe", ""))) if partner.get("wardrobe") and not pov else []
    por_traducir = [("situacion", h) for h in hechos] + [("lugar", lugar_t)] + [("hora", h) for h in hora] + [("luz", luz_t)]
    por_traducir += [("ropa_main", r) for r in ropas_main] + [("ropa_par", r) for r in ropas_par]
    textos = [t for _, t in por_traducir]
    ingles = [_limpiar_ingles(x, pov) if x and x.strip() else "" for x in (traducir_lote(textos))]
    tr = {}
    for (k, _), en in zip(por_traducir, ingles):
        tr.setdefault(k, []).append(en)
    # «sobre los hombros» -> «on your shoulders»: el traductor no sabe de quién es la prenda; es de quien la lleva
    for clave, nombre in (("ropa_main", n_main), ("ropa_par", n_par)):
        pos = "her" if nombre in ("woman", "girl") else "his"
        tr[clave] = [re.sub(r"\b(?:your|my|our)\b", pos, x, flags=re.I) for x in tr.get(clave, [])]
    ropa = _lista_ropa(tr.get("ropa_main", []))
    ropa_par = _lista_ropa(tr.get("ropa_par", []))
    # la luz que ya dijo el lugar («illuminated by the cold light of a desk lamp») no se repite
    lugar_en = " ".join(tr.get("lugar", [])).lower()
    tr["luz"] = [l for l in tr.get("luz", []) if not l or len({w for w in re.findall(r"[a-z]{5,}", l.lower())} - set(re.findall(r"[a-z]{5,}", lugar_en))) > 1]
    varias = len([x for x in tr.get("ropa_main", []) if x]) > 1  # varias prendas: «wearing a blouse, a vest and trousers»
    sujeto = f"{_articulo(n_main)}" + (f" {'wearing' if varias else 'in'} {ropa}" if ropa else "")
    partes = []
    if cuerpo:
        partes.append(f"One {n_main}" + (f" {'wearing' if varias else 'in'} {ropa}" if ropa else "") + ".")
    elif pov:
        partes.append(f"First-person POV photograph, seen through the eyes of the viewer, who is not visible in the frame. It shows {sujeto}.")
    else:
        vp = foto.get("viewpoint") or ""
        partes.append(f"{vp[:1].upper() + vp[1:]} hyper-realistic photograph of {sujeto}." if vp else f"Hyper-realistic photograph of {sujeto}.")
    pron_main = "she" if n_main in ("woman", "girl") else "he"
    pron_par = "she" if n_par in ("woman", "girl") else "he"
    sit = []
    for h in tr.get("situacion", []):
        if not h:
            continue
        # «that holds with both hands»: el traductor pierde el sujeto de la relativa; se recupera con el género de quien es el sujeto de la cláusula
        pron = pron_par if (n_par and re.match(rf"^(?:the\s+{n_par}|{pron_par})\b", h, re.I) and n_par != n_main) else pron_main
        h = re.sub(r"\b(that|which)\s+(holds|carries|wears|has|grips|clutches|rests|keeps|uses)\b", rf"\1 {pron} \2", h, flags=re.I)
        # en una escena de una sola persona el traductor a veces elige el género equivocado («He's standing»): se normaliza al de la persona principal
        if not (partner and n_par) and not pov:  # con pareja o espectador hay dos géneros en la escena: no se toca
            if pron_main == "she":
                h = re.sub(r"\bHe's\b", "She's", re.sub(r"\bhe's\b", "she's", h)); h = re.sub(r"\b(He|he)\b", lambda m: "She" if m.group(1) == "He" else "she", h)
                h = re.sub(r"\bhis\b", "her", re.sub(r"\bHis\b", "Her", h)); h = re.sub(r"\bhim\b", "her", h); h = re.sub(r"\bhimself\b", "herself", h)
        # un fragmento sin sujeto («Who receives it…», «Recharged against the wall», «With the guitar…», «Watering the plant…») continúa la frase anterior
        if sit and re.match(r"^(?:who|which|whose|that|with|while|as|leaning|resting|holding|supported|propped|[A-Za-z]+ing)\b", h, re.I):
            sit[-1] = sit[-1].rstrip(".") + ", " + h[:1].lower() + h[1:]
        else:
            sit.append(h)
    integrada = False
    if partner and n_par and not pov and ropa_par:  # la ropa de la pareja se pega a su primera mención: «the man in a grey shirt»
        for i, h in enumerate(sit):
            nuevo, n = re.subn(rf"\bthe\s+{n_par}\b(?!\s+in\b)", f"the {n_par} in {_articulo(ropa_par)}", h, count=1, flags=re.I)
            if n:
                sit[i], integrada = nuevo, True
                break
    if partner and n_par and not pov and not integrada:
        partes.append(f"The scene also includes {_articulo(n_par)}" + (f" in {_articulo(ropa_par)}" if ropa_par else "") + ".")
    for h in sit:
        partes.append(h[:1].upper() + h[1:].rstrip(".") + ".")
    if tr.get("lugar") and tr["lugar"][0]:
        partes.append(f"The setting is the {tr['lugar'][0].lower()}.")
    for h in tr.get("hora", []):
        if h:
            partes.append(h + ".")
    for l in tr.get("luz", []):
        if l:
            partes.append(l + ".")
    if foto.get("gaze"):
        g = str(foto["gaze"]).strip().rstrip(".")
        partes.append(g[:1].upper() + g[1:] + ".")
    prompt = re.sub(r"\s+", " ", " ".join(p for p in partes if p)).strip()
    return prompt, {"descartadas": fuera, "hechos": hechos, "traduccion": tr}


def traducir_lote(textos):
    """Traduce una lista de textos (vacíos se respetan) en una sola llamada al traductor."""
    import imagen_idea as ii

    idx = [i for i, t in enumerate(textos) if t and t.strip()]
    salida = [""] * len(textos)
    if not idx:
        return salida
    mt = ii._cargar_traductor()
    enc = mt["tok"]([aplicar_glosario(ii._restaurar_tildes(textos[i].strip())) for i in idx], return_tensors="pt", padding=True, truncation=True, max_length=160)
    with mt["torch"].no_grad():
        out = mt["m"].generate(**enc, num_beams=3, max_new_tokens=140)
    for i, en in zip(idx, mt["tok"].batch_decode(out, skip_special_tokens=True)):
        salida[i] = ii._glosario(en.strip())
    return salida


# ---------------------------------------------------------------------------------------------- confianza de la traducción (ida y vuelta) y señales de riesgo
PARADAS_ES = set("el la los las un una unos unas de del al con en y o a por para sobre sin su sus se que es esta está estan están como lo le les mi tu ella ello ellos ella mas más muy ya pero si no".split())
_RT = {}


def _cargar_retraductor():
    if "m" not in _RT:
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        _RT["tok"] = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-es")
        _RT["m"] = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-en-es").eval()
        _RT["torch"] = torch
    return _RT


def retraducir_lote(textos_en):
    rt = _cargar_retraductor()
    enc = rt["tok"](list(textos_en), return_tensors="pt", padding=True, truncation=True, max_length=160)
    with rt["torch"].no_grad():
        out = rt["m"].generate(**enc, num_beams=2, max_new_tokens=140)
    return rt["tok"].batch_decode(out, skip_special_tokens=True)


def _raices(t):
    import unicodedata

    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return {w[:5] for w in re.findall(r"[a-zñ]+", t) if len(w) > 3 and w not in PARADAS_ES}


def similitud_ida_vuelta(es, vuelta):
    a, b = _raices(es), _raices(vuelta)
    return 1.0 if not a else len(a & b) / len(a)


def clausulas_dudosas(clausulas_es, clausulas_en, umbral=0.5):
    """[(índice, similitud)] de las cláusulas cuya traducción, traducida de vuelta al español, conserva menos del `umbral` de las palabras de contenido del original. Es una señal, no una prueba."""
    if not clausulas_es:
        return []
    vuelta = retraducir_lote(clausulas_en)
    return [(i, round(similitud_ida_vuelta(e, v), 2)) for i, (e, v) in enumerate(zip(clausulas_es, vuelta)) if similitud_ida_vuelta(e, v) < umbral]


def riesgos_escena(fuente, traza, umbral=0.9):
    """Señales de que ESTA escena conviene revisarla con un LLM en vez de fiarse del redactor determinista: lista de (motivo, detalle). Vacía = sin señales.
      · ida-vuelta: la traducción de una cláusula, traducida de vuelta, pierde palabras (≈ detecta 4 de 5 errores del traductor en una prueba pequeña, con falsas alarmas)
      · posesivo-ambiguo: «su/sus» en una escena con dos personas visibles (no se sabe de quién es)
      · sin-glosario: palabras del español que salieron sin traducir
    """
    riesgos = []
    es, en = traza.get("hechos", []), (traza.get("traduccion", {}) or {}).get("situacion", [])
    if es and len(es) == len(en):
        for i, s in clausulas_dudosas_umbral(es, en, umbral):
            riesgos.append(("ida-vuelta", f"cláusula {i + 1} ({s})"))
    dos_personas = bool(fuente.get("partner")) and fuente.get("camera") != "pov"
    for i, c in enumerate(es):
        if dos_personas and re.search(r"\b(?:su|sus)\b", c, re.I):
            riesgos.append(("posesivo-ambiguo", f"cláusula {i + 1}"))
    for i, t in enumerate(en):
        if re.search(r"\b(?:el|la|los|las|una|un|con|del|que|para|sobre)\b|[áéíóúñ]", t):
            riesgos.append(("sin-traducir", f"cláusula {i + 1}"))
    return riesgos


def clausulas_dudosas_umbral(clausulas_es, clausulas_en, umbral):
    vuelta = retraducir_lote(clausulas_en)
    return [(i, round(similitud_ida_vuelta(e, v), 2)) for i, (e, v) in enumerate(zip(clausulas_es, vuelta)) if similitud_ida_vuelta(e, v) < umbral]
