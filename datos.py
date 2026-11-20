"""Genera el mundo sintético del experimento y el diccionario externo.

Idea a probar: un modelo pequeño que NO memoriza definiciones, sino que
  1) reconoce lo que conoce y responde directo,
  2) detecta cuando una palabra le es desconocida o cuando algo "no calza"
     (ej. "banco de arena": un banco-asiento no se hace de arena),
  3) consulta un diccionario externo y usa lo que leyó.

Todo el texto está en español latino neutro. El "mundo" es inventado a
propósito: así sabemos con certeza qué vio el modelo y qué no.
"""
import argparse
import json
import random
import sqlite3
from pathlib import Path

CARPETA = Path(__file__).parent / "datos"

# Palabras "de base": el modelo las ve muchas veces y debe aprenderlas
# (como el vocabulario que una persona ya maneja).
CONOCIDAS = {
    "mueble": ["silla", "mesa", "banco", "sillón", "cama", "repisa", "velador", "ropero", "escritorio", "estante"],
    "animal": ["perro", "gato", "caballo", "loro", "zorro", "conejo", "oveja", "vaca", "puma", "pato"],
    "comida": ["pan", "queso", "arroz", "empanada", "sopa", "torta", "galleta", "tortilla", "pastel", "flan"],
    "herramienta": ["martillo", "alicate", "serrucho", "taladro", "llave", "destornillador", "lima", "pala", "hacha", "tenaza"],
    "lugar": ["playa", "plaza", "cerro", "parque", "puerto", "bosque", "valle", "isla", "río", "lago"],
    "ropa": ["camisa", "chaqueta", "gorro", "bufanda", "calcetín", "pantalón", "falda", "abrigo", "guante", "chaleco"],
}

# "Sentido común" del mundo: de qué puede estar hecha / ser cada categoría.
# Un banco (mueble) de madera calza; un banco de arena no calza.
# Hay varias palabras y modificadores por categoría para que el modelo aprenda
# la REGLA (categoría de la palabra vs. categoría del modificador) y no memorice pares.
MODIFICADORES = {
    "mueble": ["madera", "metal", "plástico", "mimbre", "roble", "pino"],
    "animal": ["campo", "granja", "caza", "carrera", "monte", "corral"],
    "comida": ["maíz", "trigo", "chocolate", "harina", "avena", "manjar"],
    "herramienta": ["acero", "hierro", "goma", "bronce", "titanio", "carbono"],
    "lugar": ["arena", "piedra", "pasto", "roca", "barro", "ripio"],
    "ropa": ["lana", "algodón", "seda", "cuero", "mezclilla", "lino"],
}
EXTRANOS = ["nubes", "humo", "niebla", "espuma", "viento", "luz"]
NO_SE = "no sé"

