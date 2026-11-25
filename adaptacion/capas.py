"""Paso 2: un mundo que exige cooperación. ¿Surge la organización sola?

  - Unidades periféricas: tocan el río (el entorno las ve y ellas lo ven) y
    pueden frenarse a sí mismas (controlan su propia autoconexión).
  - Unidades internas: no tocan el río y tienen una autoexcitación fija
    (+INTRINSECO) que no pueden cambiar. Solas se disparan: solo pueden
    mantenerse en rango acoplándose con otras.
  - Saturar el entorno cuenta como caída (paso 1).

Variantes (cómo se reorganiza una unidad que se sale de rango):
  aislado (control)   nadie se conecta con nadie: debería fallar siempre
  completo            todas las conexiones presentes; rehace la fila al azar
  libre               rehace la fila; cada conexión presente o ausente al azar
  poda gradual        cambia UNA conexión: si existe, la poda o le cambia el
                      valor; si no existe, la hace crecer. La estructura se
                      conserva entre caídas.

Se mide, en los que llegan: densidad por tipo de conexión, si cada unidad
interna quedó conectada (directa o indirectamente) con alguna periférica y
el tamaño medio de los grupos.
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato import NIVELES, Entorno
from homeostato_memoria import FUERZA
from homeostato_autorregulado import HomeostatoAutorregulado

N_ENTORNO = 2
INTRINSECO = 0.05
PRESUPUESTO = 200_000
REP = 40
TAMANOS = ((2, 2), (3, 3))  # (periféricas, internas)
MODOS = ("aislado (control)", "completo", "libre", "poda gradual")


class Capas(HomeostatoAutorregulado):
    saturacion_es_caida = True

    def __init__(self, n_per, n_int, rng, modo):
        self.np_, self.ni = n_per, n_int
        super().__init__(n_per + n_int, N_ENTORNO, rng)
        self.modo = modo
        na, n = self.na, self.na + N_ENTORNO
        self.mascara = np.zeros((na, n), dtype=bool)
        if modo == "aislado (control)":
            for i in range(n_per):
                self.mascara[i, i] = True
                self.mascara[i, na:] = True
        else:
            self.mascara[:n_per, :] = True                 # periféricas: todo
            self.mascara[n_per:, :na] = True                # internas: solo unidades propias
            for i in range(n_per, na):
                self.mascara[i, i] = False                  # ...pero no su autoconexión
        self.W = np.zeros((na, n))
        for i in range(na):
            self._rehacer(i, presencia=0.5 if modo in ("libre", "poda gradual") else 1.0)
        for i in range(n_per, na):
            self.W[i, i] = INTRINSECO

    def p_recordar(self):
        return 0.0

    def _opcionales(self, i):
        """Conexiones entre unidades propias distintas (las que pueden estar o no)."""
        return [j for j in np.flatnonzero(self.mascara[i]) if j < self.na and j != i]

    def _rehacer(self, i, presencia):
        permitidas = np.flatnonzero(self.mascara[i])
        self.W[i, permitidas] = self.rng.choice(NIVELES, permitidas.size)
        if presencia < 1.0:
            opc = self._opcionales(i)
            self.W[i, opc] *= self.rng.random(len(opc)) < presencia

    def _explorar(self, fuera):
        for i in np.flatnonzero(fuera):
            if self.modo == "poda gradual":
                permitidas = np.flatnonzero(self.mascara[i])
                if permitidas.size == 0:
                    continue
                j = self.rng.choice(permitidas)
                opcional = j < self.na and j != i
                if opcional and self.W[i, j] != 0 and self.rng.random() < 0.5:
                    self.W[i, j] = 0.0                       # poda
                else:
                    self.W[i, j] = self.rng.choice(NIVELES)  # crece o cambia valor
            else:
                self._rehacer(i, presencia=0.5 if self.modo == "libre" else 1.0)


def entorno_capas(n_per, n_int, rng):
    e = Entorno(n_per + n_int, N_ENTORNO, FUERZA, rng)
    e.filas[:, n_per:n_per + n_int] = 0.0  # el río no ve a las internas
    return e


def estructura(h):
    na, p = h.na, h.np_
    adj = h.W[:, :na] != 0
    np.fill_diagonal(adj, False)

    def dens(filas, cols):
        sub = adj[np.ix_(filas, cols)]
        posibles = sum(1 for i in filas for j in cols if i != j)
        return sub.sum() / posibles if posibles else np.nan

    per, inte = list(range(p)), list(range(p, na))
    und = adj | adj.T
    # componentes conexas
    grupo = -np.ones(na, dtype=int)
    g = 0
    for s in range(na):
        if grupo[s] >= 0:
            continue
        pila = [s]
        grupo[s] = g
        while pila:
            u = pila.pop()
            for v in np.flatnonzero(und[u]):
                if grupo[v] < 0:
                    grupo[v] = g
                    pila.append(v)
        g += 1
    tam = np.bincount(grupo)
    internas_ok = np.mean([any(grupo[i] == grupo[j] for j in per) for i in inte])
    return dict(pp=dens(per, per), pi=dens(per, inte), ip=dens(inte, per), ii=dens(inte, inte),
                internas_ok=internas_ok, grupo=float(np.mean(tam)), n_grupos=g)


def correr(tarea):
    (n_per, n_int), modo = tarea
    llegan, est = 0, []
    for k in range(REP):
        rng = np.random.default_rng(12_345 + 100 * n_per + k)
        ent = entorno_capas(n_per, n_int, rng)
        h = Capas(n_per, n_int, rng, modo)
        ok, _, _ = h.vivir(ent, PRESUPUESTO)
        # "Llega" solo si además la configuración final es estable de verdad:
        # una interna aislada se aleja tan lento que puede pasar 400 pasos en rango.
        ok = ok and float(np.max(np.linalg.eigvals(np.vstack([h.W, ent.filas])).real)) < 0
        llegan += ok
        if ok:
            est.append(estructura(h))
    return tarea, llegan, est


if __name__ == "__main__":
    tareas = [(t, m) for t in TAMANOS for m in MODOS]
    with ProcessPoolExecutor(max_workers=len(tareas)) as ex:
        res = {t: (l, e) for t, l, e in ex.map(correr, tareas)}

    print(f"=== Capas · {REP} repeticiones · presupuesto {PRESUPUESTO} pasos · autoexcitación interna +{INTRINSECO} ===")
    print("Densidad de conexiones por tipo (fila recibe de columna): P←P, P←I, I←P, I←I")
    print(f"{'tamaño':<9}{'modo':<20}{'llegan':>8}{'P←P':>7}{'P←I':>7}{'I←P':>7}{'I←I':>7}"
          f"{'internas unidas a periférica':>30}{'grupos':>8}{'tam. grupo':>11}")
    for t in TAMANOS:
        for m in MODOS:
            llegan, est = res[(t, m)]

            def media(c):
                v = [e[c] for e in est if not np.isnan(e[c])]
                return f"{np.mean(v):.0%}" if v else "-"

            ng = f"{np.mean([e['n_grupos'] for e in est]):.1f}" if est else "-"
            tg = f"{np.mean([e['grupo'] for e in est]):.1f}" if est else "-"
            print(f"{t[0]}P+{t[1]}I{'':<4}{m:<20}{llegan:>5}/{REP}{media('pp'):>7}{media('pi'):>7}"
                  f"{media('ip'):>7}{media('ii'):>7}{media('internas_ok'):>30}{ng:>8}{tg:>11}")
        print()
    sys.stdout.flush()
