"""Compara RAM, VRAM y milisegundos por token: motor C++ contra PyTorch, con las mismas preguntas.

Cada backend corre en un proceso aparte (para medir su RAM real sin contaminación):
  torch_gpu  PyTorch en la RTX (bf16, como inferir.py)       torch_cpu   PyTorch en CPU (fp32)
  cpp        motor.dll con todos los hilos                   cpp_1hilo   motor.dll con 1 hilo

Los prompts son la segunda fase real (pregunta + B: consulta + resultados de ddgs, 150-330 tokens), y se
generan hasta <fin>. PyTorch recalcula toda la secuencia en cada token (así funciona inferir.py, sin caché);
el motor C++ usa caché de claves/valores. Se separa "prefill" (procesar el prompt) de "decodificación".

  python benchmark_motor.py                # todos los backends, escribe resultados/benchmark_motor.md
"""
import argparse
import json
import os
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

import psutil

RAIZ = Path(__file__).parent
MODELO = RAIZ / "modelos" / "nucleo_sft_v3.pt"
PEN = 1.1
MAX_NUEVOS = 100


def prompts(fmt, n, conjunto="general"):
    """Segunda fase (pregunta + consulta + resultados). general: Etapa 1 (ddgs real); experto: documentación, conceptos y ejecución."""
    if conjunto == "experto":
        filas = [json.loads(l) for l in open(RAIZ / "datos" / "experto_eval_B2.jsonl", encoding="utf-8")]
        filas = [r for r in filas if r["tipo"] in ("doc_ok", "concepto", "ejec_ok", "ejec_error")]
        import random

        random.Random(0).shuffle(filas)
        return [fmt.ids_prompt(r["pregunta"]) + fmt.texto(f" {r['pref']}: " + r["consulta"]) + [fmt.herramienta] +
                fmt.ids_tras_herramienta(r["resultados"], r.get("tope")) for r in filas[:n]]
    filas = [json.loads(l) for l in open(RAIZ / "datos" / "sft_eval_real.jsonl", encoding="utf-8")]
    filas = [r for r in filas if r["tipo"] in ("buscar_ok", "irrelevante")][:n]
    return [fmt.ids_prompt(r["pregunta"]) + fmt.texto(" B: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"]) for r in filas]


def mb(x):
    return x / 1e6


