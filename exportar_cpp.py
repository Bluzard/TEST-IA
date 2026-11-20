"""Exporta un modelo BitNet ajustado al formato binario del motor C++ (motor.cpp).

Formato NUCL0001 (little-endian):
  cabecera : 8 bytes "NUCL0001" + 13 int32:
             vocab, bloque, d, capas, cabezas, vueltas, ff, id_fin, id_herramienta, id_asistente,
             id_usuario, id_relleno, bitnet(=1)
  tok[vocab,d] (fp16), pos[bloque,d] (fp16), vuelta[vueltas,d] (fp32)
  por capa : ln1.w, ln1.b (fp32) | qkv, proy | ln2.w, ln2.b (fp32) | fc1, fc2
             cada capa lineal = escala fp32 + pesos ternarios a 2 bits (4 por byte, fila por fila)
             códigos: 0 -> 0, 1 -> +1, 2 -> -1 (el peso 0 del byte menos significativo es el primero)
  ln final w,b (fp32), cabeza[vocab,d] (fp16)

El vocabulario (tokenizador BPE) se copia junto al .bin como <nombre>.vocab.json.

  python exportar_cpp.py modelos/nucleo_sft_v3.pt [--verificar]
"""
import argparse
import shutil
import struct
from pathlib import Path

import numpy as np
import torch

from modelo import Config, Nucleo
from protocolo import TOK_SFT, Formato

MAGIA = b"NUCL0001"


def empaquetar(w):
    """Pesos de un BitLinear -> (escala, bytes empaquetados a 2 bits), igual que la cuantización del entrenamiento."""
    escala = w.abs().mean().clamp(min=1e-5)
    q = (w / escala).round().clamp(-1, 1).to(torch.int8).numpy()
    codigos = np.where(q == 1, 1, np.where(q == -1, 2, 0)).astype(np.uint8)
    out, n = codigos.shape
    assert n % 4 == 0
    c = codigos.reshape(out, n // 4, 4)
    byte = c[..., 0] | (c[..., 1] << 2) | (c[..., 2] << 4) | (c[..., 3] << 6)
    return float(escala), byte.astype(np.uint8)


def exportar(ruta_pt, salida=None):
    d = torch.load(ruta_pt, map_location="cpu", weights_only=False)
    cfg = Config(**d["config"])
    assert cfg.bitnet, "El motor C++ solo implementa modelos BitNet."
    modelo = Nucleo(cfg)
    modelo.load_state_dict(d["pesos"])
    sd = {k: v.detach().float().cpu() for k, v in modelo.state_dict().items()}
    fmt = Formato()
    ruta_pt = Path(ruta_pt)
    salida = Path(salida) if salida else ruta_pt.with_suffix(".bin")

    with open(salida, "wb") as f:
        f.write(MAGIA)
        f.write(struct.pack("<13i", cfg.vocab, cfg.bloque, cfg.d, cfg.capas, cfg.cabezas, cfg.vueltas, 4 * cfg.d,
                            fmt.fin, fmt.herramienta, fmt.asistente, fmt.usuario, fmt.relleno, 1))
        f.write(sd["tok.weight"].numpy().astype(np.float16).tobytes())
        f.write(sd["pos.weight"].numpy().astype(np.float16).tobytes())
        f.write(sd["vuelta.weight"].numpy().astype(np.float32).tobytes())

        def lineal(clave):
            esc, b = empaquetar(sd[clave])
            f.write(struct.pack("<f", esc))
            f.write(b.tobytes())

        def vec(clave):
            f.write(sd[clave].numpy().astype(np.float32).tobytes())

        for i in range(cfg.capas):
            p = f"bloques.{i}."
            vec(p + "ln1.weight"); vec(p + "ln1.bias")
            lineal(p + "qkv.weight"); lineal(p + "proy.weight")
            vec(p + "ln2.weight"); vec(p + "ln2.bias")
            lineal(p + "mlp.0.weight"); lineal(p + "mlp.2.weight")
        vec("ln.weight"); vec("ln.bias")
        f.write(sd["cabeza.weight"].numpy().astype(np.float16).tobytes())

    vocab = salida.with_suffix(".vocab.json")
    shutil.copyfile(TOK_SFT, vocab)
    print(f"{ruta_pt.name} ({ruta_pt.stat().st_size / 1e6:.1f} MB) -> {salida.name} ({salida.stat().st_size / 1e6:.1f} MB) + {vocab.name}")
    return salida, modelo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modelo")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    exportar(args.modelo, args.salida)
