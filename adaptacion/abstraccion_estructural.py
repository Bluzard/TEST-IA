"""Frente #4: ¿abstrae el sujeto lo común entre dos puentes propios?

El sujeto («satisfecho 90 %» con piezas, sin plano al nacer) vive en el mundo 1
y luego en el mundo 2. Cada mundo re-mapea en secreto qué significa cada código
de pieza (qué canal siente un ancla, a qué canal empuja un apoyo y con qué
signo). Los puentes de dos mundos tienen entonces códigos distintos: copiar la
configuración concreta no sirve. La física del puente es la misma.

Lo que el sujeto guarda de cada éxito (configuración que alcanza el 90 %):
  un grafo de influencias con signo entre las variables que percibe del
  entorno (río R y piezas P; el cuerpo W queda fuera), estimado por mínimos
  cuadrados con su propia trayectoria. La firma es el conjunto de ciclos de
  largo ≥ 2, descritos por la secuencia de tipos (R/P) y el signo del lazo.

Abstracción = lo común (intersección) entre las firmas de sus éxitos.

Uso en el mundo 3 (sin predicción): la exploración sigue siendo al azar.
Cuando el arreglo presente contiene un ciclo con piezas que está en la
abstracción, esas piezas se bloquean y se abre una ventana de acoplamiento
(modo C, R_max 20) para el cuerpo. La abstracción solo decide a quién atribuir
el fallo: al cuerpo que aún no se acopla, no al arreglo.

Sesgos declarados: la representación (grafo con signo, ciclos, umbral
UMBRAL), que el sujeto distinga sus sensores de río de los de sus piezas, y
que solo los ciclos con piezas (lo que depende de él) cuenten para reconocer.

Condiciones en el mundo 3 (desde el mismo estado al terminar el mundo 2):
  sin_memoria       repertorio vacío
  concreta          conserva el repertorio W+P de los mundos 1 y 2
  abstraccion_2     repertorio vacío + reconocer con lo común a los mundos 1 y 2
  abstraccion_1     repertorio vacío + reconocer con la firma del mundo 1 sola
  firma_invertida   control: la abstracción de 2 con los signos invertidos
  firma_dada        techo de referencia: ciclo R→P→P negativo escrito a mano
  *_sin_agencia     sin el sesgo «solo cuenta lo que pasa por piezas»: la firma
                    incluye los ciclos del río y para reconocer el arreglo debe
                    contener TODA la abstracción. Lo accidental de cada río solo
                    se filtra comparando dos éxitos.

Uso:
  python adaptacion/abstraccion_estructural.py --rep 100
"""
import argparse
import copy
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from aspiracion import INTENTO
from atribucion_fallo import mcnemar, signo
from entorno_componible import Mundo, NA, NR, NP, N, ANCLAS, APOYOS, OPCIONES, Sujeto, puentes
from homeostato import DT, SATURACION, VENTANA_ESTABLE, Entorno
from homeostato_memoria import FUERZA
from prueba_larga_componible import BucleLargo

FASE_FUENTE = 100_000
FASE_DESTINO = 60_000
UMBRAL = 0.5          # |influencia| mínima para que exista una arista
MIN_DATOS = 25        # transiciones con el mismo arreglo para estimar su firma
R_MAX = 20
CONDICIONES = ("sin_memoria", "concreta", "abstraccion_2", "abstraccion_1", "firma_invertida", "firma_dada",
               "abstraccion_2_sin_agencia", "abstraccion_1_sin_agencia", "firma_invertida_sin_agencia")
TIPOS = ("R",) * NR + ("P",) * NP  # tipo de cada variable de entorno percibida


