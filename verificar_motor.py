"""Comprueba que motor.dll calcula lo mismo que PyTorch (fp32, CPU, sin autocast).

  python verificar_motor.py [modelos/nucleo_sft_v3.pt]
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch

from inferir import cargar
from motor_cpp import MotorCpp
from protocolo import Formato

RAIZ = Path(__file__).parent
ruta = Path(sys.argv[1] if len(sys.argv) > 1 else RAIZ / "modelos" / "nucleo_sft_v3.pt")
modelo, fmt = cargar(ruta, "cpu")
motor = MotorCpp(ruta.with_suffix(".bin"))

filas = [json.loads(l) for l in open(RAIZ / "datos" / "sft_eval_real.jsonl", encoding="utf-8")][:40]
prompts = []
for r in filas:
    p = fmt.ids_prompt(r["pregunta"])
    prompts.append(p)  # fase 1: elegir buscar o responder
    if r["tipo"] != "directo":
        prompts.append(p + fmt.texto(" B: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"]))  # fase 2

dif, coincide = [], 0
for p in prompts:
    with torch.no_grad():
        ref = modelo(torch.tensor([p]))[0][0, -1].numpy()
    cpp = motor.logits(p)
    dif.append(float(np.abs(ref - cpp).max()))
    coincide += int(ref.argmax() == cpp.argmax())
print(f"Logits C++ vs PyTorch fp32 en {len(prompts)} prompts: diferencia máxima {max(dif):.2e} (media {np.mean(dif):.2e}); "
      f"mismo token siguiente en {coincide}/{len(prompts)}")
print(f"(los logits tienen escala ~{float(np.abs(ref).max()):.1f}; el motor guarda embeddings en fp16, por eso hay una diferencia pequeña)")
