"""Fichas por modelo de imagen para el experto de prompts (base local, consultable con «B: <modelo>»).

Cada ficha resume COMO se le escribe a ese modelo (estructura, longitud, negativos, parámetros). El experto no memoriza estas reglas: las lee de la ficha en cada pedido.
Las cifras vienen de documentación pública y guías de la comunidad (2025-2026) y algunas fuentes se contradicen: lo dudoso está marcado «orientativo».
Fuentes: Black Forest Labs (docs.bfl.ai), QwenLM/Qwen-Image (README, diffusers), Tongyi-MAI/Z-Image (model card, discusiones), Civitai developer docs, guías de Segmind/fal.ai/Civitai.

FICHAS_IMAGEN: id -> dict(nombres, estilo, negativo, resumen, plantilla, ejemplo)
  estilo: "natural" (frases fluidas) | "etiquetas" (tags separados por comas con pesos)
  negativo: "no" (el modelo no usa prompt negativo: lo que no se quiere se reformula en positivo) | "linea" (se añade una línea «Negative prompt: …»)
"""
import re
import unicodedata

NEGATIVO_SD = "worst quality, low quality, blurry, jpeg artifacts, watermark, signature, text, cropped, deformed, bad anatomy, extra fingers"
NEGATIVO_PONY = "score_5, score_4, score_3, blurry, worst quality, low quality, watermark, text, bad anatomy, extra fingers"
NEGATIVO_ILL = "worst quality, low quality, bad anatomy, blurry, watermark, signature, jpeg artifacts, extra digits"
NEGATIVO_NL = "blurry, low resolution, distorted, deformed, oversaturated, watermark, extra limbs"