# ---------------------------------------------------------------- mundos
class MundoFamilia(Mundo):
    """Mundos con río propio y semántica de piezas re-mapeada en secreto."""

    cambios = {}

    def __init__(self, rng, n_mundos=3):
        super().__init__(rng)
        self.rios = [self.filas_rio] + [Entorno(NA, NR, FUERZA, rng).filas for _ in range(n_mundos - 1)]
        self.mapas = [[np.r_[0, 1 + rng.permutation(o - 1)] for o in OPCIONES] for _ in range(n_mundos)]
        self.ir(0)

    def ir(self, k):
        self.terreno, self.filas_rio, self.mapa = k, self.rios[k], self.mapas[k]

    def fisico(self, P):
        return np.array([m[p] for m, p in zip(self.mapa, P)])

    def matriz(self, W, P):
        return super().matriz(W, self.fisico(P))

    def puentes_de(self, P):
        return puentes(self.fisico(P))


# ---------------------------------------------------------------- firmas
def estimar(transiciones):
    """Filas de entorno de la dinámica, estimadas por mínimos cuadrados.

    Descarta transiciones con alguna variable en el tope: el recorte no es lineal.
    """
    tope = SATURACION - 1e-9
    limpias = [(a, b) for a, b in transiciones if np.all(np.abs(a) < tope) and np.all(np.abs(b) < tope)]
    if not limpias:
        return None
    X = np.array([np.r_[a, 1.0] for a, _ in limpias])
    Y = np.array([(b[NA:] - a[NA:]) / DT for a, b in limpias])
    if len(X) < MIN_DATOS:
        return None
    # Norma mínima: lo que nunca varió (pieza sin colocar, variables gemelas) no recibe influencia inventada.
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    return coef[NA:N].T  # (entorno destino, entorno origen)


def _canonico(tipos):
    rot = [tipos[i:] + tipos[:i] for i in range(len(tipos))]
    return min(rot)


def ciclos(A):
    """Ciclos simples dirigidos (largo ≥ 2) del grafo j→i si |A[i, j]| > UMBRAL.

    Devuelve [(rasgo, nodos)], rasgo = (tipos canónicos, signo del lazo).
    """
    n = A.shape[0]
    ady = [[i for i in range(n) if i != j and abs(A[i, j]) > UMBRAL] for j in range(n)]
    hallados = []

    def dfs(inicio, nodo, camino, signo_acum):
        for sig in ady[nodo]:
            s = signo_acum * np.sign(A[sig, nodo])
            if sig == inicio and len(camino) >= 2:
                hallados.append(((_canonico(tuple(TIPOS[v] for v in camino)), int(s)), tuple(camino)))
            elif sig > inicio and sig not in camino:
                dfs(inicio, sig, camino + [sig], s)

    for v in range(n):
        dfs(v, v, [v], 1.0)
    return hallados


def firma(A):
    return frozenset(r for r, _ in ciclos(A))


def con_piezas(rasgos):
    return frozenset(r for r in rasgos if "P" in r[0])


FIRMA_DADA = frozenset({(_canonico(("R", "P", "P")), -1)})


