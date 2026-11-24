"""Fabrica entradas en ESPAÑOL realistas para el experto de prompts de imagen: traduce al español las descripciones cortas REALES en inglés de los conjuntos abiertos
(igor-im/flux_prompt_expander: «gen_p» corto -> prompt largo; primera idea de k-mktr/improved-flux-prompts y de ChrisGoringe/flux_prompts).

Modelo: Helsinki-NLP/opus-mt-en-es (Apache-2.0, 75 M de parámetros). Se usa SOLO para generar datos de entrenamiento (no forma parte del producto en ejecución):
sin esto las entradas en español eran frases de mis plantillas (≈ 40 sujetos), y el experto aprendía mi vocabulario en vez de traducir.

  python imagen_traducir.py [--max 40000]     ->  datos/imagen/raw/es_traducidos.jsonl   {en, es, fuente}
"""
import argparse
import json
import random
import re
import time
from pathlib import Path

import torch

RAIZ = Path(__file__).parent
RAW = RAIZ / "datos" / "imagen" / "raw"


def cortas(max_n, rng):
    import pandas as pd

    sal = []
    exp = pd.read_parquet(RAW / "igor-im__flux_prompt_expander" / "data" / "train-00000-of-00001.parquet")
    for r in exp.itertuples():
        if isinstance(r.gen_p, str) and 20 <= len(r.gen_p.strip()) <= 260:
            sal.append((r.gen_p.strip(), "flux_prompt_expander", r.prompt.strip()))
    for l in open(RAW / "k-mktr__improved-flux-prompts" / "20240927_flux_improved_prompts_final_cleaned.jsonl", encoding="utf-8"):
        t = json.loads(l)["prompt"].strip()
        c = re.split(r"(?<=[.!?])\s|,\s", t)[0]
        if 4 <= len(c.split()) <= 24:
            sal.append((c, "improved_flux_prompts", t))
    import pandas as pd

    ruta = RAW / "Aconexx__CivitAI-Flux-Prompts" / "Flux_Prompts_Dataset_v1.1.0.jsonl"
    if ruta.exists():  # Aconexx/CivitAI-Flux-Prompts (Apache-2.0): descripción corta -> prompt real de usuario de CivitAI (temas variados)
        ac = pd.read_json(ruta, lines=True)
        for r in ac.itertuples():
            if isinstance(r.input, str) and 20 <= len(r.input.strip()) <= 260:
                sal.append((r.input.strip(), "civitai_flux", r.output.strip()))
    rng.shuffle(sal)
    return sal[:max_n]


def pares_sd(max_n, rng):
    """Prompts reales de DiffusionDB (CC0) para SDXL/SD 1.5: la entrada es 1-4 de sus etiquetas, igual que en imagen_datos, y se traduce al español."""
    import pandas as pd

    from imagen_datos import higiene, normalizar_dd

    dd = pd.read_parquet(RAW / "poloclub__diffusiondb" / "metadata.parquet", columns=["prompt", "prompt_nsfw"])
    dd = dd[(dd.prompt_nsfw < 0.5) & dd.prompt.notna()]
    vistos, sal = set(), []
    for t in dd.prompt.sample(min(len(dd), max_n * 6), random_state=11).tolist():
        t = normalizar_dd(t)
        c = re.sub(r"\W+", " ", t.lower()).strip()[:160]
        if c in vistos or not (40 <= len(t) <= 380 and t.count(",") >= 3 and higiene(t)):
            continue
        vistos.add(c)
        trozos = [x.strip() for x in t.split(",") if x.strip()]
        elegidos = trozos[: rng.randint(1, 2)] + rng.sample(trozos[2:], min(len(trozos) - 2, rng.randint(0, 2)))
        if len(" ".join(elegidos).split()) >= 3:
            sal.append((", ".join(elegidos), "diffusiondb", t))
        if len(sal) >= max_n:
            break
    return sal


def traducir(filas, lote, nombre_salida):
    from transformers import MarianMTModel, MarianTokenizer

    nombre = "Helsinki-NLP/opus-mt-en-es"
    tok = MarianTokenizer.from_pretrained(nombre)
    modelo = MarianMTModel.from_pretrained(nombre).to("cuda").half().eval()
    salida = RAW / nombre_salida
    t0 = time.time()
    with open(salida, "w", encoding="utf-8") as f:
        for i in range(0, len(filas), lote):
            grupo = filas[i:i + lote]
            enc = tok([g[0] for g in grupo], return_tensors="pt", padding=True, truncation=True, max_length=96).to("cuda")
            with torch.no_grad():
                out = modelo.generate(**enc, num_beams=1, max_new_tokens=96)
            for g, es in zip(grupo, tok.batch_decode(out, skip_special_tokens=True)):
                f.write(json.dumps({"en": g[0], "es": es, "fuente": g[1], "largo": g[2]}, ensure_ascii=False) + "\n")
            if (i // lote) % 40 == 0:
                print(f"  {nombre_salida}: {i + len(grupo):,}/{len(filas):,} | {time.time() - t0:.0f}s", flush=True)
    print(f"listo: {len(filas):,} traducciones en {time.time() - t0:.0f}s -> {salida}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=30000)
    ap.add_argument("--max_sd", type=int, default=12000)
    ap.add_argument("--lote", type=int, default=128)
    a = ap.parse_args()
    rng = random.Random(1)
    traducir(cortas(a.max, rng), a.lote, "es_traducidos.jsonl")
    traducir(pares_sd(a.max_sd, rng), a.lote, "es_traducidos_sd.jsonl")


def _main_antiguo():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=40000)
    ap.add_argument("--lote", type=int, default=96)
    a = ap.parse_args()
    from transformers import MarianMTModel, MarianTokenizer

    rng = random.Random(1)
    filas = cortas(a.max, rng)
    nombre = "Helsinki-NLP/opus-mt-en-es"
    tok = MarianTokenizer.from_pretrained(nombre)
    modelo = MarianMTModel.from_pretrained(nombre).to("cuda").half().eval()
    salida = RAW / "es_traducidos.jsonl"
    t0 = time.time()
    with open(salida, "w", encoding="utf-8") as f:
        for i in range(0, len(filas), a.lote):
            grupo = filas[i:i + a.lote]
            enc = tok([g[0] for g in grupo], return_tensors="pt", padding=True, truncation=True, max_length=96).to("cuda")
            with torch.no_grad():
                out = modelo.generate(**enc, num_beams=2, max_new_tokens=96)
            for g, es in zip(grupo, tok.batch_decode(out, skip_special_tokens=True)):
                f.write(json.dumps({"en": g[0], "es": es, "fuente": g[1], "largo": g[2]}, ensure_ascii=False) + "\n")
            if (i // a.lote) % 25 == 0:
                print(f"  {i + len(grupo):,}/{len(filas):,} | {time.time() - t0:.0f}s", flush=True)
    print(f"listo: {len(filas):,} traducciones en {time.time() - t0:.0f}s -> {salida}")


if __name__ == "__main__":
    main()
