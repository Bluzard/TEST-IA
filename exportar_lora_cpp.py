"""Exporta un adaptador LoRA entrenado (modelos/experto_<nombre>.lora.pt) al formato binario del motor C++.

Formato LORA0001 (little-endian):
  "LORA0001" + int32: r, capas, d, ff, mascara(bit0 qkv, bit1 proy, bit2 fc1, bit3 fc2) + float32 alpha
  por capa y por matriz activa en la máscara: A[r,in] (fp16) y Bt[r,out] (fp16; B transpuesta para sumar vectorizado)

  python exportar_lora_cpp.py modelos/experto_r16_B_e3.lora.pt [--salida modelos/experto_codigo.lora]
"""
import argparse
import struct
from pathlib import Path

import numpy as np
import torch

ORDEN = ("qkv", "proy", "fc1", "fc2")


def exportar(ruta_pt, salida=None, d=512, ff=2048):
    ruta_pt = Path(ruta_pt)
    datos = torch.load(ruta_pt, map_location="cpu", weights_only=False)
    r, alpha, objetivos, pesos = datos["r"], datos["alpha"], datos["objetivos"], datos["pesos"]
    capas = 1 + max(int(k.split(".")[1]) for k in pesos)
    mascara = sum(1 << i for i, n in enumerate(ORDEN) if n in objetivos)
    salida = Path(salida) if salida else ruta_pt.with_name(ruta_pt.name.replace(".lora.pt", ".lora"))
    with open(salida, "wb") as f:
        f.write(b"LORA0001")
        f.write(struct.pack("<5if", r, capas, d, ff, mascara, float(alpha)))
        for i in range(capas):
            for n in ORDEN:
                if n not in objetivos:
                    continue
                A = pesos[f"bloques.{i}.{n}.A"].float().numpy()       # [r, in]
                B = pesos[f"bloques.{i}.{n}.B"].float().numpy()       # [out, r]
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
