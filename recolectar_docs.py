"""Recolecta resultados REALES de ddgs para el experto de código (documentación, conceptos de cola, funciones inventadas).

Guarda los resultados crudos en datos/ddgs_docs_raw.jsonl (reanudable). Después los usa experto_datos.py.

  python recolectar_docs.py [--hilos 6] [--falsas 2]
"""
import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ddgs import DDGS

from experto_fichas import COLA, api_falsa, lista_apis
from sft_datos import DATOS, inventar

SALIDA = DATOS / "ddgs_docs_raw.jsonl"


def consultas(falsas_por_lib, rng):
    qs = []
    for lib, item in lista_apis():
        qs.append({"consulta": f"{lib} {item}", "tipo": "api", "lib": lib, "item": item})
    for c in COLA:
        qs.append({"consulta": f"{c} programación", "tipo": "cola", "lib": None, "item": c})
    libs = sorted({lib for lib, _ in lista_apis()})
    for lib in libs:
        for _ in range(falsas_por_lib):
            f = api_falsa(lib, rng)
            qs.append({"consulta": f"{lib} {f}", "tipo": "falsa_api", "lib": lib, "item": f})
    for _ in range(40):
        f = inventar(rng)
        qs.append({"consulta": f"algoritmo {f} programación", "tipo": "falsa_cola", "lib": None, "item": f"algoritmo {f}"})
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--falsas", type=int, default=3, help="funciones inventadas por biblioteca")
    args = ap.parse_args()

    qs = consultas(args.falsas, random.Random(7))
    random.Random(1).shuffle(qs)
    hechas = set()
    if SALIDA.exists():
        hechas = {json.loads(l)["consulta"] for l in open(SALIDA, encoding="utf-8")}
    pend = [q for q in qs if q["consulta"] not in hechas]
    print(f"{len(qs)} consultas en total, {len(hechas)} ya hechas, {len(pend)} pendientes", flush=True)

    cerrojo, cuenta, t0 = threading.Lock(), [0, 0], time.time()
    f = open(SALIDA, "a", encoding="utf-8")

    def trabajo(q):
        for intento in range(4):
            try:
                crudos = DDGS().text(q["consulta"], region="xl-es", max_results=8)
                break
            except Exception as e:
                if "No results" in str(e):
                    crudos = []
                    break
                time.sleep(3 * (intento + 1))
        else:
            with cerrojo:
                cuenta[1] += 1
            return
        with cerrojo:
            f.write(json.dumps({**q, "crudos": crudos}, ensure_ascii=False) + "\n")
            f.flush()
            cuenta[0] += 1
            if cuenta[0] % 50 == 0:
                print(f"  {cuenta[0]} listas, {cuenta[1]} fallidas | {time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(args.hilos) as ex:
        list(ex.map(trabajo, pend))
    print(f"Listo: {cuenta[0]} nuevas, {cuenta[1]} fallidas", flush=True)


if __name__ == "__main__":
    main()
