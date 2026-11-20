"""Entrena una variante del núcleo.

  A = sin herramientas (tiene que memorizar todo)
  B = con diccionario externo (aprende a detectar lo que no sabe y buscar)

Ejemplo:  python entrenar.py --variante B
"""
import argparse
import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import torch

from modelo import Config, Nucleo, elegir_dispositivo

RAIZ = Path(__file__).parent


def vocabulario():
    # base de letras del español para no perder caracteres que solo aparecen al evaluar
    chars = set("\n abcdefghijklmnñopqrstuvwxyzáéíóúü.,;:¿?¡!")
    for v in ("A", "B"):
        with open(RAIZ / "datos" / f"entrenamiento_{v}.jsonl", encoding="utf-8") as f:
            for linea in f:
                chars.update(json.loads(linea)["texto"])
    # índice 0 reservado para relleno
    return {c: i + 1 for i, c in enumerate(sorted(chars))}


def codificar(textos, stoi, bloque):
    """Entrada, objetivo y máscara: solo se aprende a escribir líneas B: y R:."""
    n = len(textos)
    X = torch.zeros(n, bloque, dtype=torch.long)
    Y = torch.zeros(n, bloque, dtype=torch.long)
    M = torch.zeros(n, bloque)
    for i, t in enumerate(textos):
        ids = [stoi[c] for c in t]
        assert len(ids) <= bloque + 1, f"ejemplo demasiado largo ({len(ids)}): {t!r}"
        aprender = []
        for linea in t.splitlines(keepends=True):
            v = 1.0 if linea.startswith(("B: ", "R: ")) else 0.0
            aprender += [v] * len(linea)
        X[i, : len(ids) - 1] = torch.tensor(ids[:-1])
        Y[i, : len(ids) - 1] = torch.tensor(ids[1:])
        M[i, : len(ids) - 1] = torch.tensor(aprender[1:])
    return X, Y, M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variante", choices=["A", "B"], required=True)
    ap.add_argument("--pasos", type=int, default=3000)
    ap.add_argument("--lote", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--capas", type=int, default=4)
    ap.add_argument("--cabezas", type=int, default=4)
    ap.add_argument("--vueltas", type=int, default=1)
    ap.add_argument("--bitnet", action="store_true")
    ap.add_argument("--bloque", type=int, default=256)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    torch.manual_seed(args.semilla)
    dispositivo = elegir_dispositivo()
    stoi = vocabulario()
    with open(RAIZ / "datos" / f"entrenamiento_{args.variante}.jsonl", encoding="utf-8") as f:
        textos = [json.loads(l)["texto"] for l in f]
    X, Y, M = codificar(textos, stoi, args.bloque)

    cfg = Config(vocab=len(stoi) + 1, bloque=args.bloque, d=args.d, capas=args.capas,
                 cabezas=args.cabezas, vueltas=args.vueltas, bitnet=args.bitnet)
    modelo = Nucleo(cfg).to(dispositivo)
    opt = torch.optim.AdamW(modelo.parameters(), lr=args.lr, weight_decay=0.01)
    print(f"Variante {args.variante} | dispositivo {dispositivo} | {modelo.parametros():,} parámetros | {len(textos):,} ejemplos")

    calentamiento = 100
    t0 = time.time()
    modelo.train()
    for paso in range(1, args.pasos + 1):
        lr = args.lr * min(1, paso / calentamiento) * 0.5 * (1 + math.cos(math.pi * paso / args.pasos))
        for g in opt.param_groups:
            g["lr"] = lr
        idx = torch.randint(0, len(textos), (args.lote,))
        x, y, m = X[idx].to(dispositivo), Y[idx].to(dispositivo), M[idx].to(dispositivo)
        _, perdida = modelo(x, y, m)
        opt.zero_grad(set_to_none=True)
        perdida.backward()
        torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
        opt.step()
        if paso % 200 == 0 or paso == 1:
            print(f"  paso {paso:5d}/{args.pasos} | pérdida {perdida.item():.4f} | {time.time() - t0:5.0f}s")

    (RAIZ / "modelos").mkdir(exist_ok=True)
    salida = Path(args.salida) if args.salida else RAIZ / "modelos" / f"modelo_{args.variante}.pt"
    torch.save({"config": asdict(cfg), "pesos": modelo.state_dict(), "stoi": stoi}, salida)
    print(f"Guardado en {salida} ({time.time() - t0:.0f}s en total)")


if __name__ == "__main__":
    main()
