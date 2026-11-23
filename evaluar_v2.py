"""Evaluación del núcleo v2 por el camino de producción (motor C++ con el .bin exportado), con las mismas pruebas que v1.

  python evaluar_v2.py modelos/experimentos/nucleo_v2_sft.bin [--n 300]

Mide:
  1. Etapa 1 (ddgs real, datos/sft_eval_real.jsonl): hechos (respuesta exacta), abstención (irrelevante / vacío). Línea base v1: 71,6 % / 98,1 %.
  2. Charla (datos/v2/sft/sft_eval.jsonl, tipo «charla», frases reservadas): no busca y responde con una de las respuestas válidas de su intención.
     La conversación de v1 era 18 saludos exactos (100 %); la de v2 es más amplia, no comparable palabra por palabra.
  3. Simulado con artículos reservados (datos/v2/sft/sft_eval.jsonl): buscar_ok / irrelevante / vacio.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from inferir import _texto, evaluar, generar_lote
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2
import charla_v2

RAIZ = Path(__file__).parent


def evaluar_charla(motor, fmt, filas, n=300):
    filas = filas[:n]
    validas = {i: set(r) for i, (_, r) in charla_v2.INTENCIONES.items()}
    sin_buscar = ok = 0
    malas = []
    for a in range(0, len(filas), 50):
        grupo = filas[a:a + 50]
        sal = generar_lote(motor, fmt, [fmt.ids_prompt(r["pregunta"]) for r in grupo], "cpu", 1.1)
        for r, (nuevo, parada) in zip(grupo, sal):
            if parada == fmt.herramienta:
                continue
            sin_buscar += 1
            t = _texto(fmt, nuevo).removeprefix("R:").strip()
            lista = {x.replace("{n}", "") for x in validas[r["intencion"]]}
            if t in validas[r["intencion"]] or any(v and t.startswith(v.split("{n}")[0]) for v in validas[r["intencion"]] if "{n}" in v):
                ok += 1
            elif len(malas) < 8:
                malas.append((r["pregunta"], t))
    return {"no_busco": sin_buscar / len(filas), "respuesta_valida": ok / len(filas), "n": len(filas), "ejemplos_malos": malas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "ETAPA4_eval_v2.json"))
    a = ap.parse_args()
    fmt = FormatoV2()
    motor = MotorCpp(a.bin)
    t0 = time.time()
    res = {"bin": a.bin}
    print("== 1. Etapa 1 · ddgs real (línea base v1: hechos 71,6 %, abstención 98,1 %)", flush=True)
    res["real"] = evaluar(motor, fmt, "cpu", ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=a.n, penalizacion=1.1)
    for t, m in res["real"].items():
        print(f"  {t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()), flush=True)
    ev = [json.loads(l) for l in open(RAIZ / "datos" / "v2" / "sft" / "sft_eval.jsonl", encoding="utf-8")]
    sim = [r for r in ev if r["tipo"] != "charla"]
    tmp = RAIZ / "datos" / "v2" / "sft" / "_tmp_eval_sim.jsonl"
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sim), encoding="utf-8")
    print("== 2. Simulado con artículos reservados", flush=True)
    res["simulado"] = evaluar(motor, fmt, "cpu", ruta=tmp, n_por_tipo=a.n, penalizacion=1.1)
    tmp.unlink()
    for t, m in res["simulado"].items():
        print(f"  {t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()), flush=True)
    print("== 3. Charla de TEST-IA (frases reservadas)", flush=True)
    res["charla"] = evaluar_charla(motor, fmt, [r for r in ev if r["tipo"] == "charla"], a.n)
    print(f"  no busca {res['charla']['no_busco']:.1%} | respuesta válida {res['charla']['respuesta_valida']:.1%} ({res['charla']['n']} frases)", flush=True)
    for p, t in res["charla"]["ejemplos_malos"]:
        print(f"    mal: {p!r} -> {t!r}", flush=True)
    res["segundos"] = round(time.time() - t0)
    Path(a.salida).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo en {res['segundos']} s -> {a.salida}", flush=True)


if __name__ == "__main__":
    main()
