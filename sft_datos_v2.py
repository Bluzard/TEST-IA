"""Dataset de SFT del núcleo v2 (datos/v2/sft/): buscar, abstenerse y conversar. No toca los archivos de v1 (datos/sft_*.jsonl).

Mezcla (por defecto ≈ 150 k ejemplos):
  · 125 k simulados de herramienta (buscar_ok / irrelevante / vacio), con artículos de Wikipedia es leídos de los parquet ya descargados (pool de hasta 200 k)
  · ≈ 4 k reales de ddgs (datos/ddgs_raw.jsonl) repetidos 3 veces: los que más enseñan el formato de producción
  · 25 k de charla de TEST-IA (charla_v2.py): saludos, ánimo, identidad, límites, humor sutil
Evaluación: artículos reservados por hash del título (5 %) + frases de charla reservadas + ddgs_raw_eval.jsonl; el entrenamiento EXCLUYE además
todo título que aparezca en algún conjunto de evaluación de las Etapas 1–4 (los mismos «títulos reservados» de la descontaminación del corpus).

  python sft_datos_v2.py [--ejemplos 125000] [--articulos 200000] [--charla 25000]
"""
import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import charla_v2
from sft_datos import (SALUDOS, directo, ejemplo, ejemplos_reales, es_eval, primera_oracion)
from herramientas import _limpio

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
SALIDA = DATOS / "v2" / "sft"
POOL = SALIDA / "pool_v2.jsonl"


def construir_pool(n_max):
    import pyarrow.parquet as pq

    SALIDA.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(POOL, "w", encoding="utf-8") as f:
        for ruta in sorted((DATOS / "v2" / "raw" / "wikipedia").rglob("*.parquet")):
            for lote in pq.ParquetFile(ruta).iter_batches(batch_size=4096, columns=["title", "text"]):
                for titulo0, texto in zip(lote.column("title").to_pylist(), lote.column("text").to_pylist()):
                    titulo = re.sub(r"\s*\(.*?\)", "", titulo0).strip()
                    if ":" in titulo or not 3 <= len(titulo) <= 40 or titulo.lower().startswith(("anexo", "lista")):
                        continue
                    parrafo = re.sub(r"\s+", " ", texto.split("\n")[0]).strip()
                    if len(parrafo) < 80:
                        continue
                    frase = primera_oracion(parrafo)
                    if not frase or not 40 <= len(frase) <= 190:
                        continue
                    fragmento = _limpio(parrafo, 200)
                    if frase not in fragmento:
                        continue
                    f.write(json.dumps({"titulo": titulo, "fragmento": fragmento, "frase": frase}, ensure_ascii=False) + "\n")
                    n += 1
                    if n >= n_max:
                        print(f"Pool: {n:,} artículos -> {POOL}", flush=True)
                        return
            print(f"  {n:,} artículos ({ruta.name})", flush=True)
    print(f"Pool: {n:,} artículos -> {POOL}", flush=True)


def norm_titulo(t):
    return re.sub(r"\W+", " ", t.lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articulos", type=int, default=200000)
    ap.add_argument("--ejemplos", type=int, default=125000)
    ap.add_argument("--charla", type=int, default=25000)
    ap.add_argument("--eval", type=int, default=800, help="ejemplos de evaluación por tipo principal")
    ap.add_argument("--rep_real", type=int, default=3)
    ap.add_argument("--semilla", type=int, default=0)
    a = ap.parse_args()

    if not POOL.exists():
        construir_pool(a.articulos)
    pool = [json.loads(l) for l in open(POOL, encoding="utf-8")]
    from fase1_datos import textos_de_evaluacion

    _, reservados, _ = textos_de_evaluacion()
    train = [x for x in pool if not es_eval(x["titulo"]) and norm_titulo(x["titulo"]) not in reservados]
    held = [x for x in pool if es_eval(x["titulo"])]
    print(f"Pool {len(pool):,} | entrenamiento {len(train):,} (excluidos {len(pool) - len(train) - len(held):,} títulos de evaluación) | reservados {len(held):,}", flush=True)
    rng = random.Random(a.semilla)

    def generar(fuente, n, pesos):
        salida = []
        for _ in range(n):
            tipo = rng.choices(list(pesos), list(pesos.values()))[0]
            salida.append(ejemplo(rng, pool, rng.choice(fuente), tipo))
        return salida

    reales = ejemplos_reales(DATOS / "ddgs_raw.jsonl", rng) if (DATOS / "ddgs_raw.jsonl").exists() else []
    print("Ejemplos reales de ddgs:", dict(Counter(r["tipo"] for r in reales)), flush=True)
    sim = generar(train, a.ejemplos, {"buscar_ok": 0.68, "irrelevante": 0.16, "vacio": 0.16})
    filas = sim + reales * a.rep_real + charla_v2.generar(a.charla, "train", a.semilla + 1)
    rng.shuffle(filas)
    eval_sim = generar(held, a.eval * 3, {"buscar_ok": 1 / 3, "irrelevante": 1 / 3, "vacio": 1 / 3})
    eval_charla = charla_v2.generar(a.eval, "eval", a.semilla + 2)
    eval_real = ejemplos_reales(DATOS / "ddgs_raw_eval.jsonl", random.Random(5)) if (DATOS / "ddgs_raw_eval.jsonl").exists() else []
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, f_ in (("sft_train", filas), ("sft_eval", eval_sim + eval_charla), ("sft_eval_real", eval_real)):
        with open(SALIDA / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for r in f_:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{nombre}: {len(f_):,} ejemplos {dict(Counter(r['tipo'] for r in f_))}", flush=True)


if __name__ == "__main__":
    main()
