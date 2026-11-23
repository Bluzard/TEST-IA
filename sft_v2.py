"""SFT del núcleo v2-A: parte del preentrenamiento y enseña el protocolo (conversar, B:/E:/R:, abstenerse). Solo aprende lo que escribe el asistente.

  .venv/Scripts/python.exe sft_v2.py --base modelos/experimentos/pretrain_v2/nucleo_v2_pretrain.pt --datos datos/v2/sft/sft_train.jsonl --salida modelos/experimentos/nucleo_v2_sft.pt
  prueba:  --base modelos/experimentos/piloto_v2.pt --max 64 --epocas 1 --lote_tokens 2048 --dispositivo cpu --salida modelos/experimentos/humo_sft.pt

Los lotes se arman por presupuesto de tokens (ejemplos de longitud parecida juntos). Las 4 etiquetas de turno (ids 24000–24003) no se vieron en el
preentrenamiento: sus filas del embedding atado se reinician a la media + ruido, como se hizo en v1.
Varias fuentes: --datos acepta varios archivos .jsonl; el campo opcional "peso" (número de repeticiones) se respeta.
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch

from modelo_v2 import ConfigV2, NucleoV2
from protocolo_v2 import CONTEXTO_V2, FormatoV2

RAIZ = Path(__file__).parent


def cargar_base(ruta, vocab_base_texto=24000):
    d = torch.load(ruta, map_location="cpu", weights_only=False)
    cfg = ConfigV2(**d["config"]) if "config" in d else ConfigV2()
    m = NucleoV2(cfg)
    m.load_state_dict(d["pesos"])
    with torch.no_grad():
        E = m.tok.weight
        E[vocab_base_texto:] = E[:vocab_base_texto].mean(0) + 0.02 * torch.randn(cfg.vocab - vocab_base_texto, E.shape[1])
    return m, cfg


def tokenizar(filas, fmt, tope):
    datos, descartados = [], 0
    for r in filas:
        ids, mk = fmt.ejemplo(r["pregunta"], r.get("consulta"), r.get("resultados"), r["respuesta"], prefijo=r.get("pref", "B"), tope=r.get("tope"))
        if len(ids) <= tope:
            datos.extend([(ids, mk)] * int(r.get("peso", 1)))
        else:
            descartados += 1
    return datos, descartados


def lotes(datos, lote_tokens, rng):
    """Agrupa por longitud parecida; cada lote tiene como mucho `lote_tokens` posiciones (incluyendo relleno)."""
    orden = sorted(datos, key=lambda x: len(x[0]) + rng.random() * 24)
    grupos, actual, mayor = [], [], 0
    for ej in orden:
        mayor_n = max(mayor, len(ej[0]))
        if actual and mayor_n * (len(actual) + 1) > lote_tokens:
            grupos.append(actual)
            actual, mayor_n = [], len(ej[0])
        actual.append(ej)
        mayor = mayor_n
    if actual:
        grupos.append(actual)
    rng.shuffle(grupos)
    return grupos


def tensores(grupo, relleno, disp):
    L = max(len(i) for i, _ in grupo)
    x = torch.full((len(grupo), L - 1), relleno, dtype=torch.long)
    y = torch.full_like(x, relleno)
    m = torch.zeros(len(grupo), L - 1)
    for j, (ids, mk) in enumerate(grupo):
        n = len(ids) - 1
        x[j, :n], y[j, :n], m[j, :n] = torch.tensor(ids[:-1]), torch.tensor(ids[1:]), torch.tensor(mk[1:])
    return x.to(disp), y.to(disp), m.to(disp)


def perdida_mascara(modelo, x, y, m):
    logits = modelo(x)
    p = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), y.reshape(-1), reduction="none")
    return (p * m.reshape(-1)).sum() / m.sum().clamp(min=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(RAIZ / "modelos" / "experimentos" / "pretrain_v2" / "nucleo_v2_pretrain.pt"))
    ap.add_argument("--datos", nargs="+", default=[str(RAIZ / "datos" / "v2" / "sft" / "sft_train.jsonl")])
    ap.add_argument("--eval", default=None, help="jsonl de evaluación: pérdida enmascarada al final de cada época")
    ap.add_argument("--salida", default=str(RAIZ / "modelos" / "experimentos" / "nucleo_v2_sft.pt"))
    ap.add_argument("--epocas", type=int, default=3)
    ap.add_argument("--lote_tokens", type=int, default=32768)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--dispositivo", default="cuda")
    a = ap.parse_args()

    torch.manual_seed(a.semilla)
    rng = random.Random(a.semilla)
    disp = a.dispositivo
    fmt = FormatoV2()
    modelo, cfg = cargar_base(a.base)
    assert fmt.vocab == cfg.vocab
    modelo.to(disp).train()
    filas = [json.loads(l) for ruta in a.datos for l in open(ruta, encoding="utf-8")]
    if a.max:
        filas = filas[:a.max]
    datos, desc = tokenizar(filas, fmt, CONTEXTO_V2)
    val = tokenizar([json.loads(l) for l in open(a.eval, encoding="utf-8")], fmt, CONTEXTO_V2)[0] if a.eval else []
    ntok = sum(len(i) for i, _ in datos)
    print(f"{modelo.parametros() / 1e6:.1f} M parámetros | {len(datos):,} ejemplos ({desc} descartados por largo), {ntok / 1e6:.1f} M tokens | {disp}", flush=True)

    pasos = a.epocas * len(lotes(datos, a.lote_tokens, random.Random(0)))
    decay = [p for n, p in modelo.named_parameters() if p.ndim >= 2 and "pos" not in n]
    nodecay = [p for n, p in modelo.named_parameters() if not (p.ndim >= 2 and "pos" not in n)]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.01}, {"params": nodecay, "weight_decay": 0.0}], lr=a.lr, betas=(0.9, 0.95))
    paso, t0 = 0, time.time()
    for ep in range(a.epocas):
        for grupo in lotes(datos, a.lote_tokens, rng):
            x, y, m = tensores(grupo, fmt.relleno, disp)
            paso += 1
            lr = a.lr * min(1, paso / 50) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * paso / pasos)))
            for g in opt.param_groups:
                g["lr"] = lr
            with torch.autocast(disp, dtype=torch.bfloat16):
                perd = perdida_mascara(modelo, x, y, m)
            opt.zero_grad(set_to_none=True)
            perd.backward()
            gn = torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
            opt.step()
            if paso % 25 == 0 or paso == 1:
                print(f"  época {ep + 1}/{a.epocas} paso {paso}/{pasos} | pérdida {perd.item():.4f} | gnorm {gn.item():.2f} | lr {lr:.1e} | {time.time() - t0:.0f}s", flush=True)
        if val:
            modelo.eval()
            with torch.no_grad(), torch.autocast(disp, dtype=torch.bfloat16):
                ps = [perdida_mascara(modelo, *tensores(g, fmt.relleno, disp)).item() for g in lotes(val, a.lote_tokens, random.Random(1))]
            modelo.train()
            print(f"  época {ep + 1}: pérdida de evaluación {sum(ps) / len(ps):.4f}", flush=True)
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    torch.save({"config": cfg.__dict__, "pesos": modelo.state_dict()}, a.salida)
    print(f"Guardado en {a.salida} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
