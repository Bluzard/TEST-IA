"""Pruebas de abstraccion_estructural.py."""
import copy
import unittest

import numpy as np

from abstraccion_estructural import (
    FIRMA_DADA, MundoFamilia, SujetoAbstraccion, ciclos, con_piezas, estimar, firma, preparar_destino,
)
from entorno_componible import NA, NR, NP, N, puentes
from homeostato import DT, SATURACION

PUENTE = next(iter(FIRMA_DADA))


def trayectoria(mundo, P, pasos=300, semilla=0):
    rng = np.random.default_rng(semilla)
    W = rng.uniform(-1, 1, (NA, N))
    A = mundo.matriz(W, P)
    x, trans = rng.uniform(-0.3, 0.3, N), []
    for t in range(pasos):
        nuevo = np.clip(x + DT * (A @ x), -SATURACION, SATURACION)
        trans.append((x, nuevo))
        x = nuevo.copy()
        if t % 20 == 0:  # reinicios pequeños: excitan sin saturar
            x = rng.uniform(-0.3, 0.3, N)
    return A, trans


class AbstraccionTest(unittest.TestCase):
    def test_mundos_remapean_codigos(self):
        m = MundoFamilia(np.random.default_rng(3))
        puentes_por_mundo = []
        for k in range(3):
            m.ir(k)
            validos = {(a, b, c, d) for a in range(3) for b in range(3) for c in range(9) for d in range(9)
                       if m.puentes_de(np.array([a, b, c, d])) == {0, 1}}
            puentes_por_mundo.append(validos)
        self.assertEqual(len({len(v) for v in puentes_por_mundo}), 1)  # misma dificultad
        self.assertNotEqual(puentes_por_mundo[0], puentes_por_mundo[1])  # códigos distintos

    def test_estimar_recupera_la_dinamica_del_entorno(self):
        m = MundoFamilia(np.random.default_rng(1))
        A, trans = trayectoria(m, np.array([1, 2, 3, 5]))
        np.testing.assert_allclose(estimar(trans), A[NA:, NA:], atol=1e-6)

    def test_firma_ve_el_lazo_de_puente_solo_si_existe(self):
        m = MundoFamilia(np.random.default_rng(2))
        con = sin = None
        for codigos in np.ndindex(3, 3, 9, 9):
            P = np.array(codigos)
            if 0 in P:
                continue
            hay = bool(m.puentes_de(P))
            if hay and con is None:
                con = P
            if not hay and sin is None:
                sin = P
        for P, esperado in ((con, True), (sin, False)):
            A, trans = trayectoria(m, P)
            self.assertEqual(PUENTE in firma(estimar(trans)), esperado)

    def test_preparar_destino(self):
        e1 = [frozenset({PUENTE, (("R", "R"), 1)}), 0, True, 5]
        e2 = [frozenset({PUENTE, (("R", "R"), -1)}), 1, True, 5]
        h = SujetoAbstraccion(np.random.default_rng(0))
        for c, esperado in (("abstraccion_2", {PUENTE}), ("abstraccion_1", {PUENTE}),
                            ("firma_invertida", {(PUENTE[0], 1)}), ("sin_memoria", None)):
            hc = copy.deepcopy(h)
            preparar_destino(hc, c, e1, e2)
            self.assertEqual(None if hc.abstraccion is None else set(hc.abstraccion), esperado)
        self.assertEqual(con_piezas(e1[0] & e2[0]), {PUENTE})
        # Sin agencia: la abstracción de 1 arrastra el accidente del río; la de 2 lo filtra.
        for c, esperado in (("abstraccion_1_sin_agencia", e1[0]), ("abstraccion_2_sin_agencia", {PUENTE})):
            hc = copy.deepcopy(h)
            preparar_destino(hc, c, e1, e2)
            self.assertTrue(hc.exigir_todo)
            self.assertEqual(set(hc.abstraccion), set(esperado))

    def test_sin_agencia_exige_toda_la_abstraccion(self):
        m = MundoFamilia(np.random.default_rng(2))
        P = next(np.array(c) for c in np.ndindex(3, 3, 9, 9) if 0 not in c and m.puentes_de(np.array(c)))
        _, trans = trayectoria(m, P)
        h = SujetoAbstraccion(np.random.default_rng(0))
        h._t, h._trans, h.P = 0, trans, P.copy()
        h.exigir_todo, h.abstraccion = True, frozenset({PUENTE, (("R", "R", "R", "R", "R"), 1)})
        h._reconocer()
        self.assertIsNone(h.ventana)  # falta un rasgo: no reconoce
        h.abstraccion = frozenset({PUENTE})
        h._reconocer()
        self.assertIsNotNone(h.ventana)


if __name__ == "__main__":
    unittest.main()
