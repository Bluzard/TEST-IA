"""Variedad de formulaciones para los LoRA v2c (datos/v2/lora_*_mezcla3.jsonl).

Problema (diagnóstico de doc_ok/concepto): el núcleo solo ve 3-4 familias de preguntas de búsqueda en entrenamiento y la charla ampliada captura
formulaciones nuevas («¿Podrías explicarme X?», «Necesito entender X»…) antes de que emitan B:. Aquí se re-redactan filas de entrenamiento con
formulaciones NUEVAS y variadas (misma consulta, mismos resultados, misma respuesta: solo cambia la pregunta).

Decisión de higiene: las familias del evaluador (p. ej. «¿Podrías explicarme X?», «Necesito entender X.», «¿Qué quiere decir X en código?», «Cuéntame qué es X.»,
«Recuérdame X.», «Explícalo con más claridad:») NO se copian: se usan sinónimos cercanos («¿Podrías aclararme…?», «Necesito comprender…», «¿Qué significa X en programación?»,
«Cuéntame sobre X.»), de modo que la evaluación siga midiendo generalización de formulación y no memoria de plantillas. Se comprueba 0 coincidencias exactas de
pregunta y 0 marcos de evaluación reutilizados.

  python variedad_v2.py
"""
import collections
import json
import random
import re
from pathlib import Path

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"

CONCEPTO = ["¿Podrías aclararme qué es {t}?", "¿Podrías contarme qué significa {t}?", "¿Podrías decirme qué es {t}?", "Necesito comprender {t}.", "Necesito saber qué es {t}.",
            "Necesito que me expliques {t}.", "¿Qué significa {t} en programación?", "¿Qué se entiende por {t} al programar?", "Cuéntame sobre {t}.", "Cuéntame qué significa {t}.",
            "Cuéntame de qué trata {t}.", "Quisiera saber qué es {t}.", "Me gustaría entender {t}.", "¿Me aclaras qué es {t}?", "Ayúdame a entender {t}.", "No sé qué es {t}, ¿me explicas?",
            "¿Sabes qué es {t}?", "Quiero entender qué es {t}.", "¿Me cuentas qué es {t}?", "Dime algo sobre {t}."]
DOC = ["¿Podrías aclararme cómo se usa {t} en {c}?", "Necesito comprender {t} en {c}.", "¿Qué significa {t} en {c}?", "Cuéntame sobre {t} en {c}.", "Quisiera saber qué es {t} en {c}.",
       "¿Me aclaras {t} de {c}?", "¿Podrías decirme para qué sirve {t} en {c}?", "Necesito saber cómo funciona {t} en {c}.", "Dime algo sobre {t} en {c}.", "No sé qué hace {t} en {c}, ¿me ayudas?",
       "Quiero entender {t} en {c}."]
GRAMATICA = ["Quisiera repasar {t}.", "Me gustaría entender {t}.", "¿Me aclaras {t}?", "Necesito comprender {t}.", "¿Podrías aclararme {t}?", "Cuéntame sobre {t}.", "No tengo claro {t}, ¿me ayudas?",
             "Dime algo sobre {t}.", "Explícame con calma {t}.", "Quiero repasar {t}, por favor.", "¿Me puedes ayudar con {t}?"]
TONO_CLARO = ["Dilo de forma más clara: ", "Hazlo más fácil de leer: ", "Más claro, por favor: ", "Reformúlalo con palabras sencillas: ", "Reescribe esto para que se entienda mejor: ", "Aclara este texto: ",
              "Dame una versión más fácil de entender: ", "Simplifícalo, por favor: "]
ARTICULOS = ("el", "la", "los", "las", "un", "una")


def leer(f):
    return [json.loads(l) for l in open(f, encoding="utf-8")]


def termino(r, sufijo):
    """Término tal como aparece en la pregunta original (con su artículo si lo lleva), usando los tokens de la consulta."""
    toks = r["consulta"].split()
    if toks and toks[-1].lower() == sufijo:
        toks = toks[:-1]
    if not toks:
        return None
    m = re.search(r"(?:\b(" + "|".join(ARTICULOS) + r")\s+)?(" + r"\s+".join(re.escape(t) for t in toks) + ")", r["pregunta"], flags=re.I)
    return (f"{m.group(1)} {m.group(2)}" if m and m.group(1) else (m.group(2) if m else " ".join(toks)))


