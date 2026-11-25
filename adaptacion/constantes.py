"""Prueba 1: ¿las constantes de la memoria autorregulada importan, y se pueden quitar?

Compara:
  - castigo (cuánto pierde un recuerdo que falla) x prueba (pasos para contar
    como éxito), todas las combinaciones;
  - "conteo": sin esas constantes (éxitos y fallos por recuerdo, el éxito es
    llegar a estabilizarse);
  - memoria fija 30 % como referencia de velocidad.

Además reporta p_recordar al final: qué tan probable es que el sistema
recurra a lo conocido en vez de explorar, después de mucha experiencia.
Si tiende a 1, deja de explorar: nadie inventa el puente.
"""
import sys

import numpy as np

from homeostato import Entorno
from homeostato_memoria import HomeostatoMemoria, variante, fmt, FUERZA
from homeostato_autorregulado import HomeostatoAutorregulado

REP_C = 20
REP_E = 40


def variantes():
    v = [("fija 30 %", lambda rng: HomeostatoMemoria(4, 2, rng, 0.3))]
    for castigo in (0.5, 0.8, 0.95):
        for prueba in (100, 200, 400):
            v.append((f"c={castigo} p={prueba}",
                      lambda rng, c=castigo, p=prueba: HomeostatoAutorregulado(4, 2, rng, c, p)))
    v.append(("conteo (sin const.)", lambda rng: HomeostatoAutorregulado(4, 2, rng, conteo=True)))
    return v


def evaluar(crear):
    # C: alternar E1/E2
    m, fallos_c, p_final = [], 0, []
    for r in range(REP_C):
        rng = np.random.default_rng(777 + r)
        e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
        h = crear(rng)
        fila = []
        for v in range(6):
            ok, c, _ = h.vivir(e1 if v % 2 == 0 else e2)
            fila.append(c if ok else np.nan)
            fallos_c += not ok
        m.append(fila)
        p_final.append(h.p_recordar() if hasattr(h, "p_recordar") else h.p)
    m = np.array(m, dtype=float)
    revisitas = fmt(m[:, 2:].ravel())

    # E/F: entorno parecido y nuevo tras vivir E1 y E2
    llega3 = llega4 = 0
    c3, c4 = [], []
    for r in range(REP_E):
        rng = np.random.default_rng(31_337 + r)
        e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
        e3, e4 = variante(e1, 0.25, rng), Entorno(4, 2, FUERZA, rng)
        for destino, lista, es3 in ((e3, c3, True), (e4, c4, False)):
            h = crear(np.random.default_rng(9_000 + r))
            h.vivir(e1)
            h.vivir(e2)
            ok, c, _ = h.vivir(destino)
            lista.append(c if ok else np.nan)
            if es3:
                llega3 += ok
            else:
                llega4 += ok
    return revisitas, fallos_c, m.size, fmt(c3), llega3, fmt(c4), llega4, float(np.mean(p_final))


if __name__ == "__main__":
    print(f"{'variante':<21}{'revisitas':>10}{'no llegó C':>12}{'E3':>8}{'llega':>7}"
          f"{'E4':>8}{'llega':>7}{'p_recordar final':>18}")
    for nombre, crear in variantes():
        rv, fc, nc, e3, l3, e4, l4, p = evaluar(crear)
        print(f"{nombre:<21}{rv:>10}{fc:>7}/{nc}{e3:>8}{l3:>4}/{REP_E}{e4:>8}{l4:>4}/{REP_E}{p:>18.2f}")
        sys.stdout.flush()