FICHAS_IMAGEN = {
    "flux": dict(
        nombres=["flux", "flux.1", "flux1", "flux dev", "flux.1 dev", "flux schnell", "flux.1 schnell", "flux 1", "flux1 dev"],
        estilo="natural", negativo="no",
        resumen="Flux.1 (dev/schnell) entiende lenguaje natural: escribe frases completas en inglés, sin etiquetas sueltas ni pesos. No usa prompt negativo: describe lo que SÍ quieres. "
                "Orden útil: sujeto, acción, entorno, iluminación, cámara o estilo, ambiente. Los primeros términos pesan más. Admite hasta unos 512 tokens, pero 40-120 palabras bastan. Evita «white background» en dev (puede difuminar).",
        plantilla="[sujeto con rasgos concretos] [acción o pose] in [entorno], [iluminación], [cámara/lente o medio artístico], [ambiente y paleta de colores].",
        ejemplo="A weathered fisherman in a yellow raincoat mends a net on a wooden pier at dawn, soft golden light breaking through low fog, shot on a 35mm lens with shallow depth of field, calm and nostalgic mood, muted teal and amber tones."),
    "z-image-turbo": dict(
        nombres=["z-image turbo", "z image turbo", "zimage turbo", "z-image-turbo", "zit", "z-image", "z image", "zimage", "turbo"],
        estilo="natural", negativo="no",
        resumen="Z-Image Turbo (Tongyi, destilado a pocos pasos: unos 8-9 pasos, guidance 0-1 orientativo) ignora el prompt negativo: escribe todo en positivo («sharp focus», «clean background»). "
                "Rinde con prompts largos y específicos en lenguaje natural (inglés o chino): sujeto, entorno, estilo y luz. Dibuja bien texto corto entre comillas, también en chino.",
        plantilla="[estilo/medio], [sujeto detallado], [entorno], [iluminación], [lente o textura], [texto entre comillas si hay]. Todo en frases naturales y en positivo.",
        ejemplo="A candid street photograph of an elderly woman selling flowers at a rainy night market, neon signs reflecting on wet pavement, warm tungsten light on her face, sharp focus, fine skin texture, 50mm lens, shallow depth of field, cinematic color grading."),
    "z-image-base": dict(
        nombres=["z-image base", "z image base", "zimage base", "z-image-base"],
        estilo="natural", negativo="linea",
        resumen="Z-Image Base (sin destilar: unos 28-50 pasos, guidance 3-5 orientativo) sí respeta el prompt negativo y da más variedad que Turbo. Mismo estilo natural y detallado en inglés o chino; "
                "usa «Negative prompt:» para excluir defectos y detalles no deseados.",
        plantilla="[estilo/medio], [sujeto detallado], [entorno], [iluminación], [lente o textura]. Línea aparte: Negative prompt: [defectos a evitar].",
        ejemplo="A cozy watercolor illustration of a fox reading by a lantern inside a hollow tree, warm amber glow, soft paper texture, gentle brush strokes, storybook style.\nNegative prompt: blurry, low resolution, distorted, watermark, extra limbs"),
    "qwen-image": dict(
        nombres=["qwen-image", "qwen image", "qwen", "qwen-image 2512", "qwenimage"],
        estilo="natural", negativo="linea",
        resumen="Qwen-Image (20B) destaca por RENDERIZAR TEXTO en la imagen (inglés y chino, varias líneas): pon el texto exacto entre comillas y di dónde va y con qué tipografía o color. "
                "Lenguaje natural largo y claro; el prompt negativo solo actúa con true_cfg_scale > 1 (el repositorio usa 4.0 y 50 pasos; para no usar negativo se pasa un espacio).",
        plantilla="[tipo de imagen o cartel], [sujeto y composición], el texto «[texto exacto]» [dónde, tipografía y color], [estilo e iluminación]. Línea aparte opcional: Negative prompt: [defectos].",
        ejemplo="A vintage coffee shop poster in warm cream and brown tones, a steaming cup illustrated at the center, the title \"MORNING BREW\" in bold retro serif letters at the top and the line \"Fresh roasted daily\" in smaller script at the bottom, clean flat illustration style.\nNegative prompt: blurry, distorted text, low resolution"),
    "sdxl": dict(
        nombres=["sdxl", "sd xl", "stable diffusion xl", "stable diffusion sdxl", "sd", "stable diffusion", "sd 1.0", "juggernaut", "realvis"],
        estilo="etiquetas", negativo="linea",
        resumen="SDXL (1024x1024) funciona con etiquetas o frases cortas separadas por comas; necesita menos palabras que SD 1.5. Pesos con (palabra:1.2), nunca mayores de 1.5. "
                "Se acostumbra abrir con «masterpiece, best quality» y llevar prompt negativo (worst quality, low quality, blurry, watermark…).",
        plantilla="masterpiece, best quality, [sujeto], [rasgos], [entorno], [iluminación], [estilo o medio], [cámara]. Línea aparte: Negative prompt: [defectos].",
        ejemplo=f"masterpiece, best quality, a lone astronaut sitting on a red desert dune, (dramatic rim lighting:1.2), twin moons in the sky, dust in the air, cinematic composition, ultra detailed, 35mm photo\nNegative prompt: {NEGATIVO_SD}"),
    "sd15": dict(
        nombres=["sd1.5", "sd 1.5", "sd15", "stable diffusion 1.5", "sd 1.4", "stable diffusion 1.4", "sd1.4"],
        estilo="etiquetas", negativo="linea",
        resumen="SD 1.5 (512x512) se escribe con etiquetas separadas por comas, de lo más importante a lo menos, con pesos (palabra:1.2). Abre con etiquetas de calidad (masterpiece, best quality, highly detailed) "
                "y lleva siempre prompt negativo; con 75 tokens por bloque conviene ser conciso.",
        plantilla="masterpiece, best quality, highly detailed, [sujeto], [rasgos], [entorno], [iluminación], [estilo]. Línea aparte: Negative prompt: [defectos].",
        ejemplo=f"masterpiece, best quality, highly detailed, portrait of an old sailor, (weathered face:1.2), thick white beard, stormy sea background, dramatic lighting, oil painting\nNegative prompt: {NEGATIVO_SD}, lowres"),
    "pony": dict(
        nombres=["pony", "pony xl", "pony diffusion", "pdxl", "pony v6", "ponyxl"],
        estilo="etiquetas", negativo="linea",
        resumen="Pony Diffusion (SDXL) se abre con etiquetas de puntuación «score_9, score_8_up, score_7_up» y sigue con etiquetas estilo Danbooru (sujeto, rasgos, ropa, pose, fondo). "
                "Prompt negativo con score_5, score_4, score_3. Es de los modelos que más dependen de las etiquetas exactas.",
        plantilla="score_9, score_8_up, score_7_up, [personaje], [rasgos], [ropa], [pose], [fondo], [iluminación]. Línea aparte: Negative prompt: score_5, score_4, score_3, [defectos].",
        ejemplo=f"score_9, score_8_up, score_7_up, 1girl, silver hair, red scarf, winter coat, standing in snowy street, night, city lights, looking at viewer, soft lighting\nNegative prompt: {NEGATIVO_PONY}"),
    "illustrious": dict(
        nombres=["illustrious", "illustrious xl", "illustriousxl", "noobai", "noob ai", "noobai-xl", "waiillustrious"],
        estilo="etiquetas", negativo="linea",
        resumen="Illustrious XL (y derivados como NoobAI) usa etiquetas estilo Danbooru; abre con etiquetas de calidad (masterpiece, best quality, newest, absurdres) y lleva prompt negativo "
                "(worst quality, low quality, bad anatomy). No necesita los score_X de Pony.",
        plantilla="masterpiece, best quality, newest, absurdres, [personajes], [rasgos], [ropa], [pose], [fondo]. Línea aparte: Negative prompt: [defectos].",
        ejemplo=f"masterpiece, best quality, newest, absurdres, 1girl, long black hair, yellow raincoat, holding umbrella, rainy city street, reflections, cinematic lighting\nNegative prompt: {NEGATIVO_ILL}"),
}

