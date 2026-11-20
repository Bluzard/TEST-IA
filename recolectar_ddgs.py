"""Recolecta resultados reales de DuckDuckGo (ddgs) para entrenar con ruido web de verdad.

Consulta títulos de artículos del pool de entrenamiento (nunca los reservados para evaluar) y
palabras inventadas, y guarda los resultados CRUDOS en datos/ddgs_raw.jsonl (reanudable).

  python recolectar_ddgs.py --n 4000 --hilos 4
"""
import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ddgs import DDGS

from sft_datos import DATOS, POOL, es_eval, inventar

SALIDA = DATOS / "ddgs_raw.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--inventadas", type=float, default=0.15, help="fracción de consultas con palabras inventadas")
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--eval", action="store_true", help="consultar los artículos reservados para evaluación")
    args = ap.parse_args()

    global SALIDA
    pool = [json.loads(l) for l in open(POOL, encoding="utf-8")]
    if args.eval:  # artículos reservados: solo para evaluar, nunca para entrenar
        SALIDA = DATOS / "ddgs_raw_eval.jsonl"
    train = [a for a in pool if es_eval(a["titulo"]) == args.eval]
    rng = random.Random(1)
    consultas = []
    for a in rng.sample(train, int(args.n * (1 - args.inventadas))):
        consultas.append({"consulta": a["titulo"], "gold": a["titulo"], "frase": a["frase"]})
    for _ in range(int(args.n * args.inventadas)):
        consultas.append({"consulta": inventar(rng), "gold": None, "frase": None})
    rng.shuffle(consultas)  # mezclar: así se puede detener en cualquier momento con la proporción correcta
    hechas = set()
    if SALIDA.exists():
        hechas = {json.loads(l)["consulta"] for l in open(SALIDA, encoding="utf-8")}
    pendientes = [c for c in consultas if c["consulta"] not in hechas]
    print(f"{len(hechas)} ya hechas, {len(pendientes)} pendientes", flush=True)

    cerrojo, cuenta, t0 = threading.Lock(), [0, 0], time.time()
    f = open(SALIDA, "a", encoding="utf-8")

    def trabajo(c):
        for intento in range(4):
            try:
                crudos = DDGS().text(c["consulta"], region="xl-es", max_results=8)
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
            f.write(json.dumps({**c, "crudos": crudos}, ensure_ascii=False) + "\n")
            f.flush()
            cuenta[0] += 1
            if cuenta[0] % 100 == 0:
                print(f"  {cuenta[0]} listas, {cuenta[1]} fallidas | {time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(args.hilos) as ex:
        list(ex.map(trabajo, pendientes))
    print(f"Listo: {cuenta[0]} nuevas, {cuenta[1]} fallidas", flush=True)


if __name__ == "__main__":
    main()
