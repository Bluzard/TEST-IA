"""Prueba 10: aprender de los errores, propios y ajenos.

Base: "satisfecho 90 %" (aspiración + desconfiar rápido + no buscar si está
satisfecho). K sujetos con el mismo cuerpo viven juntos el mismo río (mismas
crecidas; cada uno con sus propias perturbaciones menores). Cruzan el río 1
y luego uno distinto, con lo que aprendieron.

Variantes:
  solo            sin aprender de errores ni de otros (referencia)
  a1              no vuelve a EXPLORAR una configuración exacta que ya falló
  a2              a1 + no vuelve a RECORDAR una solución que alguna vez falló
  c1 caídas       a1 + cuando otro cae: anota su configuración como fallida
                  y, si la tiene guardada, le baja la confianza
  c2 éxitos       cuando otro se estabiliza, copia su solución (contraste)
  c3 ambos        c1 + c2

Mediciones por sujeto y río: caídas, caídas del primer tramo, puente (último
tramo sin caídas), % del tiempo en pie, si se estabilizó alguna vez y si al
final se sostiene saturando el entorno.
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from homeostato import DT, LIMITE, SATURACION, VENTANA_ESTABLE, CADA_PERTURBACION
from homeostato_memoria import FUERZA
from aspiracion import INTENTO
from aspiracion_100 import Satisfecho, fisher
import puente

K = 4
GRUPOS = 25
VIDA = 300_000
REINTENTOS_TABU = 50

VARIANTES = {
    "solo": dict(),
    "a1 tabú al explorar": dict(tabu_explorar=True),
    "a2 tabú explorar+recordar": dict(tabu_explorar=True, tabu_recordar=True),
    "c1 caídas ajenas": dict(tabu_explorar=True, ver_caidas=True),
    "c2 éxitos ajenos": dict(ver_exitos=True),
    "c3 caídas+éxitos ajenos": dict(tabu_explorar=True, ver_caidas=True, ver_exitos=True),
}


class Sujeto(Satisfecho):
    def __init__(self, rng, tabu_explorar=False, tabu_recordar=False, ver_caidas=False, ver_exitos=False):
        super().__init__(4, 2, rng, 0.90)
        self.tabu_explorar = tabu_explorar
        self.tabu_recordar = tabu_recordar
        self.ver_caidas = ver_caidas
        self.ver_exitos = ver_exitos
        self.tabu: set[bytes] = set()
        self.excluidos: set[int] = set()
        self.evitadas = 0
        self.actual, self.desde, self.sin_violar = None, 0, 0
        self.nuevo_rio()

    def nuevo_rio(self):
        self.caidas, self.en_pie, self.se_estabilizo = [], 0, False

    # --- memoria filtrada por lo que falló ---
    def _candidatos(self):
        return [k for k in range(len(self.repertorio)) if k not in self.excluidos]

    def _satisfactorias(self):
        return [k for k in self._candidatos() if self.tasa(k) >= self.aspiracion]

    def p_recordar(self):
        cand = self._candidatos()
        if not cand:
            return 0.0
        if self._satisfactorias():
            return 1.0
        return min(1.0, max(self.rapida[k] for k in cand))

    def _agregar(self, W):
        """Agrega una solución al repertorio si es nueva; devuelve su índice."""
        for k, m in enumerate(self.repertorio):
            if np.array_equal(W, m):
                return k
        guardada = self.W
        self.W = W.copy()
        self._guardar()
        self.W = guardada
        return len(self.repertorio) - 1

    # --- un paso de vida ---
    def paso(self, t, filas, empuje):
        """Devuelve (configuración con la que cayó o None, solución guardada o None)."""
        A = np.vstack([self.W, filas])
        self.x = np.clip(self.x + DT * (A @ self.x + empuje), -SATURACION, SATURACION)
        if t % CADA_PERTURBACION == 0:
            self.x += self.rng.normal(0, puente.PERTURBACION_NORMAL, self.x.size)

        fuera = np.abs(self.x[: self.na]) > LIMITE
        if fuera.any():
            return self._caer(t, fuera), None
        self.en_pie += 1
        self.sin_violar += 1
        guardada = None
        if self.sin_violar == VENTANA_ESTABLE:
            self.se_estabilizo = True
            if self.actual is None:
                self._guardar()
                self.actual, self.desde = self._indice(), t
                guardada = self.W.copy()
        if self.actual is not None and t - self.desde >= INTENTO:
            self._premiar(self.actual)
            self.desde = t
        return None, guardada

    def _caer(self, t, fuera):
        self.caidas.append(t)
        self.sin_violar = 0
        fallida = self.W.copy()
        if self.tabu_explorar:
            self.tabu.add(fallida.tobytes())
        if self.actual is not None:
            self._castigar(self.actual)
            if self.tabu_recordar:
                self.excluidos.add(self.actual)
            self.actual = None

        cand = self._candidatos()
        if cand and self.rng.random() < self.p_recordar():
            w = np.array([self._peso(k) for k in cand])
            self.actual = cand[int(self.rng.choice(len(cand), p=w / w.sum()))]
            self.W = self.repertorio[self.actual].copy()
            self.desde = t
        else:
            for _ in range(REINTENTOS_TABU):
                self._explorar(fuera)
                if not self.tabu_explorar or self.W.tobytes() not in self.tabu:
                    break
                self.evitadas += 1
        self.x[: self.na][fuera] *= 0.5
        return fallida

    # --- aprender de otros ---
    def observar(self, caida, guardada):
        if caida is not None and self.ver_caidas:
            self.tabu.add(caida.tobytes())
            for k, m in enumerate(self.repertorio):
                if np.array_equal(caida, m):
                    self._castigar(k)
        if guardada is not None and self.ver_exitos:
            self._agregar(guardada)


def vivir_rio(sujetos, filas, rng_rio, social):
    rio = puente.Rio(4, 2, FUERZA, rng_rio)
    rio.filas = filas
    for s in sujetos:
        s.nuevo_rio()
    for t in range(1, VIDA + 1):
        emp = rio.empuje(rng_rio)
        eventos = [s.paso(t, filas, emp) for s in sujetos]
        if social:
            for i, (caida, guardada) in enumerate(eventos):
                if caida is None and guardada is None:
                    continue
                for j, otro in enumerate(sujetos):
                    if j != i:
                        otro.observar(caida, guardada)
    tramo = VIDA // puente.TRAMOS
    salida = []
    for s in sujetos:
        ep = puente.episodios(s.caidas)
        t1 = int(np.sum(ep <= tramo))
        ultimo = int(np.sum(ep > VIDA - tramo))
        saturado = bool(np.any(np.abs(s.x[s.na:]) >= SATURACION - 1e-6))
        salida.append(dict(caidas=len(ep), t1=t1, puente=ultimo == 0, en_pie=s.en_pie / VIDA,
                           estabilizo=s.se_estabilizo, saturado=saturado))
    return salida


def correr_variante(nombre):
    kw = VARIANTES[nombre]
    social = kw.get("ver_caidas", False) or kw.get("ver_exitos", False)
    res = {"rio1": [], "distinto": []}
    evitadas = 0
    for g in range(GRUPOS):
        rng_mundo = np.random.default_rng(4_242 + g)
        rio1 = puente.Rio(4, 2, FUERZA, rng_mundo).filas
        distinto = puente.Rio(4, 2, FUERZA, rng_mundo).filas
        sujetos = [Sujeto(np.random.default_rng(6_000 + 10 * g + k), **kw) for k in range(K)]
        res["rio1"] += vivir_rio(sujetos, rio1, np.random.default_rng(8_000 + g), social)
        res["distinto"] += vivir_rio(sujetos, distinto, np.random.default_rng(9_000 + g), social)
        evitadas += sum(s.evitadas for s in sujetos)
    return nombre, res, evitadas


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=len(VARIANTES)) as ex:
        resultados = {n: (r, e) for n, r, e in ex.map(correr_variante, VARIANTES)}

    n = K * GRUPOS
    print(f"=== {GRUPOS} grupos de {K} sujetos ({n} sujetos) · {VIDA} pasos por río ===")
    print(f"{'variante':<28}{'río':<10}{'caídas':>8}{'T1':>6}{'puente':>9}{'% en pie':>10}"
          f"{'estabilizó':>12}{'saturado':>10}")
    puentes = {}
    for nombre in VARIANTES:
        res, evitadas = resultados[nombre]
        for rio in ("rio1", "distinto"):
            d = res[rio]
            pu = sum(x["puente"] for x in d)
            puentes[(nombre, rio)] = pu
            print(f"{nombre if rio == 'rio1' else '':<28}{rio:<10}"
                  f"{np.median([x['caidas'] for x in d]):>8.0f}{np.median([x['t1'] for x in d]):>6.0f}"
                  f"{pu:>5}/{n}{100 * np.mean([x['en_pie'] for x in d]):>9.2f}%"
                  f"{sum(x['estabilizo'] for x in d):>8}/{n}{sum(x['saturado'] for x in d):>6}/{n}")
        print(f"{'':<28}repeticiones exactas evitadas: {evitadas}\n")
        sys.stdout.flush()

    print("Fisher, puentes frente a 'solo' (p < 0.05 = difícil que sea azar; en las variantes"
          " sociales los sujetos de un grupo no son independientes):")
    for nombre in VARIANTES:
        if nombre == "solo":
            continue
        for rio in ("rio1", "distinto"):
            a, b = puentes[("solo", rio)], puentes[(nombre, rio)]
            print(f"  {nombre:<28}{rio:<10}{a:>3} vs {b:>3}   p = {fisher(a, b, n):.3f}")
