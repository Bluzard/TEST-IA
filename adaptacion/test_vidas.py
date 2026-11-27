"""Pruebas de vidas_sucesivas.py."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from abstraccion_estructural import FIRMA_DADA, MundoFamilia, estimar
from entorno_componible import ANCLAS, NP, decodificar_apoyo
from test_abstraccion import trayectoria
from vidas_sucesivas import Memoria, SujetoVidas

PUENTE = next(iter(FIRMA_DADA))


def rol_verdadero(mundo, ranura, codigo):
    v = mundo.mapa[ranura][codigo]
    if ranura < ANCLAS:
        return ("A", int(v) - 1)
    j, f, s = decodificar_apoyo(int(v))
    return ("B", j, f, s)


def sujeto(carpeta, condicion="completo"):
    with Memoria(Path(carpeta) / "m.sqlite") as m:
        return SujetoVidas(np.random.default_rng(0), m, condicion)


class VidasTest(unittest.TestCase):
    def test_abduce_roles_verdaderos(self):
        m = MundoFamilia(np.random.default_rng(4), n_mundos=2)
        P = np.array([1, 2, 3, 6])
        _, trans = trayectoria(m, P)
        with tempfile.TemporaryDirectory() as c:
            h = sujeto(c)
        h.P = P.copy()
        h._abducir_roles(estimar(trans))
        for (ranura, codigo), rol in h.roles.items():
            verdad = rol_verdadero(m, ranura, codigo)
            self.assertEqual(rol[0], verdad[0])
            self.assertTrue(all(x is None or x == y for x, y in zip(rol[1:], verdad[1:])), (rol, verdad))
        self.assertEqual(len(h.roles), 4)

    def test_deduce_un_puente_nunca_probado(self):
        m = MundoFamilia(np.random.default_rng(5), n_mundos=2)
        with tempfile.TemporaryDirectory() as c:
            h = sujeto(c)
        h.abstraccion, h.soporte = frozenset({PUENTE}), {PUENTE: 1}
        # Roles verdaderos de todos los códigos, conocidos por separado: ningún arreglo armado.
        for ranura in range(NP):
            for codigo in range(1, len(m.mapa[ranura])):
                h.roles[(ranura, codigo)], h.origen_rol[(ranura, codigo)] = rol_verdadero(m, ranura, codigo), "visto"
        fijo, bloqueo = h._deducir()
        P = np.zeros(NP, dtype=int)
        for ranura, c in fijo:
            P[ranura] = c
        self.assertTrue(m.puentes_de(P))

    def test_mundo_adoptado_se_descarta_ante_contradiccion(self):
        with tempfile.TemporaryDirectory() as c:
            h = sujeto(c)
        h.pasados = {1: {(0, 1): ("A", 0), (2, 3): ("B", 0, 0, -1), (3, 5): ("B", 1, 1, -1)}}
        h._ver((0, 1), ("A", 0))
        h._ver((2, 3), ("B", 0, 0, -1))
        h._abducir_mundo()
        self.assertEqual(h.adopcion, 1)
        self.assertEqual(h.origen_rol[(3, 5)], "adoptado")
        h._ver((3, 5), ("B", 1, 1, 1))  # el signo contradice lo adoptado
        self.assertIsNone(h.adopcion)
        self.assertIn(1, h.descartadas)
        self.assertEqual(h.roles[(3, 5)], ("B", 1, 1, 1))

    def test_memoria_persiste_entre_ejecuciones(self):
        with tempfile.TemporaryDirectory() as c:
            db = Path(c) / "memoria.sqlite"
            for vida in (1, 2):
                r = subprocess.run([sys.executable, "vidas_sucesivas.py", "vivir", "--db", str(db), "--vida",
                                    str(vida), "--semilla", "2", "--pasos", "20000"],
                                   capture_output=True, text=True, cwd=Path(__file__).parent, check=True)
            self.assertIn('"vida": 2', r.stdout)
            with Memoria(db) as m:
                self.assertEqual(m.vidas_previas(), 2)
                self.assertTrue(m.roles())


if __name__ == "__main__":
    unittest.main()
