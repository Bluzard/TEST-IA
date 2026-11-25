"""Paso 3: transferir método, no solo recuerdos (meta-adaptación).

Base: "satisfecho 90 %" con saturación como caída (paso 1). El sujeto cruza
N_RIOS ríos completamente distintos, uno tras otro, conservando todo.

Reglas que el propio sujeto ajusta (y que viajan de un río a otro):
  - amplitud: cuántas conexiones cambia al explorar (1 .. todas). Cada
    amplitud lleva una tasa de éxito con la misma regla del usuario: si tras
    el cambio se sostiene PRUEBA_META pasos, sube de a poco; si cae antes,
    se parte a la mitad. Se elige en proporción a esa tasa.
  - aspiración: si pasan PACIENCIA intentos sin que nada la alcance, baja
    2 puntos (mínimo 70 %); si algo la supera por 5 puntos, sube 1 (máx. 95 %).

Variantes: fijo · meta amplitud · meta aspiración · meta ambas.
Se mide por número de río: caídas, pasos hasta la primera estabilidad y
puente (último tercio del río sin caídas). Si hay meta-adaptación, los ríos
posteriores deberían cruzarse más rápido que los primeros.
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato import DT, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION, NIVELES
from homeostato_memoria import FUERZA
from aspiracion import INTENTO
from aspiracion_100 import Satisfecho
import puente

N_RIOS = 6
VIDA_RIO = 100_000
REP = 40
PRUEBA_META = 200
PACIENCIA = 50
AMPLITUDES = np.arange(1, 7)  # 6 = toda la fila (4 propias + 2 de entorno)
VARIANTES = {
    "fijo": dict(),
    "meta amplitud": dict(meta_amplitud=True),
    "meta aspiración": dict(meta_aspiracion=True),
    "meta ambas": dict(meta_amplitud=True, meta_aspiracion=True),
}


class Meta(Satisfecho):
    saturacion_es_caida = True

    def __init__(self, rng, meta_amplitud=False, meta_aspiracion=False):
        super().__init__(4, 2, rng, 0.90)
        self.meta_amplitud = meta_amplitud
        self.meta_aspiracion = meta_aspiracion
        self.valor_k = np.full(AMPLITUDES.size, 0.5)
        self.k_en_prueba = None
        self.sin_satisfacer = 0

    # --- amplitud de cambio ---
    def _explorar(self, fuera):
        if self.meta_amplitud:
            idx = int(self.rng.choice(AMPLITUDES.size, p=self.valor_k / self.valor_k.sum()))
        else:
            idx = AMPLITUDES.size - 1
        k = AMPLITUDES[idx]
        for i in np.flatnonzero(fuera):
            cols = self.rng.choice(self.W.shape[1], size=k, replace=False)
            self.W[i, cols] = self.rng.choice(NIVELES, k)
        self.k_en_prueba = (idx, self.t)

    def _evaluar_k(self, exito):
        idx, _ = self.k_en_prueba
        if exito:
            self.valor_k[idx] += 0.3 * (1 - self.valor_k[idx])
        else:
            self.valor_k[idx] = max(self.valor_k[idx] * 0.5, 1e-3)
        self.k_en_prueba = None

    # --- aspiración adaptable ---
    def _ajustar_aspiracion(self):
        if not self.meta_aspiracion:
            return
        if self._satisfactorias():
            self.sin_satisfacer = 0
            if any(self.tasa(k) >= self.aspiracion + 0.05 for k in range(len(self.repertorio))):
                self.aspiracion = min(0.95, self.aspiracion + 0.01)
        else:
            self.sin_satisfacer += 1
            if self.sin_satisfacer % PACIENCIA == 0:
                self.aspiracion = max(0.70, self.aspiracion - 0.02)

    def _premiar(self, k):
        super()._premiar(k)
        self._ajustar_aspiracion()

    def _castigar(self, k):
        super()._castigar(k)
        self._ajustar_aspiracion()

    def vivir_rio(self, rio, pasos):
        caidas, primera_estable = [], None
        actual, desde, sin_violar = None, 0, 0
        for t in range(1, pasos + 1):
            self.t = t
            A = np.vstack([self.W, rio.filas])
            self.x = np.clip(self.x + DT * (A @ self.x + rio.empuje(self.rng)), -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self._perturbar(rio)
            fuera = self._fuera()
            if fuera.any():
                caidas.append(t)
                sin_violar = 0
                if self.k_en_prueba is not None:
                    self._evaluar_k(False)
                if actual is not None:
                    self._castigar(actual)
                    actual = None
                if self.repertorio and self.rng.random() < self.p_recordar():
                    w = np.array([self._peso(k) for k in range(len(self.repertorio))])
                    actual = int(self.rng.choice(len(w), p=w / w.sum()))
                    self.W = self.repertorio[actual].copy()
                    desde = t
                else:
                    self._explorar(fuera)
                self.x[: self.na][fuera] *= 0.5
            else:
                sin_violar += 1
                if self.k_en_prueba is not None and t - self.k_en_prueba[1] >= PRUEBA_META:
                    self._evaluar_k(True)
                if sin_violar == VENTANA_ESTABLE:
                    if primera_estable is None:
                        primera_estable = t
                    if actual is None:
                        self._guardar()
                        actual, desde = self._indice(), t
                if actual is not None and t - desde >= INTENTO:
                    self._premiar(actual)
                    desde = t
        ep = puente.episodios(caidas)
        return dict(caidas=len(ep), primera=primera_estable if primera_estable else pasos,
                    puente=int(np.sum(ep > pasos - pasos // 3)) == 0)


def correr(nombre):
    kw = VARIANTES[nombre]
    por_rio = [[] for _ in range(N_RIOS)]
    finales_k, finales_asp = [], []
    for r in range(REP):
        rng_mundo = np.random.default_rng(31_000 + r)
        rios = [puente.Rio(4, 2, FUERZA, rng_mundo) for _ in range(N_RIOS)]
        h = Meta(np.random.default_rng(32_000 + r), **kw)
        for j, rio in enumerate(rios):
            por_rio[j].append(h.vivir_rio(rio, VIDA_RIO))
        finales_k.append(h.valor_k / h.valor_k.sum())
        finales_asp.append(h.aspiracion)
    return nombre, por_rio, np.mean(finales_k, axis=0), float(np.mean(finales_asp))


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=len(VARIANTES)) as ex:
        res = {n: (p, k, a) for n, p, k, a in ex.map(correr, VARIANTES)}

    print(f"=== Meta-adaptación · {REP} sujetos · {N_RIOS} ríos distintos seguidos · {VIDA_RIO} pasos por río ===")
    for titulo, clave, fmt in (("caídas por río (mediana)", "caidas", "{:>7.0f}"),
                               ("pasos hasta la primera estabilidad (mediana)", "primera", "{:>7.0f}"),
                               ("puentes por río", "puente", None)):
        print(f"\n{titulo}")
        print(f"{'variante':<18}" + "".join(f"{'río ' + str(j + 1):>9}" for j in range(N_RIOS)))
        for n in VARIANTES:
            por_rio = res[n][0]
            if fmt:
                celdas = [fmt.format(np.median([d[clave] for d in por_rio[j]])) for j in range(N_RIOS)]
            else:
                celdas = [f"{sum(d['puente'] for d in por_rio[j]):>3}/{REP}" for j in range(N_RIOS)]
            print(f"{n:<18}" + "".join(f"{c:>9}" for c in celdas))

    print("\nReglas al final (promedio de los sujetos):")
    for n in VARIANTES:
        _, k, a = res[n]
        reparto = ("  ".join(f"k={AMPLITUDES[i]}:{k[i]:.0%}" for i in range(AMPLITUDES.size))
                   if VARIANTES[n].get("meta_amplitud") else "(no la ajusta: siempre toda la fila)")
        print(f"  {n:<18} aspiración {a:.0%}   preferencia de amplitud: {reparto}")
    sys.stdout.flush()
