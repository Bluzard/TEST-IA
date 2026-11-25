"""Prueba 6: tu regla (explorar según el fallo reciente) + castigo duro.

  - Éxito de un recuerdo: la confianza sube de a poco (promedio móvil, 0.3).
  - Fallo: la confianza cae a la mitad de golpe (castigo duro).
  - Éxito = sostenerse PRUEBA pasos tras recordarlo (como el castigo duro).
  - Probabilidad de explorar = 1 - confianza del mejor recuerdo.

Se compara en el río (puente) con más repeticiones, y en las pruebas de
revisitas y entornos nuevos (C, E/F).
"""
import sys

import numpy as np

from tasa_fallo import TasaReciente
from homeostato_autorregulado import HomeostatoAutorregulado
from constantes import evaluar, REP_E
import puente

PRUEBA = 200
REP_PUENTE = 40


class Combinada(TasaReciente):
    def __init__(self, n_agente, n_entorno, rng):
        super().__init__(n_agente, n_entorno, rng)
        self.prueba = PRUEBA

    def _castigar(self, k):
        self.rapida[k] *= 0.5


VARIANTES_PUENTE = (
    ("sin memoria (caos)", lambda rng: puente.SinMemoria(4, 2, rng)),
    ("castigo duro c=0.5", lambda rng: HomeostatoAutorregulado(4, 2, rng, 0.5, 200)),
    ("fallo reciente (tu regla)", lambda rng: TasaReciente(4, 2, rng)),
    ("tu regla + castigo duro", lambda rng: Combinada(4, 2, rng)),
)

if __name__ == "__main__":
    print("=== C, E/F · revisitas y entornos nuevos ===")
    print(f"{'variante':<27}{'revisitas':>10}{'no llegó C':>12}{'E3':>8}{'llega':>7}"
          f"{'E4':>8}{'llega':>7}{'p_recordar final':>18}")
    rv, fc, nc, e3, l3, e4, l4, p = evaluar(lambda rng: Combinada(4, 2, rng))
    print(f"{'tu regla + castigo duro':<27}{rv:>10}{fc:>7}/{nc}{e3:>8}{l3:>4}/{REP_E}"
          f"{e4:>8}{l4:>4}/{REP_E}{p:>18.2f}")
    sys.stdout.flush()

    print(f"\n=== Puente · {REP_PUENTE} repeticiones, fallos por tramo (mediana) ===")
    print(f"{'variante':<27}" + "".join(f"{'T' + str(j + 1):>7}" for j in range(puente.TRAMOS))
          + f"{'fallos total':>14}{'puente':>10}{'soluciones':>12}")
    for nombre, crear in VARIANTES_PUENTE:
        t, pu, _, rp = puente.correr(crear, rep=REP_PUENTE)
        med = np.median(t, axis=0)
        total = np.median(t.sum(axis=1))
        print(f"{nombre:<27}" + "".join(f"{x:>7.0f}" for x in med)
              + f"{total:>14.0f}{pu:>6}/{REP_PUENTE}{rp:>12.1f}")
        sys.stdout.flush()
