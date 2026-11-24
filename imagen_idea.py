"""Opción B del experto de prompts de imagen: CONSERVAR LA IDEA DEL USUARIO.

Medido (imagen_d): con descripciones libres el núcleo apenas usa la entrada (ganancia de pérdida 0,1-0,3 nats en prompts reales largos), así que reescribir la idea con el modelo la pierde
(«gato dormido en una ventana lluviosa» -> «gato en un campo de lavanda»). Aquí la idea no pasa por el modelo:

  1. extraer_idea     quita el marco del pedido («hazme un prompt para flux de…», el nombre del modelo, JSON/YAML/viñetas) y deja lo que se quiere ver
  2. traducir_es_en   traduce al inglés con opus-mt-es-en (Apache-2.0, 75 M; se carga la primera vez que hace falta). Los textos entre comillas NO se traducen (son lo que se escribe en la imagen),
                      y antes se restauran las tildes con el corrector determinista del proyecto («luciernagas» -> «luciérnagas»)
  3. el prompt EMPIEZA con la idea traducida y el núcleo solo CONTINÚA (estilo, luz, cámara, calidad, según la ficha del modelo) forzando ese comienzo (inferir.escribir_cuerpo_imagen)

Dependencia opcional: `pip install transformers sentencepiece sacremoses`. Sin ella (o con --sin-traductor) se usa el camino anterior.
"""
import json
import re
import unicodedata

from imagen_fichas import _INDICE

_MT = {}
ES_PALABRAS = set("el la los las un una unos unas de del al con en y o que para por sobre sin se es son muy más mas como cuando donde hacia desde entre tipo estilo foto imagen dibujo noche día dia lluvia bosque gato perro".split())
EN_PALABRAS = set("the a an of with in on at and or for to is are very more as from by under over style photo image drawing night day rain forest cat dog".split())
CLAVES_IGNORADAS = {"model", "modelo", "aspect_ratio", "ratio", "seed", "steps", "cfg", "width", "height", "negative_prompt", "negative"}
CLAVES_TEXTO = {"text", "texto", "title", "titulo", "título", "caption", "subtext", "subtexto", "slogan", "headline"}


def _n(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


_ALIAS = sorted((a for a in _INDICE if len(a) >= 3), key=len, reverse=True)
_RE_ALIAS = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(a).replace(r"\ ", r"[\s\-_.]*") for a in _ALIAS) + r")(?![a-z0-9])", re.I)
_RE_PEDIDO = re.compile(
    r"\b(?:hazme|haz|hagame|me\s+haces|me\s+puedes\s+hacer|puedes\s+hacerme|genera(?:me)?|escribe(?:me)?|redacta(?:me)?|crea(?:me)?|dame|necesito|quiero|quisiera|ayudame(?:\s+con)?|ayuda\s+con|"
    r"write|make\s+me|make|generate|create|i\s+need|i\s+want|give\s+me)\b[^:\n]{0,40}?\b(?:prompts?|imagen|image|foto|picture|ilustracion|dibujo)\b(?:\s+(?:de|del|para|of|for|about|sobre))?",
    re.I)
_RE_PROMPT = re.compile(r"\b(?:prompts?)\b(?:\s+(?:de|del|para|of|for|en|pa))?", re.I)


