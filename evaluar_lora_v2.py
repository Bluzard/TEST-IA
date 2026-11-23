"""Evaluación de UN adaptador LoRA v2 (para búsqueda de hiperparámetros): mismo evaluador que v1, motor C++.

  python evaluar_lora_v2.py codigo modelos/experimentos/experto_codigo_lr3e4_v2.lora [--rapida 40] [--general]
Imprime puntaje, métrica principal por tipo y (con --general) hechos/abstención con el adaptador activo y dormido.
"""
import argparse
import json
import time
from pathlib import Path

from evaluar_experto import PRINCIPAL, evaluar_experto
from evaluar_expertos_v2 import EXPERTOS, general
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2

RAIZ = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experto", choices=list(EXPERTOS))
    ap.add_argument("lora")
    ap.add_argument("--rapida", type=int, default=0, help="máximo de ejemplos por tipo (0 = todos)")
    ap.add_argument("--general", action="store_true")
    ap.add_argument("--bin", default=str(RAIZ / "modelos" / "experimentos" / "nucleo_v2_sft.bin"))
    a = ap.parse_args()
    fmt, motor, t0 = FormatoV2(), MotorCpp(a.bin), time.time()
    motor.cargar_lora(a.lora)
    res = evaluar_experto(motor, fmt, "cpu", ruta=EXPERTOS[a.experto]["datos"], pen=1.0, max_por_tipo=a.rapida or None)
    out = {"lora": a.lora, "rapida": a.rapida, "puntaje": res["_puntaje"], "tipos": {t: round(m[PRINCIPAL[t]], 3) for t, m in res.items() if t[0] != "_"}}
    if a.general:
        g1 = general(motor, fmt)
        motor.activar_lora(False)
        g0 = general(motor, fmt)
        k = lambda g: {t: round(list(m.values())[1], 3) for t, m in g.items()}
        out["general_activo"], out["general_dormido"] = k(g1), k(g0)
    out["segundos"] = round(time.time() - t0)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
