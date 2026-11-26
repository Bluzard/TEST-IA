"""Adaptador entre el sujeto componible y la biblioteca de planos."""
import json

import numpy as np

from entorno_componible import NA, NR, NP, N, OPCIONES, Sujeto, puentes
from homeostato import LIMITE, SATURACION, VENTANA_ESTABLE

VERSION = "rio-observado-v1"
VENTANA_CONTEXTO = 256
TAM_CONFIG = NA * N + NP


def huella_contexto(observaciones):
    """Rasgos acotados del río observado, sensibles a la estrategia del sujeto.

    Nunca recibe Mundo, su matriz ni la semilla: no identifica terrenos por oráculo.
    Esta primera versión asume los dos canales sensoriales del laboratorio actual.
    """
    x = np.asarray(observaciones, dtype=float)
    if x.ndim != 2 or x.shape[1] != NR or len(x) < 2 or not np.isfinite(x).all():
        raise ValueError("Se necesitan observaciones finitas de los canales del río")
    media = np.mean(np.abs(x), axis=0) / SATURACION
    desv = np.std(x, axis=0) / SATURACION
    cambio = np.mean(np.abs(np.diff(x, axis=0)), axis=0) / SATURACION
    centrado = x - x.mean(axis=0)
    norma = np.linalg.norm(centrado, axis=0)
    corr = float(centrado[:, 0] @ centrado[:, 1] / np.prod(norma)) if np.all(norma > 1e-12) else 0.0
    return np.clip(np.r_[media, desv, cambio, corr], -1, 1)


def validar_concreto(contenido):
    """null significa no especificado: al aplicar se conserva el valor actual."""
    if not isinstance(contenido, dict) or set(contenido) != {"version", "configuracion"} or contenido["version"] != "componible-v1":
        raise ValueError("Formato de plano concreto incompatible")
    valores = contenido["configuracion"]
    if not isinstance(valores, list) or len(valores) != TAM_CONFIG:
        raise ValueError(f"La configuración debe tener {TAM_CONFIG} posiciones")
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))) for v in valores):
        raise ValueError("Solo se admiten números o null")
    c = np.array([np.nan if v is None else v for v in valores], dtype=float)
    mascara = ~np.isnan(c)
    if not mascara.any() or any(v is not None and not np.isfinite(v) for v in valores):
        raise ValueError("El plano debe especificar al menos un valor finito")
    if np.any(np.abs(c[:NA * N][mascara[:NA * N]]) > 1):
        raise ValueError("Conexiones fuera del rango [-1,1]")
    for valor, opciones in zip(c[NA * N:], OPCIONES):
        if not np.isnan(valor) and (valor != int(valor) or not 0 <= valor < opciones):
            raise ValueError("Colocación de pieza inválida")
    return c


def contenido_concreto(c):
    return dict(version="componible-v1", configuracion=[None if np.isnan(v) else float(v) for v in c])


def importar_planos(biblioteca, ruta):
    with open(ruta, encoding="utf-8") as f:
        documentos = json.load(f)
    if not isinstance(documentos, list):
        raise ValueError("El archivo debe contener una lista de planos")
    # Validar todo antes de escribir el primero.
    for d in documentos:
        if not isinstance(d, dict) or set(d) != {"tipo", "contenido"}:
            raise ValueError("Cada plano debe contener tipo y contenido")
        if d["tipo"] == "concreto":
            validar_concreto(d["contenido"])
        elif d["tipo"] != "abstracto" or not isinstance(d["contenido"], dict):
            raise ValueError("Tipo de plano inválido")
        json.dumps(d, allow_nan=False)
    return [biblioteca.guardar(d["contenido"], d["tipo"], "externo") for d in documentos]


class SujetoPersistente(Sujeto):
    def __init__(self, rng, biblioteca):
        super().__init__(rng)
        self.biblioteca = biblioteca
        self.contexto = None
        self.ids = []
        self.scores = []
        self.usos = {}
        self.recuperados = 0

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        if pasos < VENTANA_CONTEXTO:
            raise ValueError(f"Se necesitan al menos {VENTANA_CONTEXTO} pasos")
        # Evidencia local nueva por visita; el cuerpo actual sí puede conservarse.
        for nombre in ("repertorio", "pesos", "exitos", "fallos", "rapida", "lenta", "intentos", "logros", "ids", "scores"):
            setattr(self, nombre, [])
        self.contexto = None
        self.observaciones = []
        self.usos = {}
        self.recuperados = 0
        self.primer_puente_estable = None
        self._racha_puente = 0
        return super().vivir(mundo, pasos, rng_perturbaciones)

    def _observar(self, t):
        viable = np.all(np.abs(self.x[:NA]) <= LIMITE) and np.all(np.abs(self.x[NA:]) < SATURACION - 1e-9)
        self._racha_puente = self._racha_puente + 1 if viable and puentes(self.P) else 0
        if self._racha_puente >= VENTANA_ESTABLE and self.primer_puente_estable is None:
            self.primer_puente_estable = t
        if t <= VENTANA_CONTEXTO:
            self.observaciones.append(self.x[NA:NA + NR].copy())
        if t == VENTANA_CONTEXTO:
            self.huella = huella_contexto(self.observaciones)
            self.contexto = self.biblioteca.contexto(self.huella, VERSION)
            for candidato in self.biblioteca.candidatos(self.huella, VERSION, self.contexto):
                c = validar_concreto(candidato['contenido'])
                self._agregar(c, candidato['id'], candidato['stats'],
                              candidato['score'] / max(candidato['stats'][2], 1e-3))
            self.recuperados = len(self.ids)

    def _agregar(self, c, pid, stats, score=1.0):
        self.repertorio.append(c.copy())
        self.ids.append(pid)
        self.scores.append(score)
        n, s, r = stats
        self.intentos.append(n)
        self.logros.append(s)
        self.rapida.append(r)
        self.lenta.append(0.5)
        self.pesos.append(1.0)
        self.exitos.append(0)
        self.fallos.append(0)

    def _guardar(self):
        if self.contexto is None:
            return
        c = self._config()
        if self._indice() is None:
            pid = self.biblioteca.guardar(contenido_concreto(c))
            self.biblioteca.asociar(pid, self.contexto)
            self._agregar(c, pid, self.biblioteca.evidencia(pid, self.contexto))

    def _cargar(self, c):
        for k, plano in enumerate(self.repertorio):
            if plano is c:
                pid = self.ids[k]
                self.usos[pid] = self.usos.get(pid, 0) + 1
                break
        super()._cargar(np.where(np.isnan(c), self._config(), c))

    def _resultado(self, k, exito):
        n, s, r = self.biblioteca.registrar(self.ids[k], self.contexto, exito, self.aspiracion)
        self.intentos[k], self.logros[k], self.rapida[k] = n, s, r
        self.scores[k] = 1.0

    def _premiar(self, k):
        self._resultado(k, True)
        # Una plantilla externa que sirvió también deja su realización concreta.
        if np.isnan(self.repertorio[k]).any():
            self._guardar()

    def _castigar(self, k):
        self._resultado(k, False)

    def _peso(self, k):
        return super()._peso(k) * max(self.scores[k], 1e-3)
