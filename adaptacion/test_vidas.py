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
        fijo, bloqueo, soporte = h._deducir()
        self.assertEqual(soporte, 1)
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

    def test_cuerpo_heredado_y_pareo(self):
        with tempfile.TemporaryDirectory() as c:
            ruta = Path(c) / "m.sqlite"
            with Memoria(ruta) as m:
                W = np.full((4, 10), 0.25)
                m.cerrar_vida(0, None, frozenset(), {}, W)
                h = SujetoVidas(np.random.default_rng(1), m, "deduccion_cuerpo")
                n = SujetoVidas(np.random.default_rng(1), m, "deduccion")
                w = SujetoVidas(np.random.default_rng(1), m, "completo_cuerpo_mundo")
            np.testing.assert_array_equal(h.W, W)
            self.assertTrue(h.cuerpo_heredado)
            self.assertEqual(h.rng.random(), n.rng.random())  # mismo azar después de nacer
            # Cuerpo por mundo: nace nuevo; al adoptar la vida 1 recupera su cuerpo en la próxima caída.
            self.assertFalse(np.array_equal(w.W, W))
            w.pasados = {1: {(0, 1): ("A", 0), (2, 3): ("B", 0, 0, -1)}}
            w._ver((0, 1), ("A", 0))
            w._ver((2, 3), ("B", 0, 0, -1))
            w._abducir_mundo()
            w._explorar_unidad(0, MundoFamilia(np.random.default_rng(0), n_mundos=2))
            np.testing.assert_array_equal(w.W, W)

    def test_paciencia_segun_confianza(self):
        m = MundoFamilia(np.random.default_rng(5), n_mundos=2)
        for condicion, esperado in (("deduccion", 20), ("deduccion_paciencia", 20 * 4)):
            with tempfile.TemporaryDirectory() as c:
                h = sujeto(c, condicion)
            h._t, h.abstraccion, h.soporte = 0, frozenset({PUENTE}), {PUENTE: 3}
            for ranura in range(NP):
                for codigo in range(1, len(m.mapa[ranura])):
                    h.roles[(ranura, codigo)], h.origen_rol[(ranura, codigo)] = rol_verdadero(m, ranura, codigo), "visto"
            h._explorar_unidad(0, m)
            self.assertEqual(h.ventana["presupuesto"], esperado)
            self.assertTrue(h.ventana["es_puente"])


if __name__ == "__main__":
    unittest.main()
