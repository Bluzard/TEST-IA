"""Construye el léxico del corrector ortográfico (datos/lexico_es.tsv) contando las palabras del corpus en español del propio proyecto.

Un léxico sacado de un corpus de 336 M tokens trae conjugaciones, plurales y nombres propios que un diccionario chico no tiene
(fui, quiero, Freud…), y sus frecuencias permiten elegir entre candidatos. Se muestrean bloques repartidos por todo el archivo
(Wikipedia y web latinoamericana) hasta ~MB_TOTAL megabytes.

  python construir_lexico.py [--mb 400] [--min 5]
"""
import argparse
import re
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).parent
CORPUS = RAIZ / "datos" / "corpus_es.txt"
SALIDA = RAIZ / "datos" / "lexico_es.tsv"
PALABRA = re.compile(r"[a-záéíóúüñ]+")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mb", type=int, default=400)
    ap.add_argument("--min", type=int, default=5, help="frecuencia mínima para guardar la palabra")
    args = ap.parse_args()
    tam = CORPUS.stat().st_size
    bloque = 8 << 20
    n_bloques = max(1, args.mb * (1 << 20) // bloque)
    paso = max(bloque, tam // n_bloques)
    cuenta, leidos = Counter(), 0
    with open(CORPUS, "rb") as f:
        for k in range(n_bloques):
            f.seek(k * paso)
            texto = f.read(bloque).decode("utf-8", errors="ignore").lower()
            cuenta.update(PALABRA.findall(texto))
            leidos += bloque
            if k % 10 == 0:
                print(f"  {leidos >> 20} MB leídos, {len(cuenta):,} palabras distintas", flush=True)
    filas = [(w, c) for w, c in cuenta.items() if c >= args.min and 1 <= len(w) <= 25]
    filas.sort(key=lambda x: -x[1])
    SALIDA.write_text("\n".join(f"{w}\t{c}" for w, c in filas), encoding="utf-8")
    print(f"{len(filas):,} palabras (frecuencia >= {args.min}) -> {SALIDA} ({SALIDA.stat().st_size / 1e6:.1f} MB); {sum(cuenta.values()):,} tokens contados")


if __name__ == "__main__":
    main()
