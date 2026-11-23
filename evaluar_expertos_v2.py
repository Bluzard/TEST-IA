"""Evaluación de los expertos LoRA del núcleo v2-A por el camino de producción (motor C++ + .bin NUCL0002 + .lora LORA0002).

Reutiliza los evaluadores de v1 sin cambios de lógica (evaluar_experto.evaluar_experto: mismos tipos, mismas métricas, mismo conjunto de
evaluación reservado); solo cambia el formato de prompts (FormatoV2, tokenizador 24k) y el modelo (MotorCpp en vez de PyTorch).

  python evaluar_expertos_v2.py [--bin modelos/experimentos/nucleo_v2_sft.bin] [--solo codigo|redaccion]

Para cada experto: núcleo sin adaptador (línea base) y con adaptador, en su conjunto reservado, más regresión general (ddgs real) con el adaptador
ACTIVO y DORMIDO. Compara contra las cifras de v1 (resultados/experto_r16_B2_e3.log y redaccion_e6.log). Escribe resultados/ETAPA4_expertos_v2.json.
"""
import argparse
import json
import time
from pathlib import Path

from evaluar_experto import PRINCIPAL, evaluar_experto
from evaluar_redaccion import por_grupo
from inferir import evaluar as evaluar_general
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2

RAIZ = Path(__file__).parent
EXP = RAIZ / "modelos" / "experimentos"
EXPERTOS = {
    "codigo": dict(lora=EXP / "experto_codigo_v2.lora", datos=RAIZ / "datos" / "experto_eval_B2.jsonl", v1=0.822),
    "redaccion": dict(lora=EXP / "experto_redaccion_v2.lora", datos=RAIZ / "datos" / "redaccion_eval.jsonl", v1=0.562),
}


def general(motor, fmt):
    return evaluar_general(motor, fmt, "cpu", ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=300, penalizacion=1.1)


def lineas(res):
    return {t: round(m[PRINCIPAL[t]], 4) for t, m in res.items() if not t.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=str(EXP / "nucleo_v2_sft.bin"))
    ap.add_argument("--solo", default=None)
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "ETAPA4_expertos_v2.json"))
    ap.add_argument("--lora_codigo", default=None)
    ap.add_argument("--lora_redaccion", default=None)
    a = ap.parse_args()
    fmt = FormatoV2()
    motor = MotorCpp(a.bin)
    out = {}
    if a.lora_codigo:
        EXPERTOS["codigo"]["lora"] = Path(a.lora_codigo)
    if a.lora_redaccion:
        EXPERTOS["redaccion"]["lora"] = Path(a.lora_redaccion)
    for nombre, cfg in EXPERTOS.items():
        if a.solo and a.solo != nombre:
            continue
        t0 = time.time()
        r = {}
        print(f"== {nombre}: núcleo SIN adaptador (línea base)", flush=True)
        r["base"] = evaluar_experto(motor, fmt, "cpu", ruta=cfg["datos"], pen=1.0)
        print(f"   puntaje {r['base']['_puntaje']:.1%}", flush=True)
        ms = motor.cargar_lora(cfg["lora"])
        print(f"== {nombre}: CON adaptador ({cfg['lora'].name}, carga {ms:.0f} ms)", flush=True)
        r["experto"] = evaluar_experto(motor, fmt, "cpu", ruta=cfg["datos"], pen=1.0)
        r["grupos"] = por_grupo(r["experto"])
        print(f"   puntaje {r['experto']['_puntaje']:.1%} (v1: {cfg['v1']:.1%})", flush=True)
        r["general_activo"] = general(motor, fmt)
        motor.activar_lora(False)
        r["general_dormido"] = general(motor, fmt)
        motor.descargar_lora()
        r["segundos"] = round(time.time() - t0)
        out[nombre] = r
        Path(a.salida).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"== {nombre} listo en {r['segundos']} s", flush=True)
    print(json.dumps({n: {"base": v["base"]["_puntaje"], "experto": v["experto"]["_puntaje"]} for n, v in out.items()}))


if __name__ == "__main__":
    main()