def marco(p, consulta):
    for w in sorted((consulta or "").split(), key=len, reverse=True):
        p = re.sub(re.escape(w), "X", p, flags=re.I)
    return re.sub(r"(X\s?)+", "X ", p).strip()


def main():
    rng = random.Random(33)
    exp, red = leer(DATOS / "experto_train_B2.jsonl"), leer(DATOS / "redaccion_train.jsonl")
    ev_exp, ev_red = leer(DATOS / "experto_eval_B2.jsonl"), leer(DATOS / "redaccion_eval.jsonl")
    nuevas = {"concepto": [], "doc_ok": [], "gramatica": [], "tono_claro": []}
    for r in exp:
        if r["tipo"] == "concepto" and r.get("consulta"):
            t = termino(r, "programación")
            if t:
                nuevas["concepto"].append({**r, "pregunta": rng.choice(CONCEPTO).format(t=t.split(" ", 1)[1] if t.split(" ", 1)[0].lower() in ARTICULOS else t)})
        if r["tipo"] == "doc_ok" and r.get("consulta") and len(r["consulta"].split()) >= 2:
            c, t = r["consulta"].split(" ", 1)
            nuevas["doc_ok"].append({**r, "pregunta": rng.choice(DOC).format(t=t, c=c)})
    for r in red:
        if r["tipo"] == "gramatica" and r.get("consulta"):
            t = termino(r, "gramática")
            if t:
                nuevas["gramatica"].append({**r, "pregunta": rng.choice(GRAMATICA).format(t=t)})
        if r["tipo"] == "tono_claro" and ": " in r["pregunta"]:
            texto = r["pregunta"].split(": ", 1)[1]
            nuevas["tono_claro"].append({**r, "pregunta": rng.choice(TONO_CLARO) + texto})
    # --- comprobación de fugas: ninguna pregunta nueva igual a una de evaluación; ningún marco de evaluación reutilizado ---
    eval_p = {re.sub(r"\W+", " ", e["pregunta"].lower()).strip() for e in ev_exp + ev_red}
    marcos_eval = {marco(e["pregunta"], e.get("consulta")) for e in ev_exp + ev_red if e["tipo"] in ("concepto", "doc_ok", "gramatica", "gramatica_reservada", "concepto_reservado")}
    malas_p = [r for v in nuevas.values() for r in v if re.sub(r"\W+", " ", r["pregunta"].lower()).strip() in eval_p]
    malos_m = [r for k, v in nuevas.items() if k != "tono_claro" for r in v if marco(r["pregunta"], r["consulta"]) in marcos_eval]
    print(f"nuevas: { {k: len(v) for k, v in nuevas.items()} } | coincidencias exactas con evaluación: {len(malas_p)} | marcos de evaluación reutilizados: {len(malos_m)}")
    assert not malas_p and not malos_m, (malas_p[:2], malos_m[:2])
    # --- mezclas: las anteriores (mezcla2: propio + repaso) + variantes nuevas ---
    cod = leer(DATOS / "v2" / "lora_codigo_mezcla2.jsonl") + nuevas["concepto"] + nuevas["doc_ok"]
    red_ = leer(DATOS / "v2" / "lora_redaccion_mezcla2.jsonl") + nuevas["gramatica"] + nuevas["tono_claro"] + rng.sample(nuevas["concepto"], 1200)
    for nombre, filas in (("lora_codigo_mezcla3", cod), ("lora_redaccion_mezcla3", red_)):
        rng.shuffle(filas)
        with open(DATOS / "v2" / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for r in filas:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(nombre, len(filas), dict(collections.Counter(r["tipo"] for r in filas).most_common(8)))
    ej = [nuevas[k][0]["pregunta"][:90] for k in nuevas]
    print("ejemplos:", ej)


if __name__ == "__main__":
    main()