# Redacción de las definiciones. "train" se usa al entrenar; "test" solo al
# evaluar, para medir si el modelo entiende redacciones que nunca vio.
RASGOS = {
    "mueble": {
        "train": ["que se usa en la casa", "para sentarse o apoyar cosas", "de uso diario en el hogar",
                  "que se pone en el dormitorio", "con patas y una superficie plana", "que se arma con tornillos",
                  "para guardar objetos", "que suele estar en el comedor"],
        "test": ["que se encuentra junto a la ventana del living", "donde se dejan los libros por la noche",
                 "que se compra en una tienda de decoración"],
    },
    "animal": {
        "train": ["que vive en el bosque", "que se cría en el campo", "de cuatro patas y pelaje corto",
                  "que come hierbas", "que caza de noche", "que pone huevos", "con plumas de colores",
                  "que nada en los ríos"],
        "test": ["que duerme todo el invierno en una cueva", "que se alimenta de insectos pequeños",
                 "que corre muy rápido por la pradera"],
    },
    "comida": {
        "train": ["que se sirve caliente", "típica de las fiestas", "que se prepara al horno",
                  "dulce y esponjosa", "que se come al desayuno", "hecha con verduras",
                  "que se fríe en aceite", "salada y crujiente"],
        "test": ["que se acompaña con salsa picante", "que se cocina lentamente en una olla grande",
                 "que se vende en la feria los domingos"],
    },
    "herramienta": {
        "train": ["que se usa para reparar cosas", "útil en carpintería", "para apretar o golpear piezas",
                  "que corta madera", "para hacer agujeros", "que se guarda en la caja del taller",
                  "con mango de goma", "para medir distancias"],
        "test": ["que usan los mecánicos para soltar tuercas", "que sirve para pulir superficies ásperas",
                 "que se enchufa para cortar metal"],
    },
    "lugar": {
        "train": ["donde se reúne la gente", "cercano a la costa", "que se visita en verano",
                  "con árboles y bancas", "en lo alto de una montaña", "donde llegan los barcos",
                  "en el centro de la ciudad", "donde juegan los niños"],
        "test": ["donde se acumula arena en el fondo del mar o de un río",
                 "al que se llega caminando por un sendero", "donde se instala el mercado cada semana"],
    },
    "ropa": {
        "train": ["que se usa en invierno", "liviana para el verano", "que se pone sobre los hombros",
                  "que abriga el cuello", "que se lava a mano", "con botones al frente",
                  "para cubrir la cabeza", "que se usa para dormir"],
        "test": ["que se teje con lana gruesa durante el otoño", "que se pone encima de la camisa para salir",
                 "que protege los pies del frío"],
    },
}
NEUTROS = {
    "train": ["muy común en el sur", "de color oscuro", "que aparece en cuentos antiguos", "bastante caro",
              "conocido desde hace siglos", "de tamaño mediano", "fácil de encontrar", "que se menciona en canciones"],
    "test": ["poco conocido fuera del país", "que cambia de nombre según la región", "de origen incierto"],
}
# La respuesta siempre es la categoría base; la definición puede usar un sinónimo.
SINONIMOS = {
    "mueble": ["mueble", "pieza de mobiliario", "objeto de la casa"],
    "animal": ["animal", "criatura", "bicho"],
    "comida": ["comida", "alimento", "plato"],
    "herramienta": ["herramienta", "utensilio", "instrumento"],
    "lugar": ["lugar", "sitio", "zona", "espacio"],
    "ropa": ["ropa", "prenda", "vestimenta"],
}
PLANTILLAS = {
    "train": [
        "{t}: {cat} {rasgo}.",
        "{t}: tipo de {cat} {rasgo}.",
        "{t}: {rasgo}, del grupo {cat}.",
        "{t}: se clasifica como {cat}; {rasgo}.",
        "{t}: es un término para {cat} {rasgo}.",
        "{t}: {rasgo}. pertenece a la categoría {cat}.",
        "{t}: en general, {cat} {rasgo}.",
        "{t}: nombre de {cat} {rasgo}.",
    ],
    "test": [
        "{t}: corresponde a {cat} {rasgo}.",
        "{t}: {rasgo}; se considera {cat}.",
        "{t}: según el uso común, {cat} {rasgo}.",
    ],
}
# propio = rasgo de su categoría; neutro = no da pistas;
# mezclado = rasgo de OTRA categoría (obliga a leer la categoría, no adivinar por el rasgo)
PESOS_TIPO = {"propio": 0.45, "neutro": 0.25, "mezclado": 0.30}

ONSETS = ["b", "c", "d", "f", "g", "l", "m", "n", "p", "r", "s", "t", "v", "ch", "tr", "pl", "br", "gr"]
VOCALES = ["a", "e", "i", "o", "u"]
CODAS = ["", "", "", "n", "s", "l", "r"]


