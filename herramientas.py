"""Capa 1 (sin IA) y caja de herramientas que el núcleo puede consultar."""
import ast
import operator
import re
import sqlite3
from pathlib import Path

RUTA_DICCIONARIO = Path(__file__).parent / "datos" / "diccionario.sqlite"


class Diccionario:
    """Conocimiento fuera del modelo: vive en disco, no en los parámetros."""

    def __init__(self, ruta=RUTA_DICCIONARIO):
        self.con = sqlite3.connect(ruta)

    def buscar(self, termino):
        fila = self.con.execute("SELECT definicion FROM entradas WHERE termino = ?", (termino.strip(),)).fetchone()
        return fila[0] if fila else None


MAX_RESULTADOS = 3
MAX_FRAGMENTO = 200
SIN_RESULTADOS = "Sin resultados."


def _limpio(texto, largo):
    t = re.sub(r"\s+", " ", texto or "").strip()
    if len(t) > largo:
        t = t[:largo].rsplit(" ", 1)[0] + "…"
    return t


FRAGMENTO_CODIGO = 150  # el código gasta ~2,6 veces más tokens: fragmentos más cortos en modo código


def formatear_resultados(resultados, max_res=MAX_RESULTADOS, max_frag=MAX_FRAGMENTO):
    """Lista de {title, body} -> texto numerado que ve el modelo (formato igual al del entrenamiento)."""
    lineas = []
    for r in resultados[:max_res]:
        titulo, cuerpo = _limpio(r.get("title"), 60), _limpio(r.get("body"), max_frag)
        if titulo or cuerpo:
            lineas.append(f"{len(lineas) + 1}. {titulo}: {cuerpo}")
    return "\n".join(lineas) if lineas else SIN_RESULTADOS


_ES = set("de la el en que los las y un una es con por para del se al lo su sus como más pero fue son este esta también entre sobre".split())
_EN = set("the of and is to in for that with are was from this by on as it an be or at which has have".split())


_FR = set("le les des est un une du et dans au sur par pour avec qui sont ce cette ses".split())
_PT = set("o os as não uma um é são com para por mais foi seu sua dos das".split())


def _es_espanol(texto, permitir_ingles=False):
    letras = [c for c in texto if c.isalpha()]
    if letras and sum(c.isascii() or c in "áéíóúüñÁÉÍÓÚÜÑ¿¡" for c in letras) < 0.85 * len(letras):
        return False  # cirílico, chino, árabe...: además generan cientos de tokens
    p = re.findall(r"[a-záéíóúüñàâçèêëîïôùûœãõ]+", texto.lower())
    if len(p) < 4:
        return True
    es, en = sum(w in _ES for w in p), sum(w in _EN for w in p)
    otros = max(sum(w in c for w in p) for c in (_FR, _PT))
    if permitir_ingles:  # documentación técnica: el inglés es el idioma habitual
        return max(es, en) >= otros
    return es >= max(en, otros)


def _limpiar_titulo(t):
    t = re.sub(r"\s*[-|–]\s*Wikipedia.*$", " - Wikipedia", t or "")
    t = re.sub(r"\s*[|\[(]?\s*PDF\s*[\])]?\s*$", "", t)
    t = re.sub(r"^\s*\[?PDF\]?\s*[:\-]?\s*", "", t)
    return t.split(" | ")[0].strip()


_FECHA = re.compile(r"^\s*(?:Hace \d+ \w+|\d+ (?:second|minute|hour|day|week|month|year)s? ago|[A-Z][a-z]{2} \d{1,2}, \d{4}|\d{1,2}(?: de)? [A-Za-zéúáñ]+\.?(?: de)? \d{4}|\d{1,2}/\d{1,2}/\d{2,4})\s*[·\-–—]\s*")


def _limpiar_cuerpo(t):
    t = re.sub(r"\s+", " ", t or "")
    t = _FECHA.sub("", t)
    t = re.sub(r"\(\s*/[^)]*\)", "", t)  # pronunciaciones (/ˈ…/)
    t = re.sub(r"\[\s*\d+\s*\]", "", t)  # notas [3]
    return re.sub(r"\s+([,.;:])", r"\1", re.sub(r"\s+", " ", t)).strip()


def preparar_resultados(crudos, permitir_ingles=False):
    """Resultados crudos de ddgs -> lista limpia y ordenada de {title, body}.

    Quita fechas sueltas, etiquetas PDF, pronunciaciones y notas; descarta fragmentos en inglés
    y duplicados; pone Wikipedia en español primero y deja los PDF al final.
    """
    vistos, limpios = set(), []
    for r in crudos:
        titulo, cuerpo = _limpiar_titulo(r.get("title")), _limpiar_cuerpo(r.get("body"))
        href0 = (r.get("href") or "").lower()
        if "wikipedia.org" in href0 and "es.wikipedia.org" not in href0:
            continue  # otras ediciones de Wikipedia (idiomas distintos)
        if len(cuerpo) < 20 or not _es_espanol(titulo + " " + cuerpo, permitir_ingles):
            continue
        if cuerpo[:80] in vistos:
            continue
        vistos.add(cuerpo[:80])
        href = (r.get("href") or "").lower()
        prioridad = 0 if "es.wikipedia.org" in href else (2 if href.endswith(".pdf") or "pdf" in (r.get("title") or "").lower() else 1)
        ingles = permitir_ingles and sum(w in _EN for w in re.findall(r"[a-z]+", (titulo + " " + cuerpo).lower())) > \
            sum(w in _ES for w in re.findall(r"[a-záéíóúüñ]+", (titulo + " " + cuerpo).lower()))
        limpios.append((prioridad, int(ingles), len(limpios), {"title": titulo, "body": cuerpo}))  # español antes que inglés
    return [x[3] for x in sorted(limpios, key=lambda x: x[:3])]


