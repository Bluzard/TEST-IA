"""Atribución del fallo: ¿cayó por el plano o por el cuerpo?

Problema (README_planos.md, «Límites»): con el castigo inmediato, la primera
caída tras cargar un plano externo le parte la confianza a la mitad en SQLite,
aunque el plano solo dice dónde van las piezas y el cuerpo (W) todavía no se
acopla a ellas. Además la exploración de la unidad caída re-sortea su pieza y
deshace el plano.

Regla (sin objetivo ni predicción; solo la necesidad interna):
  1. Al cargar un plano que deja el cuerpo sin especificar (plantilla externa),
     se bloquean sus posiciones especificadas y se abre una ventana de
     acoplamiento con presupuesto de R_max reconfiguraciones del cuerpo.
  2. En la ventana, cada caída dispara la reorganización habitual de W (y de las
     piezas NO especificadas), pero no toca la confianza del plano en SQLite.
  3. Se registra la mejor racha sin caer lograda con ese plano en esta vida. Si
     una racha la supera, el acoplamiento progresa y el presupuesto se renueva.
  4. Si se agota el presupuesto sin un intento completo (INTENTO pasos sin caer,
     el primer logro que cuenta hacia la aspiración del 90 %) ni nueva mejor
     racha, el fallo se atribuye al plano: castigo duro (confianza *= 0,5) y se
     libera para que la búsqueda siga con otra cosa.
  Con el primer logro la ventana se cierra y rige la evaluación normal.

Modos comparados:
  A inmediato       castigo en la primera caída (comportamiento actual)
  B paciencia_fija  ventana de R_max caídas, sin renovar por progreso
  C progreso        ventana que se renueva cuando mejora la mejor racha

Los planos propios (W completo) no abren ventana: ahí la caída sí es del plano.

Uso:
  python adaptacion/atribucion_fallo.py --rep 40 --vida 15000 --rmax 20
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from aspiracion import INTENTO
from aspiracion_100 import fisher
from biblioteca_planos import Biblioteca
from conocimiento_persistente import SujetoPersistente
from entorno_componible import Mundo, NA, NR, N, Sujeto, puentes
from experimento_planos import VARIANTES as CONDICIONES, plano_ejemplo
from homeostato import CADA_PERTURBACION, DT, LIMITE, SATURACION, VENTANA_ESTABLE
import puente

MODOS = ("inmediato", "paciencia_fija", "progreso")
NOMBRE_MODO = {"inmediato": "A castigo inmediato", "paciencia_fija": "B paciencia fija",
               "progreso": "C atribución por progreso"}
NOMBRE_CONDICION = {"sin_plano": "Ninguno", "correcto": "Plano correcto",
                    "incorrecto": "Plano incorrecto", "parcial": "Plano parcial"}
LETRA = {"inmediato": "A", "paciencia_fija": "B", "progreso": "C"}
R_MAX = 20


class BucleAtribucion(Sujeto):
    """Copia del bucle de Sujeto.vivir con dos puntos de decisión nuevos.

    En modo «inmediato» consume el azar en el mismo orden que el original y
    reproduce su trayectoria paso a paso (ver test_atribucion.py).
    """

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        rng_fisica = self.rng if rng_perturbaciones is None else rng_perturbaciones
        caidas, con_puente = [], 0
        actual, desde, sin_violar = None, 0, 0
        self.ventana = None
        A = mundo.matriz(self.W, self.P)
        hay_puente = bool(puentes(self.P))
        for t in range(1, pasos + 1):
            self._t = t
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
                fuera[:] = True
            if fuera.any():
                caidas.append(t)
                racha, sin_violar = sin_violar, 0
                if self.ventana is not None and self._acoplar(fuera, racha, mundo):
                    desde = t  # mismo plano, otro cuerpo: el intento vuelve a empezar
                else:
                    if actual is not None:
                        self._castigar(actual)
                        actual = None
                    if self.repertorio and self.rng.random() < self.p_recordar():
                        w = np.array([self._peso(k) for k in range(len(self.repertorio))])
                        actual = int(self.rng.choice(len(w), p=w / w.sum()))
                        self._cargar(self.repertorio[actual])
                        desde = t
                        self._abrir_ventana(actual)
                    else:
                        for i in np.flatnonzero(fuera):
                            self._explorar_unidad(i, mundo)
                self.x[:NA][fuera] *= 0.5
                A = mundo.matriz(self.W, self.P)
                hay_puente = bool(puentes(self.P))
            else:
                sin_violar += 1
                if self.ventana is not None:
                    self.ventana["pasos"] += 1
                if sin_violar == VENTANA_ESTABLE and actual is None:
                    self._guardar()
                    actual, desde = self._indice(), t
                if actual is not None and t - desde >= INTENTO:
                    self._premiar(actual)
                    desde = t
            con_puente += hay_puente
        if self.ventana is not None:
            self._cerrar_ventana("abierta_al_final")
        return caidas, con_puente / pasos, A


class SujetoAtribucion(SujetoPersistente, BucleAtribucion):
    """MRO: SujetoPersistente.vivir prepara la vida y su super() llega a BucleAtribucion."""

    def __init__(self, rng, biblioteca, modo="inmediato", r_max=R_MAX):
        if modo not in MODOS:
            raise ValueError(f"Modo desconocido: {modo}")
        super().__init__(rng, biblioteca)
        self.modo, self.r_max = modo, r_max

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        self.mejor_racha = {}
        self.registro = {}
        self.ventanas = []
        self._t = 0
        return super().vivir(mundo, pasos, rng_perturbaciones)

    # ------------------------------------------------------------ registro
    def _plantilla(self, k):
        """Plano que deja el cuerpo (W) sin especificar: hay que acoplarse a él."""
        return bool(np.isnan(self.repertorio[k][:NA * N]).any())

    def _reg(self, pid):
        return self.registro.setdefault(pid, dict(
            cargas=0, castigos=0, castigos_antes_de_logro=0, logros=0,
            t_primer_castigo=None, t_primer_logro=None,
            reconfiguraciones_en_ventana=0, renovaciones=0, pasos_en_ventana=0))

    def _premiar(self, k):
        if self._plantilla(k):
            r = self._reg(self.ids[k])
            r["logros"] += 1
            if r["t_primer_logro"] is None:
                r["t_primer_logro"] = self._t
            if self.ventana is not None and self.ventana["k"] == k:
                self._cerrar_ventana("acoplado")
        super()._premiar(k)

    def _castigar(self, k):
        if self._plantilla(k):
            r = self._reg(self.ids[k])
            r["castigos"] += 1
            r["castigos_antes_de_logro"] += r["logros"] == 0
            if r["t_primer_castigo"] is None:
                r["t_primer_castigo"] = self._t
        super()._castigar(k)

    # ------------------------------------------------------------ ventana
    def _abrir_ventana(self, k):
        if not self._plantilla(k):
            return
        pid = self.ids[k]
        self._reg(pid)["cargas"] += 1
        if self.modo == "inmediato":
            return
        clave = self._clave_racha(pid)
        self.ventana = dict(k=k, pid=pid, clave=clave, presupuesto=self.r_max,
                            mejor=self.mejor_racha.get(clave, 0),
                            bloqueo=~np.isnan(self.repertorio[k]),
                            inicio=self._t, reconfiguraciones=0, renovaciones=0, pasos=0)

    def _clave_racha(self, pid):
        """La mejor racha es de este plano en esta vida (subclases: también por contexto)."""
        return pid

    def _cerrar_ventana(self, motivo):
        v, self.ventana = self.ventana, None
        r = self._reg(v["pid"])
        r["reconfiguraciones_en_ventana"] += v["reconfiguraciones"]
        r["renovaciones"] += v["renovaciones"]
        r["pasos_en_ventana"] += v["pasos"]
        self.ventanas.append(dict(pid=v["pid"], inicio=v["inicio"], fin=self._t, motivo=motivo,
                                  reconfiguraciones=v["reconfiguraciones"],
                                  renovaciones=v["renovaciones"], mejor_racha=v["mejor"]))

    def _acoplar(self, fuera, racha, mundo):
        """True: el cuerpo se reorganiza con el plano fijo. False: el fallo es del plano."""
        v = self.ventana
        if racha > v["mejor"]:
            v["mejor"] = self.mejor_racha[v["clave"]] = racha
            if self.modo == "progreso":
                v["presupuesto"] = self.r_max
                v["renovaciones"] += 1
        if v["presupuesto"] == 0:
            self._cerrar_ventana("agotado")
            return False
        v["presupuesto"] -= 1
        v["reconfiguraciones"] += 1
        for i in np.flatnonzero(fuera):
            self._explorar_unidad(i, mundo)
        # Lo que el plano especifica queda bloqueado; el resto sigue libre.
        c = self._config()
        plano = self.repertorio[v["k"]]
        c[v["bloqueo"]] = plano[v["bloqueo"]]
        Sujeto._cargar(self, c)
        return True


# ---------------------------------------------------------------- experimento
def ejecutar(tarea):
    semilla, vida, condicion, modo, r_max = tarea
    with Biblioteca(":memory:") as b:
        externo = b.guardar(plano_ejemplo(condicion), origen="externo") if condicion != "sin_plano" else None
        # Mismas semillas que experimento_planos.ejecutar: terreno, cuerpo y perturbaciones pareados.
        mundo = Mundo(np.random.default_rng(50_000 + semilla))
        h = SujetoAtribucion(np.random.default_rng(60_000 + semilla), b, modo, r_max)
        caidas, fraccion, _ = h.vivir(mundo, vida, np.random.default_rng(70_000 + semilla))
        reg = h.registro.get(externo) if externo is not None else None
        confianza = b.evidencia(externo, h.contexto)[2] if externo is not None else None
        return dict(semilla=semilla, condicion=condicion, modo=modo, r_max=r_max,
                    episodios_caida=len(puente.episodios(caidas)), pasos_con_caida=len(caidas),
                    primer_puente_estable=h.primer_puente_estable,
                    fraccion_con_puente=fraccion, puente_final=bool(puentes(h.P)),
                    plano_cargado=bool(reg and reg["cargas"]), plano=reg,
                    confianza_final_plano=confianza,
                    ventanas=[w for w in h.ventanas if w["pid"] == externo])


def mcnemar(a, b):
    """p bilateral exacta sobre pares discordantes (vidas pareadas por semilla)."""
    n01 = sum(x and not y for x, y in zip(a, b))
    n10 = sum(y and not x for x, y in zip(a, b))
    n = n01 + n10
    if n == 0:
        return 1.0
    from math import comb
    k = min(n01, n10)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def signo(a, b):
    """Prueba de signo pareada (empates fuera)."""
    menor = sum(x < y for x, y in zip(a, b))
    mayor = sum(x > y for x, y in zip(a, b))
    return mcnemar([True] * menor + [False] * mayor, [False] * menor + [True] * mayor)


def resumir(filas, rep):
    res = {}
    for c in CONDICIONES:
        for m in MODOS:
            d = sorted((x for x in filas if x["condicion"] == c and x["modo"] == m), key=lambda x: x["semilla"])
            cargadas = [x for x in d if x["plano_cargado"]]
            prem = [x["plano"]["castigos_antes_de_logro"] > 0 for x in cargadas]
            res[(c, m)] = dict(
                filas=d, puente=sum(x["primer_puente_estable"] is not None for x in d),
                caidas=float(np.median([x["episodios_caida"] for x in d])),
                tiempo=100 * float(np.mean([x["fraccion_con_puente"] for x in d])),
                cargadas=len(cargadas), prematuro=sum(prem),
                nunca_logro=sum(x["plano"]["logros"] == 0 for x in cargadas),
                confianza=float(np.median([x["confianza_final_plano"] for x in d])) if c != "sin_plano" else None)
    return res


def informe(res, rep, vida, r_max):
    print(f"=== Atribución del fallo · {rep} vidas pareadas · {vida} pasos · R_max = {r_max} ===\n")
    print(f"{'condición':<17}{'modo':<27}{'puente estable':>15}{'caídas (med)':>14}{'% t. puente':>12}"
          f"{'descarte prem.':>16}{'nunca logró':>13}{'confianza med':>15}")
    for c in CONDICIONES:
        for m in MODOS:
            r = res[(c, m)]
            prem = f"{r['prematuro']}/{r['cargadas']}" if c != "sin_plano" else "—"
            nunca = f"{r['nunca_logro']}/{r['cargadas']}" if c != "sin_plano" else "—"
            conf = f"{r['confianza']:.3f}" if r["confianza"] is not None else "—"
            print(f"{NOMBRE_CONDICION[c]:<17}{NOMBRE_MODO[m]:<27}{r['puente']:>10}/{rep:<4}{r['caidas']:>14.1f}"
                  f"{r['tiempo']:>11.1f}%{prem:>16}{nunca:>13}{conf:>15}")
        print()
    print("Pruebas pareadas por semilla (McNemar exacto para puente estable; signo para caídas):")
    for c in CONDICIONES[1:]:
        for a, b in (("inmediato", "progreso"), ("inmediato", "paciencia_fija"), ("paciencia_fija", "progreso")):
            fa, fb = res[(c, a)]["filas"], res[(c, b)]["filas"]
            pa = [x["primer_puente_estable"] is not None for x in fa]
            pb = [x["primer_puente_estable"] is not None for x in fb]
            ca = [x["episodios_caida"] for x in fa]
            cb = [x["episodios_caida"] for x in fb]
            menos, mas = sum(y < x for x, y in zip(ca, cb)), sum(y > x for x, y in zip(ca, cb))
            print(f"  {NOMBRE_CONDICION[c]:<17}{LETRA[a]} vs {LETRA[b]}:  puente {sum(pa):>2} vs {sum(pb):>2}"
                  f"  p = {mcnemar(pa, pb):.3f}   caídas de {LETRA[b]}: menos en {menos}, más en {mas}"
                  f"  p = {signo(cb, ca):.3f}")
    print("\nFisher no pareado (referencia del laboratorio), puente estable:")
    for c in CONDICIONES[1:]:
        a, b = res[(c, "inmediato")]["puente"], res[(c, "progreso")]["puente"]
        print(f"  {NOMBRE_CONDICION[c]:<17}A {a:>2} vs C {b:>2}   p = {fisher(a, b, rep):.3f}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--rep", type=int, default=40)
    p.add_argument("--vida", type=int, default=15_000)
    p.add_argument("--rmax", type=int, default=R_MAX)
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--salida", type=Path, default=Path(__file__).with_name("resultados_atribucion.json"))
    a = p.parse_args()
    if a.rep < 1 or a.vida < 256 or a.rmax < 1 or a.semilla < 0:
        p.error("rep >= 1, vida >= 256, rmax >= 1, semilla >= 0")
    tareas = [(a.semilla + r, a.vida, c, m, a.rmax) for r in range(a.rep) for c in CONDICIONES for m in MODOS]
    with ProcessPoolExecutor() as ex:
        filas = list(ex.map(ejecutar, tareas, chunksize=4))
    res = resumir(filas, a.rep)
    informe(res, a.rep, a.vida, a.rmax)
    a.salida.write_text(json.dumps(dict(rep=a.rep, vida=a.vida, r_max=a.rmax, vidas=filas),
                                   ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"\nRegistros individuales: {a.salida}")


if __name__ == "__main__":
    main()
