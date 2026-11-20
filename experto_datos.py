"""Genera el dataset del experto de código (experto_codigo.lora).

Dominios y proporciones (sobre --total):
  concepto  25 %   fichas de conceptos fundamentales (R: directo, sin buscar) + ejemplos de código
  doc       27,5 % documentación externa: B: consulta -> resultados REALES de ddgs -> R: copiar la oración correcta
  ejec      22,5 % ejecución verificada: E: código -> resultado REAL del sandbox -> R: interpretar salida o error
                   (incluye explicar errores pegados por el usuario, sin herramienta)
  abst      15 %   abstención honesta: funciones/librerías inventadas (B: sin datos relevantes), NameError de funciones
                   que no existen y código no permitido
  repaso    10 %   ejemplos de la Etapa 1 (conversación, hechos, abstención) para no degradar el núcleo

Presupuesto de contexto (512 tokens): resultados de B: <= 200 tokens (fragmentos de 150 caracteres), salida de E: <= 80
tokens (solo el resultado o la última línea de la excepción) y cada ejemplo completo <= 440 tokens. Los ejemplos que no caben
se DESCARTAN (nunca se truncan en silencio).

Evaluación: formulaciones, APIs, conceptos y códigos reservados (nunca aparecen en el entrenamiento).

  python experto_datos.py [--total 14000]
"""
import argparse
import hashlib
import json
import random
import re
from collections import Counter

from experto_fichas import COLA, FICHAS, es_eval as _reservado
from herramientas import _limpio, formatear_resultados, linea_ficha, preparar_resultados
from protocolo import SIN_INFO, TOPE_EJECUCION, TOPE_EJEMPLO, TOPE_EXPERTO, Formato
from sandbox import NO_PERMITIDO, TIEMPO_AGOTADO, ejecutar_lote
from sft_datos import DATOS, _norm, primera_oracion

# ---------------------------------------------------------------- plantillas de pregunta (entrenamiento / evaluación)
Q_DEF_TRAIN = ["¿Qué es {u}?", "¿Qué significa {n} en programación?", "Explícame qué es {u}.", "Define {n}.",
               "¿Qué es {n} en programación?", "Dime qué es {u} en programación.", "Explícame brevemente {n}."]
# Ronda "formulaciones 27": más variedad de preguntas por concepto (ninguna coincide con las de evaluación)
Q_DEF_TRAIN_V2 = Q_DEF_TRAIN + [
    "¿Qué se entiende por {n}?", "¿Me defines {n}?", "Quiero saber qué es {u}.", "¿En qué consiste {n}?", "Dame la definición de {n}.",
    "Háblame de {n} en programación.", "¿Qué es exactamente {u}?", "¿Puedes decirme qué es {u}?", "Describe {n} en pocas palabras.",
    "Explica {n} en programación.", "¿Qué entiendes por {n}?", "Dime qué significa {n}.", "Resume qué es {u}.",
    "¿A qué llamamos {n} en programación?", "Estoy aprendiendo y no sé qué es {u}.", "¿Cuál es la definición de {n}?",
    "En programación, ¿qué es {u}?", "¿Qué es eso de {n}?", "Defíneme {n}, por favor.", "Explícame {n} como si fuera principiante."]
Q_EJ_TRAIN_V2 = ["Dame un ejemplo de {n}.", "Muéstrame un ejemplo de {n} en Python.", "¿Cómo se ve {u} en código?", "Escribe un ejemplo de {n}.",
                 "Un ejemplo de {n}, por favor.", "¿Cómo se escribe {u} en Python?", "Enséñame {n} con código.", "Quiero ver {u} en un ejemplo."]
Q_DEF_EVAL = ["¿Podrías explicarme {n}?", "Necesito entender {n}.", "¿Qué quiere decir {n} en código?", "Cuéntame qué es {u}.", "{n}: ¿qué es?"]
Q_EJ_TRAIN = ["Dame un ejemplo de {n}.", "Muéstrame un ejemplo de {n} en Python.", "¿Cómo se ve {u} en código?"]
Q_EJ_EVAL = ["Ponme un ejemplo de {n}.", "¿Tienes un ejemplo de {n}?"]
Q_API_TRAIN = ["¿Cómo se usa {item} en {lib}?", "¿Para qué sirve {item} en {lib}?", "¿Qué hace {item} de {lib}?",
               "Explícame {item} en {lib}.", "¿Cómo funciona {item} en {lib}?", "Necesito usar {item} de {lib}, ¿cómo es?"]
