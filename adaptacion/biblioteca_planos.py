"""Memoria externa SQLite: vectores perceptivos, planos y evidencia local.

No usa embeddings ni extensiones SQLite. La búsqueda exacta NumPy es O(n).
Los grafos abstractos se pueden conservar, pero no se ejecutan como planos.
"""
import hashlib
import json
import sqlite3

import numpy as np


class Biblioteca:
    def __init__(self, ruta):
        self.db = sqlite3.connect(str(ruta))
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError(f"Versión de biblioteca no compatible: {version}")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS contextos (
                id INTEGER PRIMARY KEY, version TEXT NOT NULL,
                dimension INTEGER NOT NULL, huella BLOB NOT NULL,
                UNIQUE(version, dimension, huella));
            CREATE TABLE IF NOT EXISTS planos (
                id INTEGER PRIMARY KEY, tipo TEXT NOT NULL,
                contenido TEXT NOT NULL, origen TEXT NOT NULL,
                firma TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS confianza (
                plano_id INTEGER NOT NULL REFERENCES planos(id),
                contexto_id INTEGER NOT NULL REFERENCES contextos(id),
                intentos INTEGER NOT NULL DEFAULT 0,
                logros INTEGER NOT NULL DEFAULT 0,
                reciente REAL NOT NULL DEFAULT 0.5,
                PRIMARY KEY(plano_id, contexto_id));
            CREATE INDEX IF NOT EXISTS confianza_contexto ON confianza(contexto_id);
            PRAGMA user_version = 1;
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    @staticmethod
    def _vector(huella):
        v = np.asarray(huella, dtype="<f8")
        if v.ndim != 1 or not v.size or not np.isfinite(v).all():
            raise ValueError("La huella debe ser un vector finito no vacío")
        return v

    def contexto(self, huella, version):
        v = self._vector(huella)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO contextos(version,dimension,huella) VALUES(?,?,?)",
                (version, v.size, v.tobytes()))
        return self.db.execute(
            "SELECT id FROM contextos WHERE version=? AND dimension=? AND huella=?",
            (version, v.size, v.tobytes())).fetchone()[0]

    def cercanos(self, huella, version, limite=5, radio=0.25):
        v = self._vector(huella)
        filas = self.db.execute(
            "SELECT id,huella FROM contextos WHERE version=? AND dimension=?",
            (version, v.size)).fetchall()
        distancias = [(i, float(np.sqrt(np.mean((np.frombuffer(b, dtype='<f8') - v)**2))))
                      for i, b in filas]
        return sorted(((i, d) for i, d in distancias if d <= radio),
                      key=lambda x: (x[1], x[0]))[:limite]

    def guardar(self, contenido, tipo="concreto", origen="propio"):
        if tipo not in ("concreto", "abstracto") or origen not in ("propio", "externo"):
            raise ValueError("Tipo u origen inválido")
        if not isinstance(contenido, dict):
            raise ValueError("El contenido debe ser un objeto JSON")
        serial = json.dumps(contenido, sort_keys=True, separators=(",", ":"), allow_nan=False)
        firma = hashlib.sha256((tipo + origen + serial).encode()).hexdigest()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO planos(tipo,contenido,origen,firma) VALUES(?,?,?,?)",
                (tipo, serial, origen, firma))
        return self.db.execute("SELECT id FROM planos WHERE firma=?", (firma,)).fetchone()[0]

    def evidencia(self, plano, contexto):
        fila = self.db.execute(
            "SELECT intentos,logros,reciente FROM confianza WHERE plano_id=? AND contexto_id=?",
            (plano, contexto)).fetchone()
        return fila if fila is not None else (0, 0, 0.5)

    def asociar(self, plano, contexto):
        """Conserva una configuración estable sin inventar un intento completo."""
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO confianza(plano_id,contexto_id) VALUES(?,?)",
                (plano, contexto))

    def registrar(self, plano, contexto, exito, aspiracion=0.9):
        # Solo evidencia observada aquí; nunca copia los contadores de otro contexto.
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO confianza(plano_id,contexto_id) VALUES(?,?)",
                (plano, contexto))
            n, s, r = self.evidencia(plano, contexto)
            n, s = n + 1, s + int(bool(exito))
            if not exito:
                r *= 0.5
            elif (s + 1) / (n + 2) >= aspiracion:
                r += 0.3 * (1 - r)
            self.db.execute(
                "UPDATE confianza SET intentos=?,logros=?,reciente=? WHERE plano_id=? AND contexto_id=?",
                (n, s, r, plano, contexto))
        return n, s, r

    def candidatos(self, huella, version, contexto, limite=32):
        vecinos = self.cercanos(huella, version)
        evidencia = {}
        for cid, distancia in vecinos:
            for pid, n, s, r in self.db.execute(
                    "SELECT plano_id,intentos,logros,reciente FROM confianza WHERE contexto_id=?", (cid,)):
                # El vecino más cercano con evidencia decide el prior de recuperación.
                if pid not in evidencia:
                    evidencia[pid] = (distancia, n, s, r)
        opciones = []
        for pid, contenido, origen in self.db.execute(
                "SELECT id,contenido,origen FROM planos WHERE tipo='concreto'"):
            local = self.evidencia(pid, contexto)
            if local[0]:
                stats, distancia = local, 0.0
            elif pid in evidencia:
                distancia, *stats = evidencia[pid]
            elif origen == "externo":
                stats, distancia = (0, 0, 0.5), 0.0
            else:
                continue
            score = max(stats[2], 1e-3) / (1 + distancia)
            opciones.append(dict(id=pid, contenido=json.loads(contenido), origen=origen,
                                 stats=tuple(stats), score=score))
        return sorted(opciones, key=lambda x: (-x['score'], x['id']))[:limite]
