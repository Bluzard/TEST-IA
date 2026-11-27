"""Pruebas de prueba_larga_componible.py: equivalencia y reglas de contexto."""
import unittest

import numpy as np

from atribucion_fallo import ejecutar as ejecutar_atribucion
from biblioteca_planos import Biblioteca
from conocimiento_persistente import VERSION, VENTANA_CONTEXTO
from entorno_componible import Mundo, Sujeto
from experimento_planos import plano_ejemplo
from prueba_larga_componible import MundoCambiante, SujetoBase, SujetoLargo, ejecutar

VIDA = 4000


class PruebaLargaTest(unittest.TestCase):
    def test_base_sin_cambios_reproduce_sujeto_original(self):
        for s in (0, 1):
            o = Sujeto(np.random.default_rng(60_000 + s)).vivir(
                Mundo(np.random.default_rng(50_000 + s), con_piezas=False), VIDA, np.random.default_rng(70_000 + s))[0]
            n = SujetoBase(np.random.default_rng(60_000 + s)).vivir(
                MundoCambiante(np.random.default_rng(50_000 + s), VIDA, con_piezas=False, recorrido=(0,)),
                VIDA, np.random.default_rng(70_000 + s))[0]
            self.assertEqual(o, n)

    def test_A_fijo_sin_cambios_reproduce_atribucion(self):
        for s in (0, 2):
            o = ejecutar_atribucion((s, VIDA, "correcto", "inmediato", 20))
            with Biblioteca(":memory:") as b:
                b.guardar(plano_ejemplo("correcto"), origen="externo")
                h = SujetoLargo(np.random.default_rng(60_000 + s), b, "inmediato", False)
                caidas, _, _ = h.vivir(MundoCambiante(np.random.default_rng(50_000 + s), VIDA, recorrido=(0,)),
                                       VIDA, np.random.default_rng(70_000 + s))
            self.assertEqual(o["pasos_con_caida"], len(caidas))

    def test_revisita_usa_el_mismo_terreno(self):
        m = MundoCambiante(np.random.default_rng(5), 5000)
        primero = m.filas_rio.copy()
        vistos = [m.cambio_en(t) for t in sorted(m.cambios)]
        self.assertEqual(vistos, [1, 0, 2, 1])
        self.assertTrue(np.array_equal(m.terrenos[0], primero))
        self.assertFalse(np.array_equal(m.terrenos[1], m.terrenos[0]))

    def test_evidencia_incierta_no_se_anota_y_racha_por_contexto(self):
        with Biblioteca(":memory:") as b:
            pid = b.guardar(plano_ejemplo("correcto"), origen="externo")
            h = SujetoLargo(np.random.default_rng(0), b, "progreso", True, radio=0.05)
            h.mejor_racha, h.registro, h.ventanas, h._t, h.fases = {}, {}, [], 1, [dict(revisita=False)]
            h._obs, h.huellas, h.contextos_vistos, h._contexto_nuevo = None, [], [], False
            h._fijar_contexto(np.full(7, 0.1), 300)
            ctx = h.contexto
            self.assertEqual(h.ids, [pid])
            h._inestabilidad(400)  # empieza a observar: contexto incierto
            h._castigar(0)
            self.assertEqual(b.evidencia(pid, ctx), (0, 0, 0.5))
            self.assertEqual(h._clave_racha(pid), (pid, ctx))
            for _ in range(VENTANA_CONTEXTO):
                h.x[4:6] = 0.9
                h._observar(500)
            self.assertNotEqual(h.contexto, ctx)  # huella lejana -> contexto nuevo
            self.assertTrue(h._contexto_nuevo)
            self.assertNotEqual(h._clave_racha(pid), (pid, ctx))
            h._castigar(0)
            self.assertEqual(b.evidencia(pid, h.contexto)[0], 1)
            self.assertEqual(b.evidencia(pid, ctx), (0, 0, 0.5))

    def test_vida_corta_completa(self):
        for c in ("sin_piezas", "A_fijo", "C_contexto"):
            r = ejecutar((3, 6000, c, "correcto", 0.05))
            self.assertEqual(len(r["fases"]), 5)
            self.assertEqual([f["revisita"] for f in r["fases"]], [False, False, True, False, True])


if __name__ == "__main__":
    unittest.main()
