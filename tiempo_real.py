"""Consultas de tiempo real (solo núcleo v2, `inferir.py --v2`): hora/fecha del reloj del equipo, clima y datos en vivo que SÍ se pueden buscar.

El núcleo no tiene reloj ni red. Antes (charla `hora_fecha`, `clima`, `tiempo_real`) respondía con una negativa genérica, y en consultas mixtas
(«¿qué hora es y la temperatura en Santiago?») mezclaba dos negativas. Ahora:
  · hora y fecha: se leen del reloj del equipo (capa determinista, sin IA) y se dicen como tales;
  · clima/temperatura con lugar: se fuerza una búsqueda («clima <lugar>») y el núcleo responde con los resultados (turno de herramienta normal);
  · datos en vivo (dólar, euro, bitcoin, noticias, resultado de partidos…): se fuerza una búsqueda con la propia pregunta;
  · sin lugar: no se fuerza nada (el núcleo pide la ciudad, como en la charla `clima`).
`dividir(pregunta)` devuelve las partes a resolver, para que una consulta mixta se conteste completa y sin repeticiones.
"""
import re
import unicodedata
from datetime import datetime

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _n(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


RE_HORA = re.compile(r"\b(que hora (es|son|tienes)|la hora|me das la hora|decirme la hora|hora actual)\b")
RE_FECHA = re.compile(r"\b(que (dia|fecha) (es|es hoy|estamos|tenemos|cae)|que ano es|fecha de hoy|fecha actual|a que (dia|fecha) estamos|en que (dia|fecha|mes|ano) estamos|que dia es hoy)\b")
RE_CLIMA = re.compile(r"\b(clima|temperatura|pronostico|llover|lluvia|llueve|lloviendo|nevar|nieve|hace (frio|calor)|hara (frio|calor|sol)|grados|tiempo (hace|hara|esta))\b")
RE_VIVO = re.compile(r"\b(dolar|euro|bitcoin|cotizacion|noticias?|titulares?|partido|resultado del|precio del (oro|petroleo|cobre|dolar)|bolsa de)\b")
# lugar: «en Santiago de Chile», «aquí en Valparaíso», «de Lima»; se corta en conjunciones/puntuación
RE_LUGAR = re.compile(r"\b(?:en|de|para|por)\s+((?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)(?:\s+(?:de(?:l)?\s+|la\s+|los\s+|las\s+|el\s+)?[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)*)")
RE_LUGAR_MIN = re.compile(r"\b(?:en|para)\s+((?:[a-záéíóúñ]+)(?:\s+de(?:l)?\s+[a-záéíóúñ]+)?)\s*[?.!,]*$")
NO_LUGAR = {"hoy", "mañana", "manana", "este", "esta", "ese", "esa", "casa", "internet", "general", "serio", "verdad", "realidad", "total", "este momento"}


RE_FALTA = re.compile(r"\b(?:cuantos dias (?:faltan|quedan|hay) (?:para|hasta)|cuanto (?:falta|queda) para|cuantos dias para)\s+(?:el\s+|la\s+)?(.+?)\s*[?.!]*$")
FECHAS_FIJAS = {"navidad": (12, 25), "nochebuena": (12, 24), "ano nuevo": (1, 1), "nochevieja": (12, 31), "fin de ano": (12, 31), "halloween": (10, 31),
                "San valentin": (2, 14), "san valentin": (2, 14), "fiestas patrias": (9, 18)}


def dias_hasta(pregunta, ahora=None):
    """«¿Cuántos días faltan para Navidad / el 3 de marzo?» -> respuesta con el reloj del equipo, o None."""
    from datetime import date

    m = RE_FALTA.search(_n(pregunta))
    if not m:
        return None
    objetivo, hoy = m.group(1).strip(), (ahora or datetime.now()).date()
    md = FECHAS_FIJAS.get(objetivo)
    if md is None:
        mm = re.match(r"(?:dia\s+)?(\d{1,2}) de ([a-z]+)", objetivo)
        meses = [_n(x) for x in MESES]
        if not mm or mm.group(2) not in meses:
            return None
        md = (meses.index(mm.group(2)) + 1, int(mm.group(1)))
    mes, dia = md if md[0] <= 12 else (md[1], md[0])
    try:
        f = date(hoy.year, mes, dia)
        if f < hoy:
            f = date(hoy.year + 1, mes, dia)
    except ValueError:
        return None
    n = (f - hoy).days
    nombre = {"ano nuevo": "Año Nuevo", "fin de ano": "fin de año"}.get(objetivo, objetivo.capitalize() if md in FECHAS_FIJAS.values() else None) or f"el {dia} de {MESES[mes - 1]}"
    cuando = "Es hoy" if n == 0 else f"Faltan {n} día{'s' if n != 1 else ''}"
    return f"{cuando} para {nombre} ({f.day} de {MESES[f.month - 1]} de {f.year}), según el reloj de este equipo."


def hora_fecha(pregunta, ahora=None):
    """Respuesta determinista con el reloj del equipo, o None si no se pregunta la hora ni la fecha."""
    t = _n(pregunta)
    falta = dias_hasta(pregunta, ahora)
    quiere_hora, quiere_fecha = bool(RE_HORA.search(t)), bool(RE_FECHA.search(t))
    if not (quiere_hora or quiere_fecha or falta):
        return None
    d = ahora or datetime.now()
    partes = []
    if quiere_hora:
        partes.append(f"Son las {d:%H:%M}")
    if quiere_fecha:
        partes.append(f"Hoy es {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}")
    if not partes:
        return falta
    return " y ".join(partes) + " (según el reloj de este equipo)." + (" " + falta if falta else "")


def lugar(pregunta):
    m = RE_LUGAR.search(pregunta)
    if m:
        return m.group(1).strip()
    m = RE_LUGAR_MIN.search(pregunta.strip())
    if m and _n(m.group(1)) not in NO_LUGAR:
        return m.group(1).strip()
    return None


def consulta_clima(pregunta):
    """«clima <lugar>» si se pregunta por el tiempo atmosférico en un lugar concreto; None si no hay clima o falta el lugar."""
    if not RE_CLIMA.search(_n(pregunta)):
        return None
    l = lugar(pregunta)
    return f"clima {l}" if l else None


def consulta_vivo(pregunta):
    """La propia pregunta (limpia) como búsqueda para datos en vivo: dólar, noticias, partidos…"""
    t = _n(pregunta)
    if RE_VIVO.search(t) and not RE_CLIMA.search(t):
        return re.sub(r"[¿?¡!]", "", pregunta).strip()
    return None


def dividir(pregunta, ahora=None):
    """[(tipo, valor)] en el orden en que se preguntó: ('texto', respuesta ya resuelta) o ('buscar', consulta). Vacío si no aplica."""
    partes = []
    r = hora_fecha(pregunta, ahora)
    if r:
        partes.append(("texto", r))
    q = consulta_clima(pregunta) or consulta_vivo(pregunta)
    if q:
        partes.append(("buscar", q))
    return partes
