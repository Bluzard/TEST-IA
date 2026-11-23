"""Benchmark de sistema v1 vs v2c en CPU (motor C++), con las MISMAS preguntas: RAM, disco, carga, prefill, ms/token, tokens/s y palabras/s.

Cada configuración corre en un proceso aparte (RAM real sin contaminación). Los prompts son la segunda fase real (pregunta + «B: consulta» + resultados de
ddgs) de datos/sft_eval_real.jsonl (general) o de los tipos de documentación/ejecución del evaluador de expertos (experto); cada núcleo usa su tokenizador,
así que el mismo texto ocupa distinto número de tokens: por eso se informa también palabras/s (palabras de la respuesta generada / tiempo de decodificación).

  python benchmark_v2.py [--n 25]            # escribe resultados/ETAPA4_benchmark_v1_v2c.md y .json
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
EXP = RAIZ / "modelos" / "experimentos"
CFG = {
    "v1": dict(bin=RAIZ / "modelos" / "nucleo_sft_v3.bin", codigo=RAIZ / "modelos" / "experto_codigo.lora", redaccion=RAIZ / "modelos" / "experto_redaccion.lora"),
    "v2c": dict(bin=EXP / "nucleo_v2c_sft.bin", codigo=EXP / "experto_codigo_g_v2.lora", redaccion=EXP / "experto_redaccion_f_v2.lora"),
}
PEN, MAX_NUEVOS = 1.1, 100


def prompts(fmt, n, conjunto):
    if conjunto == "experto":
        import random

        filas = [json.loads(l) for l in open(RAIZ / "datos" / "experto_eval_B2.jsonl", encoding="utf-8")]
        filas = [r for r in filas if r["tipo"] in ("doc_ok", "concepto", "ejec_ok", "ejec_error")]
        random.Random(0).shuffle(filas)
        return [fmt.ids_prompt(r["pregunta"]) + fmt.texto(f" {r['pref']}: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"], r.get("tope")) for r in filas[:n]]
    filas = [json.loads(l) for l in open(RAIZ / "datos" / "sft_eval_real.jsonl", encoding="utf-8")]
    filas = [r for r in filas if r["tipo"] in ("buscar_ok", "irrelevante")][:n]
    return [fmt.ids_prompt(r["pregunta"]) + fmt.texto(" B: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"]) for r in filas]


def trabajador(version, lora, n, conjunto):
    from motor_cpp import MotorCpp

    if version == "v1":
        from protocolo import Formato

        fmt = Formato()
    else:
        from protocolo_v2 import FormatoV2

        fmt = FormatoV2()
    c = CFG[version]
    proc = psutil.Process()
    ps = prompts(fmt, n, conjunto)
    base = proc.memory_info().wset
    t0 = time.perf_counter()
    m = MotorCpp(c["bin"])
    carga = time.perf_counter() - t0
    extra = {}
    if lora == "codigo":  # un adaptador activo
        extra["lora_carga_ms"] = m.cargar_lora(c["codigo"])
        extra["lora_mb"] = m.bytes_lora / 1e6
    elif lora == "dos":  # sesión real: ambos expertos en la caché de 2 ranuras; el de código activo
        ms = 0.0
        for i, nombre in enumerate(("codigo", "redaccion")):
            m.registrar_experto(nombre, str(c[nombre]), i)
            ms += m.cargar_ranura(str(c[nombre]), i)
        m.seleccionar("codigo")
        extra["lora_carga_ms"] = ms
        extra["lora_mb"] = m.bytes_lora / 1e6
    pre, dec, pasos, palabras, salidas = [], [], [], [], []
    for p in ps:
        nuevos, parada = m.generar(p, PEN, MAX_NUEVOS)
        a, b, k = m.ultimos_tiempos
        pre.append(a)
        dec.append(b)
        pasos.append(k)
        txt = fmt.tok.decode([i for i in nuevos if i not in (fmt.fin, fmt.herramienta)])
        palabras.append(len(txt.split()))
        salidas.append(txt)
    w = 3  # calentamiento
    tot_dec, tot_pasos, tot_pal = sum(dec[w:]), sum(pasos[w:]), sum(palabras[w:])
    mem = proc.memory_info()
    print(json.dumps({
        "version": version, "lora": lora, "conjunto": conjunto, "carga_s": carga, "ram_base_mb": base / 1e6, "ram_pico_mb": mem.peak_wset / 1e6,
        "prefill_ms": st.median(pre[w:]), "prompt_tokens": st.mean(len(p) for p in ps), "ms_token": tot_dec / tot_pasos if tot_pasos else float("nan"),
        "tokens_s": 1000 * tot_pasos / tot_dec if tot_dec else float("nan"), "palabras_s": 1000 * tot_pal / tot_dec if tot_dec else float("nan"),
        "palabras_por_token": tot_pal / tot_pasos if tot_pasos else float("nan"), "tokens_generados_medio": st.mean(pasos[w:]), "muestra": salidas[w:w + 2], **extra}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trabajador", nargs=4, default=None, metavar=("VERSION", "LORA", "N", "CONJUNTO"))
    ap.add_argument("--n", type=int, default=25)
    a = ap.parse_args()
    if a.trabajador:
        v, l, n, cj = a.trabajador
        return trabajador(v, None if l == "ninguno" else l, int(n), cj)
    config = [("v1", "ninguno", "general", "all"), ("v2c", "ninguno", "general", "all"), ("v1", "ninguno", "general", "1"), ("v2c", "ninguno", "general", "1"),
              ("v1", "codigo", "experto", "all"), ("v2c", "codigo", "experto", "all"), ("v1", "dos", "experto", "all"), ("v2c", "dos", "experto", "all")]
    res = []
    for v, l, cj, hilos in config:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if hilos == "1":
            env["OMP_NUM_THREADS"] = "1"
        print(f"== {v} lora={l} {cj} hilos={hilos} ...", flush=True)
        p = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__)), "--trabajador", v, l, str(a.n), cj], capture_output=True, text=True, env=env, cwd=RAIZ)
        if p.returncode != 0:
            print(p.stderr[-800:])
            continue
        r = json.loads(p.stdout.strip().splitlines()[-1])
        r["hilos"] = hilos
        res.append(r)
    disco = {v: {"nucleo_mb": CFG[v]["bin"].stat().st_size / 1e6, "codigo_mb": CFG[v]["codigo"].stat().st_size / 1e6, "redaccion_mb": CFG[v]["redaccion"].stat().st_size / 1e6,
                 "vocab_mb": (CFG[v]["bin"].with_suffix(".vocab.json").stat().st_size / 1e6 if CFG[v]["bin"].with_suffix(".vocab.json").exists() else None)} for v in CFG}
    (RAIZ / "resultados" / "ETAPA4_benchmark_v1_v2c.json").write_text(json.dumps({"disco": disco, "medidas": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    nombres = {"ninguno": "núcleo solo", "codigo": "núcleo + LoRA código", "dos": "núcleo + 2 LoRA en caché (código activo)"}
    filas = ["| versión | configuración | hilos | RAM pico | carga | prefill | tokens de prompt | ms/token | tokens/s | palabras/s | palabras/token |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        filas.append(f"| {r['version']} | {nombres[r['lora'] or 'ninguno']} ({r['conjunto']}) | {r['hilos']} | {r['ram_pico_mb']:.0f} MB | {r['carga_s']:.2f} s | {r['prefill_ms']:.1f} ms | "
                     f"{r['prompt_tokens']:.0f} | {r['ms_token']:.2f} | {r['tokens_s']:.0f} | {r['palabras_s']:.0f} | {r['palabras_por_token']:.2f} |")
    d = ["| artefacto | v1 | v2c |", "|---|---|---|"]
    for k, nom in (("nucleo_mb", "núcleo .bin"), ("codigo_mb", "LoRA código"), ("redaccion_mb", "LoRA redacción")):
        d.append(f"| {nom} | {disco['v1'][k]:.1f} MB | {disco['v2c'][k]:.1f} MB |")
    (RAIZ / "resultados" / "ETAPA4_benchmark_v1_v2c.md").write_text(
        f"# Benchmark v1 vs v2c (motor C++, CPU, {a.n} prompts reales, 3 de calentamiento)\n\n## Rendimiento y RAM\n\n" + "\n".join(filas) + "\n\n## Disco\n\n" + "\n".join(d) + "\n", encoding="utf-8")
    print("\n".join(filas)); print("\n".join(d))


if __name__ == "__main__":
    main()
