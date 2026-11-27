"""Cámara de regulación: física privada, catálogo observable y testimonio JSON."""
import random

from conocimiento_relacional import Accion


class Camara:
    def __init__(self, semilla, pasos, destino=False, permutar_roles=False):
        rng = random.Random(10_000 + semilla)
        self.canales = ['q0', 'q1', 'q2']
        self.necesidades = {k: [-0.25, 0.25] for k in self.canales}
        self.estado = {k: rng.uniform(-0.65, 0.65) for k in self.canales}
        roles = [f'r{rng.getrandbits(48):012x}' for _ in range(4)]
        self.acciones = []
        self._fisica = {}
        for j, (efecto, coste) in enumerate(((0.30, 0.8), (-0.30, 0.8), (0.16, 0.4), (-0.16, 0.4))):
            for k in self.canales:
                aid = f'{"nuevo" if destino else "original"}-{rng.getrandbits(48):012x}'
                rol = roles[(j + 1) % 4] if permutar_roles else roles[j]
                a = Accion(aid, dict(rol=rol, canal=k), 'activar', coste)
                self.acciones.append(a)
                self._fisica[aid] = (k, efecto)
        rng.shuffle(self.acciones)
        if destino:
            # Mismo mundo fuente subyacente; otras condiciones iniciales y deriva.
            self.estado = {k: -v * 1.15 for k, v in self.estado.items()}
            self.acciones.reverse()
        ruido = random.Random(20_000 + semilla)
        self._ruidos = [{k: ruido.uniform(-0.008, 0.008) for k in self.canales} for _ in range(pasos)]
        self._deriva = {k: rng.choice([-1, 1]) * (0.032 if destino else 0.025) for k in self.canales}
        self.pasos = pasos

    def contexto(self, t):
        return {'modo': 'seco' if t < self.pasos // 2 else 'humedo'}

    def fondo(self, t):
        return dict(self._deriva)

    def paso(self, accion, t):
        efecto = {}
        if accion is not None:
            k, v = self._fisica[accion.id]
            efecto[k] = v * (1.0 if self.contexto(t)['modo'] == 'seco' else 0.75)
        self.estado = {k: v + self._deriva[k] + self._ruidos[t][k] + efecto.get(k, 0)
                       for k, v in self.estado.items()}
        return dict(self.estado)

    def documentos(self, incorrectos=False):
        """Autor de la información; nunca se pasa esta función al intérprete."""
        relaciones = {}
        for a in self.acciones:
            _, delta = self._fisica[a.id]
            for modo, escala in [('seco', 1.0), ('humedo', 0.75)]:
                relaciones[a.entidad['rol'], modo] = dict(
                    selector={'rol': a.entidad['rol']}, operacion=a.operacion,
                    contexto={'modo': modo}, condiciones={},
                    efectos={'$canal': delta * escala * (-1 if incorrectos else 1)},
                    fuente='manual-del-proveedor', tolerancia=0.04)
        return list(relaciones.values())
