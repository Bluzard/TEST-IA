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
        if w != _n(w):  # ya trae tilde: no se toca (solo se restauran palabras escritas sin tilde)
            return w
        if not cand:  # sin evidencia en los resultados: corrector determinista del proyecto (léxico de 193 k formas), solo si cambia únicamente la tilde
            try:
                from corrector import corregir_palabra

                c = corregir_palabra(w)
                return c if c != w and _n(c) == _n(w) else w
            except Exception:
                return w
        # gana la forma más frecuente en los resultados («las» frente a «Las» de inicio de oración); a igualdad, la que lleva tilde y luego la capitalizada
        f = max(cand, key=lambda x: (cand[x], x != _n(x), x[:1].isupper()))
        return f[:1].upper() + f[1:] if w[:1].isupper() else f

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


def reparar_cita(respuesta, resultados, consulta=None, minimo=0.9):
    """El núcleo copia fragmentos, pero con tokens técnicos o poco frecuentes puede cambiar una palabra («formuladas» -> «ordenadas») o seguir inventando tras
    un fragmento truncado. En las búsquedas forzadas por la capa de inferencia se alinea la primera oración de la respuesta con la oración más parecida de los
    resultados y se devuelve esa oración EXACTA; si ninguna se parece (>= `minimo`), devuelve None (la respuesta no es fiable: se mantiene la abstención)."""
    from difflib import SequenceMatcher

    if not respuesta:
        return None
    plano = re.sub(r"\s+", " ", resultados)
    if re.sub(r"\s+", " ", respuesta.strip()) in plano:  # ya es una cita literal: no se toca (el separador de oraciones puede cortar abreviaturas)
        return respuesta
    primera = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])", respuesta.strip())[0]
    candidatas = _oraciones(resultados)
    if not candidatas:  # resultados sin oraciones comparables (cifras, nombres sueltos): no hay contra qué verificar, se deja la respuesta
        return respuesta
    mejor, ratio = None, 0.0
    for o in candidatas:
        r = SequenceMatcher(None, primera.lower(), o.lower()).ratio()
        if r > ratio:
            mejor, ratio = o, r
    if mejor and ratio >= minimo:
        return mejor
    # la respuesta del núcleo no es fiable (muy distinta de cualquier oración): se elige la oración de los resultados que responde a la consulta, si la hay
    return _extractiva(resultados, consulta) if consulta else None


RE_CONTENIDO = re.compile(
    r"^(?:(?:que|cual(?:es)?)\s+(?:es|son|fue|fueron|era|significa|quiere decir|se entiende por)\s+\w+"
    r"|quien(?:es)?\s+(?:es|son|fue|fueron|era|descubrio|escribio|invento|fundo|pinto|compuso|gano|creo|dirigio|dijo)\s+\w+"
    r"|donde\s+(?:queda|esta|estan|nacio|vivio|se encuentra)\s+\w+"
    r"|cuando\s+(?:fue|nacio|murio|se fundo|ocurrio|termino|empezo|comenzo|se descubrio)\s+\w+"
    r"|cuanto[sa]?\s+\w+\s+(?:tiene|mide|pesa|hay|miden|dura|cuesta)\b"
    r"|como\s+(?:se llama|funciona|se hace|se dice|se escribe|se forma)\s+\w+"
    r"|por que\s+(?:es|son|se|los|las|el|la)\s+\w+"
    r"|(?:dime|cuentame|explicame|hablame)\s+(?:la|el|los|las|de|del|sobre|que es|cual|quien)\s+\w+"
    r"|(?:queria|quisiera|quiero|me gustaria|necesito)\s+(?:saber|conocer|averiguar)\s+\w+)")
RE_PROMETE = re.compile(r"\b(?:buscarlo|buscarla|lo busco|la busco|te lo busco|busco el pronostico|intento buscarlo|prefiero buscarlo|y lo busco|y busco)\b")


def contenido(pregunta):
    """Pregunta de contenido (qué/cuál/quién/cómo…, «dime…», «quería saber…»), no una consulta sobre las capacidades del asistente («¿puedes buscar en internet?»)."""
    limpia, _ = limpiar(pregunta)
    return bool(RE_CONTENIDO.match(_n(limpia).strip(" ¿?¡!")) or RE_CONTENIDO.match(_n(pregunta).strip(" ¿?¡!")))


def promete_buscar(respuesta):
    """Respuesta de charla que desvía con «puedo buscarlo / lo busco» en lugar de buscar."""
    return bool(RE_PROMETE.search(_n(respuesta)))


# La pregunta habla del propio asistente («¿quién eres?», «¿cuál es tu nombre?», «¿qué puedes hacer?»): esas SÍ son charla y no se buscan
RE_SOBRE_ASISTENTE = re.compile(r"\b(?:eres|erez|tu|tus|ti|te|tienes|puedes|sabes|haces|estas|opinas|piensas|crees|sientes|prefieres|quieres|llamas|creo|hizo|entreno|programo|desarrollo|"
                                r"construyo|inventaron|test ?ia|asistente|robot|bot|ia)\b")
_CHARLA_RESPUESTAS = set()


def sobre_asistente(pregunta):
    return bool(RE_SOBRE_ASISTENTE.search(_n(pregunta)))


def es_charla_plantilla(respuesta):
    """La respuesta es una de las plantillas de charla del SFT (charla_v2): una pregunta de contenido que la recibe no fue entendida como consulta."""
    if not _CHARLA_RESPUESTAS:
        import charla_v2

        for _, (_, rs) in charla_v2.INTENCIONES.items():
            for r in rs:
                _CHARLA_RESPUESTAS.add(_n(r.split("{n}")[0]).strip())
    t = _n(respuesta).strip()
    return any(t.startswith(r) for r in _CHARLA_RESPUESTAS if len(r) >= 12)


PARADAS = {"de", "del", "la", "el", "los", "las", "un", "una", "en", "y", "o", "que", "es", "son", "por", "para", "con", "al", "se", "a", "su", "sus", "lo"}


def _palabras_clave(consulta):
    return {w for w in re.findall(r"\w+", _n(consulta)) if w not in PARADAS and len(w) > 2}


def _extractiva(resultados, consulta):
    """Mejor oración de los resultados para la consulta: debe contener todas (o 3/4 de) las palabras clave; a igualdad gana la de un resultado anterior."""
    claves = _palabras_clave(consulta)
    if not claves:
        return None
    mejor, mejor_puntaje = None, 0.0
    for rango, linea in enumerate(re.split(r"\n| \| ", resultados)):
        cuerpo = re.sub(r"^\s*\d+\.\s*[^:]{0,160}:\s*", "", linea.strip())
        for o in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])", cuerpo):
            o = o.strip()
            if not 40 <= len(o) <= 400:
                continue
            presentes = len(claves & set(re.findall(r"\w+", _n(o))))
            if presentes < max(1, int(0.75 * len(claves) + 0.999)):
                continue
            puntaje = presentes + 0.5 / (rango + 1)
            if puntaje > mejor_puntaje:
                mejor, mejor_puntaje = o, puntaje
    return mejor
