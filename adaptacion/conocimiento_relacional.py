"""Intérprete numérico de relaciones. No importa el simulador ni usa LLMs."""
from dataclasses import dataclass
import json
import math
import random
import sqlite3

ASPIRACION = 0.90


def serial(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False)


def numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validar(r):
    campos = {"selector", "operacion", "contexto", "condiciones", "efectos", "fuente", "tolerancia"}
    if not isinstance(r, dict) or set(r) != campos:
        raise ValueError("Campos de relación inválidos")
    for key in ("selector", "contexto", "condiciones", "efectos"):
        if not isinstance(r[key], dict):
            raise ValueError(f"{key} debe ser un objeto")
    if not r['selector'] or not r['efectos']:
        raise ValueError("Selector y efectos no pueden estar vacíos")
    for key in ('selector', 'contexto'):
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in r[key].items()):
            raise ValueError("Los selectores y contextos usan cadenas")
    if any(not isinstance(k, str) or not numero(v) for k, v in r['efectos'].items()):
        raise ValueError("Efectos deben ser deltas finitos")
    for k, v in r['condiciones'].items():
        if not isinstance(k, str) or not isinstance(v, list) or len(v) != 2 or not all(map(numero, v)) or v[0] > v[1]:
            raise ValueError("Condiciones deben ser intervalos finitos ordenados")
    if not all(isinstance(r[k], str) and r[k] for k in ('operacion', 'fuente')):
        raise ValueError("Operación y fuente requeridas")
    if not numero(r['tolerancia']) or r['tolerancia'] <= 0:
        raise ValueError("Tolerancia debe ser positiva")
    serial(r)


@dataclass(frozen=True)
class Accion:
    id: str
    entidad: dict
    operacion: str
    coste: float

    def __post_init__(self):
        if not numero(self.coste) or self.coste < 0:
            raise ValueError("Coste inválido")


def enlazar(clave, entidad):
    return entidad.get(clave[1:]) if clave.startswith('$') else clave


def aplicable(r, accion, estado, contexto):
    return (r['operacion'] == accion.operacion
            and all(accion.entidad.get(k) == v for k, v in r['selector'].items())
            and all(contexto.get(k) == v for k, v in r['contexto'].items())
            and all(enlazar(k, accion.entidad) in estado
                    and lo <= estado[enlazar(k, accion.entidad)] <= hi
                    for k, (lo, hi) in r['condiciones'].items())
            and all(enlazar(k, accion.entidad) in estado for k in r['efectos']))


