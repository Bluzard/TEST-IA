"""Homeostato ultraestable (Ashby, 1952) frente a entornos desconocidos.

Sin objetivo, sin predicción, sin premio, sin sesgo:
  - El sistema tiene "variables esenciales": el estado de cada unidad propia
    debe quedarse en [-1, 1]. Esa es la única "necesidad".
  - Cuando una unidad sale de rango, su "uniselector" cambia AL AZAR sus
    conexiones (toda su fila). No sabe hacia dónde cambiar; solo cambia.
  - El entorno son unidades cuyas conexiones el sistema no puede tocar y
    que cambian sin aviso.

Pruebas:
  A. Capacidad: ¿llega a estabilizarse en entornos que nunca vio?
  B. Propia vs. pasiva: mismo sistema con conexiones congeladas.
  C. Memoria/generación: ¿vuelve más rápido a un entorno ya visto?
  D. Límites: ¿hasta qué tamaño sigue llegando?
"""
import argparse

import numpy as np

NIVELES = np.linspace(-1.0, 1.0, 25)  # posiciones del uniselector, como en Ashby
DT = 0.05
LIMITE = 1.0          # rango viable de las variables esenciales
SATURACION = 3.0      # tope físico de cualquier unidad
VENTANA_ESTABLE = 400  # pasos sin violaciones (con perturbaciones) = estabilizado
CADA_PERTURBACION = 60
FUERZA_PERTURBACION = 0.5


class Entorno:
    """Filas de la matriz que el sistema no controla."""

    def __init__(self, n_agente, n_entorno, fuerza, rng):
        n = n_agente + n_entorno
        self.filas = rng.normal(0, fuerza, (n_entorno, n))
        self.filas[:, n_agente:] -= 0.3 * np.eye(n_entorno)  # leve disipación propia


class Homeostato:
    def __init__(self, n_agente, n_entorno, rng, plastico=True):
        self.na, self.ne = n_agente, n_entorno
        self.rng = rng
        self.plastico = plastico
        self.W = rng.choice(NIVELES, (n_agente, n_agente + n_entorno))
        self.x = rng.uniform(-0.3, 0.3, n_agente + n_entorno)
        self.cambios = 0

    def vivir(self, entorno, max_pasos):
        """Corre hasta estabilizarse o agotar pasos. Devuelve (llegó, pasos, cambios)."""
        cambios_ini = self.cambios
        sin_violar = 0
        for t in range(1, max_pasos + 1):
            A = np.vstack([self.W, entorno.filas])
            self.x = np.clip(self.x + DT * (A @ self.x), -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self.x += self.rng.normal(0, FUERZA_PERTURBACION, self.x.size)

            fuera = np.abs(self.x[: self.na]) > LIMITE
            if fuera.any():
                sin_violar = 0
                if self.plastico:
                    for i in np.flatnonzero(fuera):
                        self.W[i] = self.rng.choice(NIVELES, self.W.shape[1])
                        self.cambios += 1
                    self.x[: self.na][fuera] *= 0.5  # el "relé" se dispara y amortigua
            else:
                sin_violar += 1
                if sin_violar >= VENTANA_ESTABLE:
                    return True, t, self.cambios - cambios_ini
        return False, max_pasos, self.cambios - cambios_ini


def estable_lineal(W, entorno):
    A = np.vstack([W, entorno.filas])
    return float(np.max(np.linalg.eigvals(A).real)) < 0


def prueba_a_b(n_entornos, presupuesto, fuerza, seed):
    print(f"\n=== A/B · {n_entornos} entornos nuevos (4 propias + 2 de entorno, fuerza {fuerza}) ===")
    for plastico in (True, False):
        llegan, cambios, lineal = 0, [], 0
        for k in range(n_entornos):
            rng = np.random.default_rng(seed * 10_000 + k)
            ent = Entorno(4, 2, fuerza, rng)
            h = Homeostato(4, 2, rng, plastico=plastico)
            ok, _, c = h.vivir(ent, presupuesto)
            llegan += ok
            lineal += ok and estable_lineal(h.W, ent)
            if ok:
                cambios.append(c)
        etiqueta = "homeostato (se reorganiza)" if plastico else "congelado (no se reorganiza)"
        med = f"{np.median(cambios):.0f}" if cambios else "-"
        print(f"{etiqueta:<30} llegan {llegan:3d}/{n_entornos}  "
              f"(estables de verdad: {lineal:3d})  reconfiguraciones mediana: {med}")


def prueba_c(seed, presupuesto, fuerza, vueltas=6):
    print("\n=== C · alternar entre dos entornos E1 y E2 (¿aprende de haberlos visto?) ===")
    filas = []
    for rep in range(10):
        rng = np.random.default_rng(seed * 777 + rep)
        e1, e2 = Entorno(4, 2, fuerza, rng), Entorno(4, 2, fuerza, rng)
        h = Homeostato(4, 2, rng)
        fila = []
        for v in range(vueltas):
            ok, _, c = h.vivir(e1 if v % 2 == 0 else e2, presupuesto)
            fila.append(c if ok else np.nan)
        filas.append(fila)
    m = np.array(filas, dtype=float)
    encabezado = "  ".join(f"{'E1' if v % 2 == 0 else 'E2'}#{v // 2 + 1:<3}" for v in range(vueltas))
    print("reconfiguraciones mediana por visita:")
    print("  " + encabezado)
    print("  " + "  ".join(f"{np.nanmedian(m[:, v]):6.0f}" for v in range(vueltas)))
    print(f"  visitas que no llegaron: {int(np.isnan(m).sum())}/{m.size}")


def prueba_d(seed, presupuesto, fuerza, n_entornos=40):
    print("\n=== D · límites: más unidades propias (mismo presupuesto) ===")
    for na in (2, 4, 6, 8, 10):
        llegan, cambios = 0, []
        for k in range(n_entornos):
            rng = np.random.default_rng(seed * 55_555 + na * 1000 + k)
            ok, _, c = Homeostato(na, 2, rng).vivir(Entorno(na, 2, fuerza, rng), presupuesto)
            llegan += ok
            if ok:
                cambios.append(c)
        med = f"{np.median(cambios):.0f}" if cambios else "-"
        print(f"  {na:2d} unidades propias: llegan {llegan:2d}/{n_entornos}  reconfiguraciones mediana: {med}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--presupuesto", type=int, default=60_000, help="pasos máximos por entorno")
    p.add_argument("--fuerza", type=float, default=0.8, help="fuerza del acople del entorno")
    a = p.parse_args()
    prueba_a_b(200, a.presupuesto, a.fuerza, a.seed)
    prueba_c(a.seed, a.presupuesto, a.fuerza)
    prueba_d(a.seed, a.presupuesto, a.fuerza)
