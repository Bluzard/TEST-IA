"""Cadena automática posterior al preentrenamiento del núcleo v2-A. Espera a que termine pretrain_v2.py y ejecuta, en orden:

  1 comprobar   el preentrenamiento terminó bien (resultados/ETAPA4_pretrain_final.json y nucleo_v2_pretrain.pt)
  2 sft_humo    prueba rápida del SFT en GPU (64 ejemplos); si falla, se detiene antes de gastar horas
  3 sft         SFT completo (datos/v2/sft/sft_train.jsonl, 3 épocas) -> modelos/experimentos/nucleo_v2_sft.pt
  4 exportar    NUCL0002 + verificación de logits motor vs PyTorch (debe dar TODO CORRECTO)
  5 evaluar     evaluación por el motor C++ (ddgs real, simulado, charla)
  6 lora_codigo / 7 lora_redaccion   expertos LoRA (recetas de v1) + exportación LORA0002
  8 verificar_lora   motor vs PyTorch con cada LoRA
  9 informe     estudios/ETAPA4_FASE3_resultados.md

Reglas: todo se escribe en modelos/experimentos/ (nunca en modelos/, que es producción congelada); no hace commit ni push; no promueve nada.
Se detiene en el primer fallo y lo deja en resultados/ETAPA4_cadena_estado.json. Es reanudable: las etapas hechas se saltan.

  .venv/Scripts/python.exe cadena_v2.py --esperar_pid 18968
  .venv/Scripts/python.exe cadena_v2.py --simulacro        # solo muestra qué haría
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
ESTADO = RES / "ETAPA4_cadena_estado.json"
PY = sys.executable


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def vivo(pid):
    if not pid:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out and "python" in out.lower()


def cargar_estado():
    return json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {"etapas": {}}


def guardar_estado(e):
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


def etapas():
    sft = [PY, "sft_v2.py", "--datos", "datos/v2/sft/sft_train.jsonl", "--eval", "datos/v2/sft/sft_eval.jsonl", "--lote_tokens", "8192", "--epocas", "3",
           "--base", str(EXP / "pretrain_v2" / "nucleo_v2_pretrain.pt"), "--salida", str(EXP / "nucleo_v2_sft.pt")]
    return [
        ("sft_humo", [PY, "sft_v2.py", "--datos", "datos/v2/sft/sft_train.jsonl", "--max", "128", "--epocas", "1", "--lote_tokens", "8192",
                      "--base", str(EXP / "pretrain_v2" / "nucleo_v2_pretrain.pt"), "--salida", str(EXP / "_humo_sft.pt")], [EXP / "_humo_sft.pt"]),
        ("sft", sft, [EXP / "nucleo_v2_sft.pt"]),
        ("exportar", [PY, "exportar_v2.py", str(EXP / "nucleo_v2_sft.pt"), "--verificar"], [EXP / "nucleo_v2_sft.bin"]),
        ("evaluar", [PY, "evaluar_v2.py", str(EXP / "nucleo_v2_sft.bin"), "--n", "300"], [RES / "ETAPA4_eval_v2.json"]),
        ("lora_codigo", [PY, "entrenar_lora_v2.py", "--nombre", "codigo", "--datos", "datos/experto_train_B2.jsonl", "--epocas", "3", "--lote_tokens", "8192"], [EXP / "experto_codigo_v2.lora"]),
        ("lora_redaccion", [PY, "entrenar_lora_v2.py", "--nombre", "redaccion", "--datos", "datos/redaccion_train.jsonl", "--epocas", "6", "--lote_tokens", "8192"], [EXP / "experto_redaccion_v2.lora"]),
        ("verificar_lora_codigo", [PY, "verificar_lora_v2.py", str(EXP / "nucleo_v2_sft.pt"), str(EXP / "nucleo_v2_sft.bin"), str(EXP / "experto_codigo_v2.lora.pt")], []),
        ("verificar_lora_redaccion", [PY, "verificar_lora_v2.py", str(EXP / "nucleo_v2_sft.pt"), str(EXP / "nucleo_v2_sft.bin"), str(EXP / "experto_redaccion_v2.lora.pt")], []),
    ]


def informe(estado):
    ev = json.loads((RES / "ETAPA4_eval_v2.json").read_text(encoding="utf-8")) if (RES / "ETAPA4_eval_v2.json").exists() else {}
    real = ev.get("real", {})
    hechos = real.get("buscar_ok", {}).get("respuesta_exacta")
    abst = [real[t]["se_abstuvo"] for t in ("irrelevante", "vacio") if t in real]
    ch = ev.get("charla", {})

    def pct(x):
        return "—" if x is None else f"{x:.1%}"

    def perdidas(log):
        p = RES / f"ETAPA4_cadena_{log}.log"
        if not p.exists():
            return "—"
        lineas = [l for l in p.read_text(encoding="utf-8", errors="ignore").splitlines() if "pérdida" in l]
        return lineas[-1].strip() if lineas else "—"

    filas = "\n".join(f"| {k} | {v['estado']} | {v.get('segundos', '—')} s |" for k, v in estado["etapas"].items())
    sim = ev.get("simulado", {})
    (RAIZ / "estudios" / "ETAPA4_FASE3_resultados.md").write_text(f"""# Etapa 4 · Fase 3 — Resultados de la cadena automática (SFT, exportación, evaluación y expertos)

