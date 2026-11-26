"""CLI para vidas persistentes y comparación pareada de conocimiento externo."""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np

from biblioteca_planos import Biblioteca
from conocimiento_persistente import (
    SujetoPersistente, TAM_CONFIG, VENTANA_CONTEXTO, contenido_concreto, importar_planos,
)
from entorno_componible import Mundo, NA, puentes
from homeostato import SATURACION
import puente

VARIANTES = ("sin_plano", "correcto", "incorrecto", "parcial")


def plano_ejemplo(nombre):
    # Conexiones internas sin especificar; solo se entrega colocación de piezas.
    # 2 y 8: apoyos negativos sobre las partes 0 y 1, con sus respectivas anclas.
    piezas = {"correcto": [1, 2, 2, 8], "incorrecto": [1, 2, 1, 7],
              "parcial": [1, 2, None, None]}[nombre]
    return contenido_concreto(np.array([np.nan] * (TAM_CONFIG - 4) +
                                      [np.nan if x is None else x for x in piezas]))


def ejecutar(ruta, semilla, vida, plano="sin_plano", importar=None):
    with Biblioteca(ruta) as b:
        externos = []
        if plano != "sin_plano":
            externos.append(b.guardar(plano_ejemplo(plano), origen="externo"))
        if importar:
            externos.extend(importar_planos(b, importar))
        # Todas las variantes reciben el mismo terreno, estado inicial y perturbaciones.
        mundo = Mundo(np.random.default_rng(50_000 + semilla))
        h = SujetoPersistente(np.random.default_rng(60_000 + semilla), b)
        caidas, fraccion, A = h.vivir(mundo, vida, np.random.default_rng(70_000 + semilla))
        episodios = puente.episodios(caidas)
        ultimo = int(np.sum(episodios > vida - max(1, vida // puente.TRAMOS)))
        saturado = bool(np.any(np.abs(h.x[NA:]) >= SATURACION - 1e-6))
        estable = bool(np.max(np.linalg.eigvals(A).real) < 0)
        # Incluir también planos externos importados en ejecuciones anteriores.
        externos = [x[0] for x in b.db.execute("SELECT id FROM planos WHERE origen='externo'")]
        return dict(semilla=semilla, vida=vida, variante=plano, contexto=h.contexto,
                    episodios_caida=len(episodios), pasos_con_caida=len(caidas),
                    caidas_ultimo_tramo=ultimo, primer_puente_estable=h.primer_puente_estable,
                    fraccion_con_puente=fraccion, puente_final=bool(puentes(h.P)),
                    viable_final=ultimo == 0 and estable and not saturado,
                    recuperados=h.recuperados, usos={str(k): v for k, v in h.usos.items()},
                    externos=[dict(id=pid, intentos=(e := b.evidencia(pid, h.contexto))[0],
                                   logros=e[1], confianza=e[2], usos=h.usos.get(pid, 0)) for pid in externos],
                    planos_guardados=b.db.execute("SELECT COUNT(*) FROM planos").fetchone()[0])


def comparar(rep, vida, semilla):
    resultados = []
    # Cada vida y variante tiene su propia BD: sin contaminación entre controles.
    with tempfile.TemporaryDirectory(prefix="comparar-planos-") as carpeta:
        for r in range(rep):
            for variante in VARIANTES:
                ruta = Path(carpeta) / f"{r}-{variante}.sqlite"
                resultados.append(ejecutar(ruta, semilla + r, vida, variante))
    resumen = {}
    for variante in VARIANTES:
        filas = [x for x in resultados if x['variante'] == variante]
        tiempos = [x['primer_puente_estable'] for x in filas if x['primer_puente_estable'] is not None]
        resumen[variante] = dict(vidas=rep, con_puente_estable=len(tiempos),
                                mediana_tiempo_solo_exitos=float(np.median(tiempos)) if tiempos else None,
                                mediana_episodios=float(np.median([x['episodios_caida'] for x in filas])),
                                media_fraccion_puente=float(np.mean([x['fraccion_con_puente'] for x in filas])))
    return dict(resumen=resumen, vidas=resultados,
                nota="Comparación exploratoria pareada; tiempos sin éxito quedan como null. No demuestra analogía.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)
    vivir = sub.add_parser("vivir", help="Aprender/reutilizar una biblioteca entre ejecuciones")
    vivir.add_argument("--db", type=Path, required=True)
    vivir.add_argument("--plano", choices=VARIANTES, default="sin_plano")
    vivir.add_argument("--importar", type=Path)
    comp = sub.add_parser("comparar", help="Cuatro variantes en bibliotecas aisladas temporales")
    comp.add_argument("--rep", type=int, default=3)
    for parser in (vivir, comp):
        parser.add_argument("--vida", type=int, default=5000)
        parser.add_argument("--semilla", type=int, default=0)
        parser.add_argument("--salida", type=Path)
    a = p.parse_args()
    if a.vida < VENTANA_CONTEXTO or a.semilla < 0 or (a.comando == 'comparar' and a.rep < 1):
        p.error(f"vida >= {VENTANA_CONTEXTO}, semilla >= 0 y rep >= 1")
    if a.comando == "vivir":
        a.db.parent.mkdir(parents=True, exist_ok=True)
        resultado = ejecutar(a.db, a.semilla, a.vida, a.plano, a.importar)
    else:
        resultado = comparar(a.rep, a.vida, a.semilla)
    serial = json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False)
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text(serial + "\n", encoding="utf-8")
    print(serial)


if __name__ == "__main__":
    main()
