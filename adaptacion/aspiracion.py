"""Prueba 7: nivel de aspiración (Simon).

La necesidad ya no es solo "no salirse de rango ahora", sino "que lo que uso
funcione al menos ASPIRACION de las veces". Mientras no se alcance, lo que se
está usando no gana confianza (los éxitos no suman) y cada fallo la parte a
la mitad: el sistema sigue buscando. Al alcanzarla, deja de buscar.

Cambio respecto de las pruebas anteriores: los éxitos y fallos se le cobran
a la configuración EN USO durante toda su vida (no solo justo después de
recordarla). Un intento = INTENTO pasos seguidos; éxito si no se cae.
"""
import sys

import numpy as np

from homeostato import DT, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION
from tasa_fallo import TasaReciente, RAPIDA
import puente

INTENTO = 1_000
REP = 40


class Aspiracion(TasaReciente):
    def __init__(self, n_agente, n_entorno, rng, aspiracion=None):
        super().__init__(n_agente, n_entorno, rng)
        self.aspiracion = aspiracion
        self.intentos: list[int] = []
        self.logros: list[int] = []

    def _guardar(self):
        n = len(self.repertorio)
        super()._guardar()
        if len(self.repertorio) > n:
            self.intentos.append(0)
            self.logros.append(0)

    def tasa(self, k):
        return (self.logros[k] + 1) / (self.intentos[k] + 2)

    def _premiar(self, k):
        self.intentos[k] += 1
        self.logros[k] += 1
        if self.aspiracion is None or self.tasa(k) >= self.aspiracion:
            self.rapida[k] += RAPIDA * (1 - self.rapida[k])

    def _castigar(self, k):
        self.intentos[k] += 1
        self.rapida[k] *= 0.5

    def _indice(self):
        for k, m in enumerate(self.repertorio):
            if np.allclose(self.W, m):
                return k
        return None

    def vivir(self, entorno, max_pasos, hasta_estable=False):
        pasos_con_fallo, sin_violar = [], 0
        actual, desde = None, 0  # configuración en uso (índice en el repertorio)
        empuje = getattr(entorno, "empuje", None)
        for t in range(1, max_pasos + 1):
            A = np.vstack([self.W, entorno.filas])
            dx = A @ self.x if empuje is None else A @ self.x + empuje(self.rng)
            self.x = np.clip(self.x + DT * dx, -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self._perturbar(entorno)

            fuera = self._fuera()
            if fuera.any():
                pasos_con_fallo.append(t)
                sin_violar = 0
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
                if sin_violar == VENTANA_ESTABLE and actual is None:
                    self._guardar()
                    actual, desde = self._indice(), t
                if actual is not None and t - desde >= INTENTO:
                    self._premiar(actual)
                    desde = t
        return pasos_con_fallo


VARIANTES = (
    ("tu regla + castigo duro", lambda rng: Aspiracion(4, 2, rng)),
    ("+ aspiración 90 %", lambda rng: Aspiracion(4, 2, rng, 0.90)),
    ("+ aspiración 95 %", lambda rng: Aspiracion(4, 2, rng, 0.95)),
)

if __name__ == "__main__":
    print(f"=== Puente · {REP} repeticiones · intento = {INTENTO} pasos ===")
    print(f"{'variante':<26}" + "".join(f"{'T' + str(j + 1):>7}" for j in range(puente.TRAMOS))
          + f"{'fallos total':>14}{'puente':>10}{'soluciones':>12}")
    for nombre, crear in VARIANTES:
        t, pu, _, rp = puente.correr(crear, rep=REP)
        med = np.median(t, axis=0)
        print(f"{nombre:<26}" + "".join(f"{x:>7.0f}" for x in med)
              + f"{np.median(t.sum(axis=1)):>14.0f}{pu:>6}/{REP}{rp:>12.1f}")
        sys.stdout.flush()
