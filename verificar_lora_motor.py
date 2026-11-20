"""Verifica motor.dll con LoRA contra PyTorch (fp32, CPU) y que el adaptador dormido no cambia NADA.

  python verificar_lora_motor.py modelos/experto_r16_B_e3.lora.pt
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch

import lora
from exportar_lora_cpp import exportar
from inferir import cargar
from motor_cpp import MotorCpp

RAIZ = Path(__file__).parent
ruta_lora = Path(sys.argv[1])
BASE = RAIZ / "modelos" / "nucleo_sft_v3.pt"

modelo, fmt = cargar(BASE, "cpu")
lora.cargar_lora(modelo, ruta_lora)
modelo.eval()
bin_lora = exportar(ruta_lora)
motor = MotorCpp(BASE.with_suffix(".bin"))
base_motor = MotorCpp(BASE.with_suffix(".bin"))  # segundo motor sin adaptador, de referencia

filas = [json.loads(l) for l in open(RAIZ / "datos" / "experto_eval_B.jsonl", encoding="utf-8")]
prompts = []
for r in filas[::7][:120]:
    p = fmt.ids_prompt(r["pregunta"])
    prompts.append(p)
    if "consulta" in r:
        prompts.append(p + fmt.texto(f" {r['pref']}: " + r["consulta"]) + [fmt.herramienta] + fmt.ids_tras_herramienta(r["resultados"], r.get("tope")))

ms = motor.cargar_lora(bin_lora)
print(f"{len(prompts)} prompts | .lora de {motor.bytes_lora / 1e6:.2f} MB cargado en {ms:.1f} ms")
dif, igual = [], 0
for p in prompts:
    with torch.no_grad():
        ref = modelo(torch.tensor([p]))[0][0, -1].numpy()
    cpp = motor.logits(p)
    dif.append(float(np.abs(ref - cpp).max()))
    igual += int(ref.argmax() == cpp.argmax())
print(f"LoRA ACTIVO  C++ vs PyTorch fp32: diferencia máxima {max(dif):.2e} (media {np.mean(dif):.2e}); mismo token siguiente {igual}/{len(prompts)}")

motor.activar_lora(False)
ident = all(np.array_equal(motor.logits(p), base_motor.logits(p)) for p in prompts)
print(f"LoRA DORMIDO idéntico bit a bit al motor sin adaptador: {ident}")
motor.activar_lora(True)
cambia = sum(not np.array_equal(motor.logits(p), base_motor.logits(p)) for p in prompts)
print(f"LoRA ACTIVO cambia los logits en {cambia}/{len(prompts)} prompts (debe ser casi todos)")
motor.descargar_lora()
print(f"Tras descargar: {motor.bytes_lora} bytes de adaptador; idéntico al base: {all(np.array_equal(motor.logits(p), base_motor.logits(p)) for p in prompts[:20])}")
