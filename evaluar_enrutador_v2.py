"""Precisión del enrutador v1 vs v2 (EnrutadorV2) sobre los conjuntos de evaluación y sobre negativos que NO deben despertar a ningún experto.

  python evaluar_enrutador_v2.py            # escribe resultados/ETAPA4_enrutador_v2.json
Cada mensaje se enruta con un enrutador nuevo (sin histéresis), igual que evaluar_experto con el adaptador forzado.
"""
import collections
import json
from pathlib import Path

import charla_v2
from enrutador import NEGATIVOS_DIFICILES, Enrutador, EnrutadorV2

RAIZ = Path(__file__).parent


def L(f):
    return [json.loads(l) for l in open(f, encoding="utf-8")]


def medir(clase):
    out = {}
    for nombre, archivo, esperado in (("codigo", "experto_eval_B2.jsonl", "codigo"), ("redaccion", "redaccion_eval.jsonl", "redaccion")):
        por = collections.defaultdict(lambda: [0, 0])
        for r in L(RAIZ / "datos" / archivo):
            por[r["tipo"]][0] += clase().paso(r["pregunta"]) == esperado
            por[r["tipo"]][1] += 1
        out[nombre] = {"total": sum(a for a, _ in por.values()) / sum(b for _, b in por.values()), "por_tipo": {t: round(a / b, 3) for t, (a, b) in por.items()}}
    # negativos: ningún experto
    neg = {"negativos_dificiles": NEGATIVOS_DIFICILES,
           "charla (339 frases reservadas)": [r["pregunta"] for r in __import__("evaluar_v2").frases_charla_unicas()],
           "hechos (ddgs real, 287 preguntas)": [r["pregunta"] for r in L(RAIZ / "datos" / "v2" / "sft" / "sft_eval_real.jsonl")]}
    out["falsos_positivos"] = {}
    for k, v in neg.items():
        fp = [p for p in v if clase().paso(p) is not None]
        out["falsos_positivos"][k] = {"n": len(v), "falsos": len(fp), "tasa": round(len(fp) / len(v), 4), "ejemplos": fp[:5]}
    return out


if __name__ == "__main__":
    res = {"v1": medir(Enrutador), "v2": medir(EnrutadorV2)}
    (RAIZ / "resultados" / "ETAPA4_enrutador_v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for v in res:
        r = res[v]
        print(f"{v}: código {r['codigo']['total']:.1%} | redacción {r['redaccion']['total']:.1%} | falsos positivos: " + " | ".join(f"{k} {d['falsos']}/{d['n']}" for k, d in r["falsos_positivos"].items()))
        print("   código por tipo:", r["codigo"]["por_tipo"])
        print("   redacción por tipo:", r["redaccion"]["por_tipo"])
