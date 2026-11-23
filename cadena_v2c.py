"""Cadena del núcleo v2c (micro-SFT sobre v2b). Dos partes, para poder comprobar que no hay olvido antes de entrenar los LoRA:

  parte 1: micro-SFT (≈ 20-30 min) -> exportar (+verificación de paridad) -> evaluar el núcleo solo (hechos, abstención, charla)
  parte 2: LoRA código y redacción sobre v2c (repaso + parada temprana) -> verificar -> evaluación completa de expertos (núcleo solo y con LoRA)

  .venv/Scripts/python.exe cadena_v2c.py 1
  .venv/Scripts/python.exe cadena_v2c.py 2

Todo en modelos/experimentos/ (sufijo v2c). No toca modelos/, no hace commit. Se detiene en el primer fallo; reanudable.
"""
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
ESTADO = RES / "ETAPA4_cadena_v2c_estado.json"
PY = sys.executable
V2B = EXP / "nucleo_v2b_sft.pt"
SFT = EXP / "nucleo_v2c_sft.pt"
BIN = EXP / "nucleo_v2c_sft.bin"


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def etapas(parte):
    def lora(n, datos, epocas, parar):
        return [PY, "entrenar_lora_v2.py", "--nombre", n, "--base", str(SFT), "--datos", datos, "--epocas", str(epocas), "--lote_tokens", "8192", "--lr", "1e-3", "--parar_perdida", str(parar)]

    p1 = [
        ("microsft", [PY, "sft_v2.py", "--base", str(V2B), "--continuar", "--datos", "datos/v2/sft/microsft_train.jsonl", "--eval", "datos/v2/sft/sft_eval_v2b.jsonl",
                      "--lote_tokens", "8192", "--epocas", "2", "--lr", "1e-4", "--salida", str(SFT)], [SFT]),
        ("exportar", [PY, "exportar_v2.py", str(SFT), "--verificar"], [BIN]),
        ("evaluar", [PY, "evaluar_v2.py", str(BIN), "--n", "300", "--eval_sft", "sft_eval_v2b.jsonl", "--salida", str(RES / "ETAPA4_eval_v2c.json")], [RES / "ETAPA4_eval_v2c.json"]),
    ]
    p2 = [
        ("lora_redaccion", lora("redaccion_d", "datos/v2/lora_redaccion_mezcla.jsonl", 4, 0.05), [EXP / "experto_redaccion_d_v2.lora"]),
        ("lora_codigo", lora("codigo_d", "datos/v2/lora_codigo_mezcla.jsonl", 3, 0.08), [EXP / "experto_codigo_d_v2.lora"]),
        ("verificar_lora_codigo", [PY, "verificar_lora_v2.py", str(SFT), str(BIN), str(EXP / "experto_codigo_d_v2.lora.pt")], []),
        ("verificar_lora_redaccion", [PY, "verificar_lora_v2.py", str(SFT), str(BIN), str(EXP / "experto_redaccion_d_v2.lora.pt")], []),
        ("expertos", [PY, "evaluar_expertos_v2.py", "--bin", str(BIN), "--lora_codigo", str(EXP / "experto_codigo_d_v2.lora"), "--lora_redaccion", str(EXP / "experto_redaccion_d_v2.lora"),
                      "--salida", str(RES / "ETAPA4_expertos_v2c_nucleo.json")], [RES / "ETAPA4_expertos_v2c_nucleo.json"]),
    ]
    return p1 if parte == "1" else p2


def main():
    parte = sys.argv[1] if len(sys.argv) > 1 else "1"
    os.chdir(RAIZ)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {"etapas": {}}
    for nombre, cmd, salidas in etapas(parte):
        e = estado["etapas"].get(nombre)
        if e and e["estado"] == "ok":
            print(f"[{ahora()}] {nombre}: ya hecha", flush=True)
            continue
        print(f"[{ahora()}] {nombre}…", flush=True)
        t0 = time.time()
        log = RES / f"ETAPA4_v2c_{nombre}.log"
        with open(log, "w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
            if rc != 0 and "--lote_tokens" in cmd:
                i = cmd.index("--lote_tokens")
                cmd2 = cmd[:i + 1] + [str(int(cmd[i + 1]) // 2)] + cmd[i + 2:]
                f.write(f"\n=== REINTENTO con --lote_tokens {cmd2[i + 1]} ===\n")
                f.flush()
                rc = subprocess.run(cmd2, stdout=f, stderr=subprocess.STDOUT, cwd=RAIZ).returncode
        faltan = [str(s) for s in salidas if not Path(s).exists()]
        ok = rc == 0 and not faltan
        estado["etapas"][nombre] = {"estado": "ok" if ok else "FALLO", "segundos": round(time.time() - t0), "fin": ahora(), "codigo": rc}
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        if not ok:
            print(f"falló {nombre} (código {rc}); ver {log.name}", flush=True)
            sys.exit(1)
    print(f"[{ahora()}] parte {parte} terminada", flush=True)


if __name__ == "__main__":
    main()
