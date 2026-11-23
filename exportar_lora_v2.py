"""Exporta un adaptador LoRA del núcleo v2 (.lora.pt de lora.guardar_lora) al formato LORA0002 del motor C++.

Formato LORA0002: "LORA0002" + int32 r, capas, d, ff, mascara(bit0 qkv, bit1 proy, bit2 fc1, bit3 fc2) + float32 alpha;
por capa y matriz activa: A[r,in] (fp16) y Bt[r,out] (fp16). Con GQA la salida de qkv es d + 2·kv_dim (el motor la deduce de la cabecera del núcleo).

  python exportar_lora_v2.py modelos/experimentos/experto_codigo_v2.lora.pt [--salida X.lora]
"""
import argparse
import struct
from pathlib import Path

import numpy as np
import torch

from modelo_v2 import ConfigV2

ORDEN = ("qkv", "proy", "fc1", "fc2")


def exportar(ruta_pt, salida=None, cfg=None):
    cfg = cfg or ConfigV2()
    ruta_pt = Path(ruta_pt)
    datos = torch.load(ruta_pt, map_location="cpu", weights_only=False)
    r, alpha, objetivos, pesos = datos["r"], datos["alpha"], datos["objetivos"], datos["pesos"]
    capas = 1 + max(int(k.split(".")[1]) for k in pesos)
    assert capas == cfg.capas, (capas, cfg.capas)
    mascara = sum(1 << i for i, n in enumerate(ORDEN) if n in objetivos)
    salida = Path(salida) if salida else ruta_pt.with_name(ruta_pt.name.replace(".lora.pt", ".lora"))
    with open(salida, "wb") as f:
        f.write(b"LORA0002")
        f.write(struct.pack("<5if", r, capas, cfg.d, cfg.ff, mascara, float(alpha)))
        for i in range(capas):
            for n in ORDEN:
                if n not in objetivos:
                    continue
                A = pesos[f"bloques.{i}.{n}.A"].float().numpy()   # [r, in]
                B = pesos[f"bloques.{i}.{n}.B"].float().numpy()   # [out, r]
                f.write(np.ascontiguousarray(A, dtype=np.float32).astype(np.float16).tobytes())
                f.write(np.ascontiguousarray(B.T, dtype=np.float32).astype(np.float16).tobytes())
    print(f"{ruta_pt.name} -> {salida.name}: r={r}, alpha={alpha}, matrices={objetivos}, {capas} capas, {salida.stat().st_size / 1e6:.2f} MB")
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("lora")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()
    exportar(a.lora, a.salida)
