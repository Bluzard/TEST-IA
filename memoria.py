"""Memoria externa con enfriamiento (Etapa 3, paso 1). Infraestructura de Python: no toca ningún peso del modelo.

Los datos declarativos del usuario («mi proyecto se llama TEST-IA») viven en `datos/memoria.json`, fuera de la red.
La memoria es transversal a toda la conversación, por eso no es un LoRA (colisionaría con los expertos de dominio).

Ciclo de vida de un recuerdo:
  * se guarda con temperatura 10 (comando explícito detectado en capa1(), sin red neuronal);
  * en CADA turno baja 1 punto (`enfriar`); al llegar a 0 se archiva y deja de recuperarse;
  * cada vez que se recupera para responder sube 3 puntos (tope 15).

Memoria de trabajo (`MemoriaTrabajo`): buffer deslizante de los 2 últimos turnos, con tope de ~80 tokens, para que
un seguimiento como «¿y cuándo nació?» no pierda su referente sin desbordar la ventana de 512 tokens.

  python memoria.py      # autopruebas rápidas (usa un archivo temporal, no toca datos/memoria.json)
"""
import json
import os
import re
import tempfile
import unicodedata
from collections import deque
from datetime import datetime
from pathlib import Path

RUTA_MEMORIA = Path(__file__).parent / "datos" / "memoria.json"
TEMP_INICIAL, TEMP_TOPE, REFUERZO, ENFRIAMIENTO = 10, 15, 3, 1
MAX_CONTENIDO = 150
UMBRAL_COINCIDENCIA = 0.5
MAX_COINCIDENCIAS = 2
TOKENS_MEMORIA_TRABAJO = 80

_STOP = set("""de la el en que los las y un una es con por para del se al lo su sus como mas pero fue son este esta eso ese esa
mi mis tu tus me te cual cuales cuando donde quien quienes cuanto cuanta cuantos cuantas porque dime dame sabes sabe puedes
puedo hay ha han he he le les ya muy si no o a e u""".split())


