"""Piloto en GPU del núcleo v2-A: rendimiento, estabilidad y perplejidad con embedding atado fp16 vs int8 por fila.

  .venv/Scripts/python.exe piloto_v2.py --minutos 25
Entrena con tiempo limitado (el LR se planifica sobre los pasos que caben), en ventanas de 512 tokens, bf16 + torch.compile + SDPA.
No toca ningún peso congelado: escribe solo modelos/experimentos/piloto_v2.pt y resultados/ETAPA4_piloto_*.
"""
import argparse
import json
import math
import threading
import queue
import time
from pathlib import Path

import numpy as np
import torch

from modelo_v2 import ConfigV2, NucleoV2

RAIZ = Path(__file__).parent
CORPUS = RAIZ / "datos" / "v2" / "corpus"


class Datos:
    """Ventanas aleatorias de T+1 tokens, en la proporción natural del corpus (cada shard pesa por su tamaño)."""

    def __init__(self, T, semilla=0):
        self.T = T
        self.m = [np.memmap(p, dtype=np.uint16, mode="r") for p in sorted(CORPUS.glob("*.bin")) if not p.name.startswith("val")]
        n = np.array([len(a) for a in self.m], dtype=np.float64)
        self.p = n / n.sum()
        self.rng = np.random.default_rng(semilla)
        self.total = int(n.sum())

    def lote(self, B):
        out = np.empty((B, self.T + 1), dtype=np.int64)
        for i, s in enumerate(self.rng.choice(len(self.m), B, p=self.p)):
            a = self.m[s]
            o = int(self.rng.integers(0, len(a) - self.T - 1))
            out[i] = a[o:o + self.T + 1]
        return torch.from_numpy(out)


def prefetch(datos, B, n=6):
    q = queue.Queue(n)

    def run():
        while True:
            q.put(datos.lote(B))

    threading.Thread(target=run, daemon=True).start()
    return q


def cuantizar_int8_por_fila(E):
    esc = (E.abs().amax(dim=1, keepdim=True) / 127).clamp(min=1e-8).to(torch.float16).float()
    return (E / esc).round().clamp(-127, 127) * esc


