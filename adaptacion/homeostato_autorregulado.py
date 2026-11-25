"""Homeostato con memoria autorregulada.

Nadie fija cuánto usar la memoria. La misma necesidad (variables esenciales
dentro de rango) regula también la forma de usar lo recordado:
  - Cada recuerdo tiene un peso. Se recuerda en proporción a los pesos.
  - Si tras recordar algo el sistema se sostiene PRUEBA_RECUERDO pasos sin
    salirse de rango, ese recuerdo gana peso (+1).
  - Si se sale antes, pierde la mitad: "saltar no sirve en este río".
  - Probabilidad de recordar en vez de explorar = w_max / (w_max + 1):
    si los recuerdos fallan aquí, explora; si sirven, los usa.

Se compara contra: sin memoria, memoria fija al 30 % y memoria obligatoria.
"""
import numpy as np

from homeostato import DT, LIMITE, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION, \
    FUERZA_PERTURBACION, NIVELES, Entorno
from homeostato_memoria import HomeostatoMemoria, variante, fmt, PRESUPUESTO, FUERZA

PRUEBA_RECUERDO = 200
REP_C = 20
REP_E = 40


class HomeostatoAutorregulado:
    def __init__(self, n_agente, n_entorno, rng, castigo=0.5, prueba=PRUEBA_RECUERDO, conteo=False):
        """conteo=True: sin constantes. Cada recuerdo lleva éxitos y fallos;
        su peso es (éxitos+1)/(éxitos+fallos+2) y "éxito" es llegar a la
        estabilidad (la definición de la necesidad), no una ventana fija."""
        self.na = n_agente
        self.rng = rng
        self.castigo = castigo
        self.prueba = VENTANA_ESTABLE if conteo else prueba
        self.conteo = conteo
        self.W = rng.choice(NIVELES, (n_agente, n_agente + n_entorno))
        self.x = rng.uniform(-0.3, 0.3, n_agente + n_entorno)
        self.repertorio: list[np.ndarray] = []
        self.pesos: list[float] = []
        self.exitos: list[int] = []
        self.fallos: list[int] = []

    def _peso(self, k):
        if self.conteo:
            return (self.exitos[k] + 1) / (self.exitos[k] + self.fallos[k] + 2)
        return self.pesos[k]

    def _premiar(self, k):
        if self.conteo:
            self.exitos[k] += 1
        else:
            self.pesos[k] += 1.0

    def _castigar(self, k):
        if self.conteo:
            self.fallos[k] += 1
        else:
            self.pesos[k] *= self.castigo

    def p_recordar(self):
        if not self.repertorio:
            return 0.0
        w = max(self._peso(k) for k in range(len(self.repertorio)))
        return w if self.conteo else w / (w + 1.0)

    # Si es True, que una variable del entorno llegue a su tope físico también
    # cuenta como caída ("romper el río"), y se reorganizan todas las unidades.
    saturacion_es_caida = False

    def _fuera(self):
        fuera = np.abs(self.x[: self.na]) > LIMITE
        if self.saturacion_es_caida and np.any(np.abs(self.x[self.na:]) >= SATURACION - 1e-9):
            fuera = np.ones(self.na, dtype=bool)
        return fuera

    def _explorar(self, fuera):
        """Cambio al azar de las conexiones de las unidades que se salieron."""
        for i in np.flatnonzero(fuera):
            self.W[i] = self.rng.choice(NIVELES, self.W.shape[1])

    def _guardar(self):
        for i, m in enumerate(self.repertorio):
            if np.allclose(self.W, m):
                return
        self.repertorio.append(self.W.copy())
        self.pesos.append(1.0)
        self.exitos.append(0)
        self.fallos.append(0)

    def _perturbar(self, entorno):
        perturbar = getattr(entorno, "perturbar", None)
        if perturbar is not None:
            self.x += perturbar(self.rng, self.x.size)
        else:
            self.x += self.rng.normal(0, FUERZA_PERTURBACION, self.x.size)

    def vivir(self, entorno, max_pasos=PRESUPUESTO, hasta_estable=True):
        """hasta_estable=False: vive los max_pasos completos en el entorno
        (no se detiene al estabilizarse) y devuelve los pasos con fallo."""
        cambios, sin_violar, desde_memoria = 0, 0, False
        en_prueba = None  # (índice del recuerdo, paso en que se recordó)
        pasos_con_fallo = []
        empuje = getattr(entorno, "empuje", None)  # fuerza sostenida opcional del entorno
        for t in range(1, max_pasos + 1):
            A = np.vstack([self.W, entorno.filas])
            dx = A @ self.x if empuje is None else A @ self.x + empuje(self.rng)
            self.x = np.clip(self.x + DT * dx, -SATURACION, SATURACION)
            if t % CADA_PERTURBACION == 0:
                self._perturbar(entorno)

            fuera = self._fuera()
            if fuera.any():
                if not hasta_estable:
                    pasos_con_fallo.append(t)
                if en_prueba is not None:  # el recuerdo no sostuvo: aquí no sirve
                    self._castigar(en_prueba[0])
                    en_prueba = None
                sin_violar = 0
                cambios += 1
                if self.repertorio and self.rng.random() < self.p_recordar():
                    w = np.array([self._peso(k) for k in range(len(self.repertorio))])
                    k = int(self.rng.choice(len(w), p=w / w.sum()))
                    self.W = self.repertorio[k].copy()
                    en_prueba = (k, t)
                    desde_memoria = True
                else:
                    self._explorar(fuera)
                    desde_memoria = False
                self.x[: self.na][fuera] *= 0.5
            else:
                sin_violar += 1
                if en_prueba is not None and t - en_prueba[1] >= self.prueba:
                    self._premiar(en_prueba[0])  # sostuvo: sigue a mano
                    en_prueba = None
                if sin_violar == VENTANA_ESTABLE:
                    self._guardar()
                    if hasta_estable:
                        return True, cambios, desde_memoria
        if not hasta_estable:
            return pasos_con_fallo
        return False, cambios, desde_memoria


