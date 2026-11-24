"""Evalúa el modelo base con los mismos casos reservados de ddgs real que se usaron con el núcleo propio (datos/sft_eval_real.jsonl).

  .venv\\Scripts\\python.exe evaluar_3b.py [--n 80] [--modelo qwen2.5:3b]

Cada caso trae la pregunta y los resultados de búsqueda ya obtenidos; el modelo responde solo con ellos.
  buscar_ok   -> acierto si la respuesta menciona el dato esperado («gold») y no se abstiene
  irrelevante / vacio -> acierto si se abstiene
Es una medida MÁS PERMISIVA que la «respuesta exacta» del núcleo propio (83-94 %): no son cifras directamente comparables.
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path

import llm
from relevancia import ORDEN_ABSTENCION, filtrar

RAIZ = Path(__file__).parent
SISTEMA = ("Eres TEST-IA. Responde en español, en una o dos frases, SOLO con lo que digan los resultados de búsqueda, copiando el dato tal como aparece. "
           "Si los resultados no responden la pregunta, di exactamente: No tengo información suficiente para responder eso.")
ABSTENCION = re.compile(r"no tengo informacion|no encuentro|no se menciona|no hay informacion|no pude|no puedo|no (?:se )?(?:dice|indica|proporcion)|no contienen|no responden|lo siento")


def _n(t):
    return unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="casos por tipo (0 = todos)")
    ap.add_argument("--modelo", default=None)
    a = ap.parse_args()
    casos = [json.loads(l) for l in open(RAIZ / "datos" / "sft_eval_real.jsonl", encoding="utf-8")]
    por_tipo = {}
    for c in casos:
        por_tipo.setdefault(c["tipo"], []).append(c)
    total = {}
    for tipo, lista in por_tipo.items():
        lista = lista[:a.n] if a.n else lista
        ok = 0
        for c in lista:
            msg = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": f"{c['pregunta']}\n\nResultados de búsqueda:\n{filtrar(c['consulta'], c.get('resultados') or '')}"}]
            r = _n(llm.chat(msg, modelo=a.modelo, temperatura=0.0, max_tokens=200).get("content") or "")
            abst = bool(ABSTENCION.search(r))
            ok += (not abst and _n(c["gold"]) in r) if tipo == "buscar_ok" else abst
        total[tipo] = ok / len(lista)
        print(f"{tipo:12s} {ok}/{len(lista)} = {ok / len(lista):.1%}", flush=True)
    json.dump(total, open(RAIZ / "resultados" / "ETAPA7_eval_3b.json", "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