def extraer_idea(texto):
    """Lo que el usuario quiere VER, sin el marco del pedido ni el nombre del modelo. JSON/YAML/viñetas se aplanan a una lista de rasgos."""
    t = texto.strip()
    partes = []
    if t.startswith("{") or "{" in t[:80]:
        ini = t.find("{")
        try:
            obj = json.loads(t[ini:])
        except ValueError:
            obj = None
        if obj is not None:
            def hojas(o, clave=""):
                if isinstance(o, dict):
                    for k, v in o.items():
                        yield from hojas(v, str(k))
                elif isinstance(o, list):
                    for v in o:
                        yield from hojas(v, clave)
                elif o is not None and clave.lower() not in CLAVES_IGNORADAS:
                    yield clave, str(o)

            todas = [(k, v) for k, v in hojas(obj) if v.strip()]
            rasgos = [v for k, v in todas if k.lower() not in CLAVES_TEXTO]
            es = es_espanol(", ".join(rasgos))
            textos = [f'{"con el texto" if es else "with the text"} "{v}"' for k, v in todas if k.lower() in CLAVES_TEXTO]  # lo que se escribe en la imagen va entre comillas y no se traduce
            partes = rasgos + textos
            t = ", ".join(partes)
    if not partes:
        lineas = [l.strip() for l in t.splitlines() if l.strip()]
        if len(lineas) >= 2 and sum(bool(re.match(r"^[-*•]\s+|^[\w ]{2,20}:\s+\S", l)) for l in lineas) >= len(lineas) - 1:  # viñetas o «clave: valor»
            vals = []
            for l in lineas:
                m = re.match(r"^(?:[-*•]\s+)?(?:([\w ]{2,20}):\s+)?(.*)$", l)
                clave, valor = (m.group(1) or "").strip().lower(), m.group(2).strip()
                if clave in CLAVES_IGNORADAS or (not clave and valor and _RE_ALIAS.fullmatch(_n(valor))):
                    continue
                if valor:
                    vals.append(valor)
            t = ", ".join(vals)
    t = _RE_ALIAS.sub(" ", _prep_alias(t))
    t = _RE_PEDIDO.sub(" ", t)
    t = _RE_PROMPT.sub(" ", t)
    t = re.sub(r"\b(?:quiero|necesito|quisiera|me gustaria)\s+(?:generar|crear|hacer|escribir|obtener)\b(?:\s+(?:con|en|para|de))?", " ", t, flags=re.I)
    t = re.sub(r"^\W+|(?<=\s)[:\-–>]+(?=\s)", " ", t)
    t = re.sub(r"\b(?:de|del|para|for|of|en|pa|con|with|a)\s*[:,]", ":", t)
    t = re.sub(r"\s+", " ", t).strip(" :,.-–>")
    t = re.sub(r"^(?:de|del|para|for|of|en|pa|un|una)\s+(?=(?:un|una|el|la|a|an|the|\w+ de)\b)", "", t, flags=re.I)
    return t.strip(" :,.-–>")


def _prep_alias(t):
    """«para flux», «en sdxl», «pa Turbo»: la preposición que acompañaba al nombre del modelo se va con él."""
    return re.sub(r"\b(?:para|for|en|pa|con|with|de|usando|using)\s+(?=" + _RE_ALIAS.pattern + r")", " ", t, flags=re.I)


def es_espanol(t):
    pal = re.findall(r"[a-záéíóúñü]+", t.lower())
    es = sum(p in ES_PALABRAS for p in pal) + 2 * bool(re.search(r"[áéíóúñ¿¡]", t))
    en = sum(p in EN_PALABRAS for p in pal)
    return es >= en and es > 0


def _restaurar_tildes(t):
    try:
        from corrector import corregir_palabra
    except Exception:
        return t

    def fija(m):
        w = m.group(0)
        if len(w) < 4 or w != _n(w):
            return w
        c = corregir_palabra(w)
        return c if c != w and _n(c) == _n(w) else w

    return re.sub(r"[a-zñ]+", fija, t)


def _cargar_traductor():
    if "m" not in _MT:
        import os

        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        nombre = "Helsinki-NLP/opus-mt-es-en"
        _MT["tok"] = MarianTokenizer.from_pretrained(nombre)
        _MT["m"] = MarianMTModel.from_pretrained(nombre).eval()
        _MT["torch"] = torch
    return _MT


GLOSARIO = [(r"\b[Ee]lfa\b", "elven"), (r"\b[Ee]lfo\b", "elven"), (r"\bnightlights?\b", "fireflies"), (r"\b[Ll]ighthouse keeper\b", "lighthouse keeper")]


def _glosario(t):
    """Errores frecuentes del traductor en vocabulario de imágenes («elfa» -> «elven»)."""
    for pat, rem in GLOSARIO:
        t = re.sub(pat, rem, t)
    return t


