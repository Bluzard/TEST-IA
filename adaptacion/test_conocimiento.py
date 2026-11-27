"""Pruebas de contratos y controles del mecanismo relacional."""
from pathlib import Path
import tempfile
import unittest

from conocimiento_relacional import Accion, Interprete, MemoriaRelacional, aplicable
from entorno_regulacion import Camara
from experimento_conocimiento import comparar, vivir


def relacion():
    return dict(selector={'tipo': 'opaco'}, operacion='pulsar', contexto={'ambiente': 'x'},
                condiciones={'$destino': [-2, 2]}, efectos={'$destino': -0.5},
                fuente='documento-prueba', tolerancia=0.05)


class ConocimientoTest(unittest.TestCase):
    def test_propiedades_arbitrarias_y_condiciones(self):
        a = Accion('nuevo', {'tipo': 'opaco', 'destino': 'presion'}, 'pulsar', 0.4)
        r = relacion()
        with MemoriaRelacional() as m:
            m.importar([r])
            agente = Interprete(m, 1, atributos=('tipo',), exploracion=0)
            elegido, info = agente.proponer({'presion': 1}, {'presion': [-0.1, 0.1]}, [a],
                                             {'ambiente': 'x'}, {}, 1)
            self.assertEqual(elegido, a)
            self.assertEqual(info['origen'], 'externo')
            self.assertFalse(aplicable(r, a, {'presion': 3}, {'ambiente': 'x'}))
            self.assertFalse(aplicable(r, a, {'presion': 1}, {'ambiente': 'y'}))
            self.assertFalse(aplicable(r, a, {'otro': 1}, {'ambiente': 'x'}))
            self.assertIsNone(agente.proponer({'presion': 1}, {'presion': [-0.1, 0.1]}, [a],
                                            {'ambiente': 'x'}, {}, 0.1)[0])

    def test_importacion_atomica_y_datos_invalidos(self):
        with MemoriaRelacional() as m:
            for campo, valor in [('tolerancia', 0), ('efectos', {'x': float('nan')}),
                                  ('condiciones', {'x': [2, 1]}), ('selector', {}),
                                  ('fuente', ''), ('efectos', {'x': True})]:
                mala = relacion()
                mala[campo] = valor
                with self.assertRaises(ValueError):
                    m.importar([relacion(), mala])
                self.assertEqual(m.relaciones(), [])
            with self.assertRaises(ValueError):
                Accion('a', {}, 'op', -1)

    def test_esperar_sin_manual_si_no_hay_necesidad(self):
        with MemoriaRelacional() as m:
            a = Accion('a', {'rol': 'x'}, 'activar', 0.4)
            i = Interprete(m, 1, exploracion=0)
            self.assertIsNone(i.proponer({'z': 0}, {'z': [-1, 1]}, [a], {}, {}, 1)[0])

    def test_persistencia_contradiccion_y_contexto_local(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'memoria.sqlite'
            a = Accion('uno', {'tipo': 'opaco', 'destino': 'presion'}, 'pulsar', 0.4)
            with MemoriaRelacional(ruta) as m:
                m.importar([relacion()])
                i = Interprete(m, 1, atributos=('tipo',), exploracion=0)
                # Predice reducción, pero realmente aumenta; fondo 0.1 se descuenta.
                evidencia = i.observar(a, {'presion': 1}, {'presion': 1.6}, {'ambiente': 'x'}, {'presion': 0.1})
                self.assertTrue(evidencia[0]['contradice'])
                self.assertAlmostEqual(evidencia[0]['error'], 1)
                self.assertEqual(m.relaciones()[0][1], relacion())
                self.assertAlmostEqual(m.empiricas()[0]['efectos']['$destino'], 0.5)
            with MemoriaRelacional(ruta) as m:
                self.assertEqual(m.db.execute('SELECT favor,contra FROM evidencia').fetchone(), (0, 1))
                self.assertEqual(m.db.execute('SELECT count(*) FROM experiencias').fetchone()[0], 1)
                self.assertFalse(aplicable(m.empiricas()[0], a, {'presion': 1}, {'ambiente': 'y'}))
                # La predicción corregida hace que espere ante una presión ya alta.
                i = Interprete(m, 1, atributos=('tipo',), exploracion=0)
                self.assertIsNone(i.proponer({'presion': 1}, {'presion': [-0.1, 0.1]}, [a],
                                            {'ambiente': 'x'}, {}, 1)[0])

    def test_transferencia_solo_hipotesis_y_nuevos_nombres(self):
        with MemoriaRelacional() as fuente, MemoriaRelacional() as destino:
            a = Accion('viejo', {'tipo': 'opaco', 'destino': 'presion'}, 'pulsar', 0.4)
            fuente.importar([relacion()])
            fuente.hecho({'secreto': 'viejo'})
            i = Interprete(fuente, 0, atributos=('tipo',))
            i.observar(a, {'presion': 1}, {'presion': 0.5}, {'ambiente': 'x'}, {})
            fuente.transferir(destino)
            self.assertEqual(destino.relaciones(), [])
            for tabla in ('hechos', 'experiencias', 'evidencia'):
                self.assertEqual(destino.db.execute(f'SELECT count(*) FROM {tabla}').fetchone()[0], 0)
            nuevo = Accion('otro', {'tipo': 'opaco', 'destino': 'voltaje'}, 'pulsar', 0.4)
            agente = Interprete(destino, 1, atributos=('tipo',), exploracion=0)
            self.assertEqual(agente.proponer({'voltaje': 1}, {'voltaje': [-0.1, 0.1]}, [nuevo],
                                           {'ambiente': 'x'}, {}, 1)[0], nuevo)

    def test_conocimiento_no_consulta_fisica(self):
        mundo = Camara(7, 40)
        docs = mundo.documentos()
        # Cambiar la física no cambia los documentos ya recibidos ni la decisión.
        estado = dict(mundo.estado)
        with MemoriaRelacional() as m:
            m.importar(docs)
            a = Interprete(m, 2, exploracion=0).proponer(estado, mundo.necesidades, mundo.acciones,
                                                      mundo.contexto(0), mundo.fondo(0), 1)
            mundo._fisica = {k: (canal, -delta) for k, (canal, delta) in mundo._fisica.items()}
            b = Interprete(m, 2, exploracion=0).proponer(estado, mundo.necesidades, mundo.acciones,
                                                      mundo.contexto(0), mundo.fondo(0), 1)
            self.assertEqual(a, b)

    def test_pareamiento_y_destino(self):
        for seed in (0, 9):
            fuente, destino = Camara(seed, 40), Camara(seed, 40, destino=True)
            control = Camara(seed, 40, destino=True, permutar_roles=True)
            self.assertTrue(set(a.id for a in fuente.acciones).isdisjoint(a.id for a in destino.acciones))
            self.assertEqual(destino._fisica, control._fisica)
            self.assertEqual(destino.estado, control.estado)
            self.assertEqual(destino._ruidos, control._ruidos)
            self.assertEqual(destino.fondo(0), control.fondo(0))

    def test_ablacion_no_aprende_pero_audita(self):
        with MemoriaRelacional() as m:
            resultado = vivir(m, 3, 40, Camara(3, 40).documentos(True), aprender=False)
            self.assertEqual(m.empiricas(), [])
            self.assertGreater(resultado['contradicciones'], 0)
            self.assertGreater(m.db.execute('SELECT count(*) FROM experiencias').fetchone()[0], 0)

    def test_hipotesis_transferida_tambien_se_contrasta(self):
        a = Accion('a', {'tipo': 'opaco', 'destino': 'p'}, 'pulsar', 0.4)
        with MemoriaRelacional() as fuente, MemoriaRelacional() as destino:
            Interprete(fuente, 0, atributos=('tipo',)).observar(a, {'p': 1}, {'p': 0.5}, {}, {})
            fuente.transferir(destino)
            resultados = Interprete(destino, 0, atributos=('tipo',)).observar(a, {'p': 1}, {'p': 1.5}, {}, {})
            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]['tipo'], 'empirico')
            self.assertTrue(resultados[0]['contradice'])
            self.assertEqual(destino.db.execute('SELECT favor,contra FROM evidencia_hipotesis').fetchone(), (0, 1))

    def test_reproduccion_experimento_y_cobertura(self):
        a, b = comparar(2, 40, 0), comparar(2, 40, 0)
        self.assertEqual(a, b)
        self.assertEqual(len(a['vidas']), 16)
        self.assertEqual({r['condicion'] for r in a['vidas']},
                         {'A', 'B', 'C', 'B_fijo', 'C_fijo', 'D', 'D_vacio', 'D_roles_permutados'})
        self.assertTrue(all(0 <= r['satisfaccion'] <= 1 for r in a['vidas']))


if __name__ == '__main__':
    unittest.main()
