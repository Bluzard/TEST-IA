"""Corrector ortográfico y de puntuación DETERMINISTA para el español (capa 1, sin red neuronal).

La ortografía exacta no cabe en los pesos de experto_redaccion (14 % exacta): se resuelve aquí con un léxico de frecuencias sacado del corpus
del proyecto (datos/lexico_es.tsv, `construir_lexico.py`: 193 k formas con conjugaciones, plurales y nombres propios) y reglas.
`corregir(texto)` devuelve el texto corregido, o «El texto ya está bien escrito.» si no hay nada que cambiar. Se invoca desde `capa1()`
con «Corrige: …» y «Corrige la ortografía: …».

Pasos:
  1. «;» tecleado por «ñ» (ni;o -> niño) y limpieza de puntuación: espacios antes/después de signos, ¿ ¡ que falten, mayúscula inicial y
     tras cada punto, punto final.
  2. Palabra por palabra, solo las que el léxico no da por válidas: se prueban todas las palabras a UNA edición y gana la de mayor
     log-frecuencia menos el costo del error. Los errores típicos del español son baratos (tilde perdida 0,2; s/z/c, b/v, g/j, h omitida
     o sobrante 0,3; letra doble 0,5; transposición 0,7) y el resto cuesta 1: así «plasa» -> plaza y no «pasa».
  3. Una palabra sin tilde cuyo par con tilde es ≥ 15 veces más frecuente (tambien/también, mas/más) se trata como error.
Se respetan siglas, números y nombres propios en mitad de oración.
Límites: sin contexto no hay forma de arreglar errores que producen otra palabra válida (vaca/baca, compre/compré, esta/está) ni de
elegir entre candidatos igual de plausibles (juga -> «jugar» en vez de «juega»).

  python corrector.py        # evalúa contra las preguntas de ortografía de redaccion_eval.jsonl (las mismas que el modelo, 14 % exacta)
"""
import math
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).parent
YA_BIEN = "El texto ya está bien escrito."
MIN_VALIDA = 12          # frecuencia mínima (en ~65 M de tokens) para dar una forma por válida
RAZON_TILDE = 8          # sin tilde es error si el par con tilde es tantas veces más frecuente (40 si la palabra es muy común: que, como, se…)
MUY_COMUN = 20000
_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_LEX = None
_PARES_TILDE = None
_SIN_TILDE = None
_FONETICOS = {frozenset(p) for p in ("sz", "sc", "zc", "bv", "gj", "yi", "kc", "qc", "xs")}
_INTERROG = re.compile(r"\b(?:por qu[eé]|qu[eé]|c[oó]mo|cu[aá]ndo|d[oó]nde|qui[eé]nes|qui[eé]n|cu[aá]les|cu[aá]l|cu[aá]nt[oa]s?)\b", re.I)
_ACENTO_INTERROG = {"que": "qué", "como": "cómo", "cuando": "cuándo", "donde": "dónde", "quien": "quién", "quienes": "quiénes", "cual": "cuál",
                    "cuales": "cuáles", "cuanto": "cuánto", "cuanta": "cuánta", "cuantos": "cuántos", "cuantas": "cuántas", "por que": "por qué"}
_URL = re.compile(r"\S*(?:www\.|https?:|@|\.(?:com|org|net|cl|mx|ar|es|co|pe|edu|gov)\b)\S*", re.I)
_ALFABETO = "abcdefghijklmnopqrstuvwxyzáéíóúüñ"


