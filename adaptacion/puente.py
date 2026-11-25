"""Prueba 4: ¿alguien inventa el puente si saltar casi siempre funciona?

El río: perturbaciones normales suaves y, de vez en cuando, una crecida:
un empuje sostenido en una dirección al azar durante un rato.
  - "Saltar": configuraciones estables pero con poco margen; la crecida las
    desplaza mucho y las saca de rango. Fáciles de encontrar, fallan a veces.
  - "Puente": configuraciones con margen amplio; la crecida apenas las mueve.
    Más raras, no fallan.

Cada variante vive mucho tiempo en el MISMO río (sin detenerse al
estabilizarse). Se mide cuántos fallos tiene en cada tramo de su vida y si
al final cruza sin fallar (encontró el puente).
"""
import sys

import numpy as np

from homeostato import Entorno
from homeostato_autorregulado import HomeostatoAutorregulado
from homeostato_memoria import FUERZA
from tasa_fallo import TasaReciente, RapidaVsLenta

PERTURBACION_NORMAL = 0.25
CADA_CRECIDA = 3_000      # pasos promedio entre crecidas
DURACION_CRECIDA = 300
FUERZA_CRECIDA = 0.15
VIDA = 300_000
TRAMOS = 6
REP = 20


class Rio(Entorno):
    def __init__(self, n_agente, n_entorno, fuerza, rng):
        super().__init__(n_agente, n_entorno, fuerza, rng)
        self.restante = 0
        self.direccion = np.zeros(n_agente + n_entorno)

    def perturbar(self, rng, n):
        return rng.normal(0, PERTURBACION_NORMAL, n)

    def empuje(self, rng):
        if self.restante == 0 and rng.random() < 1 / CADA_CRECIDA:
            self.restante = DURACION_CRECIDA
            self.direccion = rng.normal(0, FUERZA_CRECIDA, self.direccion.size)
        if self.restante > 0:
            self.restante -= 1
            return self.direccion
        return 0.0


class SinMemoria(HomeostatoAutorregulado):
    def p_recordar(self):
        return 0.0


VARIANTES = (
    ("sin memoria", lambda rng: SinMemoria(4, 2, rng)),
    ("castigo duro c=0.5", lambda rng: HomeostatoAutorregulado(4, 2, rng, 0.5, 200)),
    ("castigo suave c=0.95", lambda rng: HomeostatoAutorregulado(4, 2, rng, 0.95, 100)),
    ("fallo histórico", lambda rng: HomeostatoAutorregulado(4, 2, rng, conteo=True)),
    ("fallo reciente", lambda rng: TasaReciente(4, 2, rng)),
    ("rápida vs lenta", lambda rng: RapidaVsLenta(4, 2, rng)),
)


def episodios(pasos_con_fallo):
    """Cuenta fallos como episodios (pasos con fallo no consecutivos)."""
    p = np.asarray(pasos_con_fallo)
    if p.size == 0:
        return p
    return p[np.concatenate([[True], np.diff(p) > 1])]


def margen(h, rio):
    A = np.vstack([h.W, rio.filas])
    return -float(np.max(np.linalg.eigvals(A).real))


def correr(crear, rep=REP, vida=VIDA):
    tramo = vida // TRAMOS
    por_tramo = np.zeros((rep, TRAMOS))
    puentes, margenes, repertorios = 0, [], []
    for r in range(rep):
        rng = np.random.default_rng(4_242 + r)
        rio = Rio(4, 2, FUERZA, rng)
        h = crear(np.random.default_rng(6_000 + r))
        ep = episodios(h.vivir(rio, vida, hasta_estable=False))
        for j in range(TRAMOS):
            por_tramo[r, j] = np.sum((ep > j * tramo) & (ep <= (j + 1) * tramo))
        puentes += por_tramo[r, -1] == 0
        margenes.append(margen(h, rio))
        repertorios.append(len(h.repertorio))
    return por_tramo, puentes, float(np.median(margenes)), float(np.mean(repertorios))


if __name__ == "__main__":
    print(f"Río: crecida cada ~{CADA_CRECIDA} pasos, dura {DURACION_CRECIDA} (fuerza {FUERZA_CRECIDA}); "
          f"perturbación normal {PERTURBACION_NORMAL}. Vida {VIDA} pasos en {TRAMOS} tramos, {REP} repeticiones.")
    print("Fallos por tramo (mediana) · puente = último tramo sin fallos · margen = robustez final\n")
    print(f"{'variante':<22}" + "".join(f"{'T' + str(j + 1):>7}" for j in range(TRAMOS))
          + f"{'puente':>10}{'margen':>9}{'soluciones':>12}")
    for nombre, crear in VARIANTES:
        t, pu, mg, rp = correr(crear)
        med = np.median(t, axis=0)
        print(f"{nombre:<22}" + "".join(f"{x:>7.0f}" for x in med)
              + f"{pu:>6}/{REP}{mg:>9.3f}{rp:>12.1f}")
        sys.stdout.flush()
