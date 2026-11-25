"""Prueba 9: después de cruzar un río, ¿cómo cruza otro?

Cada variante vive VIDA pasos en el río 1 y luego, con todo lo que aprendió
(memoria, confianza, configuración actual), pasa a:
  - río parecido: el mismo cauce con una alteración leve;
  - río distinto: reglas completamente nuevas.
Control: la misma variante SIN experiencia previa cruzando esos mismos ríos.

Se mide en el río nuevo: fallos totales, fallos del primer tramo (costo de
adaptarse) y si encontró el puente (último tramo sin fallos).
"""
import copy
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato_memoria import FUERZA
from aspiracion import Aspiracion
from aspiracion_100 import Satisfecho, fisher
import puente

VIDA = 300_000
REP = 50
VARIANTES = ("caos (sin memoria)", "tu regla + castigo duro", "aspiración 90 %", "satisfecho 90 %")


def crear(nombre, rng):
    if nombre == "caos (sin memoria)":
        return puente.SinMemoria(4, 2, rng)
    if nombre == "tu regla + castigo duro":
        return Aspiracion(4, 2, rng)
    if nombre == "aspiración 90 %":
        return Aspiracion(4, 2, rng, 0.90)
    return Satisfecho(4, 2, rng, 0.90)


def rio_con_filas(filas, rng):
    r = puente.Rio(4, 2, FUERZA, rng)
    r.filas = filas
    return r


def medir(h, rio):
    ep = puente.episodios(h.vivir(rio, VIDA, hasta_estable=False))
    tramo = VIDA // puente.TRAMOS
    por_tramo = [int(np.sum((ep > j * tramo) & (ep <= (j + 1) * tramo))) for j in range(puente.TRAMOS)]
    return sum(por_tramo), por_tramo[0], por_tramo[-1] == 0


def correr_variante(nombre):
    res = {k: [] for k in ("rio1", "parecido_exp", "distinto_exp", "parecido_nuevo", "distinto_nuevo")}
    for r in range(REP):
        rng_mundo = np.random.default_rng(4_242 + r)
        rio1 = puente.Rio(4, 2, FUERZA, rng_mundo)
        parecido = rio1.filas + rng_mundo.normal(0, 0.25, rio1.filas.shape)
        distinto = puente.Rio(4, 2, FUERZA, rng_mundo).filas

        h = crear(nombre, np.random.default_rng(6_000 + r))
        res["rio1"].append(medir(h, rio1))
        for clave, filas, semilla in (("parecido", parecido, 1), ("distinto", distinto, 2)):
            experimentado = copy.deepcopy(h)
            experimentado.rng = np.random.default_rng(7_000 + 10 * r + semilla)
            res[f"{clave}_exp"].append(medir(experimentado, rio_con_filas(filas, np.random.default_rng(8_000 + r))))
            nuevo = crear(nombre, np.random.default_rng(7_000 + 10 * r + semilla))
            res[f"{clave}_nuevo"].append(medir(nuevo, rio_con_filas(filas, np.random.default_rng(8_000 + r))))
    return nombre, res


def fila(nombre, etiqueta, datos):
    total = np.median([d[0] for d in datos])
    t1 = np.median([d[1] for d in datos])
    pu = sum(d[2] for d in datos)
    print(f"{nombre:<26}{etiqueta:<22}{total:>10.0f}{t1:>8.0f}{pu:>8}/{REP}")
    return pu


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=len(VARIANTES)) as ex:
        resultados = dict(ex.map(correr_variante, VARIANTES))

    print(f"=== Transferencia · {REP} vidas · {VIDA} pasos por río ===")
    print(f"{'variante':<26}{'río':<22}{'fallos':>10}{'T1':>8}{'puente':>11}")
    resumen = {}
    for nombre in VARIANTES:
        r = resultados[nombre]
        fila(nombre, "1 (primer río)", r["rio1"])
        for clave in ("parecido", "distinto"):
            a = fila("", f"{clave} · con experiencia", r[f"{clave}_exp"])
            b = fila("", f"{clave} · sin experiencia", r[f"{clave}_nuevo"])
            resumen[(nombre, clave)] = (a, b)
        print()

    print("Fisher, puentes con vs sin experiencia (p < 0.05 = difícil que sea azar):")
    for (nombre, clave), (a, b) in resumen.items():
        print(f"  {nombre:<26}{clave:<10}{a:>3} vs {b:>3}   p = {fisher(a, b, REP):.3f}")
    sys.stdout.flush()
