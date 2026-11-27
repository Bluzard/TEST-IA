"""Prueba larga de integración y sostenibilidad del sistema componible.

Sistema completo: «satisfecho 90 %» + entorno componible + biblioteca SQLite +
atribución del fallo (modo C). Vidas largas con cambios de terreno sin aviso.

Reglas (sin objetivo ni predicción; rige la necesidad interna):
  - Saturar el río o las piezas es caer, también dentro de la ventana.
  - El terreno cambia cada VIDA/5 pasos siguiendo RECORRIDO (nuevo, nuevo,
    revisita, nuevo, revisita). El sujeto no recibe aviso: solo siente.
  - Detectar inestabilidad = caer tras al menos VENTANA_ESTABLE pasos sin
    caer. Desde ahí observa VENTANA_CONTEXTO pasos del río y calcula la huella.
    Si cae a menos de RADIO (RMS) de un contexto conocido, es ese contexto;
    si no, uno nuevo. Mientras observa, el contexto es incierto: sus éxitos y
    caídas no se anotan en SQLite (no se puede indexar evidencia sin índice).
  - Al cambiar de contexto, el repertorio se reconstruye con la evidencia de
    ese contexto (local o de vecinos) y los planos externos. El cuerpo actual
    se conserva. La mejor racha de la ventana se indexa por (plano, contexto).
  - Modo C, R_max = 20, solo para planos que dejan W abierto; la ventana se
    cierra con el primer intento completo. El éxito consolidado guarda en el
    repertorio la realización concreta (W acoplado + piezas).

Condiciones (pareadas por semilla: mismos terrenos, crecidas y cuerpo inicial):
  1 sin_piezas     Satisfecho 90 % sin piezas ni SQLite
  2 A_fijo         componible, castigo inmediato, una huella al nacer (como hoy)
  2b A_contexto    ablación: castigo inmediato + repertorio contextual
  3 C_contexto     componible completo: modo C + repertorio contextual
Las condiciones componibles reciben al nacer el plano externo de piezas
(por defecto «correcto»: es estructural, vale para cualquier terreno).

Medición con oráculo (solo para medir, el sujeto nunca lo ve): fase y terreno.

Hallazgos que condicionan la lectura (ver README_prueba_larga.md):
  - La huella mide el estado acoplado sujeto+río, tomado justo después de una
    caída, no el río solo. Reconoce mal: 52 % de revisitas con RADIO 0,15.
  - La moratoria (no anotar evidencia mientras el contexto es incierto) es,
    en la práctica, una ventana de acoplamiento implícita para TODO plano,
    también los propios. Ablación «*_sin_moratoria»: explica < 1 de los 6
    puntos que el contexto le suma a A; sí reduce el descarte prematuro en
    revisita (A 47 %→22 %, C 38 %→6 %).
  - Los % con puente de las condiciones componibles son condicionales a tener
    en la biblioteca un plano de piezas válido (--plano correcto).

Uso:
  python adaptacion/prueba_larga_componible.py --calibrar
  python adaptacion/prueba_larga_componible.py --rep 100 --vida 300000
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from aspiracion import INTENTO
from atribucion_fallo import BucleAtribucion, SujetoAtribucion, mcnemar, signo
from biblioteca_planos import Biblioteca
from conocimiento_persistente import VERSION, VENTANA_CONTEXTO, huella_contexto, validar_concreto
from entorno_componible import Mundo, Sujeto, NA, NR, puentes
from experimento_planos import VARIANTES as PLANOS, plano_ejemplo
from homeostato import CADA_PERTURBACION, DT, LIMITE, SATURACION, VENTANA_ESTABLE, Entorno
from homeostato_memoria import FUERZA
import puente

VIDA = 300_000
RECORRIDO = (0, 1, 0, 2, 1)
RADIO = 0.15  # calibrado con --calibrar en semillas 1000-1019: reconoce 61 % de pares del mismo terreno, confunde 29 %
R_MAX = 20
CONDICIONES = ("sin_piezas", "A_fijo", "A_contexto", "C_contexto")
NOMBRE = {"sin_piezas": "1 Sin piezas / sin SQLite", "A_fijo": "2 Componible modo A",
          "A_contexto": "2b A + contexto (ablación)", "C_contexto": "3 Componible completo C"}
CONFIG = {"A_fijo": ("inmediato", False), "A_contexto": ("inmediato", True),
          "C_contexto": ("progreso", True),
          # ablación de la ablación: contexto sin moratoria (se castiga en el contexto viejo mientras observa)
          "A_contexto_sin_moratoria": ("inmediato", True), "C_contexto_sin_moratoria": ("progreso", True)}


class MundoCambiante(Mundo):
    """Terrenos generados al nacer con el mismo rng; se alternan sin aviso."""

    def __init__(self, rng, vida, con_piezas=True, recorrido=RECORRIDO):
        super().__init__(rng, con_piezas)
        self.terrenos = [self.filas_rio] + [Entorno(NA, NR, FUERZA, rng).filas
                                            for _ in range(max(recorrido))]
        largo = vida // len(recorrido)
        self.cambios = {1 + largo * i: terreno for i, terreno in enumerate(recorrido) if i}
        self.terreno = recorrido[0]

    def cambio_en(self, t):
        nuevo = self.cambios.get(t)
        if nuevo is not None:
            self.terreno, self.filas_rio = nuevo, self.terrenos[nuevo]
        return nuevo


class BucleLargo(BucleAtribucion):
    """Bucle de Sujeto.vivir + cambios de terreno + contexto + medición.

    Sin cambios de terreno ni recontextualización reproduce el bucle original.
    """
    ventana = None

    # ganchos: por defecto, sin ventana ni contexto (sujeto base)
    def _abrir_ventana(self, k):
        """Sujeto base: no hay planos externos ni ventana."""

    def _inestabilidad(self, t):
        """Sujeto base: no identifica contextos."""

    def _paso_fisico(self, x_antes):
        """Gancho: estado antes y después de la física (sin perturbación ni caída)."""

    def _hay_puente(self, mundo):
        # Oráculo de medición: un mundo puede re-mapear códigos de pieza a física.
        return bool(getattr(mundo, "puentes_de", puentes)(self.P))

    def _clave(self, k):
        return k

    def _completo(self, k):
        return not np.isnan(self.repertorio[k]).any()

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        rng_fisica = self.rng if rng_perturbaciones is None else rng_perturbaciones
        self._iniciar_medicion(mundo)
        caidas = []
        actual, desde, sin_violar = None, 0, 0
        self.ventana = None
        self._contexto_nuevo = False
        A = mundo.matriz(self.W, self.P)
        hay_puente = self._hay_puente(mundo)
        for t in range(1, pasos + 1):
            self._t = t
            if t in mundo.cambios:
                self._cerrar_fase(mundo, t - 1, caidas)
                mundo.cambio_en(t)
                self._abrir_fase(mundo, t)
                A = mundo.matriz(self.W, self.P)
            dx = A @ self.x
            emp = mundo.empuje(rng_fisica)
            if emp is not None:
                dx[: NA + NR] += emp
            x_antes = self.x
            self.x = np.clip(self.x + DT * dx, -SATURACION, SATURACION)
            self._paso_fisico(x_antes)
            if t % CADA_PERTURBACION == 0:
                self.x[: NA + NR] += rng_fisica.normal(0, puente.PERTURBACION_NORMAL, NA + NR)

            self._observar(t)
            if self._contexto_nuevo:  # el repertorio cambió: los índices viejos no valen
                self._contexto_nuevo = False
                if self.ventana is not None:
                    self._cerrar_ventana("cambio_contexto")
                actual = None

            fuera = np.abs(self.x[:NA]) > LIMITE
            saturado = bool(np.any(np.abs(self.x[NA:]) >= SATURACION - 1e-9))
            if saturado:
                fuera[:] = True
            cae = bool(fuera.any())
            self._medir(t, cae, saturado, hay_puente)
            if cae:
                caidas.append(t)
                racha, sin_violar = sin_violar, 0
                if racha >= VENTANA_ESTABLE:
                    self._inestabilidad(t)
                if self.ventana is not None and self._acoplar(fuera, racha, mundo):
                    desde = t
                else:
                    if actual is not None:
                        self._castigar(actual)
                        actual = None
                    if self.repertorio and self.rng.random() < self.p_recordar():
                        w = np.array([self._peso(k) for k in range(len(self.repertorio))])
                        actual = int(self.rng.choice(len(w), p=w / w.sum()))
                        self._cargar(self.repertorio[actual])
                        desde = t
                        self._evento("carga", actual)
                        self._abrir_ventana(actual)
                    else:
                        for i in np.flatnonzero(fuera):
                            self._explorar_unidad(i, mundo)
                self.x[:NA][fuera] *= 0.5
                A = mundo.matriz(self.W, self.P)
                hay_puente = self._hay_puente(mundo)
            else:
                sin_violar += 1
                if self.ventana is not None:
                    self.ventana["pasos"] += 1
                if sin_violar == VENTANA_ESTABLE and actual is None:
                    self._guardar()
                    actual, desde = self._indice(), t
                    if actual is not None:
                        self._evento("carga", actual)
                if actual is not None and t - desde >= INTENTO:
                    self._premiar(actual)
                    desde = t
        if self.ventana is not None:
            self._cerrar_ventana("abierta_al_final")
        self._cerrar_fase(mundo, pasos, caidas)
        return caidas, self.tiempo_genuino / pasos, A

    # ------------------------------------------------------------ medición
    def _iniciar_medicion(self, mundo):
        self.fases, self._consolidados = [], {}
        self.tiempo_genuino = self.tiempo_saturado = 0
        self._abrir_fase(mundo, 1)

    def _abrir_fase(self, mundo, t):
        revisita = any(f["terreno"] == mundo.terreno for f in self.fases)
        self.fases.append(dict(terreno=mundo.terreno, inicio=t, revisita=revisita,
                               rec_estable=None, rec_puente=None,
                               consolidados=sorted(self._consolidados.get(mundo.terreno, ())) if revisita else [],
                               seguimiento={}))
        self._racha_v = self._racha_p = 0

    def _cerrar_fase(self, mundo, t, caidas):
        f = self.fases[-1]
        f["fin"] = t
        tramo = (t - f["inicio"] + 1) // puente.TRAMOS
        ep = puente.episodios([c for c in caidas if f["inicio"] <= c <= t])
        sat = bool(np.any(np.abs(self.x[NA:]) >= SATURACION - 1e-6))
        estable = float(np.max(np.linalg.eigvals(mundo.matriz(self.W, self.P)).real)) < 0
        f.update(episodios=len(ep), saturado_final=sat, puente_final=self._hay_puente(mundo),
                 genuino_final=int(np.sum(ep > t - tramo)) == 0 and not sat and estable and self._hay_puente(mundo),
                 contexto_final=getattr(self, "contexto", None))
        f["seguimiento"] = {str(k): v for k, v in f["seguimiento"].items()}
        if not f["revisita"]:
            # Consolidados: configuraciones completas propias sobre la aspiración al terminar la visita.
            self._consolidados[f["terreno"]] = {self._clave(k) for k in range(len(self.repertorio))
                                                if self._completo(k) and self.tasa(k) >= self.aspiracion}

    def _medir(self, t, cae, saturado, hay_puente):
        f = self.fases[-1]
        genuino = hay_puente and not cae
        self.tiempo_genuino += genuino
        self.tiempo_saturado += saturado
        self._racha_v = 0 if cae else self._racha_v + 1
        self._racha_p = self._racha_p + 1 if genuino else 0
        if f["rec_estable"] is None and self._racha_v >= VENTANA_ESTABLE:
            f["rec_estable"] = t - f["inicio"] + 1
        if f["rec_puente"] is None and self._racha_p >= VENTANA_ESTABLE:
            f["rec_puente"] = t - f["inicio"] + 1

    def _evento(self, tipo, k):
        f = self.fases[-1]
        if not f["revisita"]:
            return
        clave = self._clave(k)
        if clave not in f["consolidados"]:
            return
        s = f["seguimiento"].setdefault(clave, dict(cargado=False, primero=None))
        if tipo == "carga":
            s["cargado"] = True
        elif s["cargado"] and s["primero"] is None:
            s["primero"] = tipo  # "castigo" antes de "logro" = descarte prematuro


class SujetoBase(BucleLargo):
    """Condición 1: satisfecho 90 % sin piezas ni biblioteca."""

    def _premiar(self, k):
        self._evento("logro", k)
        super()._premiar(k)

    def _castigar(self, k):
        self._evento("castigo", k)
        super()._castigar(k)


class SujetoLargo(SujetoAtribucion, BucleLargo):
    """MRO: SujetoAtribucion → SujetoPersistente → BucleLargo → BucleAtribucion → Sujeto."""

    def __init__(self, rng, biblioteca, modo, recontextualizar, r_max=R_MAX, radio=RADIO, moratoria=True):
        super().__init__(rng, biblioteca, modo, r_max)
        self.recontextualizar, self.radio, self.moratoria = recontextualizar, radio, moratoria

    def vivir(self, mundo, pasos, rng_perturbaciones=None):
        self._obs = []
        self.contextos_vistos, self.huellas = [], []
        return super().vivir(mundo, pasos, rng_perturbaciones)

    def _clave(self, k):
        return self.ids[k]

    def _clave_racha(self, pid):
        return (pid, self.contexto) if self.recontextualizar else pid

    def _incierto(self):
        return self.moratoria and self.recontextualizar and self._obs is not None and self.contexto is not None

    # ------------------------------------------------------------ contexto
    def _inestabilidad(self, t):
        if self.recontextualizar and self._obs is None:
            self._obs = []

    def _observar(self, t):
        if self._obs is None:
            return
        self._obs.append(self.x[NA:NA + NR].copy())
        if len(self._obs) == VENTANA_CONTEXTO:
            huella = huella_contexto(self._obs)
            self._obs = None
            self._fijar_contexto(huella, t)

    def _identificar(self, huella):
        if not self.recontextualizar:
            return self.biblioteca.contexto(huella, VERSION)
        cerca = self.biblioteca.cercanos(huella, VERSION, limite=1, radio=self.radio)
        return cerca[0][0] if cerca else self.biblioteca.contexto(huella, VERSION)

    def _fijar_contexto(self, huella, t):
        self.huellas.append(dict(t=t, terreno=None, huella=huella.tolist()))
        ctx = self._identificar(huella)
        if ctx == self.contexto:
            return
        if self.contexto is not None:
            for nombre in ("repertorio", "pesos", "exitos", "fallos", "rapida", "lenta",
                           "intentos", "logros", "ids", "scores"):
                setattr(self, nombre, [])
            self._contexto_nuevo = True
        self.contexto, self.huella = ctx, huella
        self.contextos_vistos.append((t, ctx))
        for c in self.biblioteca.candidatos(huella, VERSION, ctx):
            self._agregar(validar_concreto(c["contenido"]),
                          c["id"], c["stats"], c["score"] / max(c["stats"][2], 1e-3))
        self.recuperados = len(self.ids)

    # ------------------------------------------------------------ evidencia
    def _premiar(self, k):
        if self._incierto():
            return
        self._evento("logro", k)
        super()._premiar(k)

    def _castigar(self, k):
        if self._incierto():
            return
        self._evento("castigo", k)
        super()._castigar(k)

    def _guardar(self):
        if not self._incierto():
            super()._guardar()


# ---------------------------------------------------------------- experimento
def ejecutar(tarea):
    semilla, vida, condicion, plano, radio = tarea
    mundo = MundoCambiante(np.random.default_rng(50_000 + semilla), vida, con_piezas=condicion != "sin_piezas")
    rng_sujeto, rng_fisica = np.random.default_rng(60_000 + semilla), np.random.default_rng(70_000 + semilla)
    if condicion == "sin_piezas":
        h = SujetoBase(rng_sujeto)
        caidas, genuino, _ = h.vivir(mundo, vida, rng_fisica)
        extra = {}
    else:
        modo, recontextualizar = CONFIG[condicion]
        moratoria = not condicion.endswith("sin_moratoria")
        with Biblioteca(":memory:") as b:
            if plano != "sin_plano":
                b.guardar(plano_ejemplo(plano), origen="externo")
            h = SujetoLargo(rng_sujeto, b, modo, recontextualizar, radio=radio, moratoria=moratoria)
            caidas, genuino, _ = h.vivir(mundo, vida, rng_fisica)
            for x in h.huellas:  # etiqueta de oráculo, solo para calibrar
                x["terreno"] = next(f["terreno"] for f in reversed(h.fases) if f["inicio"] <= x["t"])
            extra = dict(contextos=b.db.execute("SELECT COUNT(*) FROM contextos").fetchone()[0],
                         huellas=h.huellas, ventanas_plano=len(h.ventanas),
                         plano_externo=next(iter(h.registro.values()), None))
    return dict(semilla=semilla, condicion=condicion, episodios=len(puente.episodios(caidas)),
                fraccion_genuino=genuino, fraccion_saturado=h.tiempo_saturado / vida,
                saturado_final=bool(np.any(np.abs(h.x[NA:]) >= SATURACION - 1e-6)),
                fases=h.fases, **extra)


def calibrar(rep, vida, semilla, radio):
    """Distancias de huella dentro y entre terrenos, con semillas ajenas a la prueba."""
    with ProcessPoolExecutor() as ex:
        filas = list(ex.map(ejecutar, [(semilla + r, vida, "C_contexto", "correcto", radio) for r in range(rep)]))
    mismo, distinto = [], []
    for f in filas:
        hs = f["huellas"]
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                d = float(np.sqrt(np.mean((np.array(hs[i]["huella"]) - np.array(hs[j]["huella"])) ** 2)))
                (mismo if hs[i]["terreno"] == hs[j]["terreno"] else distinto).append(d)
    mismo, distinto = np.array(mismo), np.array(distinto)
    print(f"=== Calibración de RADIO · radio en uso {radio} · {rep} vidas (semillas {semilla}+) · {vida} pasos ===")
    print(f"huellas por vida (mediana): {np.median([len(f['huellas']) for f in filas]):.0f}")
    print(f"pares mismo terreno: {mismo.size}   distinto: {distinto.size}")
    for q in (10, 25, 50, 75, 90):
        print(f"  percentil {q:>2}: mismo {np.percentile(mismo, q):.3f}   distinto {np.percentile(distinto, q):.3f}")
    print(f"{'radio':>7}{'reconoce mismo':>16}{'confunde distinto':>19}")
    for r in (0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.25):
        print(f"{r:>7.3f}{np.mean(mismo <= r):>15.0%}{np.mean(distinto <= r):>18.0%}")


# ---------------------------------------------------------------- informe
def _cambios(filas, revisita):
    return [f for x in filas for f in x["fases"][1:] if f["revisita"] == revisita]


def _rec(fases, clave, largo):
    t = [f[clave] for f in fases]
    ok = [v for v in t if v is not None]
    cens = [largo if v is None else v for v in t]
    return len(ok), len(t), (float(np.median(ok)) if ok else None), float(np.median(cens))


def informe(filas, rep, vida, radio):
    largo = vida // len(RECORRIDO)
    por = {c: sorted((x for x in filas if x["condicion"] == c), key=lambda x: x["semilla"]) for c in CONDICIONES}
    print(f"=== Prueba larga componible · {rep} vidas pareadas · {vida} pasos · terrenos {RECORRIDO} "
          f"cada {largo} · R_max {R_MAX} · radio {radio} ===\n")
    print(f"{'condición':<29}{'% t. puente genuino':>20}{'% t. saturado':>15}{'saturadas al final':>20}"
          f"{'genuino fin de fase':>21}{'caídas (med)':>14}")
    for c in CONDICIONES:
        d = por[c]
        gf = sum(f["genuino_final"] for x in d for f in x["fases"])
        print(f"{NOMBRE[c]:<29}{100 * np.mean([x['fraccion_genuino'] for x in d]):>19.1f}%"
              f"{100 * np.mean([x['fraccion_saturado'] for x in d]):>14.2f}%"
              f"{sum(x['saturado_final'] for x in d):>15}/{rep:<4}{gf:>15}/{rep * len(RECORRIDO):<5}"
              f"{np.median([x['episodios'] for x in d]):>14.0f}")
    print("\nCambios de terreno que no producen ninguna caída en los 400 pasos siguientes:")
    for c in CONDICIONES:
        cambios = [f for x in por[c] for f in x["fases"][1:]]
        print(f"  {NOMBRE[c]:<29}{sum(f['rec_estable'] == VENTANA_ESTABLE for f in cambios):>4}/{len(cambios)}")
    print("\nReferencia saturacion.py (otro entorno, sin piezas): 31–35/100 terminan saturadas.\n")

    print("Recuperación tras cambio de terreno (pasos hasta 400 seguidos viables; sin recuperar = censurado en "
          f"{largo}):")
    print(f"{'condición':<29}{'tipo':<10}{'puente: recup.':>16}{'med. recup.':>13}{'med. cens.':>12}"
          f"{'estable: recup.':>17}{'med. recup.':>13}{'med. cens.':>12}")
    for c in CONDICIONES:
        for revisita, tipo in ((False, "nuevo"), (True, "revisita")):
            fs = _cambios(por[c], revisita)
            p, e = _rec(fs, "rec_puente", largo), _rec(fs, "rec_estable", largo)
            fmt = lambda r: f"{r[0]:>10}/{r[1]:<5}{(f'{r[2]:.0f}' if r[2] is not None else '—'):>13}{r[3]:>12.0f}"
            print(f"{NOMBRE[c]:<29}{tipo:<10}{fmt(p)}  {fmt(e)}")
    print("\nPlanos propios consolidados (≥ 90 % al terminar la primera visita) al volver a ese terreno:")
    print(f"{'condición':<29}{'consolidados':>13}{'recargados':>12}{'descarte prem.':>16}{'logran antes':>14}")
    for c in CONDICIONES:
        fs = _cambios(por[c], True)
        cons = sum(len(f["consolidados"]) for f in fs)
        seg = [s for f in fs for s in f["seguimiento"].values() if s["cargado"]]
        prem = sum(s["primero"] == "castigo" for s in seg)
        logra = sum(s["primero"] == "logro" for s in seg)
        tasa = f"{prem}/{len(seg)} ({100 * prem / len(seg):.0f} %)" if seg else "—"
        print(f"{NOMBRE[c]:<29}{cons:>13}{len(seg):>12}{tasa:>16}{logra:>14}")

    print("\nReconocimiento de contexto (oráculo solo para medir):")
    for c in ("A_contexto", "C_contexto"):
        rec, nuevos_ok, n_rev, n_new = 0, 0, 0, 0
        for x in por[c]:
            fin = {}
            for i, f in enumerate(x["fases"]):
                if i and f["revisita"]:
                    n_rev += 1
                    rec += f["contexto_final"] == fin.get(f["terreno"])
                elif i:  # la fase 0 siempre es «distinta»: no cuenta
                    n_new += 1
                    nuevos_ok += f["contexto_final"] not in fin.values()
                fin.setdefault(f["terreno"], f["contexto_final"])
        print(f"  {NOMBRE[c]:<29}revisitas reconocidas {rec}/{n_rev}   terrenos nuevos distinguidos "
              f"{nuevos_ok}/{n_new}   contextos por vida (med) {np.median([x['contextos'] for x in por[c]]):.0f}")

    print("\nPruebas pareadas por semilla (signo para % puente genuino; McNemar para saturadas al final):")
    for a, b in (("A_fijo", "C_contexto"), ("A_contexto", "C_contexto"), ("A_fijo", "A_contexto"),
                 ("sin_piezas", "C_contexto")):
        ga = [x["fraccion_genuino"] for x in por[a]]
        gb = [x["fraccion_genuino"] for x in por[b]]
        sa = [x["saturado_final"] for x in por[a]]
        sb = [x["saturado_final"] for x in por[b]]
        print(f"  {NOMBRE[a]:<29} vs {NOMBRE[b]:<27} puente: {NOMBRE[b][:1]} mayor en "
              f"{sum(y > z for z, y in zip(ga, gb))}, menor en {sum(y < z for z, y in zip(ga, gb))}  "
              f"p = {signo(ga, gb):.3f}   saturadas {sum(sa)} vs {sum(sb)}  p = {mcnemar(sa, sb):.3f}")
        for revisita, tipo in ((False, "nuevo"), (True, "revisita")):
            ra = [np.mean([largo if f["rec_puente"] is None else f["rec_puente"] for f in x["fases"][1:]
                           if f["revisita"] == revisita]) for x in por[a]]
            rb = [np.mean([largo if f["rec_puente"] is None else f["rec_puente"] for f in x["fases"][1:]
                           if f["revisita"] == revisita]) for x in por[b]]
            if a != "sin_piezas":
                print(f"      recuperación de puente ({tipo}): más rápida en {sum(y < z for z, y in zip(ra, rb))}, "
                      f"más lenta en {sum(y > z for z, y in zip(ra, rb))}  p = {signo(rb, ra):.3f}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--rep", type=int, default=100)
    p.add_argument("--vida", type=int, default=VIDA)
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--plano", choices=PLANOS, default="correcto")
    p.add_argument("--calibrar", action="store_true", help="medir distancias de huella (usar semillas ≥ 1000)")
    p.add_argument("--radio", type=float, default=RADIO)
    p.add_argument("--reinformar", action="store_true", help="rehacer el informe desde --salida sin volver a correr")
    p.add_argument("--salida", type=Path, default=Path(__file__).with_name("resultados_prueba_larga.json"))
    a = p.parse_args()
    if a.rep < 1 or a.vida < 10 * VENTANA_CONTEXTO * len(RECORRIDO) or a.semilla < 0:
        p.error("rep >= 1, vida suficiente para cinco fases, semilla >= 0")
    if a.reinformar:
        d = json.loads(a.salida.read_text(encoding="utf-8"))
        informe(d["vidas"], d["rep"], d["vida"], d["radio"])
        return
    if a.calibrar:
        calibrar(a.rep, a.vida, a.semilla, a.radio)
        return
    tareas = [(a.semilla + r, a.vida, c, a.plano, a.radio) for r in range(a.rep) for c in CONDICIONES]
    with ProcessPoolExecutor() as ex:
        filas = list(ex.map(ejecutar, tareas))
    informe(filas, a.rep, a.vida, a.radio)
    for x in filas:
        x.pop("huellas", None)
    a.salida.write_text(json.dumps(dict(rep=a.rep, vida=a.vida, recorrido=RECORRIDO, radio=a.radio, r_max=R_MAX,
                                        plano=a.plano, vidas=filas), ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"\nRegistros individuales: {a.salida}")


if __name__ == "__main__":
    main()
