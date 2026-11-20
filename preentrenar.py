"""Preentrena el núcleo (BitNet) en español sobre el corpus de corpus.py.

Reanudable: guarda un punto de control cada --guardar pasos; si lo vuelves a
ejecutar con la misma --salida continúa desde ahí.

Ejemplo (prueba rápida):  python preentrenar.py --bitnet --pasos 200 --salida modelos/prueba.pt
Ejemplo (real):           python preentrenar.py --bitnet --minutos 180
"""
import argparse
import math
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from modelo import Config, Nucleo, elegir_dispositivo

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"


def lote(datos, bloque, n, dispositivo, rng):
    ini = rng.integers(0, len(datos) - bloque - 1, n)
    x = np.stack([datos[i : i + bloque] for i in ini]).astype(np.int64)
    y = np.stack([datos[i + 1 : i + 1 + bloque] for i in ini]).astype(np.int64)
    return torch.from_numpy(x).to(dispositivo), torch.from_numpy(y).to(dispositivo)


@torch.no_grad()
def validar(modelo, val, bloque, lote_n, dispositivo, n=20):
    modelo.eval()
    rng = np.random.default_rng(123)
    total = 0.0
    for _ in range(n):
        x, y = lote(val, bloque, lote_n, dispositivo, rng)
        with torch.autocast(dispositivo, dtype=torch.bfloat16):
            _, p = modelo(x, y)
        total += p.item()
    modelo.train()
    return total / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bitnet", action="store_true")
    ap.add_argument("--d", type=int, default=512)
    ap.add_argument("--capas", type=int, default=10)
    ap.add_argument("--cabezas", type=int, default=8)
    ap.add_argument("--vueltas", type=int, default=1)
    ap.add_argument("--bloque", type=int, default=512)
    ap.add_argument("--lote", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--pasos", type=int, default=0, help="pasos totales (0 = calcular según --minutos)")
    ap.add_argument("--minutos", type=float, default=0, help="presupuesto de tiempo; mide la velocidad y fija los pasos")
    ap.add_argument("--guardar", type=int, default=1000)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--salida", default=str(RAIZ / "modelos" / "nucleo_es.pt"))
    args = ap.parse_args()

    torch.manual_seed(args.semilla)
    rng = np.random.default_rng(args.semilla)
    dispositivo = elegir_dispositivo()
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(DATOS / "tokenizador.json"))
    train = np.memmap(DATOS / "corpus_es.bin", dtype=np.uint16, mode="r")
    val = np.memmap(DATOS / "corpus_es_val.bin", dtype=np.uint16, mode="r")

    cfg = Config(vocab=tok.get_vocab_size(), bloque=args.bloque, d=args.d, capas=args.capas,
                 cabezas=args.cabezas, vueltas=args.vueltas, bitnet=args.bitnet)
    modelo = Nucleo(cfg).to(dispositivo)
    opt = torch.optim.AdamW(modelo.parameters(), lr=args.lr, betas=(0.9, 0.95), weight_decay=0.05)
    tokens_paso = args.lote * args.bloque
    print(f"{modelo.parametros():,} parámetros | bitnet={args.bitnet} | {dispositivo} | "
          f"{len(train) / 1e6:.0f} M tokens de entrenamiento | {tokens_paso:,} tokens por paso", flush=True)

    salida = Path(args.salida)
    salida.parent.mkdir(exist_ok=True)
    punto = salida.with_suffix(".punto.pt")
    paso0, pasos = 0, args.pasos
    if punto.exists():
        est = torch.load(punto, map_location="cpu", weights_only=False)
        modelo.load_state_dict(est["pesos"])
        opt.load_state_dict(est["opt"])
        paso0, pasos = est["paso"], est["pasos_totales"]
        print(f"Reanudando desde el paso {paso0:,} de {pasos:,}", flush=True)

    calentamiento = 200
    t0 = time.time()
    t_medida = None
    modelo.train()
    paso = paso0
    while True:
        paso += 1
        if pasos == 0 and args.minutos and paso == 51:
            # medir velocidad tras 50 pasos de calentamiento y fijar el total
            torch.cuda.synchronize() if dispositivo == "cuda" else None
            seg = (time.time() - t_medida) / 40
            pasos = int(args.minutos * 60 / seg)
            print(f"Velocidad: {seg * 1000:.0f} ms/paso -> {pasos:,} pasos ({pasos * tokens_paso / 1e6:.0f} M tokens)", flush=True)
        if pasos == 0 and paso == 11:
            t_medida = time.time()
        total = pasos if pasos else 10**9
        lr = args.lr * min(1, paso / calentamiento) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(paso / total, 1))))
        for g in opt.param_groups:
            g["lr"] = lr
        x, y = lote(train, args.bloque, args.lote, dispositivo, rng)
        with torch.autocast(dispositivo, dtype=torch.bfloat16):
            _, perdida = modelo(x, y)
        opt.zero_grad(set_to_none=True)
        perdida.backward()
        torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
        opt.step()
        if paso % 100 == 0 or paso == 1:
            print(f"  paso {paso:6d}/{pasos or '?'} | pérdida {perdida.item():.3f} | lr {lr:.2e} | {time.time() - t0:6.0f}s", flush=True)
        if paso % args.guardar == 0:
            v = validar(modelo, val, args.bloque, args.lote, dispositivo)
            print(f"  >> validación {v:.3f} (perplejidad {math.exp(v):.1f})", flush=True)
            torch.save({"pesos": modelo.state_dict(), "opt": opt.state_dict(), "paso": paso, "pasos_totales": pasos}, punto)
        if pasos and paso >= pasos:
            break

    v = validar(modelo, val, args.bloque, args.lote, dispositivo, n=50)
    print(f"Validación final {v:.3f} (perplejidad {math.exp(v):.1f})", flush=True)
    torch.save({"config": asdict(cfg), "pesos": modelo.state_dict(), "tokenizador": str(DATOS / "tokenizador.json"),
                "validacion": v}, salida)
    if punto.exists():
        punto.unlink()
    print(f"Guardado en {salida} ({(time.time() - t0) / 60:.0f} min)", flush=True)


if __name__ == "__main__":
    main()
