"""Recolecta resultados REALES de ddgs para el experto de redacción (temas de gramática de cola y temas inventados).

Guarda los resultados crudos en datos/ddgs_redaccion_raw.jsonl (reanudable). Después los usa redaccion_datos.py.

  python recolectar_redaccion.py [--hilos 4]
"""
import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ddgs import DDGS

from redaccion_fichas import COLA_GRAMATICA, FICHAS_GRAMATICA
from sft_datos import DATOS, inventar

SALIDA = DATOS / "ddgs_redaccion_raw.jsonl"
PREFIJOS_FALSOS = ["perífrasis", "oración", "verbo", "sufijo", "tilde", "concordancia", "complemento", "adjetivo"]


def consultas():
    qs = [{"consulta": f"{c} gramática español", "tipo": "cola", "item": c} for c in COLA_GRAMATICA]
    # fichas locales buscadas también en internet: sirven para evaluar «base local + ddgs»
    qs += [{"consulta": f"{f[0]} gramática español", "tipo": "ficha", "item": f[0]} for f in FICHAS_GRAMATICA]
    rng = random.Random(11)
    vistos = set()
    while len(vistos) < 70:
        f = f"{rng.choice(PREFIJOS_FALSOS)} {inventar(rng)}"
        vistos.add(f)
    qs += [{"consulta": f"{f} gramática español", "tipo": "falsa", "item": f} for f in sorted(vistos)]
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hilos", type=int, default=4)
    args = ap.parse_args()
    qs = consultas()
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
                crudos = DDGS(timeout=15).text(q["consulta"], region="xl-es", max_results=8)
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
            if cuenta[0] % 25 == 0:
                print(f"  {cuenta[0]} listas, {cuenta[1]} fallidas | {time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(args.hilos) as ex:
        list(ex.map(trabajo, pend))
    print(f"Listo: {cuenta[0]} nuevas, {cuenta[1]} fallidas", flush=True)


if __name__ == "__main__":
    main()