VARIANTES = (
    ("sin memoria", lambda rng: HomeostatoMemoria(4, 2, rng, 0.0)),
    ("fija 30 %", lambda rng: HomeostatoMemoria(4, 2, rng, 0.3)),
    ("obligatoria", lambda rng: HomeostatoMemoria(4, 2, rng, 1.0)),
    ("autorregulada", lambda rng: HomeostatoAutorregulado(4, 2, rng)),
)


def prueba_c():
    print(f"=== C · alternar E1/E2 tres veces ({REP_C} repeticiones): reconfiguraciones mediana ===")
    print(f"{'memoria':<15} E1#1    E2#1    E1#2    E2#2    E1#3    E2#3   no llegó")
    for nombre, crear in VARIANTES:
        m, fallos = [], 0
        for r in range(REP_C):
            rng = np.random.default_rng(777 + r)
            e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
            h = crear(rng)
            fila = []
            for v in range(6):
                ok, c, _ = h.vivir(e1 if v % 2 == 0 else e2)
                fila.append(c if ok else np.nan)
                fallos += not ok
            m.append(fila)
        m = np.array(m, dtype=float)
        print(f"{nombre:<15}" + "  ".join(fmt(m[:, v]) for v in range(6)) + f"   {fallos:3d}/{m.size}")


def prueba_e_f():
    print(f"\n=== E/F · tras vivir E1 y E2 ({REP_E} repeticiones) ===")
    print(f"{'memoria':<15}{'E3 parecido':>12}{'llega':>8}{'E4 nuevo':>11}{'llega':>8}"
          f"{'E4 desde memoria':>19}{'soluciones':>12}")
    for nombre, crear in VARIANTES:
        res = {3: [], 4: []}
        llega = {3: 0, 4: 0}
        mem4, rep = 0, []
        for r in range(REP_E):
            rng = np.random.default_rng(31_337 + r)
            e1, e2 = Entorno(4, 2, FUERZA, rng), Entorno(4, 2, FUERZA, rng)
            destinos = {3: variante(e1, 0.25, rng), 4: Entorno(4, 2, FUERZA, rng)}
            for k, destino in destinos.items():
                h = crear(np.random.default_rng(9_000 + r))
                h.vivir(e1)
                h.vivir(e2)
                ok, c, mem = h.vivir(destino)
                res[k].append(c if ok else np.nan)
                llega[k] += ok
                if k == 4 and ok:
                    mem4 += mem
                rep.append(len(h.repertorio))
        pm4 = f"{100 * mem4 / llega[4]:.0f} %" if llega[4] else "-"
        print(f"{nombre:<15}{fmt(res[3]):>12}{llega[3]:>5}/{REP_E}{fmt(res[4]):>11}{llega[4]:>5}/{REP_E}"
              f"{pm4:>19}{np.mean(rep):>12.1f}")


if __name__ == "__main__":
    prueba_c()
    prueba_e_f()
