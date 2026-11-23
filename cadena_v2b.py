"""Cadena del núcleo v2b: SFT conjunto (charla ampliada + copia técnica) -> exportar -> evaluar -> LoRA código/redacción -> evaluación completa.

Todo va a modelos/experimentos/ con sufijo v2b (no pisa nada del v2 anterior ni de modelos/). No hace commit ni promueve.
Se detiene en el primer fallo; reanudable (estado en resultados/ETAPA4_cadena_v2b_estado.json). Logs: resultados/ETAPA4_v2b_<etapa>.log

  .venv/Scripts/python.exe cadena_v2b.py [--simulacro]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
EXP = RAIZ / "modelos" / "experimentos"
RES = RAIZ / "resultados"
ESTADO = RES / "ETAPA4_cadena_v2b_estado.json"
PY = sys.executable
BASE = EXP / "pretrain_v2" / "nucleo_v2_pretrain.pt"
SFT = EXP / "nucleo_v2b_sft.pt"
BIN = EXP / "nucleo_v2b_sft.bin"
DATOS = ["datos/v2/sft/sft_train_v2b.jsonl", "datos/v2/sft/sft_copia_tecnica.jsonl"]


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def etapas():
    sft = [PY, "sft_v2.py", "--datos", *DATOS, "--eval", "datos/v2/sft/sft_eval_v2b.jsonl", "--lote_tokens", "8192", "--epocas", "3", "--base", str(BASE), "--salida", str(SFT)]
    humo = [PY, "sft_v2.py", "--datos", DATOS[1], "--max", "128", "--epocas", "1", "--lote_tokens", "8192", "--base", str(BASE), "--salida", str(EXP / "_humo_v2b.pt")]

    def lora(n, datos):
        return [PY, "entrenar_lora_v2.py", "--nombre", n, "--base", str(SFT), "--datos", datos, "--epocas", "5", "--lote_tokens", "8192", "--lr", "1e-3"]

    return [
        ("sft_humo", humo, [EXP / "_humo_v2b.pt"]),
        ("sft", sft, [SFT]),
        ("exportar", [PY, "exportar_v2.py", str(SFT), "--verificar"], [BIN]),
        ("evaluar", [PY, "evaluar_v2.py", str(BIN), "--n", "300", "--eval_sft", "sft_eval_v2b.jsonl", "--salida", str(RES / "ETAPA4_eval_v2b.json")], [RES / "ETAPA4_eval_v2b.json"]),
        ("lora_codigo", lora("codigo_b", "datos/experto_train_B2.jsonl"), [EXP / "experto_codigo_b_v2.lora"]),
        ("lora_redaccion", lora("redaccion_b", "datos/redaccion_train.jsonl"), [EXP / "experto_redaccion_b_v2.lora"]),
        ("verificar_lora_codigo", [PY, "verificar_lora_v2.py", str(SFT), str(BIN), str(EXP / "experto_codigo_b_v2.lora.pt")], []),
        ("verificar_lora_redaccion", [PY, "verificar_lora_v2.py", str(SFT), str(BIN), str(EXP / "experto_redaccion_b_v2.lora.pt")], []),
        ("expertos", [PY, "evaluar_expertos_v2.py", "--bin", str(BIN), "--lora_codigo", str(EXP / "experto_codigo_b_v2.lora"), "--lora_redaccion", str(EXP / "experto_redaccion_b_v2.lora"),
                      "--salida", str(RES / "ETAPA4_expertos_v2b.json")], [RES / "ETAPA4_expertos_v2b.json"]),
    ]


def pct(x):
    return "—" if x is None else f"{x:.1%}".replace(".", ",")


def informe(estado):
    def g(p):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    ev, ex = g(RES / "ETAPA4_eval_v2b.json"), g(RES / "ETAPA4_expertos_v2b.json")
    ch = ev.get("charla", {})
    real = ev.get("real", {})
    abst = [real[t]["se_abstuvo"] for t in ("irrelevante", "vacio") if t in real]
    cod, red = ex.get("codigo", {}), ex.get("redaccion", {})

    def gen(e):
        def f(x):
            return pct(list(x["irrelevante"].values())[1]) if x else "—"
        return f(e.get("general_activo")) + " / " + f(e.get("general_dormido"))

    def perd(n):
        p = RES / f"ETAPA4_v2b_{n}.log"
        if not p.exists():
            return "—"
        ls = [x.strip() for x in p.read_text(encoding="utf-8", errors="ignore").splitlines() if "pérdida" in x]
        return ls[-1] if ls else "—"

    filas = "\n".join(f"| {k} | {v['estado']} | {v.get('segundos', '—')} s |" for k, v in estado["etapas"].items())
    (RAIZ / "estudios" / "ETAPA4_FASE4_v2b.md").write_text(f"""# Etapa 4 · Fase 4 — Núcleo v2b (SFT conjunto: charla ampliada + copia técnica)

