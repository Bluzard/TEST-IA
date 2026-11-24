"""Compresión VISUAL de los textos largos de una escena real (ropa, lugar, hora, luz) antes de traducirlos.

Las escenas de b_chat no son frases cortas: la ropa llega con 1.100 caracteres de prosa («…que crujen suavemente, dejando al descubierto parte de la piel…»), el lugar con 500
(«…con el sonido lejano de una sirena… y el olor residual a café…») y la luz con 1.000. Un generador de imágenes solo puede dibujar lo visible, y el traductor automático corta a ~140 tokens
(pierde las últimas prendas). Aquí se queda lo dibujable y se descarta la narración, sin inventar nada: solo se SELECCIONAN y se CORTAN fragmentos del propio texto.

Solo se usa con textos largos (> UMBRAL caracteres): los cortos pasan intactos, así que las escenas simples no cambian.
"""
import re

UMBRAL = 160

# cortes: una subordinada o un gerundio narrativo empieza donde acaba lo dibujable
CORTE = re.compile(r"\s+(?:que|donde|mientras|creando|dejando|mostrando|presentando|cubriendo|acentuando|interrumpiendo|sugiriendo|esperando|permitiendo|proyectando|lo\s+que|para\s+(?:acentuar|finalizar|resaltar|marcar)|y\s+que)\b.*$", re.I)
INICIO_NARRATIVO = re.compile(r"^(?:creando|dejando|mostrando|presentando|cubriendo|acentuando|interrumpiendo|sugiriendo|esperando|permitiendo|proyectando|ce[ñn]id[oa]s?\s+a|lo\s+que)\b", re.I)
# lo que no se puede dibujar: sonido, olor, ánimo, ambiente
NO_VISUAL = re.compile(r"\b(?:sonid\w*|ruido\w*|zumbid\w*|eco\b|sirena\w*|silenci\w*|olor\w*|aroma\w*|huele\w*|perfume\w*|fragancia\w*|sabor\w*|humo\b|tens[oa]\w*|atm[oó]sfera\w*|privacidad|sensaci\w+|emoci\w+|ambiente|aire\b|ritmo|temperatura|expectante|cr[ií]tic[oa]\w*|anal[ií]tic[oa]\w*|mirada\w*|esperando|detective|usuario)\b", re.I)
LUZ = re.compile(r"\b(?:luz|luces|l[aá]mpara\w*|sombra\w*|ilumin\w*|brill\w*|claridad|oscuridad|resplandor\w*|ne[oó]n|sol\b|vela\w*|reflej\w*|penumbra|foco\w*|lamparita\w*)\b", re.I)
MOMENTO = re.compile(r"\b(?:noche|madrugada|ma[ñn]ana|tarde|mediod[ií]a|atardecer|amanecer|anochecer|amanece|atardece|anochece|ocaso|alba)\b", re.I)
PRENDAS = re.compile(r"\b(?:blusa|camisa|camiseta|polera|playera|remera|top|su[eé]ter|jersey|sudadera|chaleco|chaqueta|chamarra|abrigo|gabardina|saco|blazer|vestido|falda|pantal[oó]n\w*|jeans|shorts?|bermuda\w*|leggings?|medias|calcet\w+|botas?|botines|zapat\w+|tenis|sandalias|tacones|zapatillas|cintur[oó]n|corbata|bufanda|guantes|gorro|gorra|sombrero|lentes|gafas|collar|aretes|pendientes|reloj|pulsera|anillo|bikini|lencer[ií]a|sost[eé]n|bata|pijama|camis[oó]n|uniforme|delantal|capa|poncho|overol|traje|corset|body|bragas|tanga)\b", re.I)
PREFIJO_ROPA = re.compile(r"^(?:sobre\s+(?:ella|[eé]l|esto),?\s*|para\s+finalizar[^,]*,\s*|adem[aá]s,?\s*|por\s+[uú]ltimo,?\s*|(?:los|las)\s+pies\s+calzan\s+|(?:lleva|viste|calza|luce)(?:\s+puest[oa]s?)?\s+)", re.I)


def _oraciones(t):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=\S)", str(t or "").strip()) if x.strip()]


def _clausulas(t):
    for oracion in _oraciones(t):
        for cl in re.split(r"\s*[,;]\s*", oracion):
            cl = CORTE.sub("", cl).strip(" .")
            if cl and not INICIO_NARRATIVO.match(cl):
                yield cl


def comprimir_visual(texto, max_palabras=32, exigir=None):
    """Cláusulas dibujables del texto, en orden, hasta `max_palabras`. `exigir`: patrón que la cláusula debe contener (p. ej. palabras de luz)."""
    if len(str(texto or "")) <= UMBRAL:
        return str(texto or "")
    salida, total = [], 0
    for cl in _clausulas(texto):
        if NO_VISUAL.search(cl) or (exigir is not None and not exigir.search(cl)):
            continue
        n = len(cl.split())
        if total + n > max_palabras:
            break
        salida.append(cl)
        total += n
    return ", ".join(salida)


def comprimir_momento(texto):
    """«Noche avanzada, justo después de que el turno…» -> «Noche avanzada»: la primera cláusula, si nombra un momento del día."""
    if len(str(texto or "")) <= UMBRAL:
        return str(texto or "")
    for cl in _clausulas(texto):
        if MOMENTO.search(cl) and not NO_VISUAL.search(cl) and len(cl.split()) <= 6:
            return cl
        break
    return ""


def prendas(texto, max_prendas=8, max_palabras=16):
    """Lista de fragmentos de ropa, uno por prenda («botines cortos de cuero sintético negro, con suela de goma»), sin la narración de alrededor."""
    if len(str(texto or "")) <= UMBRAL:
        return [str(texto or "")] if str(texto or "").strip() else []
    items = []
    for oracion in _oraciones(texto):
        for cl in re.split(r"\s*[,;]\s*", oracion):
            cl = CORTE.sub("", cl).strip(" .")
            previo = None
            while previo != cl:  # varios prefijos seguidos: «Para finalizar…, lleva unos pantalones»
                previo, cl = cl, PREFIJO_ROPA.sub("", cl).strip(" .")
            if not cl or INICIO_NARRATIVO.match(cl):
                continue
            if PRENDAS.search(cl):
                cl = re.sub(r"^(?:unos|unas|un|una)\s+", "", cl, flags=re.I)  # «unos botines» -> «a few boots» en inglés: el artículo lo pone el ensamblado
                items.append(" ".join(cl.split()[:max_palabras]))
            elif items and re.match(r"^con\s", cl, re.I) and len(cl.split()) <= 8:
                items[-1] += ", " + cl  # un detalle de la prenda anterior («con suela de goma antideslizante»)
        if len(items) >= max_prendas:
            break
    return items[:max_prendas]
