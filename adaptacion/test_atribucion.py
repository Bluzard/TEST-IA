"""Pruebas de la ventana de acoplamiento (atribucion_fallo.py)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from atribucion_fallo import SujetoAtribucion, ejecutar as ejecutar_atribucion
from biblioteca_planos import Biblioteca
from conocimiento_persistente import validar_concreto
from entorno_componible import Mundo, NA, N
from experimento_planos import ejecutar as ejecutar_original, plano_ejemplo

VIDA = 4000


def vida(modo, condicion="correcto", semilla=3, r_max=5):
    b = Biblioteca(":memory:")
    pid = b.guardar(plano_ejemplo(condicion), origen="externo")
    h = SujetoAtribucion(np.random.default_rng(60_000 + semilla), b, modo, r_max)
    caidas, _, _ = h.vivir(Mundo(np.random.default_rng(50_000 + semilla)), VIDA,
                           np.random.default_rng(70_000 + semilla))
    return b, pid, h, caidas


class AtribucionTest(unittest.TestCase):
    def test_inmediato_reproduce_el_original(self):
        for semilla in (0, 1, 2):
            for condicion in ("sin_plano", "correcto"):
                with tempfile.TemporaryDirectory() as carpeta:
                    o = ejecutar_original(Path(carpeta) / "x.sqlite", semilla, VIDA, condicion)
                n = ejecutar_atribucion((semilla, VIDA, condicion, "inmediato", 20))
                self.assertEqual(o["pasos_con_caida"], n["pasos_con_caida"])
                self.assertEqual(o["primer_puente_estable"], n["primer_puente_estable"])
                self.assertEqual(o["fraccion_con_puente"], n["fraccion_con_puente"])

    def test_sin_plano_los_tres_modos_coinciden(self):
        filas = [ejecutar_atribucion((1, VIDA, "sin_plano", m, 20)) for m in ("inmediato", "paciencia_fija", "progreso")]
        self.assertEqual(len({x["pasos_con_caida"] for x in filas}), 1)

    def test_caida_en_ventana_no_toca_sqlite_y_bloquea_piezas(self):
        b = Biblioteca(":memory:")
        pid = b.guardar(plano_ejemplo("correcto"), origen="externo")
        h = SujetoAtribucion(np.random.default_rng(0), b, "progreso", r_max=3)
        h.mejor_racha, h.registro, h.ventanas, h._t = {}, {}, [], 10
        h.contexto = b.contexto([0.1, 0.2], "v")
        plano = validar_concreto(plano_ejemplo("correcto"))
        h._agregar(plano, pid, (0, 0, 0.5))
        h._cargar(plano)
        h.ventana = None
        h._abrir_ventana(0)
        mundo = Mundo(np.random.default_rng(1))
        fuera = np.ones(NA, dtype=bool)
        W_antes = h.W.copy()
        self.assertTrue(h._acoplar(fuera, 0, mundo))
        self.assertEqual(list(h.P), [1, 2, 2, 8])
        self.assertFalse(np.array_equal(W_antes, h.W))
        self.assertEqual(b.evidencia(pid, h.contexto), (0, 0, 0.5))

    def test_presupuesto_fijo_se_agota_y_progreso_lo_renueva(self):
        for modo in ("paciencia_fija", "progreso"):
            b = Biblioteca(":memory:")
            pid = b.guardar(plano_ejemplo("correcto"), origen="externo")
            h = SujetoAtribucion(np.random.default_rng(0), b, modo, r_max=3)
            h.mejor_racha, h.registro, h.ventanas, h._t = {}, {}, [], 1
            h._agregar(validar_concreto(plano_ejemplo("correcto")), pid, (0, 0, 0.5))
            h.ventana = None
            h._abrir_ventana(0)
            mundo, fuera = Mundo(np.random.default_rng(1)), np.ones(NA, dtype=bool)
            # Rachas: 5 (mejora), 2, 2, 7 (mejora), 1, 1, 1 ...
            usadas = 0
            for racha in (5, 2, 2, 7, 1, 1, 1, 1, 1):
                if not h._acoplar(fuera, racha, mundo):
                    break
                usadas += 1
            # B: 3 reconfiguraciones y atribuye. C: renueva en 5 (3) y en 7 (3) -> atribuye en la 7.ª caída
            self.assertEqual(usadas, {"paciencia_fija": 3, "progreso": 6}[modo])
            self.assertIsNone(h.ventana)
            self.assertEqual(h.ventanas[-1]["motivo"], "agotado")

    def test_ventana_evita_castigo_temprano(self):
        _, _, inmediato, _ = vida("inmediato")
        _, _, progreso, _ = vida("progreso")
        for h in (inmediato, progreso):
            self.assertTrue(all(np.isnan(h.repertorio[k][:NA * N]).any() == h._plantilla(k)
                                for k in range(len(h.repertorio))))
        ri = next(iter(inmediato.registro.values()), None)
        rp = next(iter(progreso.registro.values()), None)
        if ri and ri["cargas"] and rp and rp["cargas"]:
            self.assertGreaterEqual(ri["castigos"], rp["castigos"])


if __name__ == "__main__":
    unittest.main()
