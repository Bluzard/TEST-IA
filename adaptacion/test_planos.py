"""Pruebas de persistencia, atribución local y aplicación parcial."""
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

import numpy as np

from biblioteca_planos import Biblioteca
from conocimiento_persistente import (
    SujetoPersistente, VERSION, contenido_concreto, huella_contexto,
    importar_planos, validar_concreto,
)
from entorno_componible import Mundo, Sujeto, NA, N
from experimento_planos import ejecutar, plano_ejemplo


class PlanosTest(unittest.TestCase):
    def test_reabrir_vectores_y_confianza(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'memoria.sqlite'
            with Biblioteca(ruta) as b:
                ctx = b.contexto([0.1, 0.3], VERSION)
                pid = b.guardar(plano_ejemplo('correcto'), origen='externo')
                for _ in range(12):
                    b.registrar(pid, ctx, True)
                stats = b.evidencia(pid, ctx)
            with Biblioteca(ruta) as b:
                self.assertEqual(b.evidencia(pid, ctx), stats)
                self.assertEqual(b.cercanos([0.1, 0.3], VERSION)[0], (ctx, 0.0))
                self.assertEqual(b.candidatos([0.1, 0.3], VERSION, ctx)[0]['id'], pid)
                self.assertEqual(b.guardar(plano_ejemplo('correcto'), origen='externo'), pid)

    def test_fallar_no_castiga_otro_contexto(self):
        with Biblioteca(':memory:') as b:
            a, z = b.contexto([0, 0], VERSION), b.contexto([1, 1], VERSION)
            pid = b.guardar(plano_ejemplo('incorrecto'), origen='externo')
            for _ in range(15):
                b.registrar(pid, a, True)
            antes = b.evidencia(pid, a)
            b.registrar(pid, z, False)
            self.assertEqual(b.evidencia(pid, a), antes)
            self.assertEqual(b.evidencia(pid, z), (1, 0, 0.25))

    def test_vecino_no_inventa_evidencia_local(self):
        with Biblioteca(':memory:') as b:
            a = b.contexto([0.1, 0.1], VERSION)
            z = b.contexto([0.11, 0.1], VERSION)
            pid = b.guardar(plano_ejemplo('correcto'))
            for _ in range(15):
                b.registrar(pid, a, True)
            candidato = b.candidatos([0.11, 0.1], VERSION, z)[0]
            self.assertEqual(candidato['stats'][0], 15)
            self.assertEqual(b.evidencia(pid, z)[0], 0)
            b.registrar(pid, z, False)
            self.assertEqual(b.evidencia(pid, z), (1, 0, 0.25))

    def test_version_dimension_y_radio(self):
        with Biblioteca(':memory:') as b:
            b.contexto([0, 0], VERSION)
            self.assertEqual(b.cercanos([0, 0], 'otra-version'), [])
            self.assertEqual(b.cercanos([0], VERSION), [])
            self.assertEqual(b.cercanos([1, 1], VERSION), [])
            for v in ([np.nan], [], [[0]]):
                with self.assertRaises(ValueError):
                    b.contexto(v, VERSION)

    def test_parcial_preserva_cuerpo_y_piezas_no_especificadas(self):
        with Biblioteca(':memory:') as b:
            h = SujetoPersistente(np.random.default_rng(1), b)
            h.P[:] = [0, 0, 3, 5]
            antes = h.W.copy()
            h._cargar(validar_concreto(plano_ejemplo('parcial')))
            np.testing.assert_array_equal(antes, h.W)
            np.testing.assert_array_equal(h.P, [1, 2, 3, 5])

    def test_importacion_valida_todo_antes_de_escribir(self):
        with tempfile.TemporaryDirectory() as carpeta, Biblioteca(':memory:') as b:
            ruta = Path(carpeta) / 'externos.json'
            documentos = [dict(tipo='concreto', contenido=plano_ejemplo('correcto')),
                          dict(tipo='concreto', contenido={'version': 'otra'})]
            ruta.write_text(json.dumps(documentos), encoding='utf-8')
            with self.assertRaises(ValueError):
                importar_planos(b, ruta)
            self.assertEqual(b.db.execute('SELECT COUNT(*) FROM planos').fetchone()[0], 0)
            documentos[1] = dict(tipo='abstracto', contenido={'roles': ['sensor', 'actuador']})
            ruta.write_text(json.dumps(documentos), encoding='utf-8')
            self.assertEqual(len(importar_planos(b, ruta)), 2)

    def test_abstracto_no_se_ejecuta(self):
        with Biblioteca(':memory:') as b:
            c = b.contexto([0], VERSION)
            b.guardar({'roles': ['sensor']}, tipo='abstracto', origen='externo')
            self.assertEqual(b.candidatos([0], VERSION, c), [])

    def test_configuraciones_invalidas(self):
        for valor in (np.inf, np.nan, 1.5, -1, 10, True):
            plano = plano_ejemplo('correcto')
            plano['configuracion'][-1] = valor
            with self.assertRaises(ValueError):
                validar_concreto(plano)

    def test_reinicio_sujeto_recupera_exito_propio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'propia.sqlite'
            # El mismo comienzo produce la misma huella antes de consultar memoria.
            with Biblioteca(ruta) as b:
                h = SujetoPersistente(np.random.default_rng(11), b)
                h.vivir(Mundo(np.random.default_rng(12)), 256, np.random.default_rng(13))
                h._guardar()
                pid = h.ids[0]
                h._premiar(0)
                huella = h.huella.copy()
            with Biblioteca(ruta) as b:
                nuevo = SujetoPersistente(np.random.default_rng(11), b)
                nuevo.vivir(Mundo(np.random.default_rng(12)), 256, np.random.default_rng(13))
                np.testing.assert_array_equal(huella, nuevo.huella)
                self.assertIn(pid, nuevo.ids)
                self.assertEqual(nuevo.recuperados, 1)
                self.assertEqual(nuevo.intentos[0], 1)

    def test_perturbaciones_independientes_de_busqueda(self):
        class MundoRegistrado(Mundo):
            def __init__(self):
                super().__init__(np.random.default_rng(5))
                self.empujes = []

            def empuje(self, rng):
                e = super().empuje(rng)
                self.empujes.append(None if e is None else e.copy())
                return e

        mundos = [MundoRegistrado(), MundoRegistrado()]
        for semilla, mundo in enumerate(mundos):
            Sujeto(np.random.default_rng(semilla)).vivir(mundo, 1500, np.random.default_rng(17))
        for a, b in zip(mundos[0].empujes, mundos[1].empujes):
            if a is None:
                self.assertIsNone(b)
            else:
                np.testing.assert_array_equal(a, b)

    def test_cli_simulacion_reproducible(self):
        with tempfile.TemporaryDirectory() as carpeta:
            a = ejecutar(Path(carpeta) / 'a.sqlite', 0, 1500, 'correcto')
            b = ejecutar(Path(carpeta) / 'b.sqlite', 0, 1500, 'correcto')
            self.assertEqual(a, b)
            self.assertGreater(a['externos'][0]['usos'], 0)

    def test_huella_sin_variacion_es_finita(self):
        np.testing.assert_array_equal(huella_contexto(np.zeros((256, 2))), np.zeros(7))

    def test_vida_real_guarda_y_reutiliza_solucion_propia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'vida.sqlite'
            primera = ejecutar(ruta, 0, 15000, 'correcto')
            segunda = ejecutar(ruta, 0, 15000)
            self.assertEqual(primera['contexto'], segunda['contexto'])
            self.assertGreater(segunda['recuperados'], primera['recuperados'])
            externos = {str(x['id']) for x in segunda['externos']}
            self.assertTrue(any(pid not in externos for pid in segunda['usos']))
            self.assertIsNotNone(segunda['primer_puente_estable'])

    def test_version_futura_no_se_reescribe(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'futura.sqlite'
            with closing(sqlite3.connect(ruta)) as db:
                db.execute('PRAGMA user_version=99')
            with self.assertRaises(ValueError):
                Biblioteca(ruta)
            with closing(sqlite3.connect(ruta)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)


if __name__ == '__main__':
    unittest.main()