# conceptos transversales (también consultables): qué es cada cosa y cómo se usa en un prompt
FICHAS_TEMAS = {
    "orden del prompt": "En un prompt de imagen conviene ir de lo más importante a lo menos: sujeto, acción, entorno, iluminación, cámara o estilo y ambiente. Los primeros términos pesan más.",
    "prompt negativo": "El prompt negativo lista lo que NO debe aparecer (blurry, watermark, bad anatomy). Lo usan SD, SDXL, Pony, Illustrious, Z-Image Base y Qwen-Image; Flux y Z-Image Turbo lo ignoran: ahí se reformula en positivo.",
    "peso de etiquetas": "En SD/SDXL (palabra:1.2) sube la importancia de una palabra y (palabra:0.8) la baja; se evita pasar de 1.5 porque deforma la imagen. Flux y Qwen-Image no usan pesos.",
    "texto en la imagen": "Para escribir texto dentro de la imagen se pone entre comillas, exacto, y se indica dónde va y con qué estilo. Qwen-Image y Z-Image lo hacen bien; SD 1.5 casi nunca.",
    "iluminación": "La luz define el ambiente: golden hour, soft diffused light, dramatic rim lighting, neon glow, overcast, candlelight, studio softbox, backlit.",
    "cámara y lente": "Para fotografía realista se nombra encuadre y lente: close-up, wide shot, low angle, 35mm, 85mm portrait lens, shallow depth of field, bokeh, macro.",
}


def _n(t):
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


_INDICE = {}
for _k, _f in FICHAS_IMAGEN.items():
    for _nom in _f["nombres"] + [_k]:
        _INDICE[_n(_nom)] = _k
# alias del vocabulario común que SIEMPRE se resuelven a Turbo cuando dicen solo «z-image»
_INDICE[_n("z-image")] = "z-image-turbo"


def resolver_modelo(texto):
    """id de modelo (clave de FICHAS_IMAGEN) mencionado en el texto, o None. Gana la mención más específica (más larga)."""
    t = " " + _n(texto) + " "
    mejor = None
    for alias, k in _INDICE.items():
        if f" {alias} " in t and (mejor is None or len(alias) > mejor[0]):
            mejor = (len(alias), k)
    return mejor[1] if mejor else None


def modelo_pedido(texto):
    """Modelo destino que el usuario NOMBRA COMO DESTINO del prompt, o None. Más estricto que `resolver_modelo`: «un pony en un prado» no pide el modelo Pony.
    Cuenta un alias si está al inicio del mensaje, tras «para / for / con / en / de / usando / prompt», seguido de «:» o «->», o en una clave model/modelo de JSON o YAML."""
    import re as _re

    t = _n(texto)
    raw = texto.lower()
    m = _re.search(r'"?(?:model|modelo)"?\s*[:=]\s*"?([a-z0-9 .\-_]+)', raw)
    if m:
        k = resolver_modelo(m.group(1))
        if k:
            return k
    mejor = None
    for alias, k in _INDICE.items():
        if len(alias) < 3:
            continue
        a = _re.escape(alias)
        if (_re.match(rf"\s*{a}(?![a-z0-9])", t) or _re.search(rf"(?:^|\s)(?:para|for|con|with|en|in|de|usando|using|prompt|prompts)\s+{a}(?![a-z0-9])", t)
                or _re.search(rf"(?<![a-z0-9]){a}\s*(?:->|=>)", t) or _re.search(rf"(?<![a-z0-9]){a}\s*:", _re.sub(r"[^\w\s:.\-]", "", raw))):
            if mejor is None or len(alias) > mejor[0]:
                mejor = (len(alias), k)
    return mejor[1] if mejor else None


def ficha_linea(k):
    f = FICHAS_IMAGEN[k]
    return f"{f['resumen']} Plantilla: {f['plantilla']} Ejemplo: {f['ejemplo']}"


def buscar_ficha_imagen(consulta):
    """Base local para «B: <modelo>» o «B: <tema>»: «1. <modelo> - base local: …» o None."""
    k = resolver_modelo(consulta)
    if k:
        return f"1. {k} - base local: {ficha_linea(k)}"
    q = _n(consulta)
    for tema, txt in FICHAS_TEMAS.items():
        if _n(tema) in q or q in _n(tema):
            return f"1. {tema} - base local: {txt}"
    return None


if __name__ == "__main__":
    for m in ("flux", "Z-Image Turbo", "qwen image", "sdxl", "pony xl", "z-image base", "illustrious", "sd 1.5", "stable diffusion"):
        print(m, "->", resolver_modelo(m))
    print(buscar_ficha_imagen("flux")[:200])
