"""Evaluación del experto de prompts de imagen por el motor C++ (mismo camino de producción: B: <modelo> -> ficha -> R: prompt).

  python evaluar_imagen.py --lora modelos/experimentos/experto_imagen_a_v2.lora [--n 400] [--sin-lora]

Métricas (sobre filas RESERVADAS de datos/imagen/eval.jsonl, estratificadas por tipo):
  enruta      emite «B:» con el modelo correcto (o, en img_sin_modelo, NO busca y pregunta el modelo)
  formato     tras la capa determinista (imagen_formato.formatear) respeta la regla del modelo; el núcleo escribe solo el cuerpo, así que esto es 100 % por construcción y se mantiene como prueba de regresión
  limpio      el núcleo NO emite él mismo líneas de prompt negativo ni prefijos de calidad (eso es de la capa determinista)
  ruido       fracción de palabras de la salida (>= 4 letras) que no existen en el vocabulario de los datos de entrenamiento ni en la entrada: mide palabras corruptas o inventadas (<= 8 % para dar por buena una salida)
  ingles      la salida es inglés (>= 97 % ASCII y sin palabras españolas comunes)
  sin_repet   sin degeneración: ninguna 4-grama se repite más de 3 veces
  f1          F1 de unigramas contra la referencia (orientativo: para prompts reales hay muchas salidas buenas)
  recall      de las palabras de la ENTRADA que también están en la referencia, cuántas conserva la salida (fidelidad a lo que pidió; independiente del idioma de la entrada)
  ok          cumple a la vez enruta + formato + ingles + sin_repet + ruido bajo
"""
import argparse
import collections
import json
import random
import re
import time
from pathlib import Path

from imagen_fichas import FICHAS_IMAGEN, buscar_ficha_imagen, resolver_modelo
from imagen_formato import formatear
from inferir import _texto, generar_lote
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2

RAIZ = Path(__file__).parent
ES = re.compile(r"\b(el|la|los|las|una|un|con|del|para|que|bosque|gato|perro|noche|luz)\b", re.I)
PARADAS = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "for", "to", "is", "are", "prompt", "make", "me", "write", "i", "need", "generate", "pls", "nice", "good", "quality"}


def tokens(t):
    return re.findall(r"[a-z0-9']+", t.lower())


def f1(a, b):
    ca, cb = collections.Counter(tokens(a)), collections.Counter(tokens(b))
    c = sum((ca & cb).values())
    if not c:
        return 0.0
    p, r = c / sum(ca.values()), c / sum(cb.values())
    return 2 * p * r / (p + r)


def repite(t):
    g = tokens(t)
    cuatro = collections.Counter(tuple(g[i:i + 4]) for i in range(len(g) - 3))
    return bool(cuatro) and max(cuatro.values()) > 3


def formato_ok(k, salida):
    tiene_neg = "\nNegative prompt:" in salida
    cuerpo = salida.split("\nNegative prompt:")[0]
    if k in ("flux", "z-image-turbo"):
        return not tiene_neg
    if k in ("z-image-base", "qwen-image"):
        return tiene_neg
    if k == "pony":
        return tiene_neg and cuerpo.startswith("score_9, score_8_up, score_7_up")
    if k == "illustrious":
        return tiene_neg and cuerpo.startswith("masterpiece, best quality")
    return tiene_neg and cuerpo.startswith("masterpiece, best quality")  # sdxl, sd15