def definir(rng, termino, cat, conjunto="train", tipo=None):
    if tipo is None:
        tipo = rng.choices(list(PESOS_TIPO), weights=list(PESOS_TIPO.values()))[0]
    if tipo == "propio":
        rasgo = rng.choice(RASGOS[cat][conjunto])
    elif tipo == "neutro":
        rasgo = rng.choice(NEUTROS[conjunto])
    else:
        otra = rng.choice([c for c in RASGOS if c != cat])
        rasgo = rng.choice(RASGOS[otra][conjunto])
    nombre = rng.choice(SINONIMOS[cat])
    return rng.choice(PLANTILLAS[conjunto]).format(t=termino, cat=nombre, rasgo=rasgo)


def inventar_palabras(rng, n, prohibidas):
    salida = set()
    while len(salida) < n:
        silabas = rng.choice([2, 2, 3])
        p = "".join(rng.choice(ONSETS) + rng.choice(VOCALES) + rng.choice(CODAS) for _ in range(silabas))
        if p not in prohibidas and 4 <= len(p) <= 11:
            salida.add(p)
    return sorted(salida)


def texto_ejemplo(termino, cat, busca, definicion):
    if busca:
        if definicion is None:  # buscó y no existe: debe admitirlo en vez de inventar
            return f"P: ¿qué es {termino}?\nB: {termino}\nD: sin resultados.\nR: {NO_SE}\n"
        return f"P: ¿qué es {termino}?\nB: {termino}\nD: {definicion}\nR: {cat}\n"
    return f"P: ¿qué es {termino}?\nR: {cat}\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--inventadas", type=int, default=3000, help="palabras inventadas para entrenar")
    ap.add_argument("--inventadas-test", type=int, default=600, help="mitad normales, mitad mezcladas")
    ap.add_argument("--inexistentes", type=int, default=600, help="palabras que NO están en el diccionario (entrenar)")
    ap.add_argument("--inexistentes-test", type=int, default=150)
    ap.add_argument("--ejemplos", type=int, default=60000)
    args = ap.parse_args()
    rng = random.Random(args.semilla)
    CARPETA.mkdir(exist_ok=True)

    categorias = list(CONOCIDAS)
    cat_de = {w: c for c, ws in CONOCIDAS.items() for w in ws}
    todos_mod = [m for ms in MODIFICADORES.values() for m in ms] + EXTRANOS

    # --- Diccionario externo (la "base de datos" que el modelo consulta) ---
    diccionario = {}
    for w, c in cat_de.items():
        diccionario[w] = definir(rng, w, c)

    n_inex = args.inexistentes + args.inexistentes_test
    inventadas = inventar_palabras(rng, args.inventadas + args.inventadas_test + n_inex, set(cat_de) | set(todos_mod))
    rng.shuffle(inventadas)
    # Palabras que nunca se agregan al diccionario: buscar no sirve, hay que decir "no sé".
    inexistentes, inventadas = inventadas[:n_inex], inventadas[n_inex:]
    inex_train = [(w, NO_SE) for w in inexistentes[: args.inexistentes]]
    inex_test = [(w, NO_SE) for w in inexistentes[args.inexistentes:]]
    inv_train = [(w, rng.choice(categorias)) for w in inventadas[: args.inventadas]]
    inv_test = [(w, rng.choice(categorias)) for w in inventadas[args.inventadas:]]
    mitad = len(inv_test) // 2
    inv_test, inv_mezcladas = inv_test[:mitad], inv_test[mitad:]
    for w, c in inv_train:
        diccionario[w] = definir(rng, w, c)
    for w, c in inv_test:
        diccionario[w] = definir(rng, w, c, "test", rng.choice(["propio", "neutro"]))
    for w, c in inv_mezcladas:
        diccionario[w] = definir(rng, w, c, "test", "mezclado")

    # Combinaciones palabra conocida + "de" + modificador
    compatibles, incompatibles = [], []
    for w, c in cat_de.items():
        for m in todos_mod:
            frase = f"{w} de {m}"
            if m in MODIFICADORES[c]:
                compatibles.append((frase, c))
            else:
                if frase == "banco de arena":
                    c2 = "lugar"
                    diccionario[frase] = "banco de arena: lugar donde se acumula arena en el fondo del mar o de un río."
                else:
                    c2 = rng.choice([x for x in categorias if x != c])
                incompatibles.append((frase, c2))

    def dividir(lista, forzar_test=()):
        lista = lista[:]
        rng.shuffle(lista)
        corte = int(len(lista) * 0.8)
        tr, te = lista[:corte], lista[corte:]
        for f in forzar_test:
            for x in tr[:]:
                if x[0] == f:
                    tr.remove(x)
                    te.append(x)
        return tr, te

    comp_train, comp_test = dividir(compatibles)
    incomp_train, incomp_test = dividir(incompatibles, forzar_test=["banco de arena"])
    for frase, c2 in incomp_train:
        diccionario[frase] = definir(rng, frase, c2)
    for frase, c2 in incomp_test:
        if frase != "banco de arena":
            diccionario[frase] = definir(rng, frase, c2, "test")

    # --- Ejemplos de entrenamiento ---
    # Variante A: sin herramientas, tiene que memorizar todo.
    # Variante B: busca en el diccionario cuando no sabe o algo no calza.
    fuentes = [
        (0.20, [(w, c) for w, c in cat_de.items()], False),
        (0.35, inv_train, True),
        (0.20, comp_train, False),
        (0.18, incomp_train, True),
        (0.07, inex_train, True),
    ]
    for variante in ("A", "B"):
        r = random.Random(args.semilla + (1 if variante == "A" else 2))
        with open(CARPETA / f"entrenamiento_{variante}.jsonl", "w", encoding="utf-8") as f:
            for _ in range(args.ejemplos):
                x = r.random()
                acum = 0
                for peso, lista, necesita in fuentes:
                    acum += peso
                    if x <= acum:
                        break
                termino, cat = r.choice(lista)
                busca = necesita and variante == "B"
                f.write(json.dumps({"texto": texto_ejemplo(termino, cat, busca, diccionario.get(termino))}, ensure_ascii=False) + "\n")

    # --- Evaluación: lo que el modelo NUNCA vio (salvo las conocidas) ---
    evaluacion = (
        [{"grupo": "conocidas", "termino": w, "cat": c, "deberia_buscar": False} for w, c in cat_de.items()]
        + [{"grupo": "inventadas_nuevas", "termino": w, "cat": c, "deberia_buscar": True} for w, c in inv_test]
        + [{"grupo": "inventadas_mezcladas", "termino": w, "cat": c, "deberia_buscar": True} for w, c in inv_mezcladas]
        + [{"grupo": "compatibles_nuevas", "termino": w, "cat": c, "deberia_buscar": False} for w, c in comp_test]
        + [{"grupo": "no_calzan_nuevas", "termino": w, "cat": c, "deberia_buscar": True} for w, c in incomp_test]
        + [{"grupo": "inexistentes", "termino": w, "cat": c, "deberia_buscar": True} for w, c in inex_test]
    )
    with open(CARPETA / "evaluacion.jsonl", "w", encoding="utf-8") as f:
        for e in evaluacion:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # --- Diccionario en SQLite (fuera del modelo, en disco) ---
    db = CARPETA / "diccionario.sqlite"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE entradas (termino TEXT PRIMARY KEY, definicion TEXT NOT NULL)")
    con.executemany("INSERT INTO entradas VALUES (?, ?)", diccionario.items())
    con.commit()
    con.close()

    print(f"Diccionario: {len(diccionario)} entradas -> {db}")
    print(f"Conocidas: {len(cat_de)} | inventadas train/test: {len(inv_train)}/{len(inv_test)}")
    print(f"Compatibles train/test: {len(comp_train)}/{len(comp_test)} | no calzan train/test: {len(incomp_train)}/{len(incomp_test)}")
    print(f"Inexistentes (no sé) train/test: {len(inex_train)}/{len(inex_test)}")
    print(f"Ejemplos por variante: {args.ejemplos}")


if __name__ == "__main__":
    main()