def _n(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _tokens(t):
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9.\-_#+]*", _n(t)):
        w = w.strip(".-_")
        if w and w not in _STOP:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def _recortar(t, n=MAX_CONTENIDO):
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


# ---------------------------------------------------------------- extracción determinista (capa 1)
_ORDEN = re.compile(r"^(?:por favor,?\s*)?(?:recuerda|guarda|anota|apunta|memoriza|toma nota)(?P<siempre>\s+siempre)?(?:\s+de)?"
                    r"(?:\s+que|\s+esto)?\s*[:,]?\s+(?P<c>.+)$", re.I | re.S)
_OLVIDO = re.compile(r"^(?:por favor,?\s*)?(?P<v>olvida|olv[ií]date|borra|elimina|quita)(?:\s+(?:de|que|lo de|todo sobre|todo lo de|lo que dije de))?"
                     r"\s+(?P<c>.+)$", re.I | re.S)
_MI_DATO = re.compile(r"^mi\s+((?:\w+\s+){0,3}?\w+)\s+(es|se llama|son|est[aá]|tiene|tienen|se llaman)\s+(.+)$", re.I | re.S)


def extraer(texto):
    """Devuelve (clave, contenido, permanente) si el texto es una orden de guardar o un dato personal «Mi X es …»; si no, None.

    «Recuerda siempre que…» marca el recuerdo como permanente (no se enfría); «Recuerda que…» y «Mi X es…» se enfrían."""
    t = texto.strip()
    if not t or "?" in t or "¿" in t or "```" in t or len(t) > 400:
        return None
    t = t.rstrip(" .!")
    m = _ORDEN.match(t)
    permanente = False
    if m:
        contenido, permanente = m.group("c").strip(), bool(m.group("siempre"))
    elif _MI_DATO.match(t):
        contenido = t
    else:
        return None
    if len(contenido) < 3:
        return None
    mi = _MI_DATO.match(contenido)
    if mi:
        clave = mi.group(1).strip().lower()
    else:
        clave = " ".join(sorted(_tokens(contenido), key=contenido.lower().find)[:3]) or contenido[:30].lower()
    return clave, _recortar(contenido), permanente


def extraer_olvido(texto):
    """(objetivo, explicito) si el texto es una orden de olvidar («Olvida que…», «Borra mi…»); si no, None.
    explicito=True para «olvida/olvídate» (siempre se responde); «borra/elimina/quita» solo cuentan si hay un recuerdo que coincida
    (así «Borra el archivo temporal» sigue su camino normal)."""
    t = texto.strip().rstrip(" .!")
    if not t or "?" in t or "¿" in t or "```" in t or len(t) > 400:
        return None
    m = _OLVIDO.match(t)
    if not m:
        return None
    return m.group("c").strip(), _n(m.group("v")).startswith("olv")


def _oracion(t):
    t = t.strip()
    t = t[:1].upper() + t[1:]
    return t if t.endswith((".", "…", "!")) else t + "."


def _titulo(r):
    """Título del resultado. El núcleo congelado solo responde si el título es la entidad por la que preguntó
    («1. Mi proyecto: Mi proyecto se llama TEST-IA.»); con una etiqueta «[memoria]» delante se abstenía 1 de cada 4 veces
    y con cualquier otro formato probado, siempre (ver estudios/ETAPA3_PASO1_memoria_externa.md)."""
    m = _MI_DATO.match(r["contenido"])
    t = f"Mi {m.group(1).strip()}" if m else r["clave_o_entidad"]
    return t[:1].upper() + t[1:]


class Memoria:
    def __init__(self, ruta=RUTA_MEMORIA):
        self.ruta = Path(ruta)
        self.activos, self.archivados, self._sig = [], [], 1
        if self.ruta.exists():
            try:
                d = json.loads(self.ruta.read_text(encoding="utf-8"))
                self.activos, self.archivados = d.get("activos", []), d.get("archivados", [])
            except (json.JSONDecodeError, OSError):
                pass  # archivo dañado: se empieza vacío (se reescribe en el próximo cambio)
        self._sig = 1 + max([r["id"] for r in self.activos + self.archivados] or [0])

    def _guardar_disco(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.ruta.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"activos": self.activos, "archivados": self.archivados}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)  # escritura atómica

    # -- mecánica
    def guardar(self, clave, contenido, permanente=False):
        """Crea el recuerdo con temperatura 10 (los permanentes no se enfrían); si ya hay uno con la misma clave lo reemplaza.
        Un recuerdo permanente no pierde esa condición porque se vuelva a decir con «Recuerda que…» (solo «Olvida» lo borra)."""
        contenido, clave = _recortar(contenido), _n(clave).strip()
        for r in self.activos:
            if r["clave_o_entidad"] == clave:
                r.update(contenido=contenido, temperatura=TEMP_INICIAL, ultimo_uso=_ahora(),
                         permanente=bool(permanente or r.get("permanente")))
                self._guardar_disco()
                return r
        r = {"id": self._sig, "clave_o_entidad": clave, "contenido": contenido, "temperatura": TEMP_INICIAL,
             "permanente": bool(permanente), "creado_en": _ahora(), "ultimo_uso": _ahora()}
        self._sig += 1
        self.activos.append(r)
        self._guardar_disco()
        return r

    def enfriar(self):
        """Un turno de conversación: todos los recuerdos activos bajan 1; los que llegan a 0 se archivan. Devuelve cuántos."""
        if not self.activos:
            return 0
        vivos, frios = [], []
        for r in self.activos:
            if not r.get("permanente"):
                r["temperatura"] -= ENFRIAMIENTO
            (vivos if r["temperatura"] > 0 else frios).append(r)
        for r in frios:
            r["archivado_en"] = _ahora()
        self.activos, self.archivados = vivos, self.archivados + frios
        self._guardar_disco()
        return len(frios)

    def buscar(self, consulta, reforzar=True):
        """Recuerdos activos que coinciden léxicamente con la consulta (mejor primero). Los recuperados suben +3 (tope 15)."""
        q = _tokens(consulta)
        if not q:
            return []
        hits = []
        for r in self.activos:
            doc = _tokens(r["clave_o_entidad"] + " " + r["contenido"])
            puntaje = len(q & doc) / len(q)
            if puntaje >= UMBRAL_COINCIDENCIA:
                hits.append((puntaje, r["temperatura"], r))
        hits = [h[2] for h in sorted(hits, key=lambda h: (h[0], h[1]), reverse=True)[:MAX_COINCIDENCIAS]]
        if hits and reforzar:
            for r in hits:
                r["temperatura"] = min(TEMP_TOPE, r["temperatura"] + REFUERZO)
                r["ultimo_uso"] = _ahora()
            self._guardar_disco()
        return hits

    def olvidar(self, objetivo):
        """Archiva al tiro el recuerdo que mejor coincide con `objetivo` (sin reforzar). Devuelve ese recuerdo o None."""
        r = next(iter(self.buscar(objetivo, reforzar=False)[:1]), None)
        if r is None:
            return None
        self.activos.remove(r)
        r.update(archivado_en=_ahora(), motivo="olvidado por el usuario")
        self.archivados.append(r)
        self._guardar_disco()
        return r

    def temperatura(self, clave):
        for r in self.activos:
            if r["clave_o_entidad"] == _n(clave).strip():
                return r["temperatura"]
        return None

    # -- interfaz para capa1() y herramientas.py
    def guardar_si_orden(self, texto):
        """Capa 1: ejecuta una orden de olvidar o de guardar y devuelve la confirmación; si el texto no es ninguna, None."""
        o = extraer_olvido(texto)
        if o is not None:
            objetivo, explicito = o
            r = self.olvidar(objetivo)
            if r is not None:
                return f"Olvidado: {r['contenido']}"
            if explicito:
                return "No tengo nada guardado sobre eso."
            return None
        e = extraer(texto)
        if e is None:
            return None
        self.guardar(*e)
        return f"Anotado{' para siempre' if e[2] else ''}: {e[1]}"

    def buscar_memoria(self, consulta):
        """Resultado ya formateado para el núcleo («1. [memoria] …») o None si nada coincide."""
        hits = self.buscar(consulta)
        if not hits:
            return None
        return "\n".join(f"{i}. {_titulo(r)}: {_oracion(r['contenido'])}" for i, r in enumerate(hits, 1))