def es_ingles(t):
    return sum(ord(c) < 128 for c in t) / max(1, len(t)) >= 0.97 and not ES.search(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lora", default=None)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--bin", default=str(RAIZ / "modelos" / "nucleo_v2c_sft.bin"))
    ap.add_argument("--salida", default=None)
    ap.add_argument("--pen", type=float, default=1.0, help="penalización por repetición del cuerpo del prompt")
    a = ap.parse_args()
    fmt, motor = FormatoV2(), MotorCpp(a.bin)
    vocab = set()
    for l in open(RAIZ / "datos" / "imagen" / "train.jsonl", encoding="utf-8"):
        vocab.update(w for w in tokens(json.loads(l)["respuesta"]) if len(w) >= 4)
    if a.lora:
        motor.cargar_lora(a.lora)
    filas = [json.loads(l) for l in open(RAIZ / "datos" / "imagen" / "eval.jsonl", encoding="utf-8")]
    rng = random.Random(1)
    por = collections.defaultdict(list)
    for r in filas:
        por[r["tipo"].replace("_texto", "")].append(r)
    cuota = max(3, a.n // len(por))
    muestra = [r for t in sorted(por) for r in rng.sample(por[t], min(cuota, len(por[t])))]
    res = collections.defaultdict(lambda: collections.Counter())
    ejemplos = []
    t0 = time.time()
    for r in muestra:
        tipo = r["tipo"]
        p = fmt.ids_prompt(r["pregunta"])
        nuevo, parada = generar_lote(motor, fmt, [p], "cpu", 1.0, max_nuevos=60)[0]
        t = _texto(fmt, nuevo)
        c = res[tipo]
        c["n"] += 1
        if tipo == "img_sin_modelo":
            ok_ruta = not t.startswith("B:") and "modelo" in t.lower()
            c["enruta"] += ok_ruta
            c["ok"] += ok_ruta
            if not ok_ruta and len(ejemplos) < 6:
                ejemplos.append((tipo, r["pregunta"][:80], t[:100]))
            continue
        k = r["consulta"]
        ok_ruta = parada == fmt.herramienta and t.startswith("B:") and resolver_modelo(t.removeprefix("B:")) == k
        c["enruta"] += ok_ruta
        ficha = buscar_ficha_imagen(t.removeprefix("B:").strip()) if ok_ruta else None
        if not ficha:
            ficha = r["resultados"]  # si no enrutó bien, se mide igual la calidad del prompt con la ficha correcta
        ids = p + nuevo + fmt.ids_tras_herramienta(ficha, r.get("tope")) if parada == fmt.herramienta else p + fmt.texto(f" B: {k}") + [fmt.herramienta] + fmt.ids_tras_herramienta(ficha, r.get("tope"))
        n2, _ = generar_lote(motor, fmt, [ids], "cpu", a.pen, max_nuevos=260)[0]
        s = _texto(fmt, n2).removeprefix("R:").strip()
        completo = formatear(k, s, con_texto='"' in s)
        f_ok, i_ok, r_ok = formato_ok(k, completo), es_ingles(s), not repite(s)
        propias = set(tokens(r["pregunta"]))
        pal = [w for w in tokens(s) if len(w) >= 4 and w.isalpha()]
        ruido = sum(w not in vocab and w not in propias for w in pal) / max(1, len(pal))
        r_ok = r_ok and ruido <= 0.08
        c["ruido"] += ruido
        c["limpio"] += "Negative prompt" not in s and "masterpiece" not in s.lower()[:30] and "score_9" not in s
        c["formato"] += f_ok
        c["ingles"] += i_ok
        c["sin_repet"] += r_ok
        c["f1"] += f1(completo, r.get("completo", r["respuesta"]))
        ref = set(tokens(r["respuesta"]))
        ent = [w for w in tokens(r["pregunta"]) if w not in PARADAS and len(w) > 3 and w in ref]
        if ent:
            c["recall"] += sum(w in set(tokens(s)) for w in ent) / len(ent)
            c["recall_n"] += 1
        c["ok"] += ok_ruta and f_ok and i_ok and r_ok
        if not (ok_ruta and f_ok and i_ok and r_ok) and len(ejemplos) < 8:
            ejemplos.append((tipo, r["pregunta"][:80], f"B?={t[:40]!r} | {s[:110]!r}"))
    print(f"{len(muestra)} filas en {time.time() - t0:.0f} s | lora: {a.lora or 'ninguno (núcleo solo)'}")
    tot = collections.Counter()
    print(f"{'tipo':22s} {'n':>4s} {'enruta':>7s} {'limpio':>7s} {'ingles':>7s} {'sin_rep':>8s} {'ruido':>6s} {'f1':>5s} {'recall':>7s} {'ok':>5s}")
    for tipo in sorted(res):
        c = res[tipo]
        n = c["n"]
        rn = max(1, c["recall_n"])
        print(f"{tipo:22s} {n:4d} {c['enruta'] / n:7.0%} {c['limpio'] / n:7.0%} {c['ingles'] / n:7.0%} {c['sin_repet'] / n:8.0%} {c['ruido'] / n:6.1%} {c['f1'] / n:5.2f} {c['recall'] / rn:7.0%} {c['ok'] / n:5.0%}")
        tot.update(c)
    n = tot["n"]
    print(f"{'TOTAL':22s} {n:4d} {tot['enruta'] / n:7.0%} {tot['limpio'] / n:7.0%} {tot['ingles'] / n:7.0%} {tot['sin_repet'] / n:8.0%} {tot['ruido'] / n:6.1%} {tot['f1'] / n:5.2f} {tot['recall'] / max(1, tot['recall_n']):7.0%} {tot['ok'] / n:5.0%}")
    for e in ejemplos:
        print("   fallo:", e)
    if a.salida:
        Path(a.salida).write_text(json.dumps({"lora": a.lora, "n": n, "total": {k: v / n for k, v in tot.items() if k != "recall_n"}, "tipos": {t: dict(c) for t, c in res.items()}}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