@torch.no_grad()
def perplejidad(modelo, val, T, emb, B=64):
    modelo.eval()
    n = (len(val) - 1) // T
    tot, cnt = 0.0, 0
    for i in range(0, n, B):
        idx = np.arange(i, min(i + B, n))
        x = torch.from_numpy(np.stack([val[j * T:j * T + T + 1] for j in idx]).astype(np.int64)).cuda()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            p = modelo(x[:, :-1], x[:, 1:], emb_head=emb)
        tot += p.item() * len(idx)
        cnt += len(idx)
    modelo.train()
    return math.exp(tot / cnt), tot / cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=25)
    ap.add_argument("--T", type=int, default=512)
    ap.add_argument("--micro", type=int, default=32)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--medir_desde", type=int, default=30, help="paso desde el que se mide el rendimiento estable (tras el compile)")
    ap.add_argument("--sin_compile", action="store_true")
    ap.add_argument("--salida", default=str(RAIZ / "modelos" / "experimentos" / "piloto_v2.pt"))
    ap.add_argument("--registro", default=str(RAIZ / "resultados" / "ETAPA4_piloto"))
    a = ap.parse_args()

    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = True
    cfg = ConfigV2()
    modelo = NucleoV2(cfg).cuda()
    print(f"parámetros: {modelo.parametros() / 1e6:.1f} M | {torch.cuda.get_device_name()}", flush=True)
    fwd = modelo if a.sin_compile else torch.compile(modelo)

    decay = [p for n, p in modelo.named_parameters() if p.ndim >= 2 and "pos" not in n]
    nodecay = [p for n, p in modelo.named_parameters() if not (p.ndim >= 2 and "pos" not in n)]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": nodecay, "weight_decay": 0.0}], lr=a.lr, betas=(0.9, 0.95), fused=True)

    datos = Datos(a.T)
    cola = prefetch(datos, a.micro)
    tok_paso = a.micro * a.accum * a.T
    print(f"corpus de entrenamiento: {datos.total / 1e9:.3f} B tokens | {tok_paso} tokens/paso", flush=True)
    reg = open(a.registro + "_curva.jsonl", "w", encoding="utf-8")

    total_pasos = None  # se fija tras medir el rendimiento estable
    t0 = time.time()
    t_medir = None
    paso = 0
    perdidas, normas = [], []
    torch.cuda.reset_peak_memory_stats()
    while True:
        if total_pasos is None:
            lr = a.lr * min(1.0, (paso + 1) / a.warmup)
        else:
            if paso >= total_pasos:
                break
            prog = (paso - 0) / total_pasos
            lr = a.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * prog))) * min(1.0, (paso + 1) / a.warmup)
        for g in opt.param_groups:
            g["lr"] = lr
        pl = 0.0
        for _ in range(a.accum):
            x = cola.get().cuda(non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                p = fwd(x[:, :-1], x[:, 1:]) / a.accum
            p.backward()
            pl += p.item()
        gn = torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0).item()
        opt.step()
        opt.zero_grad(set_to_none=True)
        paso += 1
        perdidas.append(pl)
        normas.append(gn)
        if not (math.isfinite(pl) and math.isfinite(gn)):
            print(f"NO FINITO en el paso {paso}: loss {pl} gnorm {gn}", flush=True)
            break
        if paso == a.medir_desde:
            torch.cuda.synchronize()
            t_medir = time.time()
        if paso == a.medir_desde + 40 and total_pasos is None:
            torch.cuda.synchronize()
            seg_paso = (time.time() - t_medir) / 40
            restante = a.minutos * 60 - (time.time() - t0)
            total_pasos = paso + int(restante / seg_paso)
            print(f"rendimiento estable: {tok_paso / seg_paso:,.0f} tok/s ({seg_paso:.3f} s/paso) -> {total_pasos} pasos planificados ({total_pasos * tok_paso / 1e6:.0f} M tokens)", flush=True)
        if paso % 25 == 0 or paso <= 5:
            torch.cuda.synchronize()
            ts = (tok_paso * (paso - a.medir_desde) / (time.time() - t_medir)) if t_medir and paso > a.medir_desde else 0
            fila = {"paso": paso, "tokens_M": round(paso * tok_paso / 1e6, 1), "loss": round(pl, 4), "gnorm": round(gn, 3), "lr": lr, "tok_s": round(ts), "vram_pico_GB": round(torch.cuda.max_memory_allocated() / 2**30, 2), "min": round((time.time() - t0) / 60, 1)}
            reg.write(json.dumps(fila) + "\n")
            reg.flush()
            print(fila, flush=True)
    torch.cuda.synchronize()
    seg_total = time.time() - t0
    seg_paso_final = (time.time() - t_medir) / (paso - a.medir_desde) if t_medir else float("nan")
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    torch.save({"config": cfg.__dict__, "pesos": modelo.state_dict(), "paso": paso}, a.salida)

    # --- perplejidad en validación: embedding atado fp32 / fp16 / int8 por fila
    val = np.fromfile(CORPUS / "val_000.bin", dtype=np.uint16)
    E = modelo.tok.weight.detach()
    res = {}
    for nombre, emb in (("fp32 (master)", E), ("fp16", E.half().float()), ("int8 por fila", cuantizar_int8_por_fila(E))):
        ppl, nll = perplejidad(modelo, val, a.T, emb)
        res[nombre] = {"ppl": ppl, "nll": nll}
        print(f"val {len(val) / 1e6:.1f} M tokens | embedding {nombre:14s}: nll {nll:.4f} ppl {ppl:.3f}", flush=True)

    ult = perdidas[-50:]
    tok_s = tok_paso / seg_paso_final
    informe = {
        "pasos": paso, "tokens_entrenados": paso * tok_paso, "tokens_por_paso": tok_paso, "segundos": round(seg_total),
        "tok_s_estable": round(tok_s), "vram_pico_GB": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "horas_para_4000M": round(4e9 / tok_s / 3600, 1),
        "loss_inicial": perdidas[0], "loss_final_media50": float(np.mean(ult)), "loss_min": min(perdidas),
        "gnorm_max": max(normas), "gnorm_media": float(np.mean(normas)), "gnorm_ultimos50": float(np.mean(normas[-50:])),
        "picos_de_loss(>+0.5 sobre media móvil)": int(sum(1 for i in range(50, len(perdidas)) if perdidas[i] > np.mean(perdidas[i - 50:i]) + 0.5)),
        "validacion": res, "parametros_M": modelo.parametros() / 1e6, "compile": not a.sin_compile,
    }
    Path(a.registro + ".json").write_text(json.dumps(informe, indent=1), encoding="utf-8")
    print(json.dumps(informe, indent=1), flush=True)


if __name__ == "__main__":
    main()