Q_API_EVAL = ["¿Me explicas {item} ({lib})?", "Ayuda con {item} en {lib}, por favor.", "¿Qué es {item} en {lib}?"]
Q_EJEC_TRAIN = ["¿Qué imprime este código?\n{c}", "¿Qué resultado da este código?\n{c}", "Ejecuta este código y dime qué sale:\n{c}",
                "¿Cuál es la salida de este código?\n{c}"]
Q_EJEC_EVAL = ["¿Qué muestra este programa?\n{c}", "Corre esto y dime el resultado:\n{c}"]
Q_ERR_TRAIN = ["¿Qué significa este error? {e}", "Me sale este error: {e}. ¿Qué pasa?", "Explícame este error: {e}"]
Q_ERR_EVAL = ["¿Por qué falla con {e}?", "No entiendo este mensaje: {e}"]

EXPLICACION = {
    "ZeroDivisionError": "Se intentó dividir entre cero, lo cual no está definido.",
    "IndexError": "El índice está fuera de rango: la lista no tiene tantos elementos.",
    "KeyError": "La clave no existe en el diccionario.",
    "TypeError": "Se mezclaron tipos incompatibles o se usó un valor con una operación que no admite.",
    "NameError": "Se usó un nombre que no está definido: la variable o función no existe.",
    "ValueError": "El valor tiene el tipo correcto pero no es válido para esa operación.",
    "AttributeError": "El objeto no tiene ese atributo o método.",
    "SyntaxError": "El código está mal escrito: falta o sobra algún símbolo.",
    "RecursionError": "La recursión no termina: falta un caso base.",
}
R_NO_PERMITIDO = "No puedo ejecutar eso: usa archivos, módulos externos o funciones no permitidas."
R_BUCLE = "El código no termina: tiene un bucle infinito o tarda demasiado."

NOMBRES = ["Ana", "Luis", "Rex", "Pepe", "Sol", "Mía", "Tito", "Lola"]
PALABRAS = ["python", "codigo", "hola", "mundo", "datos", "clase", "bucle", "lista", "funcion", "texto"]


# ---------------------------------------------------------------- generadores de código (resultado = ejecución real)
def _lista(rng, n=None):
    return [rng.randint(1, 9) for _ in range(n or rng.randint(3, 5))]


def g_aritmetica(r):
    a, b, c = r.randint(2, 40), r.randint(2, 12), r.randint(1, 9)
    return r.choice([f"print({a} + {b})", f"print({a} - {b})", f"print({a} * {b})", f"print({a} // {b})", f"print({a} % {b})",
                     f"print(({a} + {b}) * {c})", f"print({b} ** 2 + {c})", f"print({a} / {b})"])


def g_sumrange(r):
    a = r.randint(0, 3)
    return f"print(sum(range({a}, {a + r.randint(3, 9)})))"


def g_lista(r):
    x = _lista(r)
    return r.choice([f"x = {x}\nx.append({r.randint(1, 9)})\nprint(x)", f"x = {x}\nx.sort()\nprint(x)", f"x = {x}\nprint(len(x), max(x))",
                     f"x = {x}\nx.reverse()\nprint(x)", f"x = {x}\nprint(x[1:3])", f"x = {x}\nprint(sum(x) / len(x))",
                     f"x = {x}\nx.pop()\nprint(x)", f"print(sorted({x}, reverse=True))"])


def g_dict(r):
    a, b = r.randint(1, 9), r.randint(1, 9)
    return r.choice([f"d = {{'a': {a}, 'b': {b}}}\nprint(d['a'] + d['b'])", f"d = {{'a': {a}}}\nprint(d.get('z', 0))",
                     f"d = {{'x': {a}, 'y': {b}}}\nd['z'] = {a + b}\nprint(len(d))", f"d = {{'x': {a}, 'y': {b}}}\nprint(sorted(d.keys()))",
                     f"d = {{}}\nd['k'] = {a}\nprint(d)"])


