"""Preentrenamiento del núcleo v2-A (≈158 M) sobre el corpus de la Fase 1.

  .venv/Scripts/python.exe pretrain_v2.py              # arranca de cero
  .venv/Scripts/python.exe pretrain_v2.py --reanudar   # continúa desde el último checkpoint válido
  (crear el archivo modelos/experimentos/pretrain_v2/PARAR pausa limpiamente: guarda checkpoint y sale)

Reglas:
 * Curriculum de longitud: 80 % de los tokens en ventanas de 512 (micro-lote 16 × 4) y 20 % final en ventanas de 1.024 (micro-lote 8 × 8);
   siempre 32.768 tokens por paso.
 * Datos: UNA época exacta. Se parte el corpus en bloques de 1.024 tokens, se barajan con semilla fija; el 80 % inicial se parte en
   dos ventanas de 512 y el 20 % final se usa entero a 1.024 (así las posiciones 512–1023 se entrenan con texto no visto antes).
   El lote del paso s es función pura de s ⇒ la reanudación es exacta.
 * Checkpoint cada 3.000 pasos (modelo + optimizador + paso), se conservan los 3 últimos; validación rápida (1 M tokens fijos) en cada uno.
 * Validación completa (8,2 M, embedding fp32 / fp16 / int8 por fila) y documento estudios/ETAPA4_FASE2_pretrain.md solo al final.
No toca ningún peso congelado.
"""
import argparse
import json
import math
import os
import queue
import threading
import time
from pathlib import Path

import numpy as np
import torch

from modelo_v2 import ConfigV2, NucleoV2

RAIZ = Path(__file__).parent
CORPUS = RAIZ / "datos" / "v2" / "corpus"
SALIDA = RAIZ / "modelos" / "experimentos" / "pretrain_v2"
B1024 = 1024
SEMILLA_DATOS = 1234