def traducir_es_en(texto):
    """Traduce al inglés respetando lo que va entre comillas (texto a escribir en la imagen). Devuelve el original si no hay traductor instalado."""
    try:
        mt = _cargar_traductor()
    except Exception:
        return texto
    trozos = re.split(r"""((?<!\w)["“'‘].{1,80}?["”'’](?!\w))""", texto)
    pendientes = [(i, _restaurar_tildes(p.strip())) for i, p in enumerate(trozos) if i % 2 == 0 and re.search(r"[A-Za-zÁÉÍÓÚáéíóúñ]{2}", p)]
    if pendientes:
        enc = mt["tok"]([p for _, p in pendientes], return_tensors="pt", padding=True, truncation=True, max_length=128)
        with mt["torch"].no_grad():
            out = mt["m"].generate(**enc, num_beams=2, max_new_tokens=100)
        for (i, _), en in zip(pendientes, mt["tok"].batch_decode(out, skip_special_tokens=True)):
            trozos[i] = " " + en.strip().rstrip(".") + " "
    return _glosario(re.sub(r"\s+", " ", "".join(trozos)).strip())


def idea_en_ingles(texto, traducir=True):
    """(idea en inglés lista para ir al inicio del prompt, idioma de la entrada, idea original)."""
    idea = extraer_idea(texto)
    if not idea:
        return "", "?", ""
    if traducir and es_espanol(idea):
        en = traducir_es_en(idea)
        idioma = "es"
    else:
        en, idioma = idea, "en"
    en = re.sub(r"^(?:i want|i need|i would like|make me|write me)\b[^,.]{0,20}?\b(?:an? )?(?:image|picture|photo|prompt) of\s+", "", en, flags=re.I).strip(" ,.")
    return (en[:1].upper() + en[1:]) if en else "", idioma, idea


# ---------------------------------------------------------------------------------------------- enriquecimiento determinista (estilo, luz, cámara, calidad)
FOTO = re.compile(r"\b(photo|photograph|photorealistic|realistic|portrait|35mm|85mm|camera|dslr|film|candid|documentary|macro|headshot|snapshot)\b", re.I)
ARTE = re.compile(r"\b(watercolor|oil painting|painting|illustration|sketch|drawing|anime|manga|cartoon|comic|pixel art|vector|3d render|render|digital art|concept art|ghibli|cyberpunk|fantasy art|artwork|poster|logo|icon)\b", re.I)
TIENE_LUZ = re.compile(r"\b(light|lighting|lit|candle|candlelight|sunset|sunrise|golden hour|neon|glow|glowing|moonlight|backlit|backlight|shadow|shadows|lamp|lantern|sunlight|dusk|dawn|twilight)\b", re.I)
TIENE_CAM = re.compile(r"\b(close-up|closeup|wide|lens|angle|macro|aerial|pov|first-person|shot|depth of field|bokeh|top-down|low angle|framing|portrait)\b", re.I)
TIENE_CAL = re.compile(r"\b(detailed|sharp|focus|8k|4k|hd|high resolution|intricate|crisp|fine textures)\b", re.I)
FANTASIA = re.compile(r"\b(dragons?|elf|elven|elfa|wizard|mage|castle|magic(?:al)?|unicorn|goblin|fairy|mermaid|spaceship|robot|alien|monster|knight|samurai|cyborg|warrior|demon|angel|ghost|zombie|phoenix|griffin|orc|dwarf|vampire|witch)\b", re.I)
LUCES_NEUTRO = ["soft cinematic lighting", "gentle ambient light", "warm balanced lighting", "soft diffused light"]
CALIDAD_NEUTRO = ["highly detailed, sharp focus", "fine detail, clean rendering", "crisp details, balanced colors"]
LUCES_FOTO = ["soft natural light", "warm golden hour light", "soft diffused window light", "cinematic lighting with gentle shadows", "overcast soft light"]
LUCES_ARTE = ["soft diffused lighting", "warm ambient glow", "gentle dramatic lighting", "luminous soft light", "balanced natural lighting"]
CAMARAS_FOTO = ["shot on an 85mm lens with shallow depth of field", "35mm lens, natural perspective, shallow depth of field", "eye-level framing with soft background blur", "balanced composition, 50mm lens"]
COMPOSICION_ARTE = ["balanced composition", "clear focal point and harmonious composition", "well-composed framing", "clean composition with a clear subject"]
CALIDAD_FOTO = ["sharp focus, fine textures, high detail", "crisp details, natural textures, high resolution", "highly detailed, true-to-life textures"]
CALIDAD_ARTE = ["rich detail, harmonious colors", "highly detailed, cohesive color palette", "fine detail, polished finish"]