def g_cadena(r):
    p = r.choice(PALABRAS)
    return r.choice([f"s = '{p}'\nprint(s.upper())", f"s = '{p}'\nprint(s[::-1])", f"s = '{p}'\nprint(len(s))", f"s = '{p}'\nprint(s.capitalize())",
                     f"s = '{p}'\nprint(s.replace('{p[0]}', 'X'))", f"s = '{p}'\nprint(s + s)", f"s = '{p}'\nprint(s.count('{p[0]}'))",
                     f"nombre = '{r.choice(NOMBRES)}'\nprint(f'Hola {{nombre}}')"])


def g_for(r):
    n = r.randint(3, 8)
    return r.choice([f"total = 0\nfor i in range(1, {n + 1}):\n    total += i\nprint(total)",
                     f"for i in range({r.randint(2, 4)}):\n    print(i * {r.randint(2, 5)})",
                     f"p = 1\nfor i in range(1, {min(n, 6) + 1}):\n    p *= i\nprint(p)",
                     f"c = 0\nfor i in range({n * 2}):\n    if i % 2 == 0:\n        c += 1\nprint(c)"])


def g_while(r):
    a, b, c = r.randint(10, 30), r.randint(0, 5), r.randint(2, 4)
    return r.choice([f"n = {a}\nwhile n > {b}:\n    n -= {c}\nprint(n)", f"n = 1\nwhile n < {a}:\n    n *= 2\nprint(n)"])


def g_cond(r):
    x = r.randint(1, 30)
    return r.choice([f"x = {x}\nif x % 2 == 0:\n    print('par')\nelse:\n    print('impar')",
                     f"x = {x}\nif x > 15:\n    print('grande')\nelif x > 5:\n    print('medio')\nelse:\n    print('chico')"])


def g_funcion(r):
    n, a, b, c = r.choice(["suma", "doble", "area", "mezcla"]), r.randint(1, 9), r.randint(1, 9), r.randint(1, 5)
    return r.choice([f"def {n}(a, b):\n    return a * b + {c}\nprint({n}({a}, {b}))", f"def {n}(x):\n    return x * {c + 1}\nprint({n}({a}))",
                     f"def {n}(a, b={c}):\n    return a + b\nprint({n}({a}))"])


def g_recursion(r):
    n = r.randint(3, 6)
    return r.choice([f"def f(n):\n    return 1 if n < 2 else n * f(n - 1)\nprint(f({n}))",
                     f"def f(n):\n    return n if n < 2 else f(n - 1) + f(n - 2)\nprint(f({n + 2}))",
                     f"def f(n):\n    return 0 if n == 0 else n + f(n - 1)\nprint(f({n}))"])


def g_clase(r):
    n, a = r.choice(NOMBRES), r.randint(1, 9)
    return r.choice([f"class Perro:\n    def __init__(self, nombre):\n        self.nombre = nombre\n    def hablar(self):\n        return self.nombre + ' dice guau'\nprint(Perro('{n}').hablar())",
                     f"class Contador:\n    def __init__(self):\n        self.n = {a}\n    def subir(self):\n        self.n += 1\nc = Contador()\nc.subir()\nprint(c.n)",
                     f"class P:\n    def __init__(self, x):\n        self.x = x\nprint(P({a}).x * 2)"])


def g_herencia(r):
    return r.choice([
        "class Animal:\n    def sonido(self):\n        return '...'\nclass Perro(Animal):\n    def sonido(self):\n        return 'guau'\nprint(Perro().sonido())",
        "class A:\n    def f(self):\n        return 'A'\nclass B(A):\n    pass\nprint(B().f())",
        "class Animal:\n    def sonido(self):\n        return '...'\nclass Perro(Animal):\n    def sonido(self):\n        return 'guau'\nclass Gato(Animal):\n    def sonido(self):\n        return 'miau'\nfor a in [Perro(), Gato()]:\n    print(a.sonido())",
        "class F:\n    def area(self):\n        return 0\nclass C(F):\n    def area(self):\n        return 9\nprint(isinstance(C(), F))"])


