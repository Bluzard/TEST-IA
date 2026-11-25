"""Paso 1: limpiar el experimento base. Saturar el entorno cuenta como caída.

Antes, cerca de un tercio de los sujetos se sostenía llevando las variables
del entorno a su tope físico ("rompiendo el río"). Aquí se repite la prueba
del puente (100 vidas) con y sin esa regla, y se mide si el puente es
GENUINO: último tramo sin caídas, sin entorno saturado y con la
configuración final estable de verdad (margen > 0).
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato import SATURACION
from homeostato_memoria import FUERZA
from aspiracion import Aspiracion
from aspiracion_100 import Satisfecho, fisher
import puente

REP = 100
VARIANTES = ("caos (sin memoria)", "tu regla + castigo duro", "aspiración 90 %", "satisfecho 90 %")


def crear(nombre, rng):
    if nombre == "caos (sin memoria)":
        return puente.SinMemoria(4, 2, rng)
    if nombre == "tu regla + castigo duro":
        return Aspiracion(4, 2, rng)
    if nombre == "aspiración 90 %":
        return Aspiracion(4, 2, rng, 0.90)
    return Satisfecho(4, 2, rng, 0.90)


def correr(tarea):
    nombre, regla = tarea
    tramo = puente.VIDA // puente.TRAMOS
    filas = []
    for r in range(REP):
        rio = puente.Rio(4, 2, FUERZA, np.random.default_rng(4_242 + r))
        h = crear(nombre, np.random.default_rng(6_000 + r))
        h.saturacion_es_caida = regla
        ep = puente.episodios(h.vivir(rio, puente.VIDA, hasta_estable=False))
        ultimo = int(np.sum(ep > puente.VIDA - tramo))
        saturado = bool(np.any(np.abs(h.x[h.na:]) >= SATURACION - 1e-6))
        margen = puente.margen(h, rio)
        filas.append(dict(caidas=len(ep), ultimo=ultimo, puente=ultimo == 0, saturado=saturado,
                          estable=margen > 0, genuino=(ultimo == 0) and not saturado and margen > 0))
    return tarea, filas


if __name__ == "__main__":
    tareas = [(n, regla) for regla in (False, True) for n in VARIANTES]
    with ProcessPoolExecutor(max_workers=len(tareas)) as ex:
        res = dict(ex.map(correr, tareas))

    print(f"=== Puente · {REP} vidas · saturar el entorno ¿cuenta como caída? ===")
    print(f"{'variante':<26}{'regla':<8}{'caídas':>8}{'T6':>6}{'puente':>9}{'saturado':>10}"
          f"{'estable':>9}{'genuino':>9}")
    genuinos = {}
    for regla in (False, True):
        for n in VARIANTES:
            d = res[(n, regla)]
            g = sum(x["genuino"] for x in d)
            genuinos[(n, regla)] = g
            print(f"{n:<26}{'sí' if regla else 'no':<8}{np.median([x['caidas'] for x in d]):>8.0f}"
                  f"{np.median([x['ultimo'] for x in d]):>6.0f}{sum(x['puente'] for x in d):>5}/{REP}"
                  f"{sum(x['saturado'] for x in d):>6}/{REP}{sum(x['estable'] for x in d):>5}/{REP}"
                  f"{g:>5}/{REP}")
        print()
    sys.stdout.flush()

    print("Fisher, puentes genuinos con la regla (p < 0.05 = difícil que sea azar):")
    con = [n for n in VARIANTES]
    for i, a in enumerate(con):
        for b in con[i + 1:]:
            ga, gb = genuinos[(a, True)], genuinos[(b, True)]
            print(f"  {a:<24} vs {b:<24} {ga:>3} vs {gb:>3}   p = {fisher(ga, gb, REP):.3f}")
