"""Agrega palabras nuevas al diccionario SIN volver a entrenar el modelo.

Prueba la idea central: el conocimiento vive fuera del modelo, así que
el diccionario puede crecer y el modelo sigue pesando lo mismo.

  python ampliar_diccionario.py --cantidad 20000
  python ampliar_diccionario.py --cantidad 20000 --evaluar modelos/modelo_B.pt

Nota: si vuelves a correr datos.py, el diccionario se regenera y se pierden
estas entradas (vuelve a correr este script).
"""
import argparse
import json
import random
import sqlite3
from collections import Counter

from datos import CARPETA, CONOCIDAS, MODIFICADORES, EXTRANOS, definir, inventar_palabras
from herramientas import RUTA_DICCIONARIO, Diccionario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cantidad", type=int, default=20000)
    ap.add_argument("--semilla", type=int, default=123)
    ap.add_argument("--evaluar", default=None, help="ruta de un modelo para medirlo con las palabras nuevas")
    ap.add_argument("--muestra", type=int, default=1000, help="cuántas palabras nuevas evaluar")
    args = ap.parse_args()
    rng = random.Random(args.semilla)

    con = sqlite3.connect(RUTA_DICCIONARIO)
    existentes = {t for (t,) in con.execute("SELECT termino FROM entradas")}
    prohibidas = existentes | {m for ms in MODIFICADORES.values() for m in ms} | set(EXTRANOS)
    nuevas = inventar_palabras(rng, args.cantidad, prohibidas)
    categorias = list(CONOCIDAS)
    filas = []
    for w in nuevas:
        c = rng.choice(categorias)
        filas.append((w, c, definir(rng, w, c)))
    con.executemany("INSERT INTO entradas VALUES (?, ?)", [(w, d) for w, _, d in filas])
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0]
    con.close()
    print(f"Agregadas {len(filas):,} palabras. Diccionario: {len(existentes):,} -> {total:,} entradas "
          f"({RUTA_DICCIONARIO.stat().st_size / 1e6:.1f} MB)")

    ruta_eval = CARPETA / "evaluacion_ampliada.jsonl"
    with open(ruta_eval, "w", encoding="utf-8") as f:
        for w, c, _ in filas:
            f.write(json.dumps({"termino": w, "cat": c}, ensure_ascii=False) + "\n")

    if args.evaluar:
        from evaluar import responder
        from modelo import cargar, elegir_dispositivo
        dispositivo = elegir_dispositivo()
        modelo, stoi, itos = cargar(args.evaluar, dispositivo)
        muestra = rng.sample(filas, min(args.muestra, len(filas)))
        res = responder(modelo, stoi, itos, dispositivo, [w for w, _, _ in muestra], Diccionario())
        aciertos = sum(r["respuesta"] == c for (_, c, _), r in zip(muestra, res))
        busco = sum(r["busco"] for r in res)
        print(f"Modelo {args.evaluar} (sin reentrenar) con {len(muestra)} palabras recién agregadas: "
              f"acierto {100 * aciertos / len(muestra):.1f}% | buscó {100 * busco / len(muestra):.1f}%")
        errores = Counter(r["respuesta"] for (_, c, _), r in zip(muestra, res) if r["respuesta"] != c)
        if errores:
            print(f"Respuestas erradas más comunes: {errores.most_common(5)}")


if __name__ == "__main__":
    main()
