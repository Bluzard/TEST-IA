"""Entrena un experto LoRA sobre el núcleo v2 congelado (SFT ya hecho) y lo exporta a LORA0002.

  python entrenar_lora_v2.py --nombre codigo   --datos datos/experto_train_B2.jsonl --base modelos/experimentos/nucleo_v2_sft.pt
  python entrenar_lora_v2.py --nombre redaccion --datos datos/redaccion_train.jsonl --epocas 6

Receta de v1 (que quedó en producción): r=16 en qkv/proy/fc1/fc2 de todas las capas, α=32, lr 1e-3, coseno; código 3 épocas, redacción 6.
Los datos de los expertos son texto (pregunta/respuesta/pref/tope), así que se reutilizan tal cual con el tokenizador v2.
El núcleo no cambia: se comprueba la suma de sus pesos antes y después. Escribe modelos/experimentos/experto_<nombre>_v2.lora(.pt).
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch

import lora
from exportar_lora_v2 import exportar
from protocolo_v2 import CONTEXTO_V2, FormatoV2
from sft_v2 import lotes, perdida_mascara, tensores, tokenizar

RAIZ = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--base", default=str(RAIZ / "modelos" / "experimentos" / "nucleo_v2_sft.pt"))
    ap.add_argument("--datos", required=True)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=float, default=32.0)
    ap.add_argument("--epocas", type=int, default=3)
    ap.add_argument("--lote_tokens", type=int, default=16384)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--dispositivo", default="cuda")
    a = ap.parse_args()

    torch.manual_seed(a.semilla)
    rng = random.Random(a.semilla)
    disp = a.dispositivo
    fmt = FormatoV2()
    d = torch.load(a.base, map_location="cpu", weights_only=False)
    from modelo_v2 import ConfigV2, NucleoV2
    cfg = ConfigV2(**d["config"]) if "config" in d else ConfigV2()
    modelo = NucleoV2(cfg)
    modelo.load_state_dict(d["pesos"])  # sin reiniciar filas: el SFT ya entrenó las etiquetas
    modelo.cfg_lora = None
    suma0 = lora.suma_base(modelo)
    lora.aplicar_lora(modelo, lora.ConfigLora(a.r, a.alpha, lora.OBJETIVOS))
    modelo.to(disp).train()
    n, mb = lora.contar(modelo)
    filas = [json.loads(l) for l in open(a.datos, encoding="utf-8")]
    if a.max:
        filas = filas[:a.max]
    datos, desc = tokenizar([{**r, "tope": r.get("tope") or 10_000} for r in filas], fmt, CONTEXTO_V2)
    print(f"[{a.nombre}] LoRA r={a.r} α={a.alpha}: {n:,} parámetros ({mb:.1f} MB fp16) | {len(datos):,} ejemplos ({desc} descartados) | {disp}", flush=True)
    pasos = a.epocas * len(lotes(datos, a.lote_tokens, random.Random(0)))
    opt = torch.optim.AdamW(lora.parametros_lora(modelo), lr=a.lr, betas=(0.9, 0.95), weight_decay=0.0)
    paso, t0 = 0, time.time()
    for ep in range(a.epocas):
        for grupo in lotes(datos, a.lote_tokens, rng):
            x, y, m = tensores(grupo, fmt.relleno, disp)
            paso += 1
            lr = a.lr * min(1, paso / a.warmup) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * paso / pasos)))
            for g in opt.param_groups:
                g["lr"] = lr
            with torch.autocast(disp, dtype=torch.bfloat16):
                perd = perdida_mascara(modelo, x, y, m)
            opt.zero_grad(set_to_none=True)
            perd.backward()
            torch.nn.utils.clip_grad_norm_(lora.parametros_lora(modelo), 1.0)
            opt.step()
            if paso % 50 == 0 or paso == 1:
                print(f"  época {ep + 1}/{a.epocas} paso {paso}/{pasos} | pérdida {perd.item():.4f} | {time.time() - t0:.0f}s", flush=True)
    modelo.eval()
    intacto = abs(lora.suma_base(modelo) - suma0) < 1e-6 * max(1.0, abs(suma0))
    print(f"[{a.nombre}] núcleo base intacto tras entrenar: {intacto}", flush=True)
    assert intacto
    ruta_pt = RAIZ / "modelos" / "experimentos" / f"experto_{a.nombre}_v2.lora.pt"
    lora.guardar_lora(modelo, ruta_pt)
    exportar(ruta_pt, cfg=cfg)
    print(f"[{a.nombre}] terminado en {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
