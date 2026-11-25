"""Prueba 8: confirmar la aspiración con 100 vidas por variante.

Variantes:
  - caos (sin memoria)
  - tu regla + castigo duro (sin aspiración)
  - aspiración 90 %: sobre el 90 % aún explora un poco tras cada fallo
  - satisfecho 90 %: si alguna configuración está sobre el 90 %, tras un
    fallo SIEMPRE vuelve a ella (no explora). Si su tasa cae bajo el 90 %,
    la búsqueda se reactiva sola.

Incluye prueba exacta de Fisher para los puentes: qué tan probable es que
la diferencia sea azar.
"""
import sys
from math import comb

import numpy as np

from aspiracion import Aspiracion
import puente

REP = 100
ASPIRACION = 0.90


class Satisfecho(Aspiracion):
    def _satisfactorias(self):
        return [k for k in range(len(self.repertorio)) if self.tasa(k) >= self.aspiracion]

    def p_recordar(self):
        return 1.0 if self._satisfactorias() else super().p_recordar()

    def _peso(self, k):
        sat = self._satisfactorias()
        if sat:
            return 1.0 if k == max(sat, key=self.tasa) else 1e-12
        return super()._peso(k)


def fisher(a, b, n=REP):
    """p bilateral de Fisher para a/n frente a b/n."""
    total = a + b

    def prob(x):
        return comb(n, x) * comb(n, total - x) / comb(2 * n, total)

    p_obs = prob(a)
    return min(1.0, sum(prob(x) for x in range(max(0, total - n), min(total, n) + 1)
                        if prob(x) <= p_obs * (1 + 1e-9)))


VARIANTES = (
    ("caos (sin memoria)", lambda rng: puente.SinMemoria(4, 2, rng)),
    ("tu regla + castigo duro", lambda rng: Aspiracion(4, 2, rng)),
    ("aspiración 90 %", lambda rng: Aspiracion(4, 2, rng, ASPIRACION)),
    ("satisfecho 90 %", lambda rng: Satisfecho(4, 2, rng, ASPIRACION)),
)

if __name__ == "__main__":
    print(f"=== Puente · {REP} vidas por variante ===")
    print(f"{'variante':<26}{'fallos total':>14}{'T1':>7}{'T6':>7}{'puente':>10}{'soluciones':>12}")
    puentes = {}
    for nombre, crear in VARIANTES:
        t, pu, _, rp = puente.correr(crear, rep=REP)
        puentes[nombre] = int(pu)
        print(f"{nombre:<26}{np.median(t.sum(axis=1)):>14.0f}{np.median(t[:, 0]):>7.0f}"
              f"{np.median(t[:, -1]):>7.0f}{pu:>6}/{REP}{rp:>12.1f}")
        sys.stdout.flush()

    print("\nFisher (p < 0.05 = difícil que sea azar):")
    nombres = [n for n, _ in VARIANTES]
    for i, a in enumerate(nombres):
        for b in nombres[i + 1:]:
            print(f"  {a:<24} vs {b:<24} {puentes[a]:>3} vs {puentes[b]:>3}   p = {fisher(puentes[a], puentes[b]):.3f}")