def _norm_ficha(t):
    import unicodedata

    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\bprogramacion\b", " ", t)
    t = re.sub(r"^(un|una|el|la|los|las)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def linea_ficha(ficha, con_ejemplo=True):
    """Formato único (entrenamiento e inferencia) de un resultado de la base local de conceptos."""
    nombre, _, definicion, ejemplo = ficha
    return f"{nombre} - base local: {definicion}" + (f" Ejemplo: {ejemplo}" if (ejemplo and con_ejemplo) else "")


def buscar_ficha(consulta):
    """Base local de conceptos fundamentales (107 fichas): consulta instantánea ANTES de ir a internet.

    Devuelve el resultado ya formateado ("1. nombre - base local: definición Ejemplo: ...") o None si el concepto no está.
    """
    from experto_fichas import FICHAS

    q = _norm_ficha(consulta)
    for f in FICHAS:
        if q in (_norm_ficha(f[0]), _norm_ficha(f[1])):
            return "1. " + linea_ficha(f)
    return None


def buscar_memoria(consulta, memoria):
    """Memoria externa del usuario (datos/memoria.json), < 1 ms: «1. [memoria] …» (y refuerza +3) o None si no hay coincidencia."""
    return memoria.buscar_memoria(consulta) if memoria is not None else None


def buscar_web(consulta, modo=None, memoria=None):
    """Cadena de búsqueda B: memoria del usuario -> base local de conceptos (modo código) -> DuckDuckGo (ddgs, sin clave).

    Pide 8 resultados, los limpia (preparar_resultados) y entrega los 3 mejores, título + fragmento
    de ~200 caracteres. Ante error de red o resultados vacíos devuelve "Sin resultados.".
    """
    import time

    from ddgs import DDGS

    local = buscar_memoria(consulta, memoria)
    if local:
        return local
    codigo = modo == "codigo"  # experto de código: acepta inglés y recorta más los fragmentos
    redaccion = modo == "redaccion"  # experto de redacción: solo español, fragmentos cortos
    if codigo:
        local = buscar_ficha(consulta)  # base local primero: instantánea, sin red
        if local:
            return local
    if redaccion:
        from redaccion_fichas import buscar_ficha_gramatica

        local = buscar_ficha_gramatica(consulta)  # base local de gramática y ortografía
        if local:
            return local
    for intento in range(2):  # un reintento: ddgs da timeouts esporádicos
        try:
            crudos = DDGS().text(consulta, region="xl-es", max_results=8)
            return formatear_resultados(preparar_resultados(crudos, permitir_ingles=codigo),
                                        max_frag=FRAGMENTO_CODIGO if (codigo or redaccion) else MAX_FRAGMENTO)
        except Exception:
            if intento == 0:
                time.sleep(1.5)
    return SIN_RESULTADOS


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_ES_CUENTA = re.compile(r"^[\d\s.,+\-*/()^]+$")


def _evaluar(nodo):
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPS:
        return _OPS[type(nodo.op)](_evaluar(nodo.left), _evaluar(nodo.right))
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPS:
        return _OPS[type(nodo.op)](_evaluar(nodo.operand))
    raise ValueError("expresión no permitida")


_TAREAS = (
    (r"^(?:escribe|pon|convierte)[^:]*may[uú]sculas?\s*:\s*(.+)$", lambda m: m.group(1).upper()),
    (r"^(?:escribe|pon|convierte)[^:]*min[uú]sculas?\s*:\s*(.+)$", lambda m: m.group(1).lower()),
    (r"^repite(?: esto)?\s*:?\s*(.+)$", lambda m: m.group(1)),
    (r"^cuenta del (\d+) al (\d+)\.?$", lambda m: ", ".join(map(str, range(int(m.group(1)), min(int(m.group(2)), int(m.group(1)) + 200) + 1)))),
    (r"^¿?cu[aá]ntas palabras tiene [«\"'](.+)[»\"']\?*$", lambda m: f"Tiene {len(m.group(1).split())} palabras."),
    (r"^¿?cu[aá]ntas letras tiene (?:la palabra )?[«\"']?(\w+)[»\"']?\?*$", lambda m: f"Tiene {len(m.group(1))} letras."),
    (r"^ordena alfab[eé]ticamente\s*:\s*(.+)$", lambda m: ", ".join(sorted(x.strip() for x in m.group(1).split(",")))),
    (r"^invierte el orden de las palabras\s*:\s*(.+)$", lambda m: " ".join(reversed(m.group(1).split()))),
)


def capa1(pregunta, memoria=None):
    """Tareas mecánicas exactas (cuentas, mayúsculas, contar, ordenar) y órdenes de guardar en memoria, sin despertar a la red.

    Con `memoria`, «Recuerda que…», «Guarda que…», «Anota que…» y «Mi X es…» se guardan (temperatura 10) y se confirma al tiro.

    Devuelve el texto de la respuesta o None si no es una tarea mecánica.
    """
    t = pregunta.strip()
    for patron, f in _TAREAS:
        m = re.match(patron, t, flags=re.I | re.S)
        if m:
            return f(m)
    r = filtro_determinista(t)
    if r is not None:
        return str(r)
    return memoria.guardar_si_orden(t) if memoria is not None else None


def filtro_determinista(texto):
    """Resuelve cuentas exactas sin despertar a la red neuronal.

    Devuelve el resultado o None si el texto no es una cuenta.
    """
    t = texto.strip()
    if not t or not _ES_CUENTA.match(t) or not re.search(r"\d", t):
        return None
    t = t.replace("^", "**").replace(",", ".")
    try:
        return _evaluar(ast.parse(t, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
