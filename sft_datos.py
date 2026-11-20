"""Genera el dataset de ajuste fino (SFT): conversar, buscar y abstenerse.

Hechos reales: artículos de Wikipedia en español (título, fragmento de ~200 caracteres y su
primera oración como respuesta correcta). Los resultados que "devuelve la herramienta" mezclan
el artículo correcto con otros de distractores, igual que un buscador real.

Tipos de ejemplo:
  buscar_ok     pregunta factual -> B: consulta -> resultados con la respuesta -> R: oración correcta
  irrelevante   los resultados no tratan del tema (como "pludos" -> Plutón) -> R: no tengo información
  vacio         "Sin resultados." -> R: no tengo información
  directo       saludos, identidad y tareas de lenguaje: R: directo, sin buscar

La evaluación usa artículos que NO aparecen en el entrenamiento (partición por hash del título).

Uso:  python sft_datos.py [--articulos 60000] [--ejemplos 48000]
"""
import argparse
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

from herramientas import SIN_RESULTADOS, _limpio, formatear_resultados, preparar_resultados
from protocolo import SIN_INFO

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
POOL = DATOS / "sft_pool.jsonl"

PREGUNTAS = ["¿Qué es {t}?", "¿Qué sabes de {t}?", "Háblame de {t}.", "Cuéntame sobre {t}.",
             "Dime algo sobre {t}.", "¿Quién o qué es {t}?", "Explícame qué es {t}.", "¿Qué me puedes decir de {t}?"]

SALUDOS = [("hola", "¡Hola! ¿En qué te puedo ayudar?"), ("buenas", "¡Buenas! ¿En qué te puedo ayudar?"),
           ("buenos días", "¡Buenos días! ¿En qué te puedo ayudar?"), ("buenas tardes", "¡Buenas tardes! ¿En qué te puedo ayudar?"),
           ("buenas noches", "¡Buenas noches! ¿En qué te puedo ayudar?"), ("hola, ¿cómo estás?", "¡Hola! Estoy bien, gracias. ¿En qué te puedo ayudar?"),
           ("¿cómo estás?", "Estoy bien, gracias por preguntar. ¿Y tú?"), ("¿cómo andas?", "Todo bien, gracias. ¿En qué te puedo ayudar?"),
           ("gracias", "¡De nada! Aquí estoy si necesitas algo más."), ("muchas gracias", "¡De nada! Aquí estoy si necesitas algo más."),
           ("chao", "¡Chao! Que te vaya bien."), ("adiós", "¡Adiós! Que te vaya bien."), ("hasta luego", "¡Hasta luego!"),
           ("¿quién eres?", "Soy un modelo de lenguaje pequeño en español. Cuando no sé algo, lo busco."),
           ("¿qué eres?", "Soy un modelo de lenguaje pequeño en español. Cuando no sé algo, lo busco."),
           ("¿qué puedes hacer?", "Puedo conversar, hacer tareas simples con texto y buscar información cuando no la sé."),
           ("¿cómo te llamas?", "No tengo nombre. Soy un modelo de lenguaje pequeño en español."),
           ("¿sabes todo?", "No. Sé poco por mí mismo, por eso busco los datos que me faltan.")]

SILABAS = ["pla", "dos", "zor", "pel", "nor", "nu", "lon", "tre", "li", "no", "kra", "mi", "vo", "fa", "ru", "san", "gue", "bri", "tal", "quen", "ba", "zu", "che", "pro", "mon"]


def inventar(rng):
    return "".join(rng.choice(SILABAS) for _ in range(rng.randint(2, 4)))


def primera_oracion(parrafo):
    m = re.match(r"(.+?[a-záéíóúüñ0-9\)\]»\"]\.)(\s+[A-ZÁÉÍÓÚÑ¿¡]|$)", parrafo)
    return m.group(1).strip() if m else None


def construir_pool(n_max):
    from datasets import load_dataset

    print("Leyendo Wikipedia (streaming)...", flush=True)
    ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
    n = 0
    with open(POOL, "w", encoding="utf-8") as f:
        for fila in ds:
            titulo = re.sub(r"\s*\(.*?\)", "", fila["title"]).strip()
            if ":" in titulo or not 3 <= len(titulo) <= 40 or titulo.lower().startswith(("anexo", "lista")):
                continue
            parrafo = re.sub(r"\s+", " ", fila["text"].split("\n")[0]).strip()
            if len(parrafo) < 80:
                continue
            frase = primera_oracion(parrafo)
            if not frase or not 40 <= len(frase) <= 190:
                continue
            fragmento = _limpio(parrafo, 200)
            if frase not in fragmento:
                continue
            f.write(json.dumps({"titulo": titulo, "fragmento": fragmento, "frase": frase}, ensure_ascii=False) + "\n")
            n += 1
            if n % 10000 == 0:
                print(f"  {n:,} artículos", flush=True)
            if n >= n_max:
                break
    print(f"Pool: {n:,} artículos -> {POOL}", flush=True)


def es_eval(titulo):
    return int(hashlib.md5(titulo.encode()).hexdigest(), 16) % 20 == 0  # 5 %


def resultado_de(a, rng):
    t = a["titulo"] + (" - Wikipedia" if rng.random() < 0.5 else "")
    return {"title": t, "body": a["fragmento"]}


def formatear(items):
    return "\n".join(f"{i + 1}. {r['title']}: {r['body']}" for i, r in enumerate(items))


