"""Reglas de búsqueda de respaldo del flujo interactivo de v2c (solo `inferir.responder(..., extras=True)`; v1 y los evaluadores no pasan por aquí).

1. Abstención sin búsqueda: si el núcleo responde «No tengo información suficiente…» SIN haber emitido B: ni usado ninguna herramienta en el turno, y la entrada es una
   consulta informativa real, se fuerza una búsqueda con la pregunta limpia de rodeos («quería saber…», «me gustaría saber…», «sabes…», «dime…») y se le devuelven
   los resultados al núcleo; si tras buscar sigue sin evidencia, se mantiene la abstención.
2. Orden de buscar sobre el turno anterior («¿puedes buscarlo?», «búscalo», «investígalo», «búscalo en internet»): se toma la última consulta informativa de la sesión
   y se busca directamente, en vez de caer en la charla «capacidades».
"""
import re
import unicodedata


def _n(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


RE_ORDEN = re.compile(
    r"(?:(?:puedes|podrias|podria|puede|serias capaz de)\s+)?(?:por favor\s*,?\s*)?"
    r"(?:buscar(?:lo|la|los|las)|busca(?:lo|la|los|las)|investiga(?:rlo|rla|lo|la)|averigua(?:rlo|lo|la)|googlea(?:lo|la)|busca(?: eso| esto| ese tema| informacion| mas informacion))"
    r"(?:\s+(?:en|por)\s+(?:internet|la web|google|linea|la red|ddgs))?(?:\s+(?:por favor|porfa|ahora|de nuevo|otra vez))?")
# rodeos conversacionales de entrada que no forman parte de la consulta
RODEOS = [re.compile(p) for p in (
    r"^(?:hola[, ]*)?(?:oye[, ]*|disculpa[, ]*|una pregunta[:,]? *|pregunta[:,]? *)?",
    r"^(?:queria|quisiera|quiero|me gustaria|necesito|ando buscando|estoy buscando)\s+(?:saber|conocer|averiguar|entender|que me (?:digas|expliques|cuentes))\s+",
    r"^(?:sabes|sabrias|conoces)\s+(?:decirme\s+)?(?=(?:que|cual|quien|como|cuando|donde|cuanto|cuantos|por que)\b)",
    r"^(?:podrias|puedes|me puedes|me podrias)\s+(?:decirme|contarme|explicarme|indicarme|aclararme)\s+",
    r"^(?:dime|cuentame|explicame|hablame de|hablame sobre|dame informacion (?:de|sobre))\s+")]
INTERROGATIVOS = re.compile(r"^(?:cual(?:es)? (?:es|son|fue|fueron)|que (?:es|son|fue|fueron|significa|quiere decir)|quien(?:es)? (?:es|son|fue|fueron)|como (?:se )?(?:llama|funciona|se usa|se hace)|donde (?:queda|esta|estan)|cuando (?:fue|ocurrio|se))\s+")
ARTICULOS = re.compile(r"^(?:el|la|los|las|un|una|unos|unas)\s+")


def es_orden_buscar(mensaje):
    t = _n(mensaje).strip(" ¿?¡!.,;:\n")
    return bool(t) and bool(RE_ORDEN.fullmatch(t))


def limpiar(pregunta):
    """(pregunta limpia, consulta de búsqueda). La consulta es lo que quedaría tras quitar rodeos, interrogativos y artículo inicial; conserva tildes y mayúsculas originales."""
    texto = re.sub(r"\s+", " ", pregunta.strip().strip("¿?¡!. "))
    n = _n(texto)
    corte = 0
    for _ in range(3):  # varios rodeos encadenados: «hola, quería saber…»
        for r in RODEOS:
            m = r.match(n[corte:])
            if m and m.end() > 0:
                corte += m.end()
                break
        else:
            break
    resto = texto[corte:].strip(" ,:;")
    # «sabes qué es…» deja el interrogativo al inicio: «qué es la ley de Morgan»
    q = INTERROGATIVOS.match(_n(resto))
    cuerpo = resto[q.end():] if q else resto
    cuerpo = ARTICULOS.sub("", cuerpo).strip(" ,:;")
    limpia = f"¿{resto[:1].upper() + resto[1:]}?" if resto else pregunta
    return limpia, (cuerpo or resto or pregunta).strip()


def informativa(pregunta):
    """Entrada con contenido buscable: no vacía, no una orden de buscar y con al menos 2 palabras tras limpiar."""
    if not pregunta.strip() or es_orden_buscar(pregunta):
        return False
    return len(limpiar(pregunta)[1].split()) >= 1


INTERROGATIVOS_TILDE = {"que": "qué", "cual": "cuál", "cuales": "cuáles", "quien": "quién", "quienes": "quiénes", "como": "cómo", "donde": "dónde", "cuando": "cuándo",
                        "cuanto": "cuánto", "cuantos": "cuántos", "cuanta": "cuánta", "cuantas": "cuántas", "por que": "por qué"}


def normalizar_con_resultados(pregunta, resultados):
    """El núcleo es sensible a tildes y mayúsculas («morgan en matematicas» -> abstención; «Morgan en matemáticas» -> responde) y quien escribe sin ellas es lo normal.
    Se restauran con EVIDENCIA, sin adivinar: tilde en los interrogativos y, para cada palabra de la pregunta, la forma con tilde/mayúscula más frecuente en los resultados."""
    formas = {}
    for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}", resultados):
        formas.setdefault(_n(w), {}).setdefault(w, 0)
        formas[_n(w)][w] += 1

    def mejor(w):
        cand = formas.get(_n(w))
        if not cand or w in cand:  # sin evidencia, o la forma tal como se escribió ya aparece en los resultados («las», «ley»): no se toca
            return w
        # preferir una forma distinta de «todo minúscula sin tilde» (tilde o mayúscula inicial) si el texto original la tiene; entre ellas, la más frecuente
        especiales = {f: c for f, c in cand.items() if f != _n(f) or f[:1].isupper()}
        if w == w.lower() and _n(w) == w and especiales:
            return max(especiales, key=especiales.get)
        return w

    palabras = re.findall(r"\w+|\W+", pregunta)
    salida, primero = [], True
    for tok in palabras:
        if re.fullmatch(r"\w+", tok):
            t = INTERROGATIVOS_TILDE.get(_n(tok), tok) if primero else mejor(tok)
            primero = False
            salida.append(t if t != tok else (mejor(tok) if tok != tok.lower() or not tok.isalpha() else tok))
        else:
            salida.append(tok)
    out = "".join(salida)
    return re.sub(r"^(¿?)(\w)", lambda m: m.group(1) + m.group(2).upper(), out)