def trabajador(backend, n, conjunto="general", ruta_lora=None):
    from protocolo import Formato

    proc = psutil.Process()
    fmt = Formato()
    ps = prompts(fmt, n, conjunto)
    base = proc.memory_info().wset
    t0 = time.perf_counter()
    prefill, decod, salidas = [], [], []
    vram = 0.0
    extra = {}

    if backend.startswith("cpp"):
        from motor_cpp import MotorCpp

        m = MotorCpp(MODELO.with_suffix(".bin"))
        carga = time.perf_counter() - t0
        if "lora" in backend or "dormido" in backend:  # adaptador de código cargado al vuelo (activo o dormido)
            extra["lora_carga_ms"] = m.cargar_lora(ruta_lora)
            extra["lora_mb"] = m.bytes_lora / 1e6
            if "dormido" in backend:
                m.activar_lora(False)
        for p in ps:
            nuevos, parada = m.generar(p, PEN, MAX_NUEVOS)
            pre, dec, pasos = m.ultimos_tiempos
            prefill.append(pre)
            decod.append(dec / pasos if pasos else float("nan"))
            salidas.append(nuevos)
    else:
        import torch

        from inferir import cargar

        disp = "cuda" if backend == "torch_gpu" else "cpu"
        m, _ = cargar(MODELO, disp)
        if disp == "cuda":
            torch.cuda.synchronize()
        carga = time.perf_counter() - t0
        sync = torch.cuda.synchronize if disp == "cuda" else (lambda: None)
        for p in ps:
            ids, usados, pasos_t, nuevos = list(p), set(), [], []
            for _ in range(MAX_NUEVOS):
                a = time.perf_counter()
                with torch.no_grad(), torch.autocast(disp, dtype=torch.bfloat16, enabled=disp == "cuda"):
                    lg = m(torch.tensor([ids], device=disp))[0][0, -1].float()
                sync()
                pasos_t.append((time.perf_counter() - a) * 1000)
                for u in usados:
                    lg[u] = lg[u] / PEN if lg[u] > 0 else lg[u] * PEN
                s = int(lg.argmax())
                nuevos.append(s)
                ids.append(s)
                if s in (fmt.fin, fmt.herramienta) or len(ids) >= m.cfg.bloque:
                    break
                usados.add(s)
            prefill.append(pasos_t[0])
            decod.append(st.mean(pasos_t[1:]) if len(pasos_t) > 1 else float("nan"))
            salidas.append(nuevos)
        if disp == "cuda":
            vram = mb(torch.cuda.max_memory_allocated())

    mem = proc.memory_info()
    w = 3  # los primeros prompts calientan cachés / kernels
    ok = [x for x in decod[w:] if x == x]
    print(json.dumps({
        "backend": backend, "carga_s": carga, "ram_base_mb": mb(base), "ram_pico_mb": mb(mem.peak_wset),
        "vram_pico_mb": vram, "prefill_ms": st.median(prefill[w:]), "ms_token": st.median(ok),
        "tokens_prompt_medio": st.mean(len(p) for p in ps), "tokens_generados_medio": st.mean(len(s) for s in salidas),
        "salidas": salidas, **extra,
    }))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trabajador", default=None)
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--backends", nargs="+", default=["torch_gpu", "torch_cpu", "cpp", "cpp_1hilo"])
    ap.add_argument("--prompts", choices=("general", "experto"), default="general")
    ap.add_argument("--lora", default=str(RAIZ / "modelos" / "experto_codigo.lora"))
    ap.add_argument("--salida", default="benchmark_motor.md")
    args = ap.parse_args()
    if args.trabajador:
        return trabajador(args.trabajador, args.n, args.prompts, args.lora)

    res = {}
    for b in args.backends:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if b.endswith("_1hilo"):
            env["OMP_NUM_THREADS"] = "1"
        print(f"== {b} ...", flush=True)
        p = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__)), "--trabajador", b, "--n", str(args.n),
                            "--prompts", args.prompts, "--lora", args.lora],
                           capture_output=True, text=True, env=env, cwd=RAIZ)
        if p.returncode != 0:
            print(p.stderr[-800:])
            continue
        res[b] = json.loads(p.stdout.strip().splitlines()[-1])

    nombre_ref = "torch_cpu" if "torch_cpu" in res else ("cpp" if "cpp" in res else next(iter(res)))
    ref = res[nombre_ref]
    filas = ["| Backend | RAM pico (proceso) | RAM del modelo* | VRAM pico | Carga | Carga del .lora | Prefill (prompt ~%d tok) | ms/token | tokens/s | Respuesta idéntica a %s |"
             % (ref["tokens_prompt_medio"], nombre_ref), "|---|---|---|---|---|---|---|---|---|---|"]
    for b, r in res.items():
        igual = sum(a == c for a, c in zip(r["salidas"], ref["salidas"])) / len(r["salidas"])
        lc = f"{r['lora_carga_ms']:.1f} ms ({r['lora_mb']:.2f} MB)" if "lora_carga_ms" in r else "—"
        filas.append(f"| {b} | {r['ram_pico_mb']:.0f} MB | {r['ram_pico_mb'] - r['ram_base_mb']:.0f} MB | "
                     f"{r['vram_pico_mb']:.0f} MB | {r['carga_s']:.2f} s | {lc} | {r['prefill_ms']:.1f} ms | {r['ms_token']:.2f} ms | "
                     f"{1000 / r['ms_token']:.0f} | {igual:.0%} |")
    tabla = "\n".join(filas)
    print("\n" + tabla)
    pie = ("\n\n\\* RAM del modelo = pico del proceso menos la RAM antes de cargar el modelo (incluye activaciones y caché de claves/valores). "
           "La RAM pico del proceso en PyTorch incluye las bibliotecas de torch y CUDA.\n"
           "PyTorch no usa caché de claves/valores (como en inferir.py): recalcula toda la secuencia en cada token. "
           "El motor C++ sí la usa.\n")
    (RAIZ / "resultados").mkdir(exist_ok=True)
    (RAIZ / "resultados" / args.salida).write_text(
        f"# Benchmark: motor C++ vs PyTorch ({args.n} prompts reales, 3 de calentamiento)\n\n{tabla}{pie}", encoding="utf-8")


if __name__ == "__main__":
    main()
