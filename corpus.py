"""Prepara el corpus en español para el preentrenamiento.

Fuentes (abiertas, sin cuenta):
  - Wikipedia en español (wikimedia/wikipedia, 20231101.es)
  - FineWeb-2 en español (HuggingFaceFW/fineweb-2, spa_Latn), solo páginas de
    dominios latinoamericanos (.cl, .mx, .ar, .co, .pe, ...) para sesgar hacia
    el español de América.

Pasos: descarga en streaming -> texto plano -> tokenizador BPE (16k) -> corpus
tokenizado en datos/corpus_es.bin (uint16) + datos/corpus_es_val.bin.

Ejemplo:  python corpus.py --wiki_mb 600 --web_mb 600
Es reanudable por etapas: si el .txt ya existe, se salta la descarga.
"""
import argparse
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
TXT = DATOS / "corpus_es.txt"
TOK = DATOS / "tokenizador.json"
BIN = DATOS / "corpus_es.bin"
BIN_VAL = DATOS / "corpus_es_val.bin"

TLD_LATAM = (".cl", ".mx", ".ar", ".co", ".pe", ".ve", ".ec", ".bo", ".py", ".uy",
             ".cr", ".pa", ".gt", ".hn", ".ni", ".sv", ".do", ".cu", ".pr")
SEPARADOR = "\n\x01\n"  # línea que solo contiene \x01 marca el fin de un documento
# Tokens reservados para la etapa de herramientas (buscar / resultado / respuesta / no sé)
ESPECIALES = ["<|fin|>", "<|relleno|>", "<|pregunta|>", "<|buscar|>", "<|resultado|>", "<|respuesta|>", "<|nose|>"]


def limpiar(t):
    t = t.replace("\r", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def es_latam(url):
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host.endswith(TLD_LATAM)


def descargar(salida, wiki_mb, web_mb):
    from datasets import load_dataset

    objetivo_wiki, objetivo_web = wiki_mb * 1_000_000, web_mb * 1_000_000
    escrito = {"wiki": 0, "web": 0}
    t0 = time.time()
    with open(salida, "w", encoding="utf-8") as f:
        if wiki_mb:
            print("Wikipedia en español...", flush=True)
            ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
            for fila in ds:
                t = limpiar(fila["text"])
                if len(t) < 300:
                    continue
                f.write(t + SEPARADOR)
                escrito["wiki"] += len(t.encode("utf-8"))
                if escrito["wiki"] >= objetivo_wiki:
                    break
                if random.random() < 0.002:
                    print(f"  wiki {escrito['wiki'] / 1e6:.0f} MB | {time.time() - t0:.0f}s", flush=True)
        if web_mb:
            print("FineWeb-2 español (dominios latinoamericanos)...", flush=True)
            ds = load_dataset("HuggingFaceFW/fineweb-2", "spa_Latn", split="train", streaming=True)
            vistos = 0
            for fila in ds:
                vistos += 1
                if not es_latam(fila.get("url", "")):
                    continue
                t = limpiar(fila["text"])
                if len(t) < 300:
                    continue
                f.write(t + SEPARADOR)
                escrito["web"] += len(t.encode("utf-8"))
                if escrito["web"] >= objetivo_web:
                    break
                if random.random() < 0.002:
                    print(f"  web {escrito['web'] / 1e6:.0f} MB (revisados {vistos:,}) | {time.time() - t0:.0f}s", flush=True)
    print(f"Texto listo: wiki {escrito['wiki'] / 1e6:.0f} MB + web {escrito['web'] / 1e6:.0f} MB -> {salida}", flush=True)


def documentos(ruta):
    with open(ruta, encoding="utf-8") as f:
        buf = []
        for linea in f:
            if linea == "\x01\n":  # fin de documento
                doc = "".join(buf).strip()
                if doc:
                    yield doc
                buf = []
            else:
                buf.append(linea)
        doc = "".join(buf).strip()
        if doc:
            yield doc


def entrenar_tokenizador(ruta_txt, vocab, muestra_mb=300):
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    entrenador = trainers.BpeTrainer(vocab_size=vocab, special_tokens=ESPECIALES,
                                     initial_alphabet=pre_tokenizers.ByteLevel.alphabet())

    def muestra():
        total = 0
        for d in documentos(ruta_txt):
            yield d
            total += len(d)
            if total > muestra_mb * 1_000_000:
                break

    print(f"Entrenando tokenizador BPE ({vocab} tokens) con {muestra_mb} MB de texto...", flush=True)
    tok.train_from_iterator(muestra(), entrenador)
    tok.save(str(TOK))
    print(f"Tokenizador guardado en {TOK}", flush=True)


def tokenizar(ruta_txt, val_fraccion=0.005):
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(TOK))
    fin = tok.token_to_id("<|fin|>")
    rng = random.Random(0)
    t0 = time.time()
    n_train = n_val = 0
    with open(BIN, "wb") as ftr, open(BIN_VAL, "wb") as fva:
        lote = []

        def volcar(lote):
            nonlocal n_train, n_val
            for enc in tok.encode_batch(lote):
                ids = np.array(enc.ids + [fin], dtype=np.uint16)
                if rng.random() < val_fraccion:
                    ids.tofile(fva)
                    n_val += len(ids)
                else:
                    ids.tofile(ftr)
                    n_train += len(ids)

        for d in documentos(ruta_txt):
            lote.append(d)
            if len(lote) == 2000:
                volcar(lote)
                lote = []
                print(f"  {n_train / 1e6:.0f} M tokens | {time.time() - t0:.0f}s", flush=True)
        if lote:
            volcar(lote)
    print(f"Tokens: entrenamiento {n_train / 1e6:.1f} M, validación {n_val / 1e6:.2f} M", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki_mb", type=int, default=600)
    ap.add_argument("--web_mb", type=int, default=600)
    ap.add_argument("--vocab", type=int, default=16000)
    ap.add_argument("--rehacer", action="store_true", help="vuelve a descargar aunque exista el texto")
    args = ap.parse_args()

    DATOS.mkdir(exist_ok=True)
    if args.rehacer or not TXT.exists():
        descargar(TXT, args.wiki_mb, args.web_mb)
    else:
        print(f"Se reutiliza {TXT} ({TXT.stat().st_size / 1e6:.0f} MB)")
    if args.rehacer or not TOK.exists():
        entrenar_tokenizador(TXT, args.vocab)
    tokenizar(TXT)


if __name__ == "__main__":
    main()
