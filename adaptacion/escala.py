"""Prueba 2: el límite de escala.

Con 8 o más unidades propias el homeostato original no llegaba nunca: cada
unidad que se sale cambia TODA su fila al azar, y el espacio de
configuraciones crece explosivamente. Se prueban dos ideas de Ashby:

  - "un peso": al salirse de rango, la unidad cambia solo UNA conexión al
    azar (cambio local) en vez de toda la fila.
  - "subsistemas": las unidades propias se agrupan en bloques de 2 que solo
    se conectan entre sí y con el entorno (dispersión). Ojo: esto es una
    estructura dada de antemano (un "cuerpo"), no algo que el sistema elige.

D1: un solo entorno nuevo por tamaño.
D2: cinco entornos nuevos seguidos, con y sin memoria autorregulada:
    ¿lo vivido en entornos anteriores sirve en los siguientes al escalar?
"""
import sys

import numpy as np

from homeostato import NIVELES, Entorno
from homeostato_memoria import PRESUPUESTO, FUERZA
from homeostato_autorregulado import HomeostatoAutorregulado

N_ENTORNO = 2
TAMANOS = (2, 4, 6, 8, 10)
REP = 30


class HomeostatoEstructura(HomeostatoAutorregulado):
    def __init__(self, n_agente, rng, cambio="fila", bloque=None, memoria=False):
        super().__init__(n_agente, N_ENTORNO, rng)
        self.cambio = cambio
        self.memoria = memoria
        n = n_agente + N_ENTORNO
        self.mascara = np.ones((n_agente, n), dtype=bool)
        if bloque:
            self.mascara[:, :n_agente] = False
            for i in range(n_agente):
                ini = (i // bloque) * bloque
                self.mascara[i, ini: ini + bloque] = True
        self.W = self.W * self.mascara

    def p_recordar(self):
        return super().p_recordar() if self.memoria else 0.0

    def _explorar(self, fuera):
        for i in np.flatnonzero(fuera):
            permitidas = np.flatnonzero(self.mascara[i])
            if self.cambio == "fila":
                self.W[i, permitidas] = self.rng.choice(NIVELES, permitidas.size)
            else:
                self.W[i, self.rng.choice(permitidas)] = self.rng.choice(NIVELES)


ESTRUCTURAS = (
    ("original (fila)", dict(cambio="fila")),
    ("un peso", dict(cambio="peso")),
    ("subsistemas", dict(cambio="fila", bloque=2)),
    ("subsistemas + un peso", dict(cambio="peso", bloque=2)),
)


def d1():
    print(f"=== D1 · un entorno nuevo por tamaño ({REP} repeticiones): llegan ===")
    print(f"{'estructura':<24}" + "".join(f"{n:>9} u." for n in TAMANOS))
    for nombre, kw in ESTRUCTURAS:
        fila = []
        for na in TAMANOS:
            llegan = 0
            for k in range(REP):
                rng = np.random.default_rng(55_555 + na * 1000 + k)
                ent = Entorno(na, N_ENTORNO, FUERZA, rng)
                ok, _, _ = HomeostatoEstructura(na, rng, **kw).vivir(ent, PRESUPUESTO)
                llegan += ok
            fila.append(f"{llegan:>7}/{REP}")
        print(f"{nombre:<24}" + "".join(fila))
        sys.stdout.flush()


def d2(tamanos=(6, 8), n_seguidos=5, rep=20):
    print(f"\n=== D2 · {n_seguidos} entornos nuevos seguidos ({rep} repeticiones): llegan por posición ===")
    for na in tamanos:
        for nombre, kw in ESTRUCTURAS:
            for memoria in (False, True):
                llegan = np.zeros(n_seguidos, dtype=int)
                for k in range(rep):
                    rng = np.random.default_rng(88_888 + na * 1000 + k)
                    h = HomeostatoEstructura(na, rng, memoria=memoria, **kw)
                    for j in range(n_seguidos):
                        ok, _, _ = h.vivir(Entorno(na, N_ENTORNO, FUERZA, rng), PRESUPUESTO)
                        llegan[j] += ok
                etiqueta = f"{na} u. · {nombre} · {'con' if memoria else 'sin'} memoria"
                print(f"{etiqueta:<48}" + "  ".join(f"{x:>2}/{rep}" for x in llegan))
                sys.stdout.flush()


if __name__ == "__main__":
    d1()
    d2()