def _elige(lista, semilla):
    import hashlib

    return lista[int(hashlib.md5(semilla.encode()).hexdigest(), 16) % len(lista)]


def enriquecer(k, idea_en, variante=0):
    """Prompt completo (sin prefijos ni negativos: eso lo pone imagen_formato) = la idea del usuario + estilo, luz, cámara y calidad CURADOS y coherentes con el tipo de imagen.
    Solo añade lo que la idea no trae ya (si dices «luz de velas» no se añade otra luz). Determinista: la misma idea da siempre el mismo prompt."""
    from imagen_fichas import FICHAS_IMAGEN

    natural = FICHAS_IMAGEN[k]["estilo"] == "natural"
    idea = idea_en.strip().rstrip(" .,;")
    base = idea
    clase = "foto" if (FOTO.search(idea) and not ARTE.search(idea)) else ("arte" if (ARTE.search(idea) or FANTASIA.search(idea)) else "neutro")
    foto = clase == "foto"
    partes = []
    if not TIENE_LUZ.search(idea):
        partes.append(_elige(LUCES_FOTO if foto else (LUCES_NEUTRO if clase == "neutro" else LUCES_ARTE), f"{idea}luz{variante}"))
    if not TIENE_CAM.search(idea):
        partes.append(_elige(CAMARAS_FOTO if foto else COMPOSICION_ARTE, f"{idea}cam{variante}"))
    if not TIENE_CAL.search(idea):
        partes.append(_elige(CALIDAD_FOTO if foto else (CALIDAD_NEUTRO if clase == "neutro" else CALIDAD_ARTE), f"{idea}cal{variante}"))
    if k == "z-image-turbo" and not re.search(r"\bsharp focus\b", " ".join(partes + [idea]), re.I):
        partes.append("sharp focus")  # Turbo no usa negativos: la nitidez se pide en positivo
    if natural:
        if not partes:
            return idea + "."
        luz = [p for p in partes if p in LUCES_FOTO + LUCES_ARTE + LUCES_NEUTRO]
        resto = [p for p in partes if p not in luz]
        frase = (f"Lit by {luz[0]}" if luz else "") + (", " if luz and resto else "") + ", ".join(resto)
        return f"{idea}. {frase[:1].upper() + frase[1:]}."
    etiqueta = re.sub(r"^(?:an?|the)\s+", "", idea, flags=re.I)
    etiqueta = re.sub(r'("[^"]*")|([^"]+)', lambda m: m.group(1) or m.group(2).lower(), etiqueta)
    return ", ".join([etiqueta] + partes)


RE_SEGUIMIENTO = re.compile(r"\b(?:otra|otro|una)\s+(?:version|variante|opcion|prompt|estilo)(?:\s+(?:del|de))?\b|\bahora\s+(?:para|en|con)\b|\bahora\b|\bpero\b|\b(?:hazlo|ponlo|cambialo|cambia)\b|\bsin\s+texto\b|\bcon\s+texto\b|\bde\s+nuevo\b", re.I)


def modificador_de_seguimiento(texto):
    """«otra version mas oscura» -> «más oscura»: lo que se quiere cambiar de la imagen anterior (vacío si solo cambia el modelo o se pide otra versión)."""
    t = extraer_idea(_n(texto))
    t = RE_SEGUIMIENTO.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip(" ,.:;-")