def g_try(r):
    b = r.choice([0, 0, 2, 5])
    return r.choice([f"try:\n    print(10 / {b})\nexcept ZeroDivisionError:\n    print('no se puede')",
                     "try:\n    int('abc')\nexcept ValueError:\n    print('valor inválido')",
                     f"try:\n    x = [1, 2][{r.randint(0, 3)}]\n    print(x)\nexcept IndexError:\n    print('fuera de rango')",
                     f"try:\n    print({b + 1})\nfinally:\n    print('fin')"])


def g_compre(r):
    k, n = r.randint(2, 4), r.randint(3, 6)
    return r.choice([f"print([x * {k} for x in range({n})])", f"print([x for x in range({n * 2}) if x % 2 == 0])",
                     f"print({{x: x * x for x in range({n})}})", f"print(list(map(lambda x: x + {k}, {_lista(r, 3)})))"])


def g_math(r):
    a = r.randint(2, 12)
    return r.choice([f"import math\nprint(math.sqrt({a * a}))", f"import math\nprint(math.floor({a} / 3))", f"import math\nprint(math.ceil({a} / 3))",
                     f"import math\nprint(round(math.pi, {r.randint(1, 3)}))"])


def g_tipos(r):
    v = r.choice(["5", "'hola'", "3.5", "True", "[1, 2]", "(1, 2)", "{'a': 1}"])
    return r.choice([f"print(type({v}).__name__)", f"print(isinstance({v}, str))"])


OK = [g_aritmetica, g_sumrange, g_lista, g_dict, g_cadena, g_for, g_while, g_cond, g_funcion, g_recursion, g_clase, g_herencia, g_try, g_compre, g_math, g_tipos]


FUNCS_FALSAS = ["calcular_total", "obtener_datos", "sumar_todo", "procesar", "convertir", "leer_archivo", "contar_items",
                "buscar_usuario", "armar_lista", "promedio_total", "limpiar_texto", "enviar_correo", "guardar_datos", "ordenar_todo"]
VARS = ["x", "lista", "datos", "nums", "valores", "a", "resultado", "total"]


def g_error(r):
    a, b, v, k = r.randint(1, 99), r.randint(1, 9), r.choice(VARS), r.choice(["x", "y", "z", "clave", "nombre", "edad"])
    f, xs = r.choice(FUNCS_FALSAS), _lista(r, r.randint(2, 4))
    return r.choice([f"print({a} / 0)", f"{v} = {xs}\nprint({v}[{len(xs) + r.randint(0, 6)}])", f"d = {{'a': {b}}}\nprint(d['{k}'])",
                     f"print('{r.choice(PALABRAS)}' + {a})", f"print(len({a}))", f"print({v})", f"print({f}({a}))",
                     f"print(int('{r.choice(PALABRAS)}'))", f"{v} = {a}\n{v}.append({b})", "print('hola'", f"if {v} = {a}:\n    print({v})",
                     f"def f(n):\n    return f(n + {b})\nf({a})", f"print('a' * '{r.choice(PALABRAS)}')", f"{v} = {xs}\nprint({v}.length)",
                     f"d = {{'{k}': {a}}}\nprint(d.keys()[0])", f"print({a} % 0)", f"print(float('{r.choice(PALABRAS)}'))",
                     f"{v} = {xs}\nprint({v}['a'])", f"print({a} + None)", f"x = {a}\nprint(x[0])"])


def g_noperm(r):
    v, n = r.choice(VARS), r.choice(["datos", "notas", "clave", "salida"])
    return r.choice([f"import os\nprint(os.getcwd())", f"open('{n}.txt').read()", f"import sys\nprint(sys.version)", f"print(eval('{r.randint(1, 9)}+2'))",
                     f"import requests\nrequests.get('http://{n}.com')", f"exec('print({r.randint(1, 9)})')", f"from os import listdir",
                     f"import os\n{v} = os.listdir('.')\nprint({v})", f"with open('{n}.txt') as f:\n    print(f.read())", f"import subprocess\nsubprocess.run(['ls'])",
                     f"import random\nprint(random.randint(1, {r.randint(2, 9)}))", f"import time\ntime.sleep({r.randint(1, 3)})"])