class MemoriaTrabajo:
    """Últimos 2 turnos, comprimidos a ~80 tokens, para resolver referencias de seguimiento («¿y cuándo nació?»)."""

    SEGUIMIENTO = re.compile(r"^\s*¿?\s*(y\b|entonces\b|pero\b)|\b(eso|esto|él|ella|ello|lo mismo|su|sus|all[ií]|aqu[ií])\b",
                             re.I)

    def __init__(self, tokenizador=None, tope=TOKENS_MEMORIA_TRABAJO):
        self.turnos = deque(maxlen=2)
        self.tok, self.tope = tokenizador, tope

    def _ntok(self, t):
        return len(self.tok.encode(t).ids) if self.tok else len(t) // 3

    def registrar(self, pregunta, respuesta):
        self.turnos.append((pregunta.strip(), respuesta.strip()))

    @staticmethod
    def tiene_termino_de_ficha(pregunta):
        """True si la pregunta ya nombra por sí sola un concepto de las fichas locales (código o gramática: «tilde», «pila», «hiato»…):
        es una consulta autocontenida, aunque empiece por «¿y…?», y no necesita el turno anterior."""
        from enrutador import BIBLIOTECAS, INEQUIVOCOS, REDACCION_FUERTES, _NOMBRES_FICHA, _n

        nt = _n(pregunta)
        palabras = set(re.findall(r"\w+", nt))
        if palabras & (REDACCION_FUERTES | BIBLIOTECAS):
            return True
        return any(re.search(r"\b" + re.escape(t) + r"\b", nt) for t in (INEQUIVOCOS | set(_NOMBRES_FICHA)))

    def es_seguimiento(self, pregunta):
        return (bool(self.turnos) and len(pregunta.split()) <= 8 and bool(self.SEGUIMIENTO.search(pregunta))
                and not self.tiene_termino_de_ficha(pregunta))

    def contexto(self):
        """Texto compacto de los últimos turnos (el más reciente se conserva primero) dentro del tope de tokens."""
        partes = []
        for p, r in reversed(self.turnos):
            for trozo in (p, r):
                trozo = re.sub(r"\s+", " ", trozo)
                while trozo and self._ntok(" ".join(partes + [trozo])) > self.tope:
                    trozo = trozo[: int(len(trozo) * 0.8)].rsplit(" ", 1)[0] if " " in trozo else ""
                if not trozo:
                    return " ".join(partes)
                partes.append(trozo)
        return " ".join(partes)

    def contextualizar(self, pregunta):
        """Si la pregunta es un seguimiento corto, le antepone el contexto reciente; si no, la deja igual."""
        if not self.es_seguimiento(pregunta):
            return pregunta
        p_prev = self.turnos[-1][0]
        base = f"{p_prev} {pregunta}"
        while self._ntok(base) > self.tope and " " in p_prev:
            p_prev = p_prev[: int(len(p_prev) * 0.8)].rsplit(" ", 1)[0]
            base = f"{p_prev} {pregunta}"
        return base