Generado por `cadena_v2.py` el {ahora()}. **No se promovió nada a `modelos/`**; todo está en `modelos/experimentos/` a la espera de decisión.

## Etapas
| etapa | estado | tiempo |
|---|---|---|
{filas}

## Núcleo v2 con SFT frente a v1 (evaluación por el motor C++, ddgs real, `datos/sft_eval_real.jsonl`)
| métrica | v1 (producción) | v2-A + SFT |
|---|---|---|
| hechos (respuesta exacta) | 71,6 % | {pct(hechos)} |
| abstención (irrelevante / vacío) | 98,1 % | {pct(sum(abst) / len(abst)) if abst else '—'} |
| charla: no busca / respuesta válida | 100 % (18 saludos exactos) | {pct(ch.get('no_busco'))} / {pct(ch.get('respuesta_valida'))} |

Simulado con artículos reservados: {json.dumps(sim, ensure_ascii=False)}

Última pérdida del SFT: `{perdidas('sft')}`
Última pérdida LoRA código: `{perdidas('lora_codigo')}` · redacción: `{perdidas('lora_redaccion')}`

Notas: la charla de v2 es más amplia que los 18 saludos de v1, así que no es comparable palabra por palabra. Los expertos LoRA aún no se evalúan con sus pruebas propias (`evaluar_experto.py` es de v1): falta portarlo antes de aceptarlos.
Detalle: `resultados/ETAPA4_eval_v2.json` y los logs `resultados/ETAPA4_cadena_*.log`.
""", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esperar_pid", type=int, default=0)
    ap.add_argument("--simulacro", action="store_true")
    a = ap.parse_args()
    RES.mkdir(exist_ok=True)
    os.chdir(RAIZ)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    estado = cargar_estado()
    estado.setdefault("etapas", {})
    if a.simulacro:
        for n, cmd, _ in etapas():
            print(n, "->", " ".join(c if " " not in c else f'"{c}"' for c in cmd))
        return
    if a.esperar_pid:
        print(f"[{ahora()}] esperando al preentrenamiento (PID {a.esperar_pid})…", flush=True)
        estado["esperando"] = {"pid": a.esperar_pid, "desde": ahora()}
        guardar_estado(estado)
        while vivo(a.esperar_pid):
            time.sleep(60)
    final = RES / "ETAPA4_pretrain_final.json"
    pesos = EXP / "pretrain_v2" / "nucleo_v2_pretrain.pt"
    if not (final.exists() and pesos.exists()):
        estado["error"] = "el preentrenamiento no terminó (falta ETAPA4_pretrain_final.json o nucleo_v2_pretrain.pt): se detiene la cadena"
        guardar_estado(estado)
        print(estado["error"], flush=True)
        sys.exit(2)
    estado["etapas"]["comprobar"] = {"estado": "ok", "fin": ahora()}
    estado.pop("error", None)
    guardar_estado(estado)
    for nombre, cmd, salidas in etapas():
        e = estado["etapas"].get(nombre)
        if e and e["estado"] == "ok":
            print(f"[{ahora()}] {nombre}: ya hecha, se salta", flush=True)
            continue
        print(f"[{ahora()}] {nombre}…", flush=True)
        t0 = time.time()
        log = RES / f"ETAPA4_cadena_{nombre}.log"
        with open(log, "w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
            if rc != 0 and "--lote_tokens" in cmd and nombre != "sft_humo":  # posible falta de VRAM: un reintento con el lote a la mitad
                i = cmd.index("--lote_tokens")
                cmd2 = cmd[:i + 1] + [str(int(cmd[i + 1]) // 2)] + cmd[i + 2:]
                f.write(f"\n=== REINTENTO con --lote_tokens {cmd2[i + 1]} (el intento anterior terminó con código {rc}) ===\n")
                f.flush()
                rc = subprocess.run(cmd2, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
        faltan = [str(s) for s in salidas if not Path(s).exists()]
        ok = rc == 0 and not faltan
        estado["etapas"][nombre] = {"estado": "ok" if ok else "FALLO", "segundos": round(time.time() - t0), "fin": ahora(), "codigo": rc, "log": "resultados/" + log.name}
        if faltan:
            estado["etapas"][nombre]["faltan"] = faltan
        if nombre == "sft_humo":
            (EXP / "_humo_sft.pt").unlink(missing_ok=True)
        guardar_estado(estado)
        if not ok:
            estado["error"] = f"falló la etapa {nombre} (código {rc}); ver {log.name}"
            guardar_estado(estado)
            print(estado["error"], flush=True)
            informe(estado)
            sys.exit(1)
    informe(estado)
    estado["terminado"] = ahora()
    guardar_estado(estado)
    print(f"[{ahora()}] cadena terminada: estudios/ETAPA4_FASE3_resultados.md", flush=True)


if __name__ == "__main__":
    main()