def g_bucle(r):
    return r.choice(["while True:\n    pass", "n = 1\nwhile n > 0:\n    n += 1"])


# ---------------------------------------------------------------- construcción de filas
def _es_error(out):
    return bool(re.match(r"^\w+(Error|Exception)\b", out)) or out in (TIEMPO_AGOTADO, NO_PERMITIDO)


def respuesta_ejec(out):
    if out == NO_PERMITIDO:
        return R_NO_PERMITIDO
    if out == TIEMPO_AGOTADO:
        return R_BUCLE
    if out == "(sin salida)":
        return "No imprime nada."
    m = re.match(r"^(\w+(?:Error|Exception))(?::|$)", out)
    if m:
        tipo = m.group(1)
        if tipo == "NameError":
            n = re.search(r"name '(\w+)'", out)
            if n:
                return f"El nombre {n.group(1)} no está definido: la variable o función no existe."
        return f"Falla con {out}. {EXPLICACION.get(tipo, 'Ocurrió un error al ejecutar el código.')}"
    return f"Imprime {out}." if "\n" not in out else f"Imprime:\n{out}"


def fila(dominio, tipo, pregunta, respuesta, consulta=None, resultados=None, pref="B", tope=None, **extra):
    r = {"dominio": dominio, "tipo": tipo, "pregunta": pregunta, "respuesta": respuesta}
    if consulta is not None:
        r.update(consulta=consulta, resultados=resultados, pref=pref, tope=tope)
    r.update(extra)
    return r


MODO_CONCEPTOS = "memoria"  # "memoria": el LoRA memoriza las definiciones | "busqueda": las lee de la base local (Opción B)


def _resultado_local(rng, ficha):
    """Resultado de la base local de conceptos: la ficha, y a veces otra ficha de distractor (como un buscador real)."""
    lineas = [linea_ficha(ficha, True)]
    if rng.random() < 0.4:
        otra = rng.choice([f for f in FICHAS if f[0] != ficha[0]])
        lineas.insert(rng.randint(0, 1), linea_ficha(otra, False))
    return "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lineas))


def filas_conceptos(rng, usar_eval, plantillas_def, plantillas_ej):
    """Fichas de conceptos NO reservadas, con las formulaciones dadas (entrenamiento u evaluación)."""
    out = []
    for f in FICHAS:
        nombre, u, definicion, ejemplo = f
        if _reservado(nombre):
            continue
        for p in plantillas_def:
            if MODO_CONCEPTOS == "busqueda":
                out.append(fila("concepto", "concepto", p.format(n=nombre, u=u), definicion, f"{nombre} programación",
                                _resultado_local(rng, f), "B", TOPE_EXPERTO, local=True))
            else:
                out.append(fila("concepto", "concepto", p.format(n=nombre, u=u), definicion))
        if ejemplo:
            for p in plantillas_ej:
                if MODO_CONCEPTOS == "busqueda":
                    out.append(fila("concepto", "concepto_ejemplo", p.format(n=nombre, u=u), f"Por ejemplo: {ejemplo}",
                                    f"{nombre} programación", _resultado_local(rng, f), "B", TOPE_EXPERTO, local=True))
                else:
                    out.append(fila("concepto", "concepto_ejemplo", p.format(n=nombre, u=u), f"Por ejemplo: {ejemplo}"))
    return out


def filas_conceptos_nuevos(rng):
    """Conceptos reservados (nunca vistos en el entrenamiento).
    memoria: deben BUSCAR en vez de inventar. busqueda: deben LEER la ficha de la base local y copiarla."""
    out = []
    for f in FICHAS:
        n, u, definicion, _ = f
        if not _reservado(n):
            continue
        for p in Q_DEF_EVAL:
            if MODO_CONCEPTOS == "busqueda":
                out.append(fila("concepto", "concepto_reservado", p.format(n=n, u=u), definicion, f"{n} programación",
                                _resultado_local(rng, f), "B", TOPE_EXPERTO, local=True))
            elif p in Q_DEF_EVAL[:2]:
                out.append(fila("concepto", "concepto_nuevo", p.format(n=n, u=u), definicion, esperado="busca"))
    return out


