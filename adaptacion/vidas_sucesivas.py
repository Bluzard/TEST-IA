"""Vidas sucesivas: memoria persistente + deducción + abducción.

Un sujeto vive una vida por ejecución. El cuerpo (W) nace de nuevo cada vez;
solo persiste su memoria, en un archivo SQLite que nunca se borra. Cada vida
ocurre en un mundo de la familia de abstraccion_estructural.py: río propio y
códigos de pieza re-mapeados en secreto. Algunos mundos se repiten.

Qué guarda la memoria (aprendido, nunca escrito por el experimentador):
  esquemas  ciclos con piezas presentes en el éxito más sostenido de cada vida,
            con su soporte (en cuántas vidas aparecieron). Inducción entre vidas.
  roles     lo que el sujeto vio hacer a cada código de pieza en cada vida.

El ciclo de las tres inferencias dentro de una vida:
  abducción  · de roles: con un arreglo puesto, la influencia observada de cada
               pieza se explica con la hipótesis más simple («el código c en
               esta ranura siente el canal k» / «empuja el canal j con signo s,
               alimentado por el ancla f»). Una sola observación basta para
               postularla.
             · de mundo: si los roles vistos coinciden con los de una vida
               pasada, «estoy otra vez en ese mundo» explica lo visto; se
               adoptan sus roles no vistos como hipótesis. Una contradicción o
               un plan fallido con ellos la descarta.
  deducción  con los roles conocidos y los esquemas, compone en memoria el
             arreglo que contendría un esquema y lo arma sin haberlo probado.
             Lo pone ante una caída (necesidad); bloquea esas piezas y abre la
             ventana de acoplamiento para el cuerpo (modo C).
  inducción  la tasa del 90 % y el soporte de los esquemas entre vidas.

No hay predicción de valores ni trayectorias: la memoria elige qué armar.

Condiciones (cada una con su propia base, pareadas por semilla):
  de_cero     la base se borra antes de cada vida: nacer desde 0
  esquemas    esquemas persistentes; solo reconocer + paciencia (sin roles)
  deduccion   esquemas + abducción de roles en la vida + deducción
  completo    deduccion + roles persistentes + abducción de mundo
  *_cuerpo    además el cuerpo persiste: nace con el W de la configuración con
              mejor tasa de la vida anterior (sin ruido; las piezas no se heredan,
              sus códigos cambian de significado). solo_cuerpo: sin conocimiento.
  *_paciencia  la ventana de un plano deducido solo con roles vistos en esta vida
              tiene presupuesto R_max × (1 + soporte del esquema); con roles
              adoptados, R_max. La confianza en el plano fija la paciencia.
  completo_cuerpo_mundo  nace con cuerpo nuevo; si la abducción de mundo
              concluye «estoy en el mundo de la vida L», recupera el cuerpo de L.

Uso:
  python adaptacion/vidas_sucesivas.py comparar --rep 100
  python adaptacion/vidas_sucesivas.py vivir --db adaptacion/memoria_vidas.sqlite --semilla 0 --vida 1
"""
import argparse
import itertools
import json
import sqlite3
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from abstraccion_estructural import (
    MundoFamilia, SujetoAbstraccion, ciclos, con_piezas, estimar, MIN_DATOS, R_MAX,
)
from atribucion_fallo import signo
from entorno_componible import ANCLAS, APOYOS, NR, NP

VIDA = 40_000
SECUENCIA = (0, 1, 2, 0, 3, 1, 4, 2, 5, 0)  # mundo de cada vida; 4, 6, 8 y 10 son revisitas
N_MUNDOS = max(SECUENCIA) + 1
FUERTE = 2.0  # |influencia| para atribuir un rol (G = 4 en la física)
CONDICIONES = ("de_cero", "esquemas", "deduccion", "completo", "solo_cuerpo", "deduccion_cuerpo", "completo_cuerpo",
               "completo_cuerpo_mundo", "deduccion_paciencia", "completo_paciencia")
