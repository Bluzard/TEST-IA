"""Homeostato con memoria opcional.

La memoria es un repertorio, no una regla:
  - Cada vez que el sistema se estabiliza, guarda esa configuración (si es nueva).
  - Cuando una variable esencial sale de rango, con probabilidad `p_memoria`
    recuerda una configuración que ya le funcionó; si no, explora al azar
    como el homeostato original.
  - Lo que encuentra explorando también se guarda: el repertorio crece.

p_memoria = 0   -> homeostato original (sin memoria)
p_memoria = 1   -> memoria obligatoria (si hay recuerdos, siempre los usa)

Pruebas:
  C. Alternar E1/E2: ¿vuelve más rápido a lo ya vivido?
  E. Exaptación: tras vivir E1 y E2, ¿le sirve lo guardado frente a
     E3 (parecido a E1) y E4 (nada que ver)?
  F. ¿Sigue encontrando soluciones nuevas o se queda en las de siempre?
"""
import numpy as np

from homeostato import DT, LIMITE, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION, \
    FUERZA_PERTURBACION, NIVELES, Entorno

PRESUPUESTO = 60_000
FUERZA = 0.8
P_MEMORIA = (0.0, 0.3, 0.7, 1.0)
REPETICIONES = 20


class HomeostatoMemoria:
    def __init__(self, n_agente, n_entorno, rng, p_memoria):
        self.na = n_agente
        self.rng = rng
        self.p = p_memoria
        self.W = rng.choice(NIVELES, (n_agente, n_agente + n_entorno))
        self.x = rng.uniform(-0.3, 0.3, n_agente + n_entorno)
        self.repertorio: list[np.ndarray] = []

    def _guardar(self):
        if not any(np.allclose(self.W, m) for m in self.repertorio):
            self.repertorio.append(self.W.copy())

    def vivir(self, entorno, max_pasos=PRESUPUESTO):
        """Devuelve (llegó, reconfiguraciones, solución vino de memoria)."""
        cambios, sin_violar, desde_memoria = 0, 0, False
        for t in range(1, max_pasos + 1):
            A = np.vstack([self.W, entorno.filas])
            self.x = np.clip(self.x + DT * (A @ self.x), -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self.x += self.rng.normal(0, FUERZA_PERTURBACION, self.x.size)

            fuera = np.abs(self.x[: self.na]) > LIMITE
            if fuera.any():
                sin_violar = 0
                cambios += 1
                if self.repertorio and self.rng.random() < self.p:
                    # Opción disponible: algo que ya funcionó alguna vez
                    self.W = self.repertorio[self.rng.integers(len(self.repertorio))].copy()
                    desde_memoria = True
                else:
                    # Explorar: cambio al azar en las unidades que se salieron
                    for i in np.flatnonzero(fuera):
                        self.W[i] = self.rng.choice(NIVELES, self.W.shape[1])
                    desde_memoria = False
                self.x[: self.na][fuera] *= 0.5
            else:
                sin_violar += 1
                if sin_violar >= VENTANA_ESTABLE:
                    self._guardar()
                    return True, cambios, desde_memoria
        return False, cambios, desde_memoria


def variante(base: Entorno, ruido, rng):
    e = Entorno.__new__(Entorno)
    e.filas = base.filas + rng.normal(0, ruido, base.filas.shape)
    return e


def fmt(valores):
    v = [x for x in valores if not np.isnan(x)]
    return f"{np.median(v):6.0f}" if v else "     -"


def prueba_c():
    print("=== C · alternar E1/E2 tres veces: reconfiguraciones mediana por visita ===")
    print(f"{'memoria':<10}  E1#1    E2#1    E1#2    E2#2    E1#3    E2#3   no llegó   éxitos desde memoria")
    for p in P_MEMORIA:
        m, fallos, de_mem, exitos = [], 0, 0, 0
        for r in range(REPETICIONES):
            rng = np.random.default_rng(777 + r)
            e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
            h = HomeostatoMemoria(4, 2, rng, p)
            fila = []
            for v in range(6):
                ok, c, mem = h.vivir(e1 if v % 2 == 0 else e2)
                fila.append(c if ok else np.nan)
                fallos += not ok
                if ok and v >= 2:  # desde la segunda visita ya hay algo que recordar
                    exitos += 1
                    de_mem += mem
            m.append(fila)
        m = np.array(m, dtype=float)
        cols = "  ".join(fmt(m[:, v]) for v in range(6))
        pct = f"{100 * de_mem / exitos:5.0f} %" if exitos else "    -"
        print(f"{p:<10.0%}{cols}   {fallos:3d}/{m.size}     {pct}")


def prueba_e_f():
    print("\n=== E/F · tras vivir E1 y E2: entorno parecido (E3) y entorno nuevo (E4) ===")
    print(f"{'memoria':<10}{'E3 parecido':>14}{'E4 nuevo':>12}   {'E3 desde memoria':>17}"
          f"{'E4 desde memoria':>18}   {'soluciones guardadas':>21}")
    for p in P_MEMORIA:
        r3, r4, m3, m4, n3, n4, rep = [], [], 0, 0, 0, 0, []
        for r in range(REPETICIONES):
            rng = np.random.default_rng(31_337 + r)
            e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
            e3 = variante(e1, 0.25, rng)
            e4 = Entorno(4, 2, FUERZA, rng)
            for destino, res, es_e3 in ((e3, r3, True), (e4, r4, False)):
                h = HomeostatoMemoria(4, 2, np.random.default_rng(9_000 + r), p)
                h.vivir(e1)
                h.vivir(e2)
                ok, c, mem = h.vivir(destino)
                res.append(c if ok else np.nan)
                if ok and es_e3:
                    n3 += 1
                    m3 += mem
                elif ok:
                    n4 += 1
                    m4 += mem
                rep.append(len(h.repertorio))
        pm3 = f"{100 * m3 / n3:.0f} % de {n3}" if n3 else "-"
        pm4 = f"{100 * m4 / n4:.0f} % de {n4}" if n4 else "-"
        print(f"{p:<10.0%}{fmt(r3):>14}{fmt(r4):>12}   {pm3:>17}{pm4:>18}   {np.mean(rep):>21.1f}")


if __name__ == "__main__":
    prueba_c()
    prueba_e_f()