def _palabras_clave(item):
    ps = [w for w in re.findall(r"\w+", _norm(item)) if len(w) >= 3]
    return ps or [_norm(item)]


def _relevante(r, item, falsa):
    txt = _norm(r["title"] + " " + r["body"])
    if falsa:
        return _norm(item) in txt
    return all(w in txt for w in _palabras_clave(item))


def filas_docs(fmt, rng, reservado):
    """Documentación real (ddgs). reservado: True -> solo evaluación, False -> solo entrenamiento."""
    buenas, abst, descartadas = [], [], Counter()
    for l in open(DATOS / "ddgs_docs_raw.jsonl", encoding="utf-8"):
        d = json.loads(l)
        if _reservado(d["consulta"]) != reservado:
            continue
        falsa = d["tipo"].startswith("falsa")
        lista = preparar_resultados(d["crudos"], permitir_ingles=True)[:3]
        for x in lista:
            x["body"] = _limpio(x["body"], 150)
        rel = [i for i, x in enumerate(lista) if _relevante(x, d["item"], falsa)]
        # plantillas de pregunta
        if d["tipo"] in ("api", "falsa_api"):
            qs = Q_API_EVAL if reservado else Q_API_TRAIN
            preguntas = [q.format(item=d["item"], lib=d["lib"]) for q in qs]
        else:
            n = d["item"]
            preguntas = [q.format(n=n, u=n) for q in (Q_DEF_EVAL if reservado else Q_DEF_TRAIN)]
        if not lista or (falsa and not rel):
            resultados = formatear_resultados(lista, max_frag=150) if lista else "Sin resultados."
            while lista and len(fmt.texto(" " + resultados)) > TOPE_EXPERTO:
                lista = lista[:-1]
                resultados = formatear_resultados(lista, max_frag=150) if lista else "Sin resultados."
            for p in preguntas:
                abst.append(fila("abst", "doc_abst", p, SIN_INFO, d["consulta"], resultados, "B", TOPE_EXPERTO, real=True))
            continue
        if falsa or not rel:
            descartadas["fake con coincidencia" if falsa else "sin relevantes"] += 1
            if not falsa and len(lista) and not rel:  # nada relevante pese a haber resultados: abstención real
                resultados = formatear_resultados(lista, max_frag=150)
                if len(fmt.texto(" " + resultados)) <= TOPE_EXPERTO:
                    for p in preguntas:
                        abst.append(fila("abst", "doc_abst", p, SIN_INFO, d["consulta"], resultados, "B", TOPE_EXPERTO, real=True))
            continue
        i0 = rel[0]
        frase = primera_oracion(lista[i0]["body"])
        if not frase or not 25 <= len(frase) <= 140:
            descartadas["sin oración utilizable"] += 1
            continue
        # recortar resultados desde el final hasta que quepan, conservando el que contiene la respuesta
        k = len(lista)
        resultados = formatear_resultados(lista[:k], max_frag=150)
        while k > i0 + 1 and len(fmt.texto(" " + resultados)) > TOPE_EXPERTO:
            k -= 1
            resultados = formatear_resultados(lista[:k], max_frag=150)
        if len(fmt.texto(" " + resultados)) > TOPE_EXPERTO or frase not in resultados:
            descartadas["no cabe"] += 1
            continue
        for p in preguntas:
            buenas.append(fila("doc", "doc_ok", p, frase, d["consulta"], resultados, "B", TOPE_EXPERTO, real=True))
    print(f"  docs ({'evaluación' if reservado else 'entrenamiento'}): {len(buenas)} con respuesta, {len(abst)} de abstención; "
          f"descartadas: {dict(descartadas)}", flush=True)
    return buenas, abst