def directo(rng, pool):
    """Solo conversación. Las tareas mecánicas (mayúsculas, contar, ordenar) las resuelve la capa 1 en Python."""
    p, r = rng.choice(SALUDOS)
    return {"tipo": "directo", "pregunta": p, "respuesta": r}


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def ejemplos_reales(ruta, rng):
    """Convierte resultados crudos de ddgs en ejemplos. Misma limpieza que en producción (preparar_resultados).

    - la primera oración del artículo aparece en un resultado  -> responder con ella
    - ningún resultado menciona el tema                        -> abstenerse
    - el tema aparece pero no se puede verificar la respuesta  -> se descarta (ambiguo)
    """
    salida = []
    for l in open(ruta, encoding="utf-8"):
        d = json.loads(l)
        lista = preparar_resultados(d["crudos"])[:3]
        for x in lista:
            x["body"] = _limpio(x["body"], 200)
        q = _norm(d["consulta"])
        pregunta = rng.choice(PREGUNTAS).format(t=d["consulta"])
        base = {"pregunta": pregunta, "consulta": d["consulta"], "gold": d["gold"], "real": True}
        if not lista:
            salida.append({**base, "tipo": "vacio", "resultados": SIN_RESULTADOS, "respuesta": SIN_INFO})
            continue
        texto = formatear_resultados(lista)  # exactamente lo que verá el modelo en producción
        if d["frase"] and any(d["frase"] in x["body"] for x in lista):
            salida.append({**base, "tipo": "buscar_ok", "resultados": texto, "respuesta": d["frase"]})
        elif not any(q in _norm(x["title"] + " " + x["body"]) for x in lista):
            salida.append({**base, "tipo": "irrelevante", "resultados": texto, "respuesta": SIN_INFO})
    return salida


def ejemplo(rng, pool, a, tipo):
    """a: artículo objetivo (de la partición correcta)."""
    def distractores(n):
        return [resultado_de(rng.choice(pool), rng) for _ in range(n)]

    if tipo == "buscar_ok":
        items = distractores(2)
        items.insert(rng.randint(0, 2), resultado_de(a, rng))
        return {"tipo": tipo, "pregunta": rng.choice(PREGUNTAS).format(t=a["titulo"]), "consulta": a["titulo"],
                "resultados": formatear(items), "respuesta": a["frase"], "gold": a["titulo"]}
    nombre = a["titulo"] if rng.random() < 0.5 else inventar(rng)
    consulta = nombre
    pregunta = rng.choice(PREGUNTAS).format(t=nombre)
    if tipo == "irrelevante":
        # resultados de otros temas; se evita que alguno tenga el mismo título
        items = [x for x in distractores(4) if x["title"].split(" - ")[0] != nombre][:rng.randint(1, 3)]
        res = formatear(items)
    else:
        res = SIN_RESULTADOS
    return {"tipo": tipo, "pregunta": pregunta, "consulta": consulta, "resultados": res, "respuesta": SIN_INFO, "gold": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articulos", type=int, default=60000)
    ap.add_argument("--ejemplos", type=int, default=48000)
    ap.add_argument("--eval", type=int, default=800, help="ejemplos de evaluación por tipo principal")
    ap.add_argument("--rep_real", type=int, default=3, help="veces que se repiten los ejemplos reales de ddgs")
    ap.add_argument("--semilla", type=int, default=0)
    args = ap.parse_args()

    if not POOL.exists():
        construir_pool(args.articulos)
    pool = [json.loads(l) for l in open(POOL, encoding="utf-8")]
    train = [a for a in pool if not es_eval(a["titulo"])]
    held = [a for a in pool if es_eval(a["titulo"])]
    rng = random.Random(args.semilla)
    print(f"Artículos: {len(train):,} de entrenamiento, {len(held):,} reservados para evaluar", flush=True)

    def generar(fuente, n, pesos):
        salida = []
        for _ in range(n):
            tipo = rng.choices(list(pesos), list(pesos.values()))[0]
            salida.append(directo(rng, pool) if tipo == "directo" else ejemplo(rng, pool, rng.choice(fuente), tipo))
        return salida

    pesos = {"buscar_ok": 0.62, "irrelevante": 0.14, "vacio": 0.14, "directo": 0.10}
    DATOS.mkdir(exist_ok=True)
    reales = ejemplos_reales(DATOS / "ddgs_raw.jsonl", rng) if (DATOS / "ddgs_raw.jsonl").exists() else []
    from collections import Counter
    print("Ejemplos reales de ddgs:", dict(Counter(r["tipo"] for r in reales)), flush=True)

    sim = generar(train, args.ejemplos, pesos)
    filas = sim + reales * args.rep_real  # los reales se repiten: son pocos y son los que más enseñan
    rng.shuffle(filas)
    salidas = [("sft_train", filas),
               ("sft_eval", generar(held, args.eval * 4, {"buscar_ok": 0.25, "irrelevante": 0.25, "vacio": 0.25, "directo": 0.25}))]
    if (DATOS / "ddgs_raw_eval.jsonl").exists():
        salidas.append(("sft_eval_real", ejemplos_reales(DATOS / "ddgs_raw_eval.jsonl", random.Random(5))))
    for nombre, filas in salidas:
        with open(DATOS / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for r in filas:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{nombre}: {len(filas):,} ejemplos", flush=True)


if __name__ == "__main__":
    main()