def _distancia(a, b):
    """Distancia de Levenshtein (las palabras son cortas)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _sin_tilde(w):
    """Quita tildes de vocales (á é í ó ú ü) pero conserva la ñ."""
    return w.translate(str.maketrans("áéíóúü", "aeiouu"))


def _cargar():
    global _LEX, _PARES_TILDE, _SIN_TILDE
    if _LEX is None:
        lex = {}
        ruta = RAIZ / "datos" / "lexico_es.tsv"
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            w, _, c = linea.partition("\t")
            lex[w] = int(c)
        # vocabulario del propio proyecto (fichas gramaticales y de código) y de oficina, que el corpus enciclopédico cubre poco
        extra = set("factura presupuesto cotización borrador reembolso adjunto adjuntar formulario expediente".split())
        try:
            from experto_fichas import FICHAS
            from redaccion_fichas import FICHAS_GRAMATICA

            for f in list(FICHAS) + list(FICHAS_GRAMATICA):
                extra.update(re.findall(r"[a-záéíóúüñ]{3,}", " ".join(str(x).lower() for x in f[:3])))
        except Exception:
            pass
        for w in extra:
            lex[w] = max(lex.get(w, 0), 200)
        _SIN_TILDE = {}
        for w, c in lex.items():
            s = _sin_tilde(w)
            if s != w:
                _SIN_TILDE.setdefault(s, []).append(w)
        _PARES_TILDE = {s: max(vs, key=lex.get) for s, vs in _SIN_TILDE.items()}
        _LEX = lex
    return _LEX


def es_valida(w):
    """¿El léxico da esta forma (en minúsculas) por correcta? Una forma sin tilde con un par con tilde mucho más frecuente no lo es."""
    lex = _cargar()
    c = lex.get(w, 0)
    if c < MIN_VALIDA:
        return False
    par = _PARES_TILDE.get(w)
    razon = RAZON_TILDE * (5 if c >= MUY_COMUN else 1)
    return not (par and lex[par] >= razon * c)


def _ediciones(w):
    """Todas las palabras a una edición, con su costo."""
    out = {}

    def poner(c, costo):
        if c not in out or costo < out[c]:
            out[c] = costo

    for i in range(len(w) + 1):
        izq, der = w[:i], w[i:]
        if der:  # borrar der[0]
            poner(izq + der[1:], 0.3 if der[0] == "h" else (0.5 if i and izq[-1] == der[0] else 1.0))
        if len(der) > 1:  # transponer
            poner(izq + der[1] + der[0] + der[2:], 0.7)
        for c in _ALFABETO:
            if der:  # sustituir der[0] por c
                a = der[0]
                if c != a:
                    if _sin_tilde(a) == _sin_tilde(c):
                        costo = 0.2
                    elif frozenset((a, c)) in _FONETICOS:
                        costo = 0.3
                    else:
                        costo = 1.0
                    poner(izq + c + der[1:], costo)
            costo = 0.3 if c == "h" else (0.5 if (i and izq[-1] == c) or (der and der[0] == c) else 1.0)
            poner(izq + c + der, costo)  # insertar
    out.pop(w, None)
    return out


def _con_caso(original, nueva):
    if original.isupper() and len(original) > 1:
        return nueva.upper()
    if original[:1].isupper():
        return nueva[:1].upper() + nueva[1:]
    return nueva


def corregir_palabra(w, inicio_de_oracion=False):
    """Palabra corregida (o la misma si el léxico la da por válida o no hay un candidato fiable)."""
    lex = _cargar()
    bajo = w.lower()
    if len(bajo) < 2 or es_valida(bajo):
        return w
    if w.isupper() or (w[:1].isupper() and not inicio_de_oracion):  # siglas y nombres propios
        return w
    candidatos = {}
    par = _PARES_TILDE.get(bajo)
    if par and lex[par] >= lex.get(bajo, 0):
        return _con_caso(w, par)                 # tambien -> también: si solo falta la tilde, esa es la corrección
    for c, costo in _ediciones(bajo).items():
        # errores de tecleo baratos (tilde, s/z/c, b/v, h, letra doble) siempre; ediciones arbitrarias (costo 1) solo en palabras de 6+
        # letras, para no «corregir» palabras raras pero válidas (mako, soju…)
        if es_valida(c) and (costo < 1.0 or len(bajo) >= 6):
            candidatos[c] = min(costo, candidatos.get(c, 9))
    if not candidatos:
        return w
    mejor = max(candidatos, key=lambda c: math.log10(lex[c]) - 2.5 * candidatos[c])
    return _con_caso(w, mejor)


def _puntuacion(t):
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.;:!?)»])", r"\1", t)            # sin espacio antes de los signos
    t = re.sub(r"([¿¡(«])\s+", r"\1", t)                 # ni después de los de apertura
    t = re.sub(r"([,;:])(?=[^\s\d])", r"\1 ", t)         # un espacio después de coma, punto y coma, dos puntos
    t = re.sub(r"([.!?])(?=[A-ZÁÉÍÓÚÑ¿¡])", r"\1 ", t)                   # «fin.El» -> «fin. El» (pero no «richmond.com»)
    partes = re.split(r"(?<=[.!?])\s+", t)               # ¿ ¡ que faltan al abrir y cierres que faltan al final
    nuevas = []
    for p in partes:
        if p.endswith("?") and "¿" not in p:
            m = _INTERROG.search(p)
            i = m.start() if m else 0
            p = p[:i] + "¿" + p[i:]
            if m:
                pal = p[i + 1 : i + 1 + len(m.group())]
                p = p[: i + 1] + _ACENTO_INTERROG.get(_sin_tilde(pal.lower()), pal.lower() if pal.islower() else pal) + p[i + 1 + len(m.group()) :]
        if p.endswith("!") and "¡" not in p:
            p = "¡" + p
        if p.startswith("¿") and not p.endswith("?"):
            p += "?"
        if p.startswith("¡") and not p.endswith("!"):
            p += "!"
        nuevas.append(p)
    t = " ".join(nuevas)
    t = re.sub(r"(^|[.!?]\s+)([¿¡]?)([a-záéíóúüñ])", lambda m: m.group(1) + m.group(2) + m.group(3).upper(), t)  # mayúscula inicial
    if t and t[-1].isalnum():
        t += "."
    return t


def _punto_y_coma_por_enie(t):
    """«ni;o» -> «niño» cuando el resultado es una palabra válida (la ñ se tecleó como «;»)."""
    def f(m):
        c = m.group(1) + "ñ" + m.group(2)
        return c if es_valida(c.lower()) else m.group(0)
    return re.sub(r"([A-Za-záéíóúü]+);([A-Za-záéíóúü]+)", f, t)


def corregir(texto):
    """Texto corregido, o «El texto ya está bien escrito.» si no cambia nada."""
    original = texto.strip()
    if not original:
        return YA_BIEN
    t = _puntuacion(_punto_y_coma_por_enie(original))
    salida, pos = [], 0
    protegidos = [(m.start(), m.end()) for m in _URL.finditer(t)]
    for m in _PALABRA.finditer(t):
        if any(a <= m.start() < b for a, b in protegidos):
            continue
        salida.append(t[pos:m.start()])
        previo = t[:m.start()].rstrip()
        salida.append(corregir_palabra(m.group(), not previo or previo[-1] in ".!?¿¡"))
        pos = m.end()
    salida.append(t[pos:])
    t = _puntuacion("".join(salida))
    return YA_BIEN if t == original else t


if __name__ == "__main__":
    import json
    import random
    import time

    from redaccion_datos import Q_ORT_EVAL, corromper

    prefijos = sorted({q.split("{x}")[0] for q in Q_ORT_EVAL}, key=len, reverse=True)
    filas = [json.loads(l) for l in open(RAIZ / "datos" / "redaccion_eval.jsonl", encoding="utf-8")]
    filas = [r for r in filas if r["tipo"].startswith("ortografia")]
    t0 = time.perf_counter()
    por_tipo = {}
    for r in filas:
        x = next(r["pregunta"][len(p):] for p in prefijos if r["pregunta"].startswith(p))
        ok = corregir(x) == r["respuesta"]
        a, b = por_tipo.get(r["tipo"], (0, 0))
        por_tipo[r["tipo"]] = (a + ok, b + 1)
    seg = time.perf_counter() - t0
    tot_ok = sum(a for a, _ in por_tipo.values())
    print(f"preguntas de ortografía de redaccion_eval.jsonl: {tot_ok}/{len(filas)} exactas ({tot_ok / len(filas):.1%}) | experto_redaccion: 14 % "
          f"| {seg / len(filas) * 1000:.0f} ms por texto")
    print("  por tipo:", {t: f"{a}/{b} ({a / b:.0%})" for t, (a, b) in por_tipo.items()})
    # error por error, sobre las oraciones originales de entrenamiento (nunca vistas por el corrector: es determinista)
    rng = random.Random(5)
    orig = [json.loads(l)["respuesta"] for l in open(RAIZ / "datos" / "redaccion_train.jsonl", encoding="utf-8")]
    orig = [o for o in orig if o != YA_BIEN and len(o.split()) >= 6][:2500:2]
    limpias = sum(corregir(o) == YA_BIEN for o in orig)
    print(f"oraciones ya correctas dejadas intactas: {limpias}/{len(orig)} ({limpias / len(orig):.1%})")
    tipos = {}
    for o in orig:
        for solo in ("tilde", "h", "bv", "punto", "mayus", "coma_espacio"):
            c = corromper(o, rng, solo=solo)
            if c:
                a, b = tipos.get(solo, (0, 0))
                tipos[solo] = (a + (corregir(c[0]) == o), b + 1)
    print("  un solo error por oración:", {t: f"{a / b:.0%} (n={b})" for t, (a, b) in tipos.items()})
    for txt in ["ayer fui al mercado y compre berduras", "el ni;o juga en la plasa", "como estas", "hola , que tal ?", "tambien quiero exelente cafe",
                "Hola, ¿cómo estás?"]:
        print(f"  {txt!r} -> {corregir(txt)!r}")