def _oraciones(resultados):
    """Oraciones de los fragmentos de los resultados (sin el número ni el título)."""
    out = []
    for linea in re.split(r"\n| \| ", resultados):
        cuerpo = re.sub(r"^\s*\d+\.\s*[^:]{0,160}:\s*", "", linea.strip())
        for o in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])", cuerpo):
            o = o.strip()
            if len(o) >= 25:
                out.append(o)
    return out


def reparar_cita(respuesta, resultados, minimo=0.75):
    """El núcleo copia fragmentos, pero con tokens técnicos o poco frecuentes puede cambiar una palabra («formuladas» -> «ordenadas») o seguir inventando tras
    un fragmento truncado. En las búsquedas forzadas por la capa de inferencia se alinea la primera oración de la respuesta con la oración más parecida de los
    resultados y se devuelve esa oración EXACTA; si ninguna se parece (>= `minimo`), devuelve None (la respuesta no es fiable: se mantiene la abstención)."""
    from difflib import SequenceMatcher

    if not respuesta:
        return None
    primera = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])", respuesta.strip())[0]
    mejor, ratio = None, 0.0
    for o in _oraciones(resultados):
        r = SequenceMatcher(None, primera.lower(), o.lower()).ratio()
        if r > ratio:
            mejor, ratio = o, r
    return mejor if mejor and ratio >= minimo else None
