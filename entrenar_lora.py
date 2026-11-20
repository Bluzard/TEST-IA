"""Entrena un adaptador LoRA (experto_codigo) sobre el Núcleo Base congelado y lo evalúa.

  python entrenar_lora.py --nombre r8_todas --r 8                              # configuración principal
  python entrenar_lora.py --nombre r4 --r 4 | r16 --r 16 | atencion --r 8 --objetivos qkv proy
  python entrenar_lora.py --nombre base --r 0                                  # sin LoRA: línea base (no entrena)

Guarda modelos/experimentos/experto_<nombre>.lora.pt y resultados/experto_<nombre>.json (evaluación del experto + regresión general).
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch

import lora
from evaluar_experto import evaluar_experto, imprimir
from inferir import cargar, evaluar as evaluar_general

RAIZ = Path(__file__).parent
BASE = RAIZ / "modelos" / "nucleo_sft_v3.pt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--r", type=int, default=8, help="rango del LoRA (0 = sin LoRA, solo evaluar el núcleo)")
    ap.add_argument("--objetivos", nargs="+", default=list(lora.OBJETIVOS))
    ap.add_argument("--epocas", type=int, default=3)
    ap.add_argument("--lote", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "experto_train.jsonl"))
    ap.add_argument("--cargar", default=None, help="evaluar un .lora.pt ya entrenado en vez de entrenar")
    ap.add_argument("--eval", default=str(RAIZ / "datos" / "experto_eval.jsonl"), help="conjunto de evaluación del experto")
    ap.add_argument("--pen_extra", type=float, default=None, help="evaluar además con otra penalización por repetición")
    args = ap.parse_args()

    torch.manual_seed(args.semilla)
    rng = random.Random(args.semilla)
    disp = "cuda" if torch.cuda.is_available() else "cpu"
    modelo, fmt = cargar(BASE, disp)
    modelo.cfg_lora = None
    suma0 = lora.suma_base(modelo)
    t0 = time.time()
    res = {"nombre": args.nombre, "r": args.r, "objetivos": args.objetivos, "semilla": args.semilla}

    if args.cargar:  # solo evaluar un adaptador existente
        lora.cargar_lora(modelo, args.cargar)
        modelo.to(disp).eval()
        n, mb = lora.contar(modelo)
        res.update(parametros=n, mb_fp16=mb, cargado=args.cargar)
    elif args.r > 0:
        lora.aplicar_lora(modelo, lora.ConfigLora(args.r, 2.0 * args.r, tuple(args.objetivos)))
        modelo.to(disp)
        n, mb = lora.contar(modelo)
        res.update(parametros=n, mb_fp16=mb)
        print(f"[{args.nombre}] LoRA r={args.r} en {args.objetivos}: {n:,} parámetros = {mb:.2f} MB (fp16)", flush=True)

        filas = [json.loads(l) for l in open(args.datos, encoding="utf-8")]
        datos = []
        for r in filas:
            ids, m = fmt.ejemplo(r["pregunta"], r.get("consulta"), r.get("resultados"), r["respuesta"],
                                 prefijo=r.get("pref", "B"), tope=r.get("tope") or 10_000)
            if len(ids) <= modelo.cfg.bloque:
                datos.append((ids, m))
        pasos = args.epocas * math.ceil(len(datos) / args.lote)
        opt = torch.optim.AdamW(lora.parametros_lora(modelo), lr=args.lr, betas=(0.9, 0.95), weight_decay=0.0)
        modelo.train()
        paso = 0
        for ep in range(args.epocas):
            rng.shuffle(datos)
            for a in range(0, len(datos), args.lote):
                grupo = datos[a : a + args.lote]
                L = max(len(i) for i, _ in grupo)
                x = torch.full((len(grupo), L - 1), fmt.relleno, dtype=torch.long)
                y = torch.full((len(grupo), L - 1), fmt.relleno, dtype=torch.long)
                m = torch.zeros(len(grupo), L - 1)
                for j, (ids, mk) in enumerate(grupo):
                    k = len(ids) - 1
                    x[j, :k], y[j, :k], m[j, :k] = torch.tensor(ids[:-1]), torch.tensor(ids[1:]), torch.tensor(mk[1:])
                paso += 1
                lr = args.lr * min(1, paso / 30) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * paso / pasos)))
                for g in opt.param_groups:
                    g["lr"] = lr
                with torch.autocast(disp, dtype=torch.bfloat16):
                    _, perdida = modelo(x.to(disp), y.to(disp), m.to(disp))
                opt.zero_grad(set_to_none=True)
                perdida.backward()
                torch.nn.utils.clip_grad_norm_(lora.parametros_lora(modelo), 1.0)
                opt.step()
                if paso % 100 == 0 or paso == 1:
                    print(f"  época {ep + 1}/{args.epocas} paso {paso}/{pasos} | pérdida {perdida.item():.4f} | {time.time() - t0:.0f}s", flush=True)
        modelo.eval()
        res["perdida_final"] = perdida.item()
        res["entrenamiento_s"] = time.time() - t0
        lora.guardar_lora(modelo, RAIZ / "modelos" / "experimentos" / f"experto_{args.nombre}.lora.pt")
        # el núcleo no puede haber cambiado: ni un peso
        res["nucleo_intacto"] = abs(lora.suma_base(modelo) - suma0) < 1e-6 * max(1.0, abs(suma0))
        print(f"[{args.nombre}] núcleo base intacto tras entrenar: {res['nucleo_intacto']}", flush=True)

    modelo.eval()
    print(f"\n[{args.nombre}] evaluación del experto (penalización 1.0)", flush=True)
    res["experto"] = evaluar_experto(modelo, fmt, disp, ruta=args.eval, pen=1.0)
    imprimir(res["experto"])
    if args.pen_extra:
        res["experto_pen_extra"] = {"pen": args.pen_extra, **evaluar_experto(modelo, fmt, disp, pen=args.pen_extra)}
        print(f"  con penalización {args.pen_extra}: puntaje {res['experto_pen_extra']['_puntaje']:.1%}", flush=True)
    print(f"\n[{args.nombre}] regresión general (Etapa 1, ddgs real)", flush=True)
    res["general"] = evaluar_general(modelo, fmt, disp, ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=300, penalizacion=1.1)
    for t, m in res["general"].items():
        print(f"  {t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()), flush=True)
    if args.r > 0:  # dormido: debe ser idéntico al núcleo base
        lora.activar(modelo, False)
        dormido = evaluar_general(modelo, fmt, disp, ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=300, penalizacion=1.1)
        res["general_dormido"] = dormido
        print("  con el adaptador DORMIDO:", {t: {k: round(v, 3) for k, v in m.items()} for t, m in dormido.items()}, flush=True)
    (RAIZ / "resultados").mkdir(exist_ok=True)
    (RAIZ / "resultados" / f"experto_{args.nombre}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[{args.nombre}] terminado en {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
