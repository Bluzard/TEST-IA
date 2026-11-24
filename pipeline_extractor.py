"""Encadena TODO el experimento del experto de extracción, sin intervención:
  1. espera a que termine gen_datos.cjs (o a que se atasque) y copia los pares
  2. descarga el modelo de Ollama de la GPU
  3. construye el dataset (extractor_datos.py)
  4. entrena dos variantes del experto (LoRA sobre el núcleo v2c CONGELADO)
  5. evalúa cada una en los turnos finales (no vistos) y contra la línea base «copiar el estado anterior»
  6. comprueba que los artefactos congelados (núcleo v2c, expertos v2c, v1) siguen idénticos
Todo queda en resultados/ETAPA6_extraccion_*.{log,json}.

  .venv\\Scripts\\python.exe pipeline_extractor.py
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).parent
DG = Path(r"D:\Documentos\bchat_datagen")
LOG = RAIZ / "resultados" / "ETAPA6_extraccion_pipeline.log"
PARES = DG / "storage" / "debug" / "extraction-pairs.jsonl"
BASE = RAIZ / "modelos" / "experimentos" / "nucleo_v2c_sft.pt"
VARIANTES = [("extraccion_a", ["--epocas", "8", "--lr", "1e-3"]), ("extraccion_b", ["--epocas", "16", "--lr", "6e-4"])]


def log(*a):
    linea = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] " + " ".join(str(x) for x in a)
    print(linea, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def n_pares():
    try:
        return sum(1 for l in open(PARES, encoding="utf-8") if l.strip())
    except OSError:
        return 0


def esperar_generacion():
    gl = DG / "gen_datos.log"
    ultimo, cuando = n_pares(), time.time()
    while True:
        txt = gl.read_text(encoding="utf-8", errors="replace") if gl.exists() else ""
        if "fin:" in txt.split("inicio:")[-1]:
            log("generación terminada:", n_pares(), "pares")
            return
        n = n_pares()
        if n != ultimo:
            ultimo, cuando = n, time.time()
        if time.time() - cuando > 45 * 60:
            log(f"sin pares nuevos en 45 min (hay {n}): se continúa con lo que hay")
            return
        time.sleep(120)


def descargar_gpu():
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=json.dumps({"model": "huihui_ai/mistral-small-abliterated:24b", "keep_alive": 0}).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=60).read()
        log("modelo de Ollama descargado de la GPU")
    except Exception as e:
        log("no se pudo descargar el modelo de Ollama:", e)
    time.sleep(8)


def correr(args, nombre):
    log("» " + " ".join(args))
    with open(RAIZ / "resultados" / f"ETAPA6_extraccion_{nombre}.log", "w", encoding="utf-8") as f:
        p = subprocess.run(args, cwd=RAIZ, stdout=f, stderr=subprocess.STDOUT)
    log(f"  salida {p.returncode} (log: ETAPA6_extraccion_{nombre}.log)")
    return p.returncode


def sha(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verificar_congelados():
    esperado = json.load(open(RAIZ / "resultados" / "ETAPA4_v2c_congelados.json", encoding="utf-8"))["sha256"]
    donde = [RAIZ / "modelos" / "experimentos", RAIZ / "modelos"]
    malos, vistos = [], 0
    for nombre, h in esperado.items():
        ruta = next((d / nombre for d in donde if (d / nombre).exists()), None)
        if ruta is None:
            continue
        vistos += 1
        if sha(ruta) != h:
            malos.append(nombre)
    log(f"congelados verificados: {vistos} | alterados: {malos or 'ninguno'}")
    return {"verificados": vistos, "alterados": malos}


def main():
    py = sys.executable
    esperar_generacion()
    descargar_gpu()
    sal = RAIZ / "datos" / "extractor"
    sal.mkdir(parents=True, exist_ok=True)
    shutil.copy(PARES, sal / "pares.jsonl")
    correr([py, "extractor_datos.py", str(sal / "pares.jsonl"), "--sal", str(sal), "--prop-eval", "0.15"], "datos")
    resumen = {"pares": n_pares(), "variantes": {}}
    for nombre, extra in VARIANTES:
        if correr([py, "entrenar_lora_v2.py", "--nombre", nombre, "--datos", str(sal / "train.jsonl"), "--base", str(BASE), *extra], f"entrenar_{nombre}") != 0:
            resumen["variantes"][nombre] = {"error": "entrenamiento"}
            continue
        salida = RAIZ / "resultados" / f"ETAPA6_extraccion_{nombre}.json"
        correr([py, "extractor_eval.py", str(sal / "pares.jsonl"), "--lora", str(RAIZ / "modelos" / "experimentos" / f"experto_{nombre}_v2.lora"), "--n", "100", "--prop-eval", "0.15",
                "--salida", str(salida)], f"eval_{nombre}")
        resumen["variantes"][nombre] = json.load(open(salida, encoding="utf-8")) if salida.exists() else {"error": "evaluación"}
    resumen["congelados"] = verificar_congelados()
    (RAIZ / "resultados" / "ETAPA6_extraccion_resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    log("PIPELINE TERMINADO")


if __name__ == "__main__":
    main()