class MemoriaRelacional:
    def __init__(self, ruta=':memory:'):
        self.db = sqlite3.connect(str(ruta))
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS hechos(id INTEGER PRIMARY KEY, contenido TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS relaciones(id INTEGER PRIMARY KEY, contenido TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS experiencias(id INTEGER PRIMARY KEY, contenido TEXT);
            CREATE TABLE IF NOT EXISTS evidencia(
                relacion INTEGER REFERENCES relaciones(id), contexto TEXT,
                favor INTEGER DEFAULT 0, contra INTEGER DEFAULT 0,
                PRIMARY KEY(relacion, contexto));
            CREATE TABLE IF NOT EXISTS hipotesis(
                clave TEXT PRIMARY KEY, selector TEXT, operacion TEXT, contexto TEXT,
                efectos TEXT, n INTEGER);
            CREATE TABLE IF NOT EXISTS evidencia_hipotesis(
                clave TEXT, contexto TEXT, favor INTEGER DEFAULT 0, contra INTEGER DEFAULT 0,
                PRIMARY KEY(clave, contexto));
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def importar(self, documentos):
        if not isinstance(documentos, list):
            raise ValueError('Se requiere una lista de relaciones')
        for r in documentos:
            validar(r)
        with self.db:
            for r in documentos:
                self.db.execute('INSERT OR IGNORE INTO relaciones(contenido) VALUES(?)', (serial(r),))

    def hecho(self, contenido):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO hechos(contenido) VALUES(?)', (serial(contenido),))

    def relaciones(self):
        return [(i, json.loads(s)) for i, s in self.db.execute('SELECT id,contenido FROM relaciones ORDER BY id')]

    def empiricas(self):
        return [dict(selector=json.loads(s), operacion=o, contexto=json.loads(c), condiciones={},
                     efectos=json.loads(e), fuente='experiencia', tolerancia=0.04, n=n)
                for s, o, c, e, n in self.db.execute(
                    'SELECT selector,operacion,contexto,efectos,n FROM hipotesis ORDER BY clave')]

    def transferir(self, destino):
        # Sólo hipótesis empíricas; sin hechos, IDs de componentes ni testimonios.
        with destino.db:
            for row in self.db.execute('SELECT * FROM hipotesis ORDER BY clave'):
                destino.db.execute('INSERT INTO hipotesis VALUES(?,?,?,?,?,?)', row)

    def registrar(self, accion, antes, despues, contexto, fondo, predicciones, selector, aprender=True,
                  predicciones_empiricas=()):
        observado = {k: despues[k] - antes[k] - fondo.get(k, 0) for k in antes}
        resultados = []
        with self.db:
            for rid, r in predicciones:
                error = max(abs(observado[enlazar(k, accion.entidad)] - v) for k, v in r['efectos'].items())
                contradice = error > r['tolerancia']
                resultados.append(dict(relacion=rid, tipo='externo', error=error, contradice=contradice))
                self.db.execute('INSERT OR IGNORE INTO evidencia(relacion,contexto) VALUES(?,?)', (rid, serial(contexto)))
                self.db.execute('UPDATE evidencia SET favor=favor+?,contra=contra+? WHERE relacion=? AND contexto=?',
                                (int(not contradice), int(contradice), rid, serial(contexto)))
            for r in predicciones_empiricas:
                clave = serial([r['selector'], r['operacion'], r['contexto']])
                error = max((abs(observado[enlazar(k, accion.entidad)] - v)
                             for k, v in r['efectos'].items()), default=0)
                contradice = error > r['tolerancia']
                resultados.append(dict(relacion=clave, tipo='empirico', error=error, contradice=contradice))
                self.db.execute('INSERT OR IGNORE INTO evidencia_hipotesis(clave,contexto) VALUES(?,?)',
                                (clave, serial(contexto)))
                self.db.execute('UPDATE evidencia_hipotesis SET favor=favor+?,contra=contra+? WHERE clave=? AND contexto=?',
                                (int(not contradice), int(contradice), clave, serial(contexto)))
            self.db.execute('INSERT INTO experiencias(contenido) VALUES(?)', (serial(dict(
                accion=accion.id, entidad=accion.entidad, operacion=accion.operacion, coste=accion.coste,
                antes=antes, despues=despues, fondo=fondo, contexto=contexto,
                resultados=resultados, efecto_observado=observado)),))
            if aprender:
                # Abstracción limitada y explícita: reemplazar nombres de propiedades por
                # referencias a atributos públicos; conservar otros efectos literales.
                inversa = {v: '$' + k for k, v in accion.entidad.items() if v in antes}
                efectos = {inversa.get(k, k): v for k, v in observado.items() if abs(v) > 0.025}
                clave = serial([selector, accion.operacion, contexto])
                row = self.db.execute('SELECT efectos,n FROM hipotesis WHERE clave=?', (clave,)).fetchone()
                viejo, n = (json.loads(row[0]), row[1]) if row else ({}, 0)
                media = {k: (viejo.get(k, 0) * n + efectos.get(k, 0)) / (n + 1) for k in viejo.keys() | efectos.keys()}
                self.db.execute('INSERT OR REPLACE INTO hipotesis VALUES(?,?,?,?,?,?)',
                                (clave, serial(selector), accion.operacion, serial(contexto), serial(media), n + 1))
        return resultados


def deficit(estado, necesidades):
    return sum(max(lo - estado[k], 0, estado[k] - hi) for k, (lo, hi) in necesidades.items())


class Interprete:
    """Política de un paso. Las claves del selector las define el adaptador público."""
    def __init__(self, memoria, semilla, atributos=('rol',), exploracion=0.15):
        self.memoria = memoria
        self.rng = random.Random(semilla)
        self.atributos = atributos
        self.exploracion = exploracion

    def selector(self, accion):
        return {k: accion.entidad[k] for k in self.atributos}

    def proponer(self, estado, necesidades, acciones, contexto, fondo, presupuesto):
        disponibles = [a for a in acciones if a.coste <= presupuesto]
        if not disponibles:
            return None, dict(exploracion=False, origen='espera')
        externas = self.memoria.relaciones()
        empiricas = self.memoria.empiricas()
        base = {k: v + fondo.get(k, 0) for k, v in estado.items()}
        candidatos = []
        for a in disponibles:
            modelos = [(r, 'externo', 0.5) for _, r in externas if aplicable(r, a, estado, contexto)]
            modelos += [(r, 'empirico', 1 / (r['n'] + 1)) for r in empiricas if aplicable(r, a, estado, contexto)]
            # La experiencia local prevalece; ningún fallo borra el testimonio recibido.
            if not modelos:
                continue
            r, origen, incertidumbre = modelos[-1]
            futuro = dict(base)
            for k, v in r['efectos'].items():
                futuro[enlazar(k, a.entidad)] += v
            valor = deficit(base, necesidades) - deficit(futuro, necesidades) - 0.015 * a.coste - 0.01 * incertidumbre
            candidatos.append((valor, a, origen))
        # Se consume siempre el mismo número de sorteos por decisión en A/B/C.
        sorteo, desempate = self.rng.random(), self.rng.random()
        # La ausencia de déficit es observable sin conocer efectos de componentes.
        # También A puede esperar: no se le obliga a actuar por carecer de manual.
        if sorteo >= self.exploracion and deficit(base, necesidades) == 0:
            return None, dict(exploracion=False, origen='espera')
        if sorteo < self.exploracion or not candidatos:
            a = disponibles[min(int(desempate * len(disponibles)), len(disponibles) - 1)]
            return a, dict(exploracion=True, origen='exploracion')
        valor, a, origen = max(candidatos, key=lambda x: x[0])
        if valor <= 0:
            return None, dict(exploracion=False, origen='espera')
        return a, dict(exploracion=False, origen=origen)

    def observar(self, accion, antes, despues, contexto, fondo, aprender=True):
        predicciones = [(i, r) for i, r in self.memoria.relaciones() if aplicable(r, accion, antes, contexto)]
        empiricas = [r for r in self.memoria.empiricas() if aplicable(r, accion, antes, contexto)]
        return self.memoria.registrar(accion, antes, despues, contexto, fondo, predicciones,
                                     self.selector(accion), aprender, empiricas)
