"""Búsqueda externa real, sin claves: Wikcionario -> Wikipedia -> DuckDuckGo.

El núcleo no memoriza conocimiento: cuando no sabe algo, llama a buscar() y lee
el resultado. Devuelve texto corto o None si no encuentra nada.

Prueba:  python buscador.py "banco de arena" "pludos"
"""
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "NucleoBuscador/0.1 (proyecto experimental)"}
MAX_CHARS = 400


def _get(url, tiempo=10):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=tiempo) as r:
        return r.read().decode("utf-8", errors="replace")


def _recortar(t):
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    return t[:MAX_CHARS].rsplit(" ", 1)[0] if len(t) > MAX_CHARS else t


def wikcionario(termino):
    """Definiciones del Wikcionario en español (texto plano de la página)."""
    url = ("https://es.wiktionary.org/w/api.php?action=query&prop=extracts&explaintext=1&redirects=1"
           "&format=json&titles=" + urllib.parse.quote(termino))
    pagina = next(iter(json.loads(_get(url))["query"]["pages"].values()))
    texto = pagina.get("extract")
    if not texto or "missing" in pagina:
        return None
    # Formato: una línea "N" o "N Área" y debajo la definición. Solo la sección "== Español ==".
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    defs, en_espanol = [], False
    for i, l in enumerate(lineas):
        if re.match(r"^== [^=].*==$", l):
            en_espanol = l == "== Español =="
        elif en_espanol and re.match(r"^\d+(\s.*)?$", l) and i + 1 < len(lineas) and not lineas[i + 1].startswith("="):
            defs.append(f"{len(defs) + 1}) {lineas[i + 1]}")
    return _recortar(" ".join(defs[:3])) or None


def wikipedia(termino):
    url = "https://es.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(termino.replace(" ", "_"))
    try:
        d = json.loads(_get(url))
    except urllib.error.HTTPError:
        return None
    if d.get("type") == "disambiguation":
        return None
    return _recortar(d.get("extract", "")) or None


def duckduckgo(consulta):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": consulta, "kl": "xl-es"})
    pagina = _get(url)
    trozos = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', pagina, flags=re.S)
    limpio = [re.sub(r"<[^>]+>", "", t) for t in trozos[:2]]
    return _recortar(" ".join(limpio)) or None


FUENTES = (("wikcionario", wikcionario), ("wikipedia", wikipedia), ("duckduckgo", duckduckgo))


def buscar(consulta, con_fuente=False):
    """Prueba las fuentes en orden; devuelve el primer resultado (o None)."""
    for nombre, f in FUENTES:
        try:
            r = f(consulta)
        except Exception:  # red caída, límite de uso, etc.: pasa a la siguiente fuente
            continue
        if r:
            return (nombre, r) if con_fuente else r
    return (None, None) if con_fuente else None


if __name__ == "__main__":
    for q in sys.argv[1:] or ["banco de arena"]:
        print(q, "->", buscar(q, con_fuente=True))
