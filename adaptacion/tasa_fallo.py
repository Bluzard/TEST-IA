"""Prueba 3: explorar en proporción a lo que falla lo conocido.

Idea: si saltar el río falla el 15 % de las veces, el 15 % de las veces
se prueba algo distinto. Probabilidad de recordar = tasa de éxito del mejor
recuerdo; probabilidad de explorar = su tasa de fallo.

La pregunta es qué tasa de fallo: la de toda la vida o la de ahora.
  - histórica: éxitos/fallos acumulados (modo "conteo").
  - reciente: promedio móvil rápido (pesa más lo último).
  - rápida vs lenta: lleva ambas; si difieren, la situación cambió y
    explora más (p_recordar = rápida - |rápida - lenta|).

Éxito de un recuerdo = llegar a estabilizarse tras recordarlo.
"""
import sys

import numpy as np

from homeostato import VENTANA_ESTABLE
from homeostato_autorregulado import HomeostatoAutorregulado
from constantes import evaluar, REP_E

RAPIDA = 0.3
LENTA = 0.03


class TasaReciente(HomeostatoAutorregulado):
    comparar_lenta = False

    def __init__(self, n_agente, n_entorno, rng):
        super().__init__(n_agente, n_entorno, rng)
        self.prueba = VENTANA_ESTABLE
        self.rapida: list[float] = []
        self.lenta: list[float] = []

    def _guardar(self):
        n = len(self.repertorio)
        super()._guardar()
        if len(self.repertorio) > n:
            self.rapida.append(0.5)
            self.lenta.append(0.5)

    def _actualizar(self, k, exito):
        self.rapida[k] += RAPIDA * (exito - self.rapida[k])
        self.lenta[k] += LENTA * (exito - self.lenta[k])

    def _premiar(self, k):
        self._actualizar(k, 1.0)

    def _castigar(self, k):
        self._actualizar(k, 0.0)

    def _peso(self, k):
        r = self.rapida[k]
        if self.comparar_lenta:
            r -= abs(self.rapida[k] - self.lenta[k])
        return max(r, 1e-3)

    def p_recordar(self):
        if not self.repertorio:
            return 0.0
        return min(1.0, max(self._peso(k) for k in range(len(self.repertorio))))


class RapidaVsLenta(TasaReciente):
    comparar_lenta = True


VARIANTES = (
    ("castigo c=0.8 p=100", lambda rng: HomeostatoAutorregulado(4, 2, rng, 0.8, 100)),
    ("fallo histórico", lambda rng: HomeostatoAutorregulado(4, 2, rng, conteo=True)),
    ("fallo reciente", lambda rng: TasaReciente(4, 2, rng)),
    ("rápida vs lenta", lambda rng: RapidaVsLenta(4, 2, rng)),
)

if __name__ == "__main__":
    print(f"{'variante':<21}{'revisitas':>10}{'no llegó C':>12}{'E3':>8}{'llega':>7}"
          f"{'E4':>8}{'llega':>7}{'p_recordar final':>18}")
    for nombre, crear in VARIANTES:
        rv, fc, nc, e3, l3, e4, l4, p = evaluar(crear)
        print(f"{nombre:<21}{rv:>10}{fc:>7}/{nc}{e3:>8}{l3:>4}/{REP_E}{e4:>8}{l4:>4}/{REP_E}{p:>18.2f}")
        sys.stdout.flush()
