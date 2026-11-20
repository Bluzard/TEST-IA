"""Compara las variantes con palabras y frases que nunca vieron al entrenar.

Ejemplo:  python evaluar.py            (evalúa modelos/modelo_A.pt y modelo_B.pt)
          python evaluar.py --modelos modelos/modelo_B.pt
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from herramientas import Diccionario
from modelo import cargar, elegir_dispositivo, generar_lineas

RAIZ = Path(__file__).parent


def responder(modelo, stoi, itos, dispositivo, terminos, diccionario):
    """Ciclo agente: el modelo responde o pide buscar; el sistema le entrega la definición."""
    textos = [f"P: ¿qué es {t}?\n" for t in terminos]
    trazas = [[] for _ in terminos]
    respuestas = [None] * len(terminos)
    busco = [False] * len(terminos)
    for _ in range(2):  # como máximo una búsqueda y luego la respuesta
        pendientes = [i for i, r in enumerate(respuestas) if r is None]
        if not pendientes:
            break
        lineas = generar_lineas(modelo, [textos[i] for i in pendientes], stoi, itos, dispositivo)
        for i, linea in zip(pendientes, lineas):
            trazas[i].append(linea)
            if linea.startswith("B: ") and not busco[i]:
                busco[i] = True
                definicion = diccionario.buscar(linea[3:]) or "sin resultados."
                trazas[i].append(f"D: {definicion}")
                textos[i] += f"{linea}\nD: {definicion}\n"
            else:
                respuestas[i] = linea[3:].strip() if linea.startswith("R: ") else f"(inválida: {linea!r})"
    return [
        {"respuesta": r or "(sin respuesta)", "busco": b, "traza": tr}
        for r, b, tr in zip(respuestas, busco, trazas)
    ]


GRUPOS = ["conocidas", "inventadas_nuevas", "inventadas_mezcladas", "compatibles_nuevas", "no_calzan_nuevas", "inexistentes"]


def cargar_casos():
    with open(RAIZ / "datos" / "evaluacion.jsonl", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def medir(ruta, casos, diccionario, dispositivo):
    """Devuelve {grupo: {"casos", "acierto", "busco"}} (porcentajes), la traza de banco de arena y el modelo."""
    modelo, stoi, itos = cargar(ruta, dispositivo)
    res = responder(modelo, stoi, itos, dispositivo, [c["termino"] for c in casos], diccionario)
    stats = defaultdict(lambda: [0, 0, 0])  # total, aciertos, buscó
    banco = None
    for c, r in zip(casos, res):
        s = stats[c["grupo"]]
        s[0] += 1
        s[1] += r["respuesta"] == c["cat"]
        s[2] += r["busco"]
        if c["termino"] == "banco de arena":
            banco = (r, c["cat"])
    tabla = {g: {"casos": t, "acierto": 100 * a / t, "busco": 100 * b / t} for g, (t, a, b) in stats.items()}
    return tabla, banco, modelo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", nargs="+", default=[str(RAIZ / "modelos" / "modelo_A.pt"), str(RAIZ / "modelos" / "modelo_B.pt")])
    args = ap.parse_args()

    dispositivo = elegir_dispositivo()
    casos = cargar_casos()
    diccionario = Diccionario()

    for ruta in args.modelos:
        if not Path(ruta).exists():
            print(f"(no existe {ruta}, se omite)")
            continue
        tabla, banco, modelo = medir(ruta, casos, diccionario, dispositivo)
        print(f"\n=== {Path(ruta).name} ({modelo.parametros():,} parámetros) ===")
        print(f"{'grupo':22s} {'casos':>6s} {'acierto':>9s} {'buscó':>8s}")
        for g in GRUPOS:
            if g in tabla:
                t = tabla[g]
                print(f"{g:22s} {t['casos']:6d} {t['acierto']:8.1f}% {t['busco']:7.1f}%")
        if banco:
            r, esperado = banco
            print("\nTraza de «banco de arena»:")
            print("  P: ¿qué es banco de arena?")
            for linea in r["traza"]:
                print(f"  {linea}")
            print(f"  -> esperado: {esperado} | {'correcto' if r['respuesta'] == esperado else 'incorrecto'}")


if __name__ == "__main__":
    main()