# (esquemas, roles, abducción de mundo, cuerpo heredado)
CONFIG = {"de_cero": (False, False, False, False), "esquemas": (True, False, False, False),
          "deduccion": (True, True, False, False), "completo": (True, True, True, False),
          "solo_cuerpo": (False, False, False, "anterior"), "deduccion_cuerpo": (True, True, False, "anterior"),
          "completo_cuerpo": (True, True, True, "anterior"), "completo_cuerpo_mundo": (True, True, True, "mundo"),
          "deduccion_paciencia": (True, True, False, False), "completo_paciencia": (True, True, True, False)}
PACIENCIA = {"deduccion_paciencia", "completo_paciencia"}  # presupuesto según la confianza en el plano


# ---------------------------------------------------------------- memoria
class Memoria:
    """Archivo SQLite del sujeto. `mundo_oraculo` solo sirve para medir."""

    def __init__(self, ruta):
        self.db = sqlite3.connect(str(ruta))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS vidas (vida INTEGER PRIMARY KEY, mundo_oraculo INTEGER,
                                              pasos_puente INTEGER);
            CREATE TABLE IF NOT EXISTS esquemas (rasgo TEXT PRIMARY KEY, soporte INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS roles (vida INTEGER NOT NULL, ranura INTEGER NOT NULL,
                                              codigo INTEGER NOT NULL, rol TEXT NOT NULL,
                                              PRIMARY KEY (vida, ranura, codigo));
            CREATE TABLE IF NOT EXISTS cuerpos (vida INTEGER PRIMARY KEY, W TEXT NOT NULL);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.db.close()

    def vidas_previas(self):
        return self.db.execute("SELECT COUNT(*) FROM vidas").fetchone()[0]

    def esquemas(self):
        filas = self.db.execute("SELECT rasgo, soporte FROM esquemas")
        return {(tuple(t), s): n for (t, s), n in ((json.loads(r), n) for r, n in filas)}

    def roles(self):
        por_vida = {}
        for vida, ranura, codigo, rol in self.db.execute("SELECT vida, ranura, codigo, rol FROM roles"):
            por_vida.setdefault(vida, {})[(ranura, codigo)] = tuple(json.loads(rol))
        return por_vida

    def cuerpo(self):
        fila = self.db.execute("SELECT W FROM cuerpos ORDER BY vida DESC LIMIT 1").fetchone()
        return None if fila is None else np.array(json.loads(fila[0]))

    def cuerpos(self):
        return {vida: np.array(json.loads(W)) for vida, W in self.db.execute("SELECT vida, W FROM cuerpos")}

    def cerrar_vida(self, mundo_oraculo, pasos_puente, rasgos, roles, W=None):
        with self.db:
            vida = self.vidas_previas() + 1
            self.db.execute("INSERT INTO vidas VALUES (?,?,?)", (vida, mundo_oraculo, pasos_puente))
            for t, s in rasgos:
                clave = json.dumps([list(t), s])
                self.db.execute("INSERT INTO esquemas VALUES (?,1) ON CONFLICT(rasgo) DO UPDATE "
                                "SET soporte = soporte + 1", (clave,))
            self.db.executemany("INSERT INTO roles VALUES (?,?,?,?)",
                                [(vida, r, c, json.dumps(list(rol))) for (r, c), rol in roles.items()])
            if W is not None:
                self.db.execute("INSERT INTO cuerpos VALUES (?,?)", (vida, json.dumps(W.tolist())))
        return vida


# ---------------------------------------------------------------- sujeto
def _consistente(a, b):
    return a[0] == b[0] and all(x is None or y is None or x == y for x, y in zip(a[1:], b[1:]))


def _completo(rol):
    return all(v is not None for v in rol[1:])


class SujetoVidas(SujetoAbstraccion):
    def __init__(self, rng, memoria, condicion):
        super().__init__(rng)
        self.usa_esquemas, self.usa_roles, self.usa_mundo, self.usa_cuerpo = CONFIG[condicion]
        self.paciencia = condicion in PACIENCIA
        heredado = memoria.cuerpo() if self.usa_cuerpo == "anterior" else None
        self.cuerpos = memoria.cuerpos() if self.usa_cuerpo == "mundo" else {}
        self._cuerpo_pendiente = None
        self.cuerpo_heredado = heredado is not None
        if heredado is not None:
            self.W = heredado.copy()  # el rng ya consumió el W al azar: el pareo no cambia
        self.soporte = memoria.esquemas() if self.usa_esquemas else {}
        if self.soporte:
            tope = max(self.soporte.values())
            self.abstraccion = frozenset(r for r, n in self.soporte.items() if n >= max(1, tope / 2))
        self.pasados = memoria.roles() if self.usa_mundo else {}
        self.roles, self.origen_rol = {}, {}
        self.adopcion, self.descartadas = None, set()
        self.registro = dict(adopciones=[], revisiones=0, contradicciones=0, deducciones=0, cuerpos_recuperados=[])
        self._plan = None

    # ------------------------------------------------------------ percepción
    def _paso_fisico(self, x_antes):
        clave = tuple(self.P)
        if clave != self._P_trans:
            self._trans, self._P_trans = [], clave
        self._trans.append((x_antes, self.x.copy()))
        if len(self._trans) > 40 * MIN_DATOS:
            del self._trans[:len(self._trans) // 2]
        if len(self._trans) in (MIN_DATOS, 4 * MIN_DATOS) and (self.usa_roles or self.abstraccion):
            A = estimar(self._trans)
            if A is None:
                return
            if self.usa_roles:
                self._abducir_roles(A)
            if self.abstraccion and self.ventana is None:
                self._reconocer(A)

    # ------------------------------------------------------------ abducción
    def _abducir_roles(self, A):
        for a in range(ANCLAS):
            c = int(self.P[a])
            col = A[NR + a, :NR]
            if c and np.max(np.abs(col)) > FUERTE:
                self._ver((a, c), ("A", int(np.argmax(np.abs(col)))))
        for b in range(APOYOS):
            ranura = ANCLAS + b
            c = int(self.P[ranura])
            if not c:
                continue
            ali = A[NR + ranura, NR:NR + ANCLAS]
            emp = A[:NR, NR + ranura]
            f = int(np.argmax(np.abs(ali))) if np.max(np.abs(ali)) > FUERTE else None
            j = int(np.argmax(np.abs(emp))) if np.max(np.abs(emp)) > FUERTE else None
            s = int(np.sign(emp[j])) if j is not None else None
            if f is not None or j is not None:
                self._ver((ranura, c), ("B", j, f, s))
        if self.usa_mundo and self.adopcion is None:
            self._abducir_mundo()

    def _ver(self, clave, rol):
        previo = self.roles.get(clave)
        if previo is not None and not _consistente(previo, rol):
            if self.origen_rol.get(clave) == "adoptado":
                self.registro["contradicciones"] += 1
                self._revisar_adopcion()
                previo = None
            else:
                self.registro["revisiones"] += 1
                previo = None  # lo nuevo explica mejor lo que veo ahora
        nuevo = rol if previo is None else (rol[0],) + tuple(
            y if y is not None else x for x, y in zip(previo[1:], rol[1:]))
        if nuevo != previo or self.origen_rol.get(clave) != "visto":
            self.roles[clave], self.origen_rol[clave] = nuevo, "visto"
            self._plan = None

    def _abducir_mundo(self):
        vistos = {k: v for k, v in self.roles.items() if self.origen_rol[k] == "visto"}
        mejor, mejor_n = None, 0
        for vida, roles in self.pasados.items():
            if vida in self.descartadas:
                continue
            comunes = [k for k in vistos if k in roles]
            if any(not _consistente(vistos[k], roles[k]) for k in comunes):
                continue
            apoyos = sum(k[0] >= ANCLAS for k in comunes)
            if len(comunes) >= 2 and apoyos >= 1 and len(comunes) > mejor_n:
                mejor, mejor_n = vida, len(comunes)
        if mejor is None:
            return
        self.adopcion = mejor
        self.registro["adopciones"].append(mejor)
        if mejor in self.cuerpos:
            self._cuerpo_pendiente = self.cuerpos[mejor]  # se aplica en la próxima caída
            self.registro["cuerpos_recuperados"].append(mejor)
        for k, rol in self.pasados[mejor].items():
            if k not in self.roles:
                self.roles[k], self.origen_rol[k] = rol, "adoptado"
        self._plan = None

    def _revisar_adopcion(self):
        self.descartadas.add(self.adopcion)
        for k in [k for k, o in self.origen_rol.items() if o == "adoptado"]:
            del self.roles[k], self.origen_rol[k]
        self.adopcion = None
        self._plan = None

    # ------------------------------------------------------------ deducción
    def _deducir(self):
        if self._plan is not None:
            return self._plan or None
        opciones = []
        for ranura in range(NP):
            codigos = [0] + sorted(c for (r, c), rol in self.roles.items() if r == ranura and _completo(rol))
            opciones.append(codigos)
        mejor, mejor_puntos = (), 0
        for arreglo in itertools.product(*opciones):
            if not any(arreglo):
                continue
            M = np.zeros((NR + NP, NR + NP))
            for ranura, c in enumerate(arreglo):
                if not c:
                    continue
                rol = self.roles[(ranura, c)]
                if rol[0] == "A":
                    M[NR + ranura, rol[1]] = 1.0
                else:
                    j, f, s = rol[1:]
                    M[NR + ranura, NR + f] = 1.0
                    M[j, NR + ranura] = float(s)
            bloqueo, puntos, soporte = set(), 0, 0
            for rasgo, nodos in ciclos(M):
                if rasgo in self.abstraccion:
                    puntos += self.soporte[rasgo]
                    soporte = max(soporte, self.soporte[rasgo])
                    bloqueo.update(v - NR for v in nodos if v >= NR)
            if not puntos:
                continue
            fijo = frozenset((i, arreglo[i]) for i in bloqueo)
            if fijo in self.agotados:
                continue
            if puntos > mejor_puntos:
                mejor, mejor_puntos = (fijo, sorted(bloqueo), soporte), puntos
        self._plan = mejor
        return mejor or None

    def _explorar_unidad(self, i, mundo):
        super()._explorar_unidad(i, mundo)
        if self._cuerpo_pendiente is not None:
            self.W = self._cuerpo_pendiente.copy()
            self._cuerpo_pendiente = None
        v = self.ventana
        if v is not None:
            if i in v["bloqueo"]:
                self.P[i] = dict(v["arreglo"])[i]  # lo deducido queda fijo
            return
        if not (self.usa_roles and self.abstraccion):
            return
        plan = self._deducir()
        if plan is None:
            return
        fijo, bloqueo, soporte = plan
        for ranura, c in fijo:
            self.P[ranura] = c
        usa_adoptados = any(self.origen_rol.get((r, c)) == "adoptado" for r, c in fijo)
        self.registro["deducciones"] += 1
        solo_plan = np.zeros_like(self.P)
        for ranura, c in fijo:
            solo_plan[ranura] = c
        r_max = R_MAX * (1 + soporte) if self.paciencia and not usa_adoptados else R_MAX
        self.ventana = dict(arreglo=fijo, bloqueo=bloqueo, presupuesto=r_max, r_max=r_max, mejor=0, inicio=self._t,
                            reconfiguraciones=0, renovaciones=0, pasos=0,
                            origen="deducido_adoptado" if usa_adoptados else "deducido",
                            es_puente=bool(mundo.puentes_de(solo_plan)))  # oráculo: solo para medir

    def _cerrar_ventana(self, motivo):
        v = self.ventana
        super()._cerrar_ventana(motivo)
        self.ventanas[-1]["es_puente"] = v.get("es_puente")

    def _acoplar(self, fuera, racha, mundo):
        origen = self.ventana.get("origen")
        sigue = super()._acoplar(fuera, racha, mundo)
        if not sigue:
            self._plan = None
            if origen == "deducido_adoptado" and self.adopcion is not None:
                self._revisar_adopcion()  # el mundo no era el que supuse
        return sigue

    # ------------------------------------------------------------ cierre
    def legado(self):
        """Lo que esta vida deja en la memoria."""
        cand = [v for v in self.firmas.values()]
        mejor = max(cand, key=lambda v: v[3]) if cand else None
        rasgos = con_piezas(mejor[0]) if mejor else frozenset()
        vistos = {k: v for k, v in self.roles.items() if self.origen_rol[k] == "visto"}
        W = None
        if self.usa_cuerpo in ("anterior", "mundo"):
            if self.repertorio:
                k = max(range(len(self.repertorio)), key=lambda i: (self.tasa(i), self.logros[i]))
                W = self.repertorio[k][:self.W.size].reshape(self.W.shape)
            else:
                W = self.W
        return rasgos, vistos, W


# ---------------------------------------------------------------- experimento
def vivir(ruta, semilla, vida, condicion="completo", pasos=VIDA):
    """Una vida = una ejecución: abre la memoria, vive, deja su legado y cierra."""
    mundo = MundoFamilia(np.random.default_rng(50_000 + semilla), n_mundos=N_MUNDOS)
    mundo.ir(SECUENCIA[(vida - 1) % len(SECUENCIA)])
    with Memoria(ruta) as m:
        h = SujetoVidas(np.random.default_rng([60_000, semilla, vida]), m, condicion)
        roles_heredados = sum(len(r) for r in h.pasados.values())
        esquemas_heredados = len(h.abstraccion or ())
        _, frac, _ = h.vivir(mundo, pasos, np.random.default_rng([70_000, semilla, vida]))
        f = h.fases[0]
        rasgos, roles, W = h.legado()
        numero = m.cerrar_vida(mundo.terreno, f["rec_puente"], rasgos, roles, W)
        oraculo = dict(m.db.execute("SELECT vida, mundo_oraculo FROM vidas").fetchall())
    adop = h.registro["adopciones"]
    return dict(semilla=semilla, vida=numero, condicion=condicion, mundo=mundo.terreno,
                revisita=mundo.terreno in SECUENCIA[:(vida - 1) % len(SECUENCIA)],
                rec_puente=f["rec_puente"], episodios=f["episodios"], fraccion_genuino=frac,
                esquemas_heredados=esquemas_heredados, roles_heredados=roles_heredados,
                roles_vistos=len(roles), esquemas_dejados=[[list(t), s] for t, s in rasgos],
                deducciones=h.registro["deducciones"],
                acopladas=dict((o, sum(v["motivo"] == "acoplado" and v["origen"] == o for v in h.ventanas))
                               for o in ("reconocido", "deducido", "deducido_adoptado")),
                adopciones=len(adop), adopciones_correctas=sum(oraculo.get(v) == mundo.terreno for v in adop),
                contradicciones=h.registro["contradicciones"], revisiones=h.registro["revisiones"],
                diagnostico={f"{'puente' if w['es_puente'] else 'no_puente'}_{w['motivo']}":
                             sum(1 for z in h.ventanas if str(z["origen"]).startswith("deducido")
                                 and z["es_puente"] == w["es_puente"] and z["motivo"] == w["motivo"])
                             for w in h.ventanas if str(w["origen"]).startswith("deducido")},
                cuerpos_recuperados=len(h.registro["cuerpos_recuperados"]),
                cuerpos_correctos=sum(oraculo.get(v) == mundo.terreno for v in h.registro["cuerpos_recuperados"]),
                primera_deduccion=next((w["inicio"] for w in h.ventanas if str(w["origen"]).startswith("deducido")), None))


def linaje(tarea):
    """Todas las vidas de un sujeto en una condición, cada una reabriendo el archivo."""
    semilla, condicion, pasos = tarea
    filas = []
    with tempfile.TemporaryDirectory(prefix="vidas-") as carpeta:
        ruta = Path(carpeta) / "memoria.sqlite"
        for vida in range(1, len(SECUENCIA) + 1):
            if condicion == "de_cero" and ruta.exists():
                ruta.unlink()
            filas.append(vivir(ruta, semilla, vida, condicion, pasos))
            filas[-1]["vida"] = vida
    return filas


def informe(filas, rep, pasos):
    cen = lambda f: pasos if f["rec_puente"] is None else f["rec_puente"]
    print(f"=== Vidas sucesivas · {rep} sujetos · {len(SECUENCIA)} vidas de {pasos} pasos · mundos {SECUENCIA} ===\n")
    print("Pasos hasta el primer puente estable (mediana; sin puente = " f"{pasos}) por vida:")
    print(f"{'vida':>5}{'mundo':>7}{'tipo':>10}" + "".join(f"{c:>22}" for c in CONDICIONES))
    for v in range(1, len(SECUENCIA) + 1):
        d = {c: [x for x in filas if x["condicion"] == c and x["vida"] == v] for c in CONDICIONES}
        tipo = "revisita" if d[CONDICIONES[0]][0]["revisita"] else "nuevo"
        print(f"{v:>5}{SECUENCIA[v - 1]:>7}{tipo:>10}" + "".join(f"{np.median([cen(x) for x in d[c]]):>22.0f}"
                                                              for c in CONDICIONES))
    print("\nResumen por sujeto (media de sus vidas 2–10; luego mediana entre sujetos):")
    por = {c: {} for c in CONDICIONES}
    for x in filas:
        if x["vida"] > 1:
            por[x["condicion"]].setdefault(x["semilla"], []).append(x)
    for grupo, filtro in (("vidas 2–10", lambda x: True), ("mundos nuevos", lambda x: not x["revisita"]),
                          ("revisitas", lambda x: x["revisita"])):
        print(f"  {grupo:<14}" + "".join(
            f"{c}: {np.median([np.mean([cen(x) for x in v if filtro(x)]) for v in por[c].values()]):>7.0f}   "
            for c in CONDICIONES))
    print("\nPareadas por sujeto (signo sobre la media censurada de las vidas 2–10):")
    for a, b in (("de_cero", "solo_cuerpo"), ("deduccion", "deduccion_cuerpo"), ("completo", "completo_cuerpo"),
                 ("deduccion_cuerpo", "completo_cuerpo"), ("completo", "completo_cuerpo_mundo"),
                 ("deduccion", "deduccion_paciencia"), ("completo", "completo_paciencia"),
                 ("de_cero", "esquemas"), ("esquemas", "deduccion"), ("deduccion", "completo"),
                 ("de_cero", "completo")):
        for grupo, filtro in (("nuevos", lambda x: not x["revisita"]), ("revisitas", lambda x: x["revisita"])):
            ma = [np.mean([cen(x) for x in por[a][s] if filtro(x)]) for s in sorted(por[a])]
            mb = [np.mean([cen(x) for x in por[b][s] if filtro(x)]) for s in sorted(por[b])]
            print(f"  {a:<16} vs {b:<21} {grupo:<10} {b} más rápida en {sum(y < z for z, y in zip(ma, mb)):>3}, "
                  f"más lenta en {sum(y > z for z, y in zip(ma, mb)):>3}  p = {signo(mb, ma):.3f}")
    print("\nCómo llegó el puente y qué hizo la abducción (totales sobre vidas 2–10):")
    for c in CONDICIONES:
        d = [x for x in filas if x["condicion"] == c and x["vida"] > 1]
        acop = {o: sum(x["acopladas"][o] for x in d) for o in ("reconocido", "deducido", "deducido_adoptado")}
        rev = [x for x in d if x["revisita"]]
        nue = [x for x in d if not x["revisita"]]
        print(f"  {c:<21} ventanas acopladas: reconocidas {acop['reconocido']}, deducidas {acop['deducido']}, "
              f"deducidas con roles adoptados {acop['deducido_adoptado']} | adopciones de mundo: "
              f"revisitas {sum(x['adopciones_correctas'] for x in rev)}/{sum(x['adopciones'] for x in rev)} correctas, "
              f"mundos nuevos {sum(x['adopciones'] for x in nue)} (todas erróneas por definición) | "
              f"contradicciones {sum(x['contradicciones'] for x in d)}")
    print("\n¿Dónde se va el tiempo? Vidas 2–10 con deducción y puente (mediana de pasos):")
    for c in ("deduccion", "completo", "deduccion_cuerpo", "completo_cuerpo", "completo_cuerpo_mundo",
              "deduccion_paciencia", "completo_paciencia"):
        d = [x for x in filas if x["condicion"] == c and x["vida"] > 1 and x["primera_deduccion"] is not None
             and x["rec_puente"] is not None and x["rec_puente"] >= x["primera_deduccion"]]
        print(f"  {c:<21} {len(d)} vidas · hasta la primera deducción {np.median([x['primera_deduccion'] for x in d]):.0f}"
              f" · de ahí al puente estable {np.median([x['rec_puente'] - x['primera_deduccion'] for x in d]):.0f}")
    print("\nDiagnóstico de planes deducidos (oráculo: ¿el arreglo deducido es un puente?), vidas 2–10:")
    for c in ("deduccion", "completo", "deduccion_cuerpo", "completo_cuerpo", "completo_cuerpo_mundo",
              "deduccion_paciencia", "completo_paciencia"):
        d = [x for x in filas if x["condicion"] == c and x["vida"] > 1]
        t = lambda k: sum(x["diagnostico"].get(k, 0) for x in d)
        print(f"  {c:<21} es puente: acoplado {t('puente_acoplado'):>5}, agotado {t('puente_agotado'):>5}, otro "
              f"{t('puente_cambio_contexto') + t('puente_abierta_al_final'):>4} | no es puente: acoplado "
              f"{t('no_puente_acoplado'):>4}, agotado {t('no_puente_agotado'):>4}, otro "
              f"{t('no_puente_cambio_contexto') + t('no_puente_abierta_al_final'):>4}")
    d = [x for x in filas if x["condicion"] == "completo_cuerpo_mundo" and x["vida"] > 1]
    for grupo, filtro in (("revisitas", lambda x: x["revisita"]), ("mundos nuevos", lambda x: not x["revisita"])):
        g = [x for x in d if filtro(x)]
        print(f"  cuerpos recuperados en {grupo}: {sum(x['cuerpos_recuperados'] for x in g)} "
              f"(del mundo correcto {sum(x['cuerpos_correctos'] for x in g)})")
    sop = [x for x in filas if x["condicion"] == "completo" and x["vida"] == len(SECUENCIA)]
    print(f"\nEsquemas que hereda la última vida (completo): mediana {np.median([x['esquemas_heredados'] for x in sop]):.0f}"
          f"; roles heredados: mediana {np.median([x['roles_heredados'] for x in sop]):.0f}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("vivir", help="una vida de un sujeto con memoria persistente en --db")
    v.add_argument("--db", type=Path, required=True)
    v.add_argument("--semilla", type=int, default=0)
    v.add_argument("--vida", type=int, required=True, help="número de vida (elige el mundo de SECUENCIA)")
    v.add_argument("--condicion", choices=[c for c in CONDICIONES if c != "de_cero"], default="completo")
    c = sub.add_parser("comparar", help="linajes pareados en bases temporales")
    c.add_argument("--rep", type=int, default=100)
    c.add_argument("--salida", type=Path, default=Path(__file__).with_name("resultados_vidas"),
                   help="carpeta: un JSON compacto por condición (archivos chicos, revisables)")
    for x in (v, c):
        x.add_argument("--pasos", type=int, default=VIDA)
    a = p.parse_args()
    if a.comando == "vivir":
        a.db.parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(vivir(a.db, a.semilla, a.vida, a.condicion, a.pasos), ensure_ascii=False, indent=1))
        return
    tareas = [(s, cond, a.pasos) for s in range(a.rep) for cond in CONDICIONES]
    with ProcessPoolExecutor() as ex:
        filas = [f for linea in ex.map(linaje, tareas) for f in linea]
    informe(filas, a.rep, a.pasos)
    guardar(a.salida, a.rep, a.pasos, filas)
    print(f"\nRegistros individuales: {a.salida}/")


def guardar(carpeta, rep, pasos, filas):
    carpeta.mkdir(parents=True, exist_ok=True)
    for c in CONDICIONES:
        datos = dict(rep=rep, pasos=pasos, secuencia=SECUENCIA, condicion=c,
                     vidas=[x for x in filas if x["condicion"] == c])
        (carpeta / f"{c}.json").write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n",
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
