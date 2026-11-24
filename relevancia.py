"""Filtro determinista de relevancia: ¿los resultados hablan de lo que se buscó?

Un modelo pequeño tiende a responder con lo primero que ve aunque la búsqueda haya devuelto otra cosa (p. ej. «brilibri» -> «Bribri», «zuchezorru» -> «Zucchero»).
Regla: alguna palabra significativa de la consulta debe aparecer (por su raíz de 5 letras) en los resultados. Si no, no hay información: no se le pasa nada al modelo.
"""
import re
import unicodedata

_VACIAS = {"que", "quien", "quienes", "cual", "cuales", "como", "cuando", "donde", "cuanto", "cuantos", "sobre", "para", "por", "con", "sin", "una", "uno", "unos", "unas",
           "los", "las", "del", "que", "puedes", "decir", "dime", "cuentame", "hablame", "explica", "significa", "es", "son", "fue", "era", "the", "and"}
SIN_RESULTADOS = "Sin resultados."


def _n(t):
    return unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()


def _raices(t, n=5):
    return {w[:n] for w in re.findall(r"[a-z0-9]{3,}", _n(t)) if w not in _VACIAS}


def relevante(consulta, resultados):
    """True si algún término de la consulta aparece en los resultados. Consultas sin términos útiles no se filtran."""
    claves = _raices(consulta)
    if not claves:
        return True
    return bool(claves & _raices(resultados))


ORDEN_ABSTENCION = "Sin resultados relevantes. Responde exactamente: No tengo información suficiente para responder eso."


def filtrar(consulta, resultados):
    """Resultados tal cual si hablan de la consulta; si no, una orden explícita de abstenerse (un 3B ignora un simple «Sin resultados»)."""
    return resultados if (resultados and resultados.strip() != SIN_RESULTADOS and relevante(consulta, resultados)) else ORDEN_ABSTENCION