if __name__ == "__main__":
    import sys

    with tempfile.TemporaryDirectory() as d:
        m = Memoria(Path(d) / "m.json")
        assert extraer("Recuerda que mi proyecto se llama TEST-IA") == ("proyecto", "mi proyecto se llama TEST-IA", False)
        assert extraer("Recuerda siempre que mi alergia es el maní")[2] is True
        assert extraer("Mi color favorito es el azul.")[0] == "color favorito"
        assert extraer("¿Cómo se llama mi proyecto?") is None and extraer("hola") is None
        print(m.guardar_si_orden("Anota que la clave del wifi es patata42"))
        assert "patata42" in m.buscar_memoria("¿Cuál es la clave del wifi?")
        assert m.buscar_memoria("capital de Chile") is None
        r = m.guardar("x", "dato"); t0 = r["temperatura"]
        for _ in range(10):
            m.enfriar()
        assert m.temperatura("x") is None and len(m.archivados) >= 1
        r = m.guardar("y", "otro"); m.buscar("otro"); m.buscar("otro"); m.buscar("otro")
        assert m.temperatura("y") == TEMP_TOPE
        # permanente vs. temporal
        assert m.guardar_si_orden("Recuerda siempre que mi alergia es el maní") == "Anotado para siempre: mi alergia es el maní"
        m.guardar_si_orden("Recuerda que mi proyecto se llama TEST-IA")
        for _ in range(12):
            m.enfriar()
        assert m.temperatura("alergia") == TEMP_INICIAL and m.temperatura("proyecto") is None
        # olvido explícito
        m.guardar_si_orden("Recuerda que mi proyecto se llama TEST-IA")
        assert m.guardar_si_orden("Olvida que mi proyecto se llama TEST-IA") == "Olvidado: mi proyecto se llama TEST-IA"
        assert m.temperatura("proyecto") is None and m.archivados[-1]["motivo"].startswith("olvidado")
        assert m.guardar_si_orden("Olvida mi proyecto") == "No tengo nada guardado sobre eso."
        assert m.guardar_si_orden("Borra el archivo temporal") is None  # «borra» sin coincidencia: sigue su camino
        assert m.guardar_si_orden("Borra mi alergia") == "Olvidado: mi alergia es el maní" and m.temperatura("alergia") is None
        print("autopruebas de memoria.py correctas")
    sys.exit(0)