def _codigos(gens, n, rng, vistos, prohibidos=()):
    """n códigos únicos (no repetidos ni en 'prohibidos') de las familias dadas."""
    out, intentos = [], 0
    while len(out) < n and intentos < n * 40:
        intentos += 1
        c = rng.choice(gens)(rng)
        if len(c) > 170 or c in vistos or c in prohibidos:
            continue
        vistos.add(c)
        out.append(c)
    return out


def pregunta_codigo(rng, plantilla, c):
    """Misma pregunta con varios formatos de entrada, como escribe la gente: código en otra línea, en la misma línea,
    código solo (sin pregunta) o dentro de un bloque ```."""
    base = plantilla.replace("\n{c}", "")
    r = rng.random()
    if r < 0.45:
        return base + "\n" + c
    if r < 0.67 and "\n" not in c:
        return base + " " + c
    if r < 0.80:
        return c
    return base + "\n```\n" + c + "\n```"


def filas_ejecucion(rng, n_ok, n_err, n_noperm, n_bucle, n_interp, prohibidos, plantillas, plantillas_err, vistos):
    cods = (_codigos(OK, n_ok, rng, vistos, prohibidos) + _codigos([g_error], n_err, rng, vistos, prohibidos) +
            _codigos([g_noperm], n_noperm, rng, vistos, prohibidos) + _codigos([g_bucle], n_bucle, rng, vistos, prohibidos))
    salidas = ejecutar_lote(cods)
    filas, errores = [], []
    for c, out in zip(cods, salidas):
        if out.endswith("…"):
            continue
        err = _es_error(out)
        tipo = "ejec_noperm" if out == NO_PERMITIDO else ("ejec_error" if err else "ejec_ok")
        dominio = "abst" if (out == NO_PERMITIDO or re.match(r"^NameError", out)) else "ejec"
        if dominio == "abst":
            tipo = "ejec_noperm" if out == NO_PERMITIDO else "ejec_nameerror"
        filas.append(fila(dominio, tipo, pregunta_codigo(rng, rng.choice(plantillas), c), respuesta_ejec(out), c, out, "E", TOPE_EJECUCION, salida=out))
        if err and out not in (NO_PERMITIDO, TIEMPO_AGOTADO) and len(errores) < 10_000:
            errores.append(out)
    # interpretar un error pegado por el usuario (conocimiento estable, sin herramienta)
    for out in rng.sample(errores, min(n_interp, len(errores))) if errores else []:
        m = re.match(r"^(\w+(?:Error|Exception))", out)
        if m and m.group(1) in EXPLICACION:
            filas.append(fila("ejec", "error_interp", rng.choice(plantillas_err).format(e=out), EXPLICACION[m.group(1)]))
    return filas


def completar(filas, fmt):
    """Mide cada ejemplo completo en tokens y descarta los que no caben en TOPE_EJEMPLO. Nada se trunca en silencio."""
    buenas, largos = [], []
    for r in filas:
        if r.get("resultados") and r.get("tope") and len(fmt.texto(" " + r["resultados"])) > r["tope"]:
            largos.append(r)  # el resultado de la herramienta no cabe en su tope: se descarta, no se trunca
            continue
        ids, _ = fmt.ejemplo(r["pregunta"], r.get("consulta"), r.get("resultados"), r["respuesta"],
                             prefijo=r.get("pref", "B"), tope=r.get("tope") or 10_000)
        r["tokens"] = len(ids)
        (buenas if len(ids) <= TOPE_EJEMPLO else largos).append(r)
    return buenas, len(largos)