class Plan:
    """Bloques de 1.024 tokens barajados; reparto 80 % (a 512) / 20 % (a 1.024). El lote del paso s es una función pura de s."""

    def __init__(self, fraccion=1.0, tokens_paso=32768):
        self.m = [np.memmap(p, dtype=np.uint16, mode="r") for p in sorted(CORPUS.glob("*.bin")) if not p.name.startswith("val")]
        nbs = [(len(a) - 1) // B1024 for a in self.m]
        self.cum = np.concatenate([[0], np.cumsum(nbs)])
        nb = int(self.cum[-1] * fraccion)
        self.perm = np.random.default_rng(SEMILLA_DATOS).permutation(int(self.cum[-1]))[:nb]
        self.K = int(0.8 * nb)  # bloques que se parten en dos ventanas de 512
        self.v1 = tokens_paso // 512      # ventanas de 512 por paso (64)
        self.v2 = tokens_paso // B1024    # ventanas de 1.024 por paso (32)
        self.pasos1 = (2 * self.K) // self.v1
        self.pasos2 = (nb - self.K) // self.v2
        self.total = self.pasos1 + self.pasos2
        self.tokens_corpus = int(self.cum[-1]) * B1024

    def T(self, paso):
        return 512 if paso < self.pasos1 else B1024

    def ventana(self, bloque, mitad, T):
        s = int(np.searchsorted(self.cum, bloque, side="right") - 1)
        o = (bloque - int(self.cum[s])) * B1024 + mitad * 512
        return self.m[s][o:o + T + 1]

    def lote_micro(self, paso, k, micro):
        """Ventanas [k·micro, (k+1)·micro) del paso `paso`."""
        T = self.T(paso)
        filas = []
        for j in range(k * micro, (k + 1) * micro):
            if T == 512:
                w = paso * self.v1 + j
                filas.append(self.ventana(int(self.perm[w // 2]), w % 2, 512))
            else:
                w = (paso - self.pasos1) * self.v2 + j
                filas.append(self.ventana(int(self.perm[self.K + w]), 0, B1024))
        return torch.from_numpy(np.stack(filas).astype(np.int64))


def productor(plan, desde, accum_micro, q):
    for paso in range(desde, plan.total):
        T = plan.T(paso)
        accum, micro = accum_micro[T]
        for k in range(accum):
            q.put((paso, plan.lote_micro(paso, k, micro)))
    q.put(None)


def cuantizar_int8_por_fila(E):
    esc = (E.abs().amax(dim=1, keepdim=True) / 127).clamp(min=1e-8).to(torch.float16).float()
    return (E / esc).round().clamp(-127, 127) * esc


@torch.no_grad()
def evaluar(modelo, ventanas, emb=None, B=16):
    """nll medio sobre ventanas (lista de arreglos uint16 de 513 tokens)."""
    modelo.eval()
    tot, cnt = 0.0, 0
    for i in range(0, len(ventanas), B):
        x = torch.from_numpy(np.stack(ventanas[i:i + B]).astype(np.int64)).cuda()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            p = modelo(x[:, :-1], x[:, 1:], emb_head=emb)
        tot += p.item() * len(x)
        cnt += len(x)
    modelo.train()
    return tot / cnt


def ventanas_val(n_ventanas):
    """Ventanas de 512(+1) repartidas a intervalos regulares por todo el archivo de validación (que está ordenado por fuente)."""
    v = np.memmap(CORPUS / "val_000.bin", dtype=np.uint16, mode="r")
    n = (len(v) - 1) // 512
    idx = np.linspace(0, n - 1, min(n_ventanas, n)).astype(int)
    return [np.array(v[i * 512:i * 512 + 513]) for i in idx]


def guardar_ckpt(modelo, opt, paso, hist, args):
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / f"ckpt_{paso:06d}.pt"
    tmp = ruta.with_suffix(".tmp")
    torch.save({"pesos": modelo.state_dict(), "opt": opt.state_dict(), "paso": paso, "hist": hist, "args": vars(args), "semilla_datos": SEMILLA_DATOS}, tmp)
    os.replace(tmp, ruta)
    for vieja in sorted(SALIDA.glob("ckpt_*.pt"))[:-3]:
        vieja.unlink()
    for t in SALIDA.glob("*.tmp"):
        t.unlink()
    return ruta


def ultimo_ckpt():
    for ruta in sorted(SALIDA.glob("ckpt_*.pt"), reverse=True):
        try:
            return ruta, torch.load(ruta, map_location="cpu", weights_only=False)
        except Exception as e:  # checkpoint corrupto (corte de luz): probar el anterior
            print(f"checkpoint ilegible {ruta.name}: {e}", flush=True)
    return None, None


def lr_en(paso, a, total):
    cos = 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * paso / total))
    return a.lr * cos * min(1.0, (paso + 1) / a.warmup)


def main():
    global SALIDA
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--ckpt_cada", type=int, default=3000)
    ap.add_argument("--val_rapida_ventanas", type=int, default=1953, help="1953 × 512 ≈ 1 M tokens")
    ap.add_argument("--val_final_ventanas", type=int, default=10**9, help="todas (8,2 M tokens) por defecto")
    ap.add_argument("--fraccion", type=float, default=1.0, help="fracción del corpus (solo para pruebas)")
    ap.add_argument("--tope_vram_gb", type=float, default=13.0)
    ap.add_argument("--dir", default=str(SALIDA))
    ap.add_argument("--registro", default=str(RAIZ / "resultados" / "ETAPA4_pretrain"))
    ap.add_argument("--doc", default=str(RAIZ / "estudios" / "ETAPA4_FASE2_pretrain.md"))
    args = ap.parse_args()
    SALIDA = Path(args.dir)

    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = True
    # techo duro de VRAM: si se superara, falla (OOM) en lugar de desbordar a memoria compartida de Windows (que haría el entrenamiento ×100 más lento)
    torch.cuda.set_per_process_memory_fraction(args.tope_vram_gb * 2**30 / torch.cuda.get_device_properties(0).total_memory)
    plan = Plan(args.fraccion)
    accum_micro = {512: (4, 16), 1024: (8, 4)}
    tok_paso = 32768
    cfg = ConfigV2()
    modelo = NucleoV2(cfg).cuda()
    fwd = torch.compile(modelo, dynamic=False)
    decay = [p for n, p in modelo.named_parameters() if p.ndim >= 2 and "pos" not in n]
    nodecay = [p for n, p in modelo.named_parameters() if not (p.ndim >= 2 and "pos" not in n)]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": nodecay, "weight_decay": 0.0}], lr=args.lr, betas=(0.9, 0.95), fused=True)

    paso0, hist = 0, {"val_rapida": [], "ckpts": []}
    if args.reanudar:
        ruta, ck = ultimo_ckpt()
        if ck is None:
            print("no hay checkpoint: se empieza de cero", flush=True)
        else:
            modelo.load_state_dict(ck["pesos"])
            opt.load_state_dict(ck["opt"])
            paso0, hist = ck["paso"], ck["hist"]
            assert ck["semilla_datos"] == SEMILLA_DATOS
            print(f"reanudado desde {ruta.name}: paso {paso0:,}", flush=True)
    SALIDA.mkdir(parents=True, exist_ok=True)
    parar = SALIDA / "PARAR"
    if parar.exists():
        parar.unlink()

    print(f"v2-A {modelo.parametros() / 1e6:.1f} M | corpus {plan.tokens_corpus / 1e9:.3f} B tokens | tramo 1: {plan.pasos1:,} pasos a 512 | tramo 2: {plan.pasos2:,} pasos a 1.024 | total {plan.total:,} pasos = {plan.total * tok_paso / 1e9:.3f} B tokens", flush=True)
    vrapida = ventanas_val(args.val_rapida_ventanas)
    curva = open(args.registro + "_curva.jsonl", "a", encoding="utf-8")
    q = queue.Queue(8)
    threading.Thread(target=productor, args=(plan, paso0, accum_micro, q), daemon=True).start()

    t_ini, tok_ini = time.time(), paso0 * tok_paso
    ventana_l, ventana_g, ultimo_log = [], [], time.time()
    paso, no_finitos, pico_vram = paso0, 0, 0.0
    T_actual = plan.T(paso0)
    hist.setdefault("tiempo_previo_s", 0.0)
    t_previo = hist["tiempo_previo_s"]
    while paso < plan.total:
        T = plan.T(paso)
        if T != T_actual:
            print(f"=== paso {paso:,}: empieza el tramo 2 (ventanas de 1.024, micro-lote 4 × 8 acumulaciones) ===", flush=True)
            T_actual = T
        lr = lr_en(paso, args, plan.total)
        for g in opt.param_groups:
            g["lr"] = lr
        accum, micro = accum_micro[T]
        acc = torch.zeros((), device="cuda")
        for _ in range(accum):
            p_, x = q.get()
            assert p_ == paso
            x = x.cuda(non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                perd = fwd(x[:, :-1], x[:, 1:]) / accum
            perd.backward()
            acc += perd.detach()
        gn = torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
        pl, gnv = acc.item(), gn.item()
        if not (math.isfinite(pl) and math.isfinite(gnv)):
            no_finitos += 1
            opt.zero_grad(set_to_none=True)
            print(f"paso {paso}: valor no finito (loss {pl}, gnorm {gnv}); se omite el paso ({no_finitos})", flush=True)
            if no_finitos >= 5:
                raise SystemExit("5 pasos no finitos: se detiene (el último checkpoint es válido)")
            paso += 1
            continue
        no_finitos = 0
        opt.step()
        opt.zero_grad(set_to_none=True)
        paso += 1
        ventana_l.append(pl)
        ventana_g.append(gnv)
        pico_vram = max(pico_vram, torch.cuda.max_memory_allocated() / 2**30)
        if paso % 100 == 0 or paso == plan.total:
            ahora = time.time()
            ts = 100 * tok_paso / (ahora - ultimo_log) if paso % 100 == 0 else 0
            ultimo_log = ahora
            hecho = (paso - paso0) * tok_paso
            seg = ahora - t_ini
            eta_h = (plan.total - paso) * tok_paso / max(ts or hecho / seg, 1) / 3600
            fila = {"paso": paso, "tokens_M": round(paso * tok_paso / 1e6, 1), "T": T, "loss": round(float(np.mean(ventana_l)), 4), "gnorm": round(float(np.mean(ventana_g)), 3), "gnorm_max": round(float(np.max(ventana_g)), 3), "lr": lr, "tok_s": round(ts), "vram_pico_GB": round(pico_vram, 2), "eta_h": round(eta_h, 1), "t_h": round((t_previo + seg) / 3600, 2)}
            ventana_l, ventana_g = [], []
            curva.write(json.dumps(fila) + "\n")
            curva.flush()
            if paso % 500 == 0 or paso <= 300 or paso == plan.total:
                print(fila, flush=True)
        if paso % args.ckpt_cada == 0 or parar.exists():
            torch.cuda.empty_cache()
            nll = evaluar(modelo, vrapida)
            hist["val_rapida"].append({"paso": paso, "tokens_M": round(paso * tok_paso / 1e6, 1), "nll": nll, "ppl": math.exp(nll)})
            hist["tiempo_previo_s"] = t_previo + (time.time() - t_ini)
            ruta = guardar_ckpt(modelo, opt, paso, hist, args)
            print(f"[checkpoint] {ruta.name} | val rápida (1 M tokens): nll {nll:.4f} ppl {math.exp(nll):.2f}", flush=True)
            ultimo_log = time.time()
            if parar.exists():
                parar.unlink()
                print("PARAR detectado: checkpoint guardado, se sale. Reanudar con --reanudar", flush=True)
                return

    # ------------------------------------------------------------------ cierre
    hist["tiempo_previo_s"] = t_previo + (time.time() - t_ini)
    guardar_ckpt(modelo, opt, paso, hist, args)
    torch.save({"config": cfg.__dict__, "pesos": modelo.state_dict(), "paso": paso, "tokens": paso * tok_paso}, SALIDA / "nucleo_v2_pretrain.pt")
    print("entrenamiento terminado; validación completa…", flush=True)
    torch.cuda.empty_cache()
    v = np.memmap(CORPUS / "val_000.bin", dtype=np.uint16, mode="r")
    n = min((len(v) - 1) // 512, args.val_final_ventanas)
    ventanas = [np.array(v[i * 512:i * 512 + 513]) for i in range(n)]
    E = modelo.tok.weight.detach()
    val = {}
    for nombre, emb in (("fp32 (master)", E), ("fp16", E.half().float()), ("int8 por fila", cuantizar_int8_por_fila(E))):
        nll = evaluar(modelo, ventanas, emb)
        val[nombre] = {"nll": nll, "ppl": math.exp(nll)}
        print(f"val completa ({n * 512 / 1e6:.1f} M tokens) | embedding {nombre:14s}: nll {nll:.4f} ppl {math.exp(nll):.3f}", flush=True)
    filas = [json.loads(l) for l in open(args.registro + "_curva.jsonl", encoding="utf-8")]
    gn = [f["gnorm"] for f in filas]
    l = [f["loss"] for f in filas]
    picos = sum(1 for i in range(20, len(l)) if l[i] > np.mean(l[i - 20:i]) + 0.3)
    horas = hist["tiempo_previo_s"] / 3600
    tok_s_med = [f["tok_s"] for f in filas if f["tok_s"] and f["T"] == 512]
    tok_s_med2 = [f["tok_s"] for f in filas if f["tok_s"] and f["T"] == 1024]
    info = {
        "pasos": paso, "tokens_entrenados": paso * tok_paso, "horas_de_entrenamiento": round(horas, 2),
        "tramo1": {"pasos": plan.pasos1, "T": 512, "tok_s_mediana": int(np.median(tok_s_med)) if tok_s_med else None},
        "tramo2": {"pasos": plan.pasos2, "T": 1024, "tok_s_mediana": int(np.median(tok_s_med2)) if tok_s_med2 else None},
        "loss_final_media": float(np.mean(l[-10:])), "loss_min": min(l), "gnorm_media": float(np.mean(gn)), "gnorm_max_ventana": max(f["gnorm_max"] for f in filas),
        "picos_de_loss": picos, "vram_pico_GB": max(f["vram_pico_GB"] for f in filas),
        "validacion_completa": val, "validacion_rapida": hist["val_rapida"], "ventanas_validacion": n, "parametros_M": modelo.parametros() / 1e6,
        "args": vars(args),
    }
    Path(args.registro + "_final.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    escribir_doc(info, filas, Path(args.doc))
    print("documento escrito:", args.doc, flush=True)


def escribir_doc(info, filas, ruta):
    cada = max(1, len(filas) // 14)
    tabla = "\n".join(f"| {f['paso']:,} | {f['tokens_M']:,.0f} | {f['T']} | {f['loss']:.3f} | {f['gnorm']:.2f} | {f['lr']:.2e} |" for f in filas[::cada])
    vr = "\n".join(f"| {v['paso']:,} | {v['tokens_M']:,.0f} | {v['nll']:.4f} | {v['ppl']:.2f} |" for v in info["validacion_rapida"])
    vc = info["validacion_completa"]
    base = vc["fp32 (master)"]["ppl"]
    vcf = "\n".join(f"| {k} | {v['nll']:.4f} | {v['ppl']:.3f} | {(v['ppl'] / base - 1) * 100:+.3f} % |" for k, v in vc.items())
    ruta.write_text(f"""# Etapa 4 · Fase 2 — Preentrenamiento del núcleo v2-A

Documento generado automáticamente al terminar `pretrain_v2.py` (métricas en `resultados/ETAPA4_pretrain_final.json`, curva en `resultados/ETAPA4_pretrain_curva.jsonl`).

## Resumen
- Modelo: v2-A, {info['parametros_M']:.1f} M parámetros (22 capas, d=768, GQA 12/4, ff 3072, embeddings atados, BitNet ternario en qkv/proy/fc1/fc2).
- Tokens entrenados: **{info['tokens_entrenados'] / 1e9:.3f} B** en {info['pasos']:,} pasos de 32.768 tokens (una época exacta del corpus de la Fase 1) — **{info['horas_de_entrenamiento']:.1f} h** de entrenamiento.
- Curriculum: tramo 1 {info['tramo1']['pasos']:,} pasos a 512 tokens ({info['tramo1']['tok_s_mediana']} tok/s mediana); tramo 2 {info['tramo2']['pasos']:,} pasos a 1.024 tokens ({info['tramo2']['tok_s_mediana']} tok/s mediana).
- Optimización: AdamW (β 0,9/0,95, wd 0,1), lr pico {info['args']['lr']:.1e} con calentamiento de {info['args']['warmup']} pasos y coseno hasta 10 %, recorte de gradiente 1,0, bf16 + torch.compile + SDPA.
- VRAM pico: {info['vram_pico_GB']} GB (tope impuesto: {info['args']['tope_vram_gb']} GB).
- Estabilidad: loss final {info['loss_final_media']:.3f} (mínimo {info['loss_min']:.3f}); norma de gradiente media {info['gnorm_media']:.2f}, máxima en una ventana de 100 pasos {info['gnorm_max_ventana']:.2f}; picos de loss detectados: {info['picos_de_loss']}.

## Curva de entrenamiento (cada ≈ {cada * 100:,} pasos)
| paso | tokens (M) | ventana | loss | gnorm | lr |
|---|---|---|---|---|---|
{tabla}

## Validación rápida (1 M tokens fijos, ventanas de 512) en cada checkpoint
| paso | tokens (M) | nll | ppl |
|---|---|---|---|
{vr}

## Validación completa ({info['ventanas_validacion'] * 512 / 1e6:.1f} M tokens): embedding atado fp32 vs fp16 vs int8 por fila
| embedding | nll | ppl | Δ ppl vs fp32 |
|---|---|---|---|
{vcf}

La validación sale del mismo reparto de fuentes que el entrenamiento (wiki, web, código), no de un conjunto fuera de dominio; la decontaminación contra las evaluaciones de las Etapas 1–3 está en `estudios/ETAPA4_FASE1_datos.md`.

## Archivos
- Pesos: `modelos/experimentos/pretrain_v2/nucleo_v2_pretrain.pt` (fp32, sin exportar al motor C++; el empaquetado NUCL0002 con embedding int8 es el paso siguiente) y los 3 últimos checkpoints `ckpt_*.pt`.
- Reanudar: `python pretrain_v2.py --reanudar`.

## Siguiente paso
SFT (conversación, protocolo B:/E:/R:, identidad TEST-IA) y evaluación contra v1 (71,6 % / 98,1 % / 100 %). Pendiente: exportar a NUCL0002 y verificar logits del motor contra PyTorch.
""", encoding="utf-8")


if __name__ == "__main__":
    main()