Generado por `cadena_v2b.py` el {ahora()}. Nada se promovió a `modelos/`.

## Etapas
| etapa | estado | tiempo |
|---|---|---|
{filas}

## Comparativa v1 · v2 anterior · v2b
| métrica | v1 (producción) | v2 anterior | **v2b** |
|---|---|---|---|
| hechos (ddgs real, respuesta exacta) | 71,6 % | 83,3 % | {pct(real.get('buscar_ok', {}).get('respuesta_exacta'))} |
| abstención (irrelevante/vacío) | 98,1 % | 99,0 % | {pct(sum(abst) / len(abst)) if abst else '—'} |
| charla, 339 frases únicas (media por intención, con equivalentes) | 100 % en 18 saludos (no comparable) | 53,6 % | {pct(ch.get('equivalentes_macro'))} |
| charla estricta (media por intención) | — | — | {pct(ch.get('estricta_macro'))} |
| experto código (puntaje, 9 tipos) | 82,2 % | 45,6 % | {pct(cod.get('experto', {}).get('_puntaje'))} |
| experto redacción (puntaje) | 56,2 % | 45,5 % | {pct(red.get('experto', {}).get('_puntaje'))} |
| abstención «irrelevante» con LoRA código, activo / dormido | 98,1 % (dormido) | 92,3 % / 98,1 % | {gen(cod)} |
| abstención «irrelevante» con LoRA redacción, activo / dormido | 100 % / 98,1 % | 94,2 % / 98,1 % | {gen(red)} |

Última pérdida: SFT `{perd('sft')}` · LoRA código `{perd('lora_codigo')}` · LoRA redacción `{perd('lora_redaccion')}`
(el techo de los LoRA con el núcleo anterior era ≈ 0,96 en código).

Detalle: `resultados/ETAPA4_eval_v2b.json`, `ETAPA4_expertos_v2b.json`, logs `resultados/ETAPA4_v2b_*.log`.
""", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulacro", action="store_true")
    a = ap.parse_args()
    os.chdir(RAIZ)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if a.simulacro:
        for n, cmd, _ in etapas():
            print(n, "->", " ".join(cmd))
        return
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {"etapas": {}}
    for nombre, cmd, salidas in etapas():
        e = estado["etapas"].get(nombre)
        if e and e["estado"] == "ok":
            print(f"[{ahora()}] {nombre}: ya hecha", flush=True)
            continue
        print(f"[{ahora()}] {nombre}…", flush=True)
        t0 = time.time()
        log = RES / f"ETAPA4_v2b_{nombre}.log"
        with open(log, "w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
            if rc != 0 and "--lote_tokens" in cmd and nombre != "sft_humo":
                i = cmd.index("--lote_tokens")
                cmd2 = cmd[:i + 1] + [str(int(cmd[i + 1]) // 2)] + cmd[i + 2:]
                f.write(f"\n=== REINTENTO con --lote_tokens {cmd2[i + 1]} ===\n")
                f.flush()
                rc = subprocess.run(cmd2, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
        faltan = [str(s) for s in salidas if not Path(s).exists()]
        ok = rc == 0 and not faltan
        estado["etapas"][nombre] = {"estado": "ok" if ok else "FALLO", "segundos": round(time.time() - t0), "fin": ahora(), "codigo": rc}
        if nombre == "sft_humo":
            (EXP / "_humo_v2b.pt").unlink(missing_ok=True)
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        if not ok:
            print(f"falló {nombre} (código {rc}); ver {log.name}", flush=True)
            informe(estado)
            sys.exit(1)
    informe(estado)
    print(f"[{ahora()}] cadena v2b terminada: estudios/ETAPA4_FASE4_v2b.md", flush=True)


if __name__ == "__main__":
    main()
