"""Prueba 5: ¿pueden surgir solos los subsistemas?

En la prueba de escala, dividir el sistema en bloques de 2 (dado de antemano)
fue lo que permitió crecer. Aquí nadie fija la estructura:

  - "libre": cuando una unidad se sale de rango, cambia su fila al azar como
    siempre, pero cada conexión con otra unidad propia también puede quedar
    presente o ausente al azar (50 %). La estructura es una cosa más que se
    explora a ciegas; se queda la que resulta viable.

Si la viabilidad favorece estar poco conectado, al final debería haber menos
conexiones que el 48 % que da el puro azar, y grupos más pequeños.

Referencias: original (todo conectado), subsistemas de 2 y unidades aisladas
(solo conectadas con el entorno), las tres con estructura fija.
"""
import sys

import numpy as np

from homeostato import NIVELES, Entorno
from homeostato_memoria import PRESUPUESTO, FUERZA
from escala import HomeostatoEstructura, N_ENTORNO

TAMANOS = (6, 8, 10)
REP = 30
AZAR = 0.5 * (1 - 1 / len(NIVELES))  # densidad esperada por puro azar (el nivel 0 también es ausencia)


class EstructuraLibre(HomeostatoEstructura):
    def __init__(self, n_agente, rng):
        super().__init__(n_agente, rng, memoria=False)
        for i in range(n_agente):
            self._fila_libre(i)

    def _fila_libre(self, i):
        fila = self.rng.choice(NIVELES, self.W.shape[1])
        otras = [j for j in range(self.na) if j != i]
        fila[otras] *= self.rng.random(len(otras)) < 0.5
        self.W[i] = fila

    def _explorar(self, fuera):
        for i in np.flatnonzero(fuera):
            self._fila_libre(i)


def densidad(W, na):
    sub = W[:, :na] != 0
    np.fill_diagonal(sub, False)
    return sub.sum() / (na * (na - 1))


def tamano_grupos(W, na):
    """Tamaño medio de los grupos de unidades propias conectadas entre sí."""
    adj = (W[:, :na] != 0) | (W[:, :na] != 0).T
    visto, tamanos = set(), []
    for s in range(na):
        if s in visto:
            continue
        pila, grupo = [s], 0
        visto.add(s)
        while pila:
            u = pila.pop()
            grupo += 1
            for v in np.flatnonzero(adj[u]):
                if v not in visto:
                    visto.add(v)
                    pila.append(v)
        tamanos.append(grupo)
    return float(np.mean(tamanos))


VARIANTES = (
    ("original (todo conectado)", lambda na, rng: HomeostatoEstructura(na, rng)),
    ("subsistemas de 2 (dado)", lambda na, rng: HomeostatoEstructura(na, rng, bloque=2)),
    ("aisladas (dado)", lambda na, rng: HomeostatoEstructura(na, rng, bloque=1)),
    ("libre (emergente)", lambda na, rng: EstructuraLibre(na, rng)),
)

if __name__ == "__main__":
    print(f"=== {REP} repeticiones por tamaño · densidad por azar = {AZAR:.0%} ===")
    print(f"{'estructura':<28}{'tamaño':>7}{'llegan':>9}{'densidad final':>16}{'grupo medio':>13}")
    for nombre, crear in VARIANTES:
        for na in TAMANOS:
            llegan, dens, grupos = 0, [], []
            for k in range(REP):
                rng = np.random.default_rng(55_555 + na * 1000 + k)
                ent = Entorno(na, N_ENTORNO, FUERZA, rng)
                h = crear(na, rng)
                ok, _, _ = h.vivir(ent, PRESUPUESTO)
                llegan += ok
                if ok:
                    dens.append(densidad(h.W, na))
                    grupos.append(tamano_grupos(h.W, na))
            d = f"{np.mean(dens):.0%}" if dens else "-"
            g = f"{np.mean(grupos):.1f}" if grupos else "-"
            print(f"{nombre:<28}{na:>7}{llegan:>6}/{REP}{d:>16}{g:>13}")
            sys.stdout.flush()