# ---------------------------------------------------------------- sujeto
class SujetoAbstraccion(BucleLargo):
    """Satisfecho 90 % con piezas, que guarda la firma de sus éxitos."""

    def __init__(self, rng):
        super().__init__(rng)
        self.firmas = {}          # índice del repertorio -> (firma, mundo, es_puente, logros)
        self.abstraccion = None   # rasgos usados para reconocer
        self.exigir_todo = False  # sin agencia: el arreglo debe contener toda la abstracción
        self.agotados = set()
        self.reconocimientos = 0
        self.ventanas = []
        self._trans, self._P_trans = [], None

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        self._mundo = mundo
        self._trans, self._P_trans = [], None
        return super().vivir(mundo, pasos, rng_perturbaciones)

    # ------------------------------------------------------------ percepción
    def _paso_fisico(self, x_antes):
        clave = tuple(self.P)
        if clave != self._P_trans:
            self._trans, self._P_trans = [], clave
        self._trans.append((x_antes, self.x.copy()))
        if len(self._trans) > 40 * MIN_DATOS:
            del self._trans[:len(self._trans) // 2]
        # Dos oportunidades por arreglo: si a los 25 pasos aún no hay datos limpios, a los 100.
        if len(self._trans) in (MIN_DATOS, 4 * MIN_DATOS) and self.abstraccion and self.ventana is None:
            self._reconocer()

    def _premiar(self, k):
        super()._premiar(k)
        if k not in self.firmas and self.tasa(k) >= self.aspiracion:
            A = estimar(self._trans)
            if A is not None:
                self.firmas[k] = [firma(A), self._mundo.terreno, self._hay_puente(self._mundo), 0]
        if k in self.firmas:
            self.firmas[k][3] = self.logros[k]

    def ejemplo(self, mundo):
        """El éxito más sostenido de ese mundo, según la propia experiencia."""
        cand = [v for v in self.firmas.values() if v[1] == mundo]
        return max(cand, key=lambda v: v[3]) if cand else None

    # ------------------------------------------------------------ reconocer
    def _reconocer(self, A=None):
        A = estimar(self._trans) if A is None else A
        if A is None:
            return
        presentes = ciclos(A)
        if self.exigir_todo and not self.abstraccion <= {r for r, _ in presentes}:
            return
        bloqueo = set()
        for rasgo, nodos in presentes:
            if rasgo in self.abstraccion:
                bloqueo.update(v - NR for v in nodos if TIPOS[v] == "P")
        if not bloqueo:
            return
        arreglo = frozenset((i, int(self.P[i])) for i in bloqueo)
        if arreglo in self.agotados:
            return
        self.reconocimientos += 1
        self.ventana = dict(arreglo=arreglo, bloqueo=sorted(bloqueo), presupuesto=R_MAX, mejor=0,
                            inicio=self._t, reconfiguraciones=0, renovaciones=0, pasos=0, origen="reconocido")

    def _acoplar(self, fuera, racha, mundo):
        v = self.ventana
        if racha > v["mejor"]:
            v["mejor"] = racha
            v["presupuesto"] = R_MAX
            v["renovaciones"] += 1
        if v["presupuesto"] == 0:
            self.agotados.add(v["arreglo"])
            self._cerrar_ventana("agotado")
            return False
        v["presupuesto"] -= 1
        v["reconfiguraciones"] += 1
        fijas = {i: self.P[i] for i in v["bloqueo"]}
        for i in np.flatnonzero(fuera):
            self._explorar_unidad(i, mundo)
        for i, codigo in fijas.items():
            self.P[i] = codigo
        return True

    def _cerrar_ventana(self, motivo):
        v, self.ventana = self.ventana, None
        self.ventanas.append(dict(inicio=v["inicio"], fin=self._t, motivo=motivo, origen=v.get("origen"),
                                  reconfiguraciones=v["reconfiguraciones"], renovaciones=v["renovaciones"]))

    def _medir(self, t, cae, saturado, hay_puente):
        super()._medir(t, cae, saturado, hay_puente)
        if self.ventana is not None and self._racha_v >= INTENTO:
            self._cerrar_ventana("acoplado")

    def olvidar_repertorio(self):
        for nombre in ("repertorio", "pesos", "exitos", "fallos", "rapida", "lenta", "intentos", "logros"):
            setattr(self, nombre, [])
        self.firmas = {}


# ---------------------------------------------------------------- experimento
def _fase(h, mundo, pasos, rng):
    caidas, frac, _ = h.vivir(mundo, pasos, rng)
    f = h.fases[0]
    return dict(rec_puente=f["rec_puente"], rec_estable=f["rec_estable"], episodios=f["episodios"],
                fraccion_genuino=frac, saturado_final=f["saturado_final"])


def preparar_destino(h, condicion, e1, e2):
    comun = e1[0] & e2[0] if e1 and e2 else None
    if condicion != "concreta":
        h.olvidar_repertorio()
    if condicion.endswith("_sin_agencia"):
        h.exigir_todo = True
        if condicion.startswith("abstraccion_2") and comun is not None:
            h.abstraccion = comun
        elif condicion.startswith("abstraccion_1") and e1:
            h.abstraccion = e1[0]
        elif condicion.startswith("firma_invertida") and comun is not None:
            h.abstraccion = frozenset((t, -s) for t, s in comun)
        return
    if condicion == "abstraccion_2" and comun is not None:
        h.abstraccion = con_piezas(comun)
    elif condicion == "abstraccion_1" and e1:
        h.abstraccion = con_piezas(e1[0])
    elif condicion == "firma_invertida" and comun is not None:
        h.abstraccion = frozenset((t, -s) for t, s in con_piezas(comun))
    elif condicion == "firma_dada":
        h.abstraccion = FIRMA_DADA


def ejecutar(semilla):
    mundo = MundoFamilia(np.random.default_rng(50_000 + semilla))
    h = SujetoAbstraccion(np.random.default_rng(60_000 + semilla))
    rng = np.random.default_rng(70_000 + semilla)
    fuente = []
    for k in (0, 1):
        mundo.ir(k)
        fuente.append(_fase(h, mundo, FASE_FUENTE, rng))
    e1, e2 = h.ejemplo(0), h.ejemplo(1)
    comun = e1[0] & e2[0] if e1 and e2 else None
    estado = (h, mundo, rng)
    destino = {}
    for c in CONDICIONES:
        hc, mc, rc = copy.deepcopy(estado)
        preparar_destino(hc, c, e1, e2)
        mc.ir(2)
        r = _fase(hc, mc, FASE_DESTINO, rc)
        r.update(abstraccion=sorted([list(t), s] for t, s in (hc.abstraccion or ())),
                 reconocimientos=hc.reconocimientos,
                 ventanas=len(hc.ventanas), acopladas=sum(v["motivo"] == "acoplado" for v in hc.ventanas),
                 agotadas=sum(v["motivo"] == "agotado" for v in hc.ventanas))
        destino[c] = r
    puente = (_canonico(("R", "P", "P")), -1)
    return dict(semilla=semilla, fuente=fuente,
                ejemplos=[None if e is None else dict(es_puente=bool(e[2]), logros=e[3], tiene_lazo_puente=puente in e[0],
                                                      rasgos=len(e[0]), con_piezas=len(con_piezas(e[0])))
                          for e in (e1, e2)],
                comun_tiene_lazo_puente=None if comun is None else puente in comun,
                comun_rasgos_con_piezas=len(con_piezas(comun)) if comun is not None else None,
                destino=destino)


# ---------------------------------------------------------------- informe
def informe(filas, rep):
    largo = FASE_DESTINO
    print(f"=== Abstracción estructural · {rep} vidas pareadas · fuente 2×{FASE_FUENTE} · destino {largo} · "
          f"umbral {UMBRAL} · R_max {R_MAX} ===\n")
    print("Fuentes (el sujeto, sin plano, en los mundos 1 y 2):")
    for k in (0, 1):
        con = sum(x["fuente"][k]["rec_puente"] is not None for x in filas)
        ej = [x["ejemplos"][k] for x in filas if x["ejemplos"][k]]
        print(f"  mundo {k + 1}: puente estable propio {con}/{rep}   éxito consolidado con firma {len(ej)}/{rep}"
              f"   ese éxito es un puente {sum(e['es_puente'] for e in ej)}/{len(ej)}"
              f"   su firma contiene el lazo R→P→P negativo {sum(e['tiene_lazo_puente'] for e in ej)}/{len(ej)}")
    dos = [x for x in filas if x["comun_rasgos_con_piezas"] is not None]
    print(f"  con dos éxitos: {len(dos)}/{rep}   lo común contiene el lazo de puente "
          f"{sum(x['comun_tiene_lazo_puente'] for x in dos)}/{len(dos)}   rasgos con piezas en lo común (mediana) "
          f"{np.median([x['comun_rasgos_con_piezas'] for x in dos]) if dos else float('nan'):.0f}\n")

    piezas = [x for x in dos if all(e["con_piezas"] for e in x["ejemplos"])]
    rio = lambda r: sum("P" not in t for t, _ in r)
    for c in ("abstraccion_1_sin_agencia", "abstraccion_2_sin_agencia"):
        print(f"  {c}: rasgos solo del río en la abstracción (mediana, vidas con dos éxitos con piezas) "
              f"{np.median([rio(x['destino'][c]['abstraccion']) for x in piezas]) if piezas else float('nan'):.0f}"
              f"   abstracciones sin ningún rasgo del río "
              f"{sum(rio(x['destino'][c]['abstraccion']) == 0 for x in piezas)}/{len(piezas)}")
    print()
    for titulo, sub in (("Todas las vidas (intención de tratar)", filas),
                        ("Solo vidas con dos éxitos propios", dos),
                        ("Solo vidas donde ambos éxitos usaron piezas", piezas)):
        n = len(sub)
        if not n:
            continue
        print(f"{titulo} — mundo 3 nuevo, {n} vidas:")
        print(f"{'condición':<28}{'puente estable':>15}{'pasos (med, éxitos)':>21}{'pasos (med, cens.)':>20}"
              f"{'caídas (med)':>14}{'% t. puente':>13}{'reconoc.':>10}{'acopladas':>11}")
        for c in CONDICIONES:
            d = [x["destino"][c] for x in sub]
            ok = [r["rec_puente"] for r in d if r["rec_puente"] is not None]
            cens = [largo if r["rec_puente"] is None else r["rec_puente"] for r in d]
            print(f"{c:<28}{len(ok):>10}/{n:<4}{(np.median(ok) if ok else float('nan')):>21.0f}{np.median(cens):>20.0f}"
                  f"{np.median([r['episodios'] for r in d]):>14.0f}{100 * np.mean([r['fraccion_genuino'] for r in d]):>12.1f}%"
                  f"{np.median([r['reconocimientos'] for r in d]):>10.0f}{np.median([r['acopladas'] for r in d]):>11.0f}")
        print("  Pareadas (signo sobre pasos censurados; McNemar sobre puente estable):")
        for a, b in (("sin_memoria", "abstraccion_2"), ("abstraccion_1", "abstraccion_2"),
                     ("firma_invertida", "abstraccion_2"), ("concreta", "abstraccion_2"),
                     ("sin_memoria", "concreta"), ("abstraccion_2", "firma_dada"),
                     ("sin_memoria", "abstraccion_2_sin_agencia"),
                     ("abstraccion_1_sin_agencia", "abstraccion_2_sin_agencia"),
                     ("firma_invertida_sin_agencia", "abstraccion_2_sin_agencia"),
                     ("abstraccion_2_sin_agencia", "abstraccion_1")):
            ta = [largo if x["destino"][a]["rec_puente"] is None else x["destino"][a]["rec_puente"] for x in sub]
            tb = [largo if x["destino"][b]["rec_puente"] is None else x["destino"][b]["rec_puente"] for x in sub]
            pa = [x["destino"][a]["rec_puente"] is not None for x in sub]
            pb = [x["destino"][b]["rec_puente"] is not None for x in sub]
            print(f"    {a:<27} vs {b:<26} B más rápida en {sum(y < z for z, y in zip(ta, tb)):>3}, más lenta en "
                  f"{sum(y > z for z, y in zip(ta, tb)):>3}  p = {signo(tb, ta):.3f}   puente {sum(pa)} vs {sum(pb)}"
                  f"  p = {mcnemar(pa, pb):.3f}")
        print()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--rep", type=int, default=100)
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--salida", type=Path, default=Path(__file__).with_name("resultados_abstraccion.json"))
    a = p.parse_args()
    with ProcessPoolExecutor() as ex:
        filas = list(ex.map(ejecutar, range(a.semilla, a.semilla + a.rep)))
    informe(filas, a.rep)
    a.salida.write_text(json.dumps(dict(rep=a.rep, semilla=a.semilla, umbral=UMBRAL, vidas=filas),
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Registros individuales: {a.salida}")


if __name__ == "__main__":
    main()