def muestrear(fuente, n, rng):
    if not fuente:
        return []
    return [rng.choice(fuente) for _ in range(n)] if n > len(fuente) else rng.sample(fuente, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=14000)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--formulaciones", type=int, default=7, choices=(7, 27), help="formulaciones de pregunta por concepto en el entrenamiento")
    ap.add_argument("--sufijo", default="", help="sufijo de los archivos de salida (ej. _f27); con sufijo NO se reescribe la evaluación")
    ap.add_argument("--conceptos", choices=("memoria", "busqueda"), default="memoria",
                    help="busqueda = Opción B: definiciones desde la base local (herramienta), no memorizadas en el LoRA")
    args = ap.parse_args()
    global Q_DEF_TRAIN, Q_EJ_TRAIN, MODO_CONCEPTOS
    MODO_CONCEPTOS = args.conceptos
    if args.formulaciones == 27:
        Q_DEF_TRAIN, Q_EJ_TRAIN = Q_DEF_TRAIN_V2, Q_EJ_TRAIN_V2
    rng = random.Random(args.semilla)
    fmt = Formato()
    N = args.total
    cuota = {"concepto": 0.25, "doc": 0.275, "ejec": 0.225, "abst": 0.15, "repaso": 0.10}

    print("Documentación real (ddgs)...", flush=True)
    doc_tr, abst_doc_tr = filas_docs(fmt, rng, reservado=False)
    doc_ev, abst_doc_ev = filas_docs(fmt, rng, reservado=True)

    print("Ejecutando código en el sandbox...", flush=True)
    vistos = set()
    n_ej = int(N * cuota["ejec"])
    n_ab = int(N * cuota["abst"])
    # entrenamiento: ok 60 %, error 25 %, interpretación de errores 15 % (del cupo de ejecución); abstención E: parte del cupo abst
    ej_tr = filas_ejecucion(rng, int(n_ej * 0.62), int(n_ej * 0.40) + int(n_ab * 0.25), int(n_ab * 0.15), 25, int(n_ej * 0.16),
                            (), Q_EJEC_TRAIN, Q_ERR_TRAIN, vistos)
    codigos_train = set(vistos)
    ej_ev = filas_ejecucion(random.Random(args.semilla + 1), 150, 90, 25, 6, 60, codigos_train, Q_EJEC_EVAL, Q_ERR_EVAL, set())

    # --- entrenamiento por dominio
    concepto = filas_conceptos(rng, False, Q_DEF_TRAIN, Q_EJ_TRAIN)
    ejec = [r for r in ej_tr if r["dominio"] == "ejec"]
    abst_e = [r for r in ej_tr if r["dominio"] == "abst"]
    repaso_fuente = [json.loads(l) for l in open(DATOS / "sft_train.jsonl", encoding="utf-8")]
    for r in repaso_fuente:
        r["dominio"] = "repaso"

    train = (muestrear(concepto, int(N * cuota["concepto"]), rng) + muestrear(doc_tr, int(N * cuota["doc"]), rng) +
             muestrear(ejec, n_ej, rng) +
             muestrear(abst_doc_tr, int(n_ab * 0.60), rng) + muestrear(abst_e, n_ab - int(n_ab * 0.60), rng) +
             rng.sample(repaso_fuente, int(N * cuota["repaso"])))
    rng.shuffle(train)

    # --- evaluación (todo reservado)
    evaluacion = (filas_conceptos(rng, True, Q_DEF_EVAL, Q_EJ_EVAL) + filas_conceptos_nuevos(rng) + doc_ev + abst_doc_ev + ej_ev)

    train, desc_tr = completar(train, fmt)
    evaluacion, desc_ev = completar(evaluacion, fmt)
    # con sufijo no se reescribe la evaluación original, salvo que cambien las filas de concepto (modo búsqueda)
    salidas = [("experto_train" + args.sufijo, train)]
    if not args.sufijo or args.conceptos == "busqueda":
        salidas.append(("experto_eval" + args.sufijo, evaluacion))
    for nombre, filas in salidas:
        with open(DATOS / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for r in filas:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def resumen(nombre, filas, desc):
        t = sorted(r["tokens"] for r in filas if "tokens" in r)
        print(f"\n{nombre}: {len(filas):,} ejemplos (descartados por exceder {TOPE_EJEMPLO} tokens: {desc})")
        print("  dominios:", dict(Counter(r["dominio"] for r in filas)))
        print("  tipos:   ", dict(Counter(r["tipo"] for r in filas)))
        if t:
            print(f"  tokens por ejemplo: media {sum(t) / len(t):.0f}, p95 {t[int(len(t) * .95)]}, p99 {t[int(len(t) * .99)]}, máximo {t[-1]} (contexto 512)")

    resumen("experto_train", train, desc_tr)
    resumen("experto_eval", evaluacion, desc_ev)


if __name__ == "__main__":
    main()
