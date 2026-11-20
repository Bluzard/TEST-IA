"""Mide tiempo de respuesta y memoria de los modelos.

  python medir_recursos.py
  python medir_recursos.py --preguntas 100

Mide en CPU y en la GPU disponible (MPS en Mac, CUDA en el PC).
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import torch

from evaluar import responder
from exportar_bitnet import cargar_empaquetado
from herramientas import Diccionario
from modelo import BitLinear, cargar

RAIZ = Path(__file__).parent
MODELOS = [
    ("normal", "modelos/cmp_normal_s0_v3.pt"),
    ("bitnet (archivo de entrenamiento)", "modelos/cmp_bitnet_s0_v3.pt"),
    ("bitnet empaquetado", "modelos/cmp_bitnet_s0_v3_empaquetado.pt"),
    ("bucle", "modelos/cmp_bucle_s0_v3.pt"),
]


def sincronizar(dispositivo):
    if dispositivo == "cuda":
        torch.cuda.synchronize()
    elif dispositivo == "mps":
        torch.mps.synchronize()


def memoria_gpu(dispositivo):
    if dispositivo == "cuda":
        return torch.cuda.memory_allocated()
    if dispositivo == "mps":
        return torch.mps.current_allocated_memory()
    return 0


def peso_ideal_mb(modelo):
    """Lo mínimo que necesita: 16 bits por peso, o 2 bits en las capas BitNet."""
    total = modelo.parametros()
    if not modelo.cfg.bitnet:
        return total * 2 / 1e6
    tern = sum(m.weight.numel() for m in modelo.modules() if isinstance(m, BitLinear))
    return (tern * 2 / 8 + (total - tern) * 2) / 1e6


def medir(ruta, dispositivo, preguntas, diccionario):
    antes = memoria_gpu(dispositivo)
    if ruta.endswith("_empaquetado.pt"):
        modelo, stoi, itos = cargar_empaquetado(RAIZ / ruta, dispositivo)
    else:
        modelo, stoi, itos = cargar(RAIZ / ruta, dispositivo)
    sincronizar(dispositivo)
    en_memoria = sum(t.numel() * t.element_size() for t in list(modelo.parameters()) + list(modelo.buffers()))
    gpu = memoria_gpu(dispositivo) - antes

    # Tiempo de una "pasada" (procesar el texto una vez): el costo puro del modelo
    x = torch.randint(1, len(stoi), (1, modelo.cfg.bloque), device=dispositivo)
    with torch.no_grad():
        for _ in range(5):
            modelo(x)
        sincronizar(dispositivo)
        tiempos = []
        for _ in range(50):
            t0 = time.perf_counter()
            modelo(x)
            sincronizar(dispositivo)
            tiempos.append(time.perf_counter() - t0)
    pasada = statistics.median(tiempos) * 1000

    # Tiempo de respuesta completo, una pregunta a la vez (incluye buscar en el diccionario)
    for p in preguntas[:3]:
        responder(modelo, stoi, itos, dispositivo, [p], diccionario)
    tiempos = []
    for p in preguntas:
        t0 = time.perf_counter()
        responder(modelo, stoi, itos, dispositivo, [p], diccionario)
        sincronizar(dispositivo)
        tiempos.append(time.perf_counter() - t0)
    tiempos.sort()
    respuesta = statistics.median(tiempos) * 1000
    p90 = tiempos[int(len(tiempos) * 0.9)] * 1000

    resultado = {
        "params": modelo.parametros(),
        "ideal_mb": peso_ideal_mb(modelo),
        "en_memoria_mb": en_memoria / 1e6,
        "gpu_mb": gpu / 1e6,
        "pasada_ms": pasada,
        "respuesta_ms": respuesta,
        "p90_ms": p90,
    }
    del modelo
    if dispositivo == "mps":
        torch.mps.empty_cache()
    elif dispositivo == "cuda":
        torch.cuda.empty_cache()
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preguntas", type=int, default=40)
    args = ap.parse_args()

    with open(RAIZ / "datos" / "evaluacion.jsonl", encoding="utf-8") as f:
        casos = [json.loads(l) for l in f]
    # Mezcla de preguntas fáciles (sin buscar) y difíciles (con búsqueda)
    paso = max(1, len(casos) // args.preguntas)
    preguntas = [c["termino"] for c in casos[::paso]][: args.preguntas]
    diccionario = Diccionario()

    dispositivos = ["cpu"]
    if torch.cuda.is_available():
        dispositivos.append("cuda")
    elif torch.backends.mps.is_available():
        dispositivos.append("mps")

    filas = []
    for dispositivo in dispositivos:
        for nombre, ruta in MODELOS:
            if not (RAIZ / ruta).exists():
                print(f"(falta {ruta}, se omite)")
                continue
            print(f"Midiendo {nombre} en {dispositivo}...", flush=True)
            filas.append((dispositivo, nombre, medir(ruta, dispositivo, preguntas, diccionario)))

    lineas = [
        f"# Recursos de los modelos ({len(preguntas)} preguntas, una a la vez)",
        "",
        "## Memoria",
        "",
        "| Modelo | Parámetros | Mínimo necesario | Ocupa hoy al cargarlo |",
        "|---|---|---|---|",
    ]
    vistos = set()
    for dispositivo, nombre, r in filas:
        if nombre in vistos:
            continue
        vistos.add(nombre)
        lineas.append(f"| {nombre} | {r['params']:,} | {r['ideal_mb']:.2f} MB | {r['en_memoria_mb']:.2f} MB |")
    lineas += [
        "",
        "## Tiempo",
        "",
        "| Dispositivo | Modelo | Una pasada | Respuesta completa (mediana) | Respuesta lenta (p90) |",
        "|---|---|---|---|---|",
    ]
    for dispositivo, nombre, r in filas:
        lineas.append(f"| {dispositivo} | {nombre} | {r['pasada_ms']:.2f} ms | {r['respuesta_ms']:.0f} ms | {r['p90_ms']:.0f} ms |")
    texto = "\n".join(lineas)
    (RAIZ / "resultados").mkdir(exist_ok=True)
    (RAIZ / "resultados" / "recursos.md").write_text(texto + "\n", encoding="utf-8")
    print("\n" + texto)


if __name__ == "__main__":
    main()
