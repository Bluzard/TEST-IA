"""Entorno componible: el río ofrece piezas con física propia.

Sin LLM, sin objetivo, sin premio. Rige solo la necesidad interna del
núcleo "satisfecho 90 %" (aspiración + fallo reciente + castigo duro +
repertorio que se apaga al estar satisfecho). Saturar el río o las piezas
cuenta como caída.

Estado: [agente (NA) | río (NR) | piezas (NP)]

Piezas (el sujeto no sabe qué son ni para qué sirven):
  - ancla a:  ancla' = -D·ancla + G·río[j]            (si está puesta sobre j)
  - apoyo b:  apoyo' = -D·apoyo + G·ancla[f]          (si está puesto)
              río[j] += signo·G·apoyo                 (signo + o -)

"Puente" = un apoyo con signo negativo que se alimenta de un ancla puesta
sobre la misma parte del río que él empuja: frena al río desde el río. Una
pieza sola no hace nada; armadas mal pueden desestabilizar.

"Saltar" = sostener el río solo con las conexiones internas del sujeto.

Cómo actúa el sujeto: ve el estado de las piezas (sus conexiones las
incluyen). Cada unidad propia tiene a cargo una pieza: cuando cae, cambia al
azar sus conexiones Y la colocación de su pieza. La memoria guarda la
configuración completa (conexiones + piezas).

Uso:
  python adaptacion/entorno_componible.py --calibrar
  python adaptacion/entorno_componible.py --rep 100 --vida 300000 [--cambio]
"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato import DT, LIMITE, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION, NIVELES, Entorno
from homeostato_memoria import FUERZA
from aspiracion import INTENTO
from aspiracion_100 import Satisfecho, fisher
import puente

NA, NR = 4, 2
ANCLAS, APOYOS = 2, 2
NP = ANCLAS + APOYOS
N = NA + NR + NP
D, G = 5.0, 4.0  # piezas rápidas: con D=1 el lazo del puente reaccionaba tarde y oscilaba
FUERZA_CRECIDA = 0.3  # calibrado: saltar aguanta ~81 % de las crecidas, el puente ~98 %
OPCIONES = [NR + 1] * ANCLAS + [NR * ANCLAS * 2 + 1] * APOYOS  # 0 = sin colocar


def decodificar_apoyo(v):
    """v > 0 -> (parte del río que empuja, ancla de la que se alimenta, signo)."""
    v -= 1
    return v // (ANCLAS * 2), (v // 2) % ANCLAS, (1 if v % 2 == 0 else -1)


def puentes(P):
    """Partes del río que tienen un puente armado."""
    hechos = set()
    for b in range(APOYOS):
        v = P[ANCLAS + b]
        if v > 0:
            j, f, s = decodificar_apoyo(v)
            if s < 0 and P[f] == j + 1:
                hechos.add(j)
    return hechos


class Mundo:
    def __init__(self, rng, con_piezas=True):
        self.filas_rio = Entorno(NA, NR, FUERZA, rng).filas  # (NR, NA+NR)
        self.con_piezas = con_piezas
        self.restante = 0
        self.direccion = np.zeros(NA + NR)

    def matriz(self, W, P):
        A = np.zeros((N, N))
        A[:NA] = W
        A[NA:NA + NR, :NA + NR] = self.filas_rio
        base = NA + NR
        for a in range(ANCLAS):
            ia = base + a
            A[ia, ia] = -D
            if P[a] > 0:
                A[ia, NA + P[a] - 1] = G
        for b in range(APOYOS):
            ib = base + ANCLAS + b
            A[ib, ib] = -D
            v = P[ANCLAS + b]
            if v > 0:
                j, f, s = decodificar_apoyo(v)
                A[ib, base + f] = G
                A[NA + j, ib] += s * G
        return A

    def empuje(self, rng):
        if self.restante == 0 and rng.random() < 1 / puente.CADA_CRECIDA:
            self.restante = puente.DURACION_CRECIDA
            self.direccion = np.zeros(NA + NR)  # la crecida es del río: al sujeto le llega por lo que siente
            self.direccion[NA:] = rng.normal(0, FUERZA_CRECIDA, NR)
        if self.restante > 0:
            self.restante -= 1
            return self.direccion
        return None


class Sujeto(Satisfecho):
    """Núcleo "satisfecho 90 %" cuya configuración incluye la colocación de piezas."""

    def __init__(self, rng, memoria=True):
        super().__init__(NA, NR + NP, rng, 0.90)
        self.memoria = memoria
        self.P = np.zeros(NP, dtype=int)
        self.x = rng.uniform(-0.3, 0.3, N)

    # la configuración completa es W + P, aplanada
    def _config(self):
        return np.concatenate([self.W.ravel(), self.P.astype(float)])

    def _cargar(self, c):
        self.W = c[: NA * N].reshape(NA, N).copy()
        self.P = c[NA * N:].astype(int)

    def _guardar(self):
        W = self.W
        self.W = self._config()
        super()._guardar()
        self.W = W

    def _indice(self):
        c = self._config()
        for k, m in enumerate(self.repertorio):
            if np.allclose(c, m):
                return k
        return None

    def p_recordar(self):
        return super().p_recordar() if self.memoria else 0.0

    def _explorar_unidad(self, i, mundo):
        self.W[i] = self.rng.choice(NIVELES, N)
        if mundo.con_piezas:
            self.P[i] = self.rng.integers(OPCIONES[i])

    def _observar(self, t):
        """Punto de extensión para memoria perceptiva, sin cambiar el control original."""

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        rng_fisica = self.rng if rng_perturbaciones is None else rng_perturbaciones
        caidas, con_puente = [], 0
        actual, desde, sin_violar = None, 0, 0
        A = mundo.matriz(self.W, self.P)
        hay_puente = bool(puentes(self.P))
        for t in range(1, pasos + 1):
            dx = A @ self.x
            emp = mundo.empuje(rng_fisica)
            if emp is not None:
                dx[: NA + NR] += emp
            self.x = np.clip(self.x + DT * dx, -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self.x[: NA + NR] += rng_fisica.normal(0, puente.PERTURBACION_NORMAL, NA + NR)

            self._observar(t)

            fuera = np.abs(self.x[:NA]) > LIMITE
            if np.any(np.abs(self.x[NA:]) >= SATURACION - 1e-9):
                fuera[:] = True  # romper el río o las piezas también es caer
            if fuera.any():
                caidas.append(t)
                sin_violar = 0
                if actual is not None:
                    self._castigar(actual)
                    actual = None
                if self.repertorio and self.rng.random() < self.p_recordar():
                    w = np.array([self._peso(k) for k in range(len(self.repertorio))])
                    actual = int(self.rng.choice(len(w), p=w / w.sum()))
                    self._cargar(self.repertorio[actual])
                    desde = t
                else:
                    for i in np.flatnonzero(fuera):
                        self._explorar_unidad(i, mundo)
                self.x[:NA][fuera] *= 0.5
                A = mundo.matriz(self.W, self.P)
                hay_puente = bool(puentes(self.P))
            else:
                sin_violar += 1
                if sin_violar == VENTANA_ESTABLE and actual is None:
                    self._guardar()
                    actual, desde = self._indice(), t
                if actual is not None and t - desde >= INTENTO:
                    self._premiar(actual)
                    desde = t
            con_puente += hay_puente
        return caidas, con_puente / pasos, A


# ---------------------------------------------------------------- calibración
def calibrar(muestras=20_000, crecidas=50):
    """¿Existen "saltos" (~75-85 %) y "puentes" (>= 90 %)?

    Para configuraciones al azar estables, mide qué fracción de crecidas
    aguanta (desplazamiento estacionario de las variables propias < 1 y del
    río/piezas bajo saturación), sin piezas y con un puente armado.
    """
    rng = np.random.default_rng(1)
    P_puente = np.array([1, 2, 1 + 0 * 4 + 0 * 2 + 1, 1 + 1 * 4 + 1 * 2 + 1])  # puentes en las 2 partes
    assert puentes(P_puente) == {0, 1}
    for etiqueta, P in (("sin piezas (saltar)", np.zeros(NP, dtype=int)), ("con puente armado", P_puente)):
        estables, tasas = 0, []
        for _ in range(muestras):
            mundo = Mundo(rng)
            W = rng.choice(NIVELES, (NA, N))
            A = mundo.matriz(W, P)
            if np.max(np.linalg.eigvals(A).real) >= 0:
                continue
            estables += 1
            ok = 0
            for _ in range(crecidas):
                b = np.zeros(N)
                b[NA:NA + NR] = rng.normal(0, FUERZA_CRECIDA, NR)
                x = np.linalg.solve(A, -b)
                ok += np.max(np.abs(x[:NA])) < LIMITE and np.max(np.abs(x[NA:])) < SATURACION
            tasas.append(ok / crecidas)
        t = np.array(tasas)
        print(f"{etiqueta:<22} estables al azar {estables:>5}/{muestras}   "
              f"aguantan crecidas: mediana {np.median(t):.0%}   "
              f"saltos (75-89 %) {np.mean((t >= .75) & (t < .9)):.0%}   robustas (>=90 %) {np.mean(t >= .9):.0%}")


# ---------------------------------------------------------------- pruebas
VARIANTES = ("sin piezas (ajuste ciego)", "caos con piezas", "satisfecho con piezas")


def correr(tarea):
    nombre, rep, vida, cambio = tarea
    tramo = vida // puente.TRAMOS
    filas = []
    for r in range(rep):
        rng_mundo = np.random.default_rng(50_000 + r)
        mundo = Mundo(rng_mundo, con_piezas=nombre != "sin piezas (ajuste ciego)")
        h = Sujeto(np.random.default_rng(60_000 + r), memoria=nombre != "caos con piezas")
        caidas, frac_puente, A = h.vivir(mundo, vida)
        ep = puente.episodios(caidas)
        ultimo = int(np.sum(ep > vida - tramo))
        saturado = bool(np.any(np.abs(h.x[NA:]) >= SATURACION - 1e-6))
        estable = float(np.max(np.linalg.eigvals(A).real)) < 0
        fila = dict(caidas=len(ep), ultimo=ultimo, genuino=ultimo == 0 and not saturado and estable,
                    frac_puente=frac_puente, puente_final=bool(puentes(h.P)))
        if cambio:
            P_antes = h.P.copy()
            mundo.filas_rio = Entorno(NA, NR, FUERZA, rng_mundo).filas  # terreno nuevo, mismas piezas
            caidas2, frac2, A2 = h.vivir(mundo, vida)
            ep2 = puente.episodios(caidas2)
            fila.update(caidas2=len(ep2), ultimo2=int(np.sum(ep2 > vida - tramo)),
                        t1_2=int(np.sum(ep2 <= tramo)), frac_puente2=frac2,
                        conservo=bool(puentes(P_antes)) and bool(puentes(P_antes) & puentes(h.P)))
        filas.append(fila)
    return nombre, filas


def informe(res, rep, cambio):
    print(f"{'variante':<28}{'caídas':>8}{'últ. tramo':>11}{'genuinos':>10}{'% tiempo con puente':>21}"
          f"{'puente al final':>17}")
    for n in VARIANTES:
        d = res[n]
        print(f"{n:<28}{np.median([x['caidas'] for x in d]):>8.0f}{np.median([x['ultimo'] for x in d]):>11.0f}"
              f"{sum(x['genuino'] for x in d):>6}/{rep}{100 * np.mean([x['frac_puente'] for x in d]):>20.0f}%"
              f"{sum(x['puente_final'] for x in d):>13}/{rep}")
    g = {n: sum(x["genuino"] for x in res[n]) for n in VARIANTES}
    print("\nFisher, puentes genuinos:")
    for i, a in enumerate(VARIANTES):
        for b in VARIANTES[i + 1:]:
            print(f"  {a:<28} vs {b:<28} {g[a]:>3} vs {g[b]:>3}   p = {fisher(g[a], g[b], rep):.3f}")
    if cambio:
        print("\nTras cambiar el terreno (mismas piezas, río nuevo):")
        print(f"{'variante':<28}{'caídas':>8}{'1er tramo':>11}{'últ. tramo':>11}{'% tiempo con puente':>21}"
              f"{'conservó su puente':>20}")
        for n in VARIANTES:
            d = res[n]
            con = [x for x in d if x["puente_final"]]
            print(f"{n:<28}{np.median([x['caidas2'] for x in d]):>8.0f}{np.median([x['t1_2'] for x in d]):>11.0f}"
                  f"{np.median([x['ultimo2'] for x in d]):>11.0f}{100 * np.mean([x['frac_puente2'] for x in d]):>20.0f}%"
                  f"{sum(x['conservo'] for x in con):>14}/{len(con)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--calibrar", action="store_true")
    p.add_argument("--rep", type=int, default=20)
    p.add_argument("--vida", type=int, default=100_000)
    p.add_argument("--cambio", action="store_true", help="cambiar el terreno a mitad de vida")
    a = p.parse_args()
    if a.calibrar:
        calibrar()
        sys.exit()
    with ProcessPoolExecutor(max_workers=len(VARIANTES)) as ex:
        res = dict(ex.map(correr, [(n, a.rep, a.vida, a.cambio) for n in VARIANTES]))
    print(f"=== Entorno componible · {a.rep} vidas · {a.vida} pasos{' + cambio de terreno' if a.cambio else ''} ===")
    informe(res, a.rep, a.cambio)
