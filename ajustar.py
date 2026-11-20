"""Ajuste fino (SFT) del núcleo preentrenado: conversar, buscar y abstenerse.

Parte de modelos/archivo/nucleo_es_bitnet.pt, agrega las 4 etiquetas de turno al vocabulario
y entrena solo sobre lo que escribe el asistente (B:, <herramienta>, R:, <fin>).

  python ajustar.py                    # 3 épocas sobre datos/sft_train.jsonl
  python ajustar.py --epocas 1 --max 2000 --salida modelos/prueba_sft.pt   # prueba rápida
"""
import argparse
import json
import math
import random
import time
from dataclasses import asdict
from pathlib import Path

import torch

from modelo import Config, Nucleo, elegir_dispositivo
from protocolo import Formato

RAIZ = Path(__file__).parent


def cargar_base(ruta, vocab_nuevo):
    d = torch.load(ruta, map_location="cpu", weights_only=False)
    cfg_base = Config(**d["config"])
    base = Nucleo(cfg_base)
    base.load_state_dict(d["pesos"])
    cfg = Config(**{**d["config"], "vocab": vocab_nuevo})
    modelo = Nucleo(cfg)
    estado = {k: v for k, v in base.state_dict().items() if k not in ("tok.weight", "cabeza.weight")}
    modelo.load_state_dict(estado, strict=False)
    V = cfg_base.vocab
    with torch.no_grad():
        for nombre in ("tok", "cabeza"):
            w_old = getattr(base, nombre).weight
            w_new = getattr(modelo, nombre).weight
            w_new[:V] = w_old
            w_new[V:] = w_old.mean(0) + 0.02 * torch.randn(vocab_nuevo - V, w_old.shape[1])
    return modelo, cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(RAIZ / "modelos" / "archivo" / "nucleo_es_bitnet.pt"))
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "sft_train.jsonl"))
    ap.add_argument("--salida", default=str(RAIZ / "modelos" / "experimentos" / "nucleo_sft.pt"))
    ap.add_argument("--epocas", type=int, default=3)
    ap.add_argument("--lote", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--max", type=int, default=0, help="usar solo N ejemplos (pruebas)")
    ap.add_argument("--semilla", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.semilla)
    rng = random.Random(args.semilla)
    disp = elegir_dispositivo()
    fmt = Formato()
    modelo, cfg = cargar_base(args.base, fmt.vocab)
    modelo.to(disp).train()

    filas = [json.loads(l) for l in open(args.datos, encoding="utf-8")]
    if args.max:
        filas = filas[: args.max]
    datos = []
    for r in filas:
        ids, m = fmt.ejemplo(r["pregunta"], r.get("consulta"), r.get("resultados"), r["respuesta"],
                             prefijo=r.get("pref", "B"), tope=r.get("tope"))
        if len(ids) <= cfg.bloque:
            datos.append((ids, m))
    print(f"{modelo.parametros():,} parámetros | {len(datos):,} ejemplos (de {len(filas):,}) | {disp}", flush=True)

    pasos = args.epocas * math.ceil(len(datos) / args.lote)
    opt = torch.optim.AdamW(modelo.parameters(), lr=args.lr, betas=(0.9, 0.95), weight_decay=0.01)
    paso, t0 = 0, time.time()
    for ep in range(args.epocas):
        rng.shuffle(datos)
        for a in range(0, len(datos), args.lote):
            grupo = datos[a : a + args.lote]
            L = max(len(i) for i, _ in grupo)
            x = torch.full((len(grupo), L - 1), fmt.relleno, dtype=torch.long)
            y = torch.full((len(grupo), L - 1), fmt.relleno, dtype=torch.long)
            m = torch.zeros(len(grupo), L - 1)
            for j, (ids, mk) in enumerate(grupo):
                n = len(ids) - 1
                x[j, :n], y[j, :n], m[j, :n] = torch.tensor(ids[:-1]), torch.tensor(ids[1:]), torch.tensor(mk[1:])
            paso += 1
            lr = args.lr * min(1, paso / 50) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * paso / pasos)))
            for g in opt.param_groups:
                g["lr"] = lr
            with torch.autocast(disp, dtype=torch.bfloat16):
                _, perdida = modelo(x.to(disp), y.to(disp), m.to(disp))
            opt.zero_grad(set_to_none=True)
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
            opt.step()
            if paso % 50 == 0 or paso == 1:
                print(f"  época {ep + 1}/{args.epocas} paso {paso}/{pasos} | pérdida {perdida.item():.4f} | {time.time() - t0:.0f}s", flush=True)

    Path(args.salida).parent.mkdir(exist_ok=True)
    torch.save({"config": asdict(cfg), "pesos": modelo.state_dict()}, args.salida)
    print(f"Guardado en {args.salida} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
