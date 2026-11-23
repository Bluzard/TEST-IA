"""Enrutador ligero (Capa 1, sin red neuronal): decide si el turno lo atiende el experto de código, el de redacción o solo el núcleo.

Tres estados EXCLUSIVOS: None (núcleo base), "codigo" y "redaccion". Un solo experto activo por turno (`paso` devuelve uno solo).
Con el adaptador dormido el núcleo responde idéntico a la Etapa 1.

Puntaje de un mensaje:
  +3 bloque ``` | +2 por patrón de código (def, class, import, print(, =>, {{ }}, SELECT, *ngFor, ...)
  +2 nombre de biblioteca/tecnología (pandas, Angular, git, SQL...) o error de Python (TypeError...) o concepto
     inequívocamente de programación (recursión, polimorfismo...) | +1 por palabra de dominio ambigua (lista, clase, función...)
Histéresis: se ACTIVA con puntaje >= 2; una vez activo se mantiene mientras haya alguna señal (>= 1) y se DUERME tras
`reposo` turnos seguidos sin señal (puntaje 0).

  python enrutador.py          # evaluación con un conjunto etiquetado
"""
import json
import random
import re
import unicodedata
from pathlib import Path

from experto_fichas import COLA, FICHAS

RAIZ = Path(__file__).parent


def _n(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


BIBLIOTECAS = {n for n in (
    "pandas numpy requests python json datetime collections itertools pathlib functools argparse logging unittest sqlite3 csv "
    "subprocess threading asyncio enum contextlib flask django fastapi pytest angular react javascript typescript node.js nodejs "
    "sql git docker bash css java c# html npm rebase stash dockerfile").split()}
AMBIGUAS = {_n(x) for x in (
    "lista clase objeto método función variable cola pila árbol grafo nodo hilo módulo operador expresión comentario índice referencia "
    "constante error programa código script librería base de datos tipo entero decimal matriz conjunto condicional intérprete "
    "asignación instancia interfaz composición abstracción cadena de texto número decimal bug commit").split()}
# Conceptos que casi no aparecen fuera de programación: nombres de las fichas y de los conceptos de cola, menos los ambiguos
INEQUIVOCOS = ({_n(f[0]) for f in FICHAS} | {_n(c) for c in COLA} |
               {_n(x) for x in ("recursión", "polimorfismo", "herencia", "bucle", "traceback", "algoritmo", "sintaxis", "depurar", "framework")}) - AMBIGUAS
# Sintaxis de Python que casi no aparece en lenguaje corriente (cada una suma 2)
SINTAXIS = [re.compile(p) for p in (
    r"\b(sum|len|range|print|sorted|min|max|abs|round|enumerate|zip|map|filter|list|dict|set|tuple|int|str|float)\s*\(.*\)",
    r"\w\s*\*\*\s*[\w(]", r"\[[^\]]*\bfor\s+\w+\s+in\b[^\]]*\]", r"\bfor\s+\w+\s+in\s+\w+", r"\w\([^()]*\d[^()]*\)",
    r"\[[^\]]*\d[^\]]*\]\s*[*+]|\w\[[^\]]+\]", r"\bejecuta\w*\b[^.?!]{0,30}:")]
# Sinónimos / derivados de los títulos de las fichas que no son el título exacto
SINONIMOS = {"recursividad", "recursivo", "recursiva", "recursivas", "recursivos", "iterativo", "iterativa", "polimorfico", "heredar",
             "lambda", "docstring", "stack", "queue", "bucles", "bucle", "listas", "diccionarios", "tuplas", "funciones recursivas"}
# Pistas de que una palabra ambigua (pila, cola, árbol...) se usa en sentido informático
CONTEXTO_PROG = re.compile(r"\b(programacion|programar|codigo|python|estructura de datos|estructuras de datos|algoritmo|computacion|"
                           r"informatica|lifo|fifo|push|pop|append|enqueue|dequeue)\b")
PATRONES = [re.compile(p) for p in (
    r"```", r"\bdef \w+\(", r"\bclass \w+\s*[:(]", r"^\s*import \w+", r"\bfrom \w+ import\b", r"\bprint\(", r"\bconsole\.log\(",
    r"=>", r"\w+\s*(\+=|-=|==|!=|<=|>=)\s*\w", r"\bfor \w+ in\b.*:", r"\bif .*:\s*$", r"\breturn\b", r"^\s*\w+\s*=\s*[\[\{(\d'\"]",
    r"\bSELECT\b.*\bFROM\b", r"\*ng\w+", r"\{\{.*\}\}", r"</?\w+>", r"\w+\(\w*\)\s*[;{]", r"\w+\.\w+\(", r"\b\w*Error\b", r"\$ ?(npm|pip|git)\b")]


def puntaje(texto):
    s = 0
    if "```" in texto:
        s += 3
    s += 2 * sum(bool(p.search(texto)) for p in PATRONES[1:])
    palabras = set(re.findall(r"[\w.#+]+", _n(texto)))
    nt = _n(texto)
    s += 2 * len(palabras & BIBLIOTECAS) + 2 * len(palabras & _INEQ_SIMPLES)
    s += sum(2 for x in _INEQ_MULTI if re.search(r"\b" + re.escape(x) + r"\b", nt))
    s += len(palabras & AMBIGUAS)
    s += 2 * sum(bool(p.search(texto)) for p in SINTAXIS)
    s += 2 * len(palabras & _SINON_SIMPLES)
    if s and CONTEXTO_PROG.search(nt):  # «¿Qué es una pila en programación?»: la palabra ambigua pasa a contar doble
        s += len(palabras & AMBIGUAS)
    return s


_SINON_SIMPLES = {_n(x) for x in SINONIMOS if " " not in x} - AMBIGUAS
_INEQ_SIMPLES = {x for x in INEQUIVOCOS if " " not in x}
_INEQ_MULTI = [x for x in INEQUIVOCOS if " " in x]


# ---------------------------------------------------------------- dominio de redacción
from redaccion_fichas import FICHAS_GRAMATICA  # noqa: E402

REDACCION_FUERTES = {_n(x) for x in (
    "ortografía ortográfica ortográfico ortográficos tilde tildes puntuación gramática gramatical gramaticales concordancia redacción "
    "sinónimo sinónimos antónimo antónimos dequeísmo queísmo laísmo leísmo diptongo hiato homófono homófonos acentuación pleonasmo solecismo "
    "perífrasis voseo parónimo prefijo sufijo gerundio subjuntivo pretérito esdrújula esdrújulas llana llanas aguda agudas").split()}
REDACCION_AMBIGUAS = {_n(x) for x in (
    "coma comillas punto tono texto palabra palabras oración oraciones frase frases verbo verbos sujeto predicado párrafo signos mayúscula mayúsculas "
    "minúscula minúsculas adjetivo adverbio sustantivo artículo plural singular acento acentos letra letras sílaba sílabas mensaje correo").split()}
VERBOS_EDICION = {_n(x) for x in ("corrige corrígeme corregir corrígelo reescribe reescríbeme reescribir reescríbelo redacta redáctame redactar redáctalo "
                                  "parafrasea parafrasear acorta acórtalo acortar arregla arréglame arreglar").split()}
# frases que por sí solas indican una tarea de redacción (+3)
PATRONES_REDACCION = [re.compile(p) for p in (
    r"\bhazlo mas (formal|conciso|claro|corto|cercano|amable|directo|sencillo|informal|cordial|profesional)\b",
    r"\b(en|a un|con un|con) tono (formal|informal|cercano|amable|cordial|profesional|cotidiano)\b",
    r"\b(pasa|cambia|ajusta|escribelo|reescribelo|redactalo|dale)\b.{0,25}\btono\b",
    r"\bmejora (la|esta|este|el|mi) (redaccion|texto|parrafo|mensaje|correo|carta)\b",
    r"\b(revisa|revisame|corrige|corrigeme) (la |mi |esta |este |el )?(ortografia|puntuacion|redaccion|gramatica|texto|parrafo|mensaje|carta)\b",
    r"\bdiferencia entre (porque|por que|sino|si no|haber|a ver|hay|ahi|ay|tambien|tan bien|tampoco|tan poco|asimismo|echo|hecho|ha|a)\b",
    r"\bse escribe (con|junto|separado|b|v|h|ll|y|g|j|s|c|z)\b", r"\bcon (b|v) o con (b|v)\b", r"\bcon (g|j) o con (g|j)\b", r"\bcon h o sin h\b",
    r"\b(mas|menos) (formal|informal|conciso|claro|cercano|amable|directo|sencillo|sencilla|cordial|profesional|simple|corto)\b", r"\bcon mas claridad\b",
    r"\buso de (la |las |el |los )?(h|b|v|g|j|ll|y|s|c|z|r|rr|m|n|tilde|coma|punto|mayuscula|mayusculas|minuscula|minusculas)\b",
    r"\b(simplifica|resume|mejora|acorta|alarga|reformula|parafrasea) (este|esta|el|la|mi) (texto|mensaje|frase|oracion|parrafo|correo|carta)\b",
    r"\bquita (lo que sobra|las muletillas|el relleno)\b", r"\bsin cambiar el sentido\b")]
# palabras de las fichas gramaticales que también aparecen en programación: cuentan 1 (no 2)
_SOLAPE = {_n(x) for x in ("condicional", "imperativo", "comillas", "raya", "preposiciones", "conjunciones", "pronombres", "módulo", "infinitivo")}
_NOMBRES_FICHA = {}
from redaccion_fichas import COLA_GRAMATICA  # noqa: E402

for _f in list(FICHAS_GRAMATICA) + [(c,) for c in COLA_GRAMATICA]:
    _k = _n(_f[0])
    if re.fullmatch(r"[a-zñ ]{4,}", _k) and _k not in AMBIGUAS and _k not in REDACCION_AMBIGUAS:
        _NOMBRES_FICHA[_k] = 1 if _k in _SOLAPE else 2


_CODIGO_FUERTE = [re.compile(p, re.M) for p in (
    r"```", r"\bdef \w+\(", r"\bclass \w+\s*[:(]", r"^\s*import \w+", r"\bfrom \w+ import\b", r"\bprint\(", r"=>", r"\bfor \w+ in\b",
    r"^\s*\w+\s*=\s*[\[\{(\d'\"]", r"\bif .*:\s*$", r"\bSELECT\b.*\bFROM\b", r"\bconsole\.log\(", r"\w+\(\w*\)\s*[;{]")]


def puntaje_redaccion(texto):
    """Puntaje de que el mensaje sea una tarea de redacción: corregir, reescribir por tono o consultar una regla del español."""
    nt = _n(texto)
    palabras = set(re.findall(r"[\w]+", nt))
    s = 3 * sum(bool(p.search(nt)) for p in PATRONES_REDACCION)
    s += 2 * len(palabras & REDACCION_FUERTES) + 2 * len(palabras & VERBOS_EDICION)
    s += len(palabras & REDACCION_AMBIGUAS)
    for nombre, peso in _NOMBRES_FICHA.items():
        if re.search(r"\b" + re.escape(nombre) + r"\b", nt):
            s += peso
    return s


def _autonomo(mensaje):
    """Mensaje que abre un tema nuevo (largo o con nombres propios), no un seguimiento corto como «¿y eso?» o «gracias»."""
    pal = mensaje.split()
    return len(pal) >= 5 or any(p[:1].isupper() for p in pal[1:])


class Enrutador:
    """Arbitraje exclusivo entre None / "codigo" / "redaccion". `activo` es siempre uno solo de los tres."""

    DOMINIOS = ("codigo", "redaccion")

    def __init__(self, umbral=2, reposo=2):
        self.umbral, self.reposo = umbral, reposo
        self.activo, self.sin_senal = None, 0

    @staticmethod
    def puntajes(mensaje):
        """Puntajes por dominio. En «Instrucción: texto a trabajar» la instrucción manda: un texto de ejemplo con palabras o signos que
        parecen código (puntos, paréntesis, «return»...) no debe llevarse el turno; solo cuenta como código si trae sintaxis inequívoca."""
        pref, sep, carga = mensaje.partition(":")
        if sep and len(pref) <= 70 and puntaje_redaccion(pref) >= 2:
            fuertes = sum(bool(p.search(carga)) for p in _CODIGO_FUERTE)
            return {"codigo": puntaje(pref) + 2 * fuertes, "redaccion": puntaje_redaccion(pref) + min(puntaje_redaccion(carga), 2)}
        return {"codigo": puntaje(mensaje), "redaccion": puntaje_redaccion(mensaje)}

    def _elegir(self, sc, mensaje):
        """Dominio con puntaje >= umbral; si ambos lo superan gana el mayor y, en empate, redacción solo con un verbo de edición."""
        c, r = sc["codigo"] >= self.umbral, sc["redaccion"] >= self.umbral
        if c and r:
            if sc["codigo"] != sc["redaccion"]:
                return "codigo" if sc["codigo"] > sc["redaccion"] else "redaccion"
            return "redaccion" if set(re.findall(r"\w+", _n(mensaje))) & VERBOS_EDICION else "codigo"
        return "codigo" if c else ("redaccion" if r else None)

    def paso(self, mensaje):
        """Devuelve "codigo", "redaccion" o None: el experto que atiende ESTE turno (nunca dos)."""
        sc = self.puntajes(mensaje)
        if self.activo is None:
            self.activo = self._elegir(sc, mensaje)
            self.sin_senal = 0
        else:
            otro = "redaccion" if self.activo == "codigo" else "codigo"
            if sc[otro] >= self.umbral and sc[otro] > sc[self.activo]:  # cambio directo de dominio, sin pasar por dormido
                self.activo, self.sin_senal = otro, 0
            elif sc[self.activo] >= 1:
                self.sin_senal = 0
            else:
                # un seguimiento corto cuenta 1 turno sin señal; un tema nuevo sin señal del dominio cuenta como 2 (duerme al tiro)
                self.sin_senal += self.reposo if _autonomo(mensaje) else 1
                if self.sin_senal >= self.reposo:
                    self.activo = None
        return self.activo


NEGATIVOS_DIFICILES = [
    "¿Qué clase de música te gusta?", "Mi variable favorita en el clima es la humedad.", "¿Cuál es la función del corazón?",
    "Necesito una lista de compras para el asado.", "¿Qué es un árbol genealógico?", "Hay una cola enorme en el banco.",
    "El objeto de la reunión es acordar fechas.", "¿Cómo funciona un método de estudio eficaz?", "Dime la capital de Chile.",
    "¿Qué es una base de datos de clientes en una tienda?", "hola, ¿cómo estás?", "¿Quién fue Gabriela Mistral?",
    "Cuéntame sobre el Teide.", "¿Qué es la fotosíntesis?", "Escribe en mayúsculas: buenos días a todos", "gracias",
    "¿Qué es un banco de arena?", "Explícame la teoría de la relatividad.", "¿Qué sabes de pludos?", "Dame una receta de empanadas.",
    "¿Cuál es el módulo de un número complejo?", "Me dio un error en la cuenta del banco, ¿qué hago?", "Hola, quiero cambiar mi clase de yoga.",
    "¿Qué comida lleva más proteína?", "¿Cuántas palabras tiene «el perro come»?", "1244123/2344", "¿Qué hora es en Tokio?",
    "Recomiéndame una película de terror.", "¿Cómo se escribe un currículum?", "¿Qué significa la palabra efímero?"]


def evaluar():
    ev = [json.loads(l) for l in open(RAIZ / "datos" / "experto_eval_B.jsonl", encoding="utf-8")]
    pos = [(r["tipo"], r["pregunta"]) for r in ev]
    tr = [json.loads(l) for l in open(RAIZ / "datos" / "experto_train_B.jsonl", encoding="utf-8")]
    random.Random(0).shuffle(tr)
    pos += [(r["tipo"], r["pregunta"]) for r in tr if r["dominio"] in ("concepto", "doc", "ejec", "abst")][:1500]
    neg = [("general", r["pregunta"]) for r in (json.loads(l) for l in open(RAIZ / "datos" / "sft_eval.jsonl", encoding="utf-8"))]
    neg += [("difícil", q) for q in NEGATIVOS_DIFICILES]
    tp = sum(puntaje(q) >= 2 for _, q in pos)
    fp = [(t, q) for t, q in neg if puntaje(q) >= 2]
    print(f"Positivos (código): {len(pos)} | recall {tp / len(pos):.1%}")
    print(f"Negativos (general): {len(neg)} | falsos positivos {len(fp)} ({len(fp) / len(neg):.1%}) | precisión {tp / (tp + len(fp)):.1%}")
    por_tipo = {}
    for t, q in pos:
        a, b = por_tipo.get(t, (0, 0))
        por_tipo[t] = (a + (puntaje(q) >= 2), b + 1)
    print("recall por tipo:", {t: f"{a / b:.0%}" for t, (a, b) in sorted(por_tipo.items())})
    print("falsos positivos:", [q for _, q in fp][:8])
    perdidos = [(t, q) for t, q in pos if puntaje(q) < 2]
    print("ejemplos de código no detectado:", [q[:60] for _, q in random.Random(1).sample(perdidos, min(6, len(perdidos)))])
    # conversación escalonada: histéresis
    e = Enrutador()
    guion = [("hola, ¿cómo estás?", None), ("¿Qué es la recursión?", "codigo"), ("¿y para qué sirve?", "codigo"),
             ("gracias, me quedó claro", None),  # 2.º turno corto sin señal: duerme
             ("¿Qué comida me recomiendas?", None), ("ok", None),
             ("¿Cómo se usa merge en pandas?", "codigo"), ("¿Quién fue Gabriela Mistral?", None),  # tema nuevo: duerme al tiro
             ("¿Qué es un decorador?", "codigo"), ("¿y eso?", "codigo"),
             ("¿puedes dar un ejemplo?", None),  # 2.º seguimiento corto seguido sin señal: duerme
             ("cuéntame más", None)]
    print("\nHistéresis (mensaje -> experto):")
    ok = True
    for m, esperado in guion:
        r = e.paso(m)
        ok &= r == esperado
        print(f"  {m!r:42s} -> {r}  {'' if r == esperado else '(esperado ' + str(esperado) + ')'}")
    print("guion correcto:", ok)
    evaluar3()


ETIQ = (None, "codigo", "redaccion")

NEGATIVOS_REDACCION_DIFICILES = [  # mensajes generales con palabras de lengua que NO piden redacción
    "El punto de venta está cerrado hoy.", "Mi tono de voz es muy grave.", "¿Quién escribió el texto de la Constitución de 1980?",
    "Tengo un acento chileno muy marcado.", "¿Qué letra tiene la canción Gracias a la vida?", "Hay una coma de agua en el suelo.",
    "El sujeto del experimento era un voluntario.", "¿Cuál es el plural de la palabra lápiz?", "La frase célebre de Napoleón fue famosa.",
    "El correo llegó tarde ayer.", "¿Qué significa mensaje en clave?", "Me encanta el tono del cielo al atardecer.",
    "¿Cuántas sílabas tiene la palabra murciélago?", "Dime una palabra bonita.", "El artículo de la Wikipedia es largo.",
    "Mi párrafo favorito del libro es el último.", "¿Cuál es la capital de Perú?", "Cuéntame un chiste corto.", "¿Cómo está el clima en Lima?",
    "Dame una receta de pan.", "¿Qué hora es en Madrid?", "¿Quién ganó el mundial de 1998?"]
POSITIVOS_REDACCION_A_MANO = [
    "Corrige: ayer fuimos al parque y jugamos mucho", "¿Se escribe con b o con v la palabra vaca?", "Hazlo más formal: oye, mándame el archivo",
    "Mejora la redacción de este correo: hola, quiero un reembolso", "¿Cuál es la diferencia entre porque y por qué?", "¿Cuándo se usa la tilde diacrítica?",
    "Reescribe este mensaje en tono más amable: ya te dije que no", "¿Qué es un hiato?", "Revisa la ortografía de mi carta", "Acórtalo sin cambiar el sentido: la verdad es que llegué tarde",
    "¿Cómo se usa el punto y coma?", "Explícame el dequeísmo", "¿Qué es un verbo copulativo?", "Corrígeme este texto: el ni;o juga en la plasa", "Redacta un mensaje formal para pedir vacaciones"]
POSITIVOS_CODIGO_A_MANO = [
    "Corrige este código: print('hola'", "Revisa la función suma, no devuelve nada", "¿Por qué me da error esta lista? x = [1, 2", "Ejecuta: sum([x**2 for x in range(1, 6)])",
    "¿Qué es la recursividad?", "Explícame qué es una clase en Python", "Reescribe este bucle for con una comprensión de listas", "¿Cómo se usa merge en pandas?",
    "Simplifica esta función: def f(x): return x*2", "Arregla este error de sintaxis: if x = 3:"]


def evaluar3(n_por_clase=1500):
    """Matriz de confusión entre las tres clases (núcleo / código / redacción) y falsos positivos de cada experto."""
    rng = random.Random(0)
    cod = [json.loads(l)["pregunta"] for l in open(RAIZ / "datos" / "experto_eval_B.jsonl", encoding="utf-8")]
    tr = [json.loads(l) for l in open(RAIZ / "datos" / "experto_train_B.jsonl", encoding="utf-8")]
    rng.shuffle(tr)
    cod += [r["pregunta"] for r in tr if r["dominio"] in ("concepto", "doc", "ejec", "abst")][:n_por_clase]
    red = [json.loads(l) for l in open(RAIZ / "datos" / "redaccion_eval.jsonl", encoding="utf-8")]
    red = [r["pregunta"] for r in red]
    tr = [json.loads(l) for l in open(RAIZ / "datos" / "redaccion_train.jsonl", encoding="utf-8")]
    rng.shuffle(tr)
    red += [r["pregunta"] for r in tr if r["dominio"] != "repaso"][:n_por_clase]
    ning = [r["pregunta"] for r in (json.loads(l) for l in open(RAIZ / "datos" / "sft_eval.jsonl", encoding="utf-8"))]
    ning += NEGATIVOS_DIFICILES + NEGATIVOS_REDACCION_DIFICILES
    conjuntos = {None: ning, "codigo": cod + POSITIVOS_CODIGO_A_MANO, "redaccion": red + POSITIVOS_REDACCION_A_MANO}
    print("\n=== Enrutador de tres estados: matriz de confusión (fila = real, columna = decidido) ===")
    print(f"{'real':12s}" + "".join(f"{str(c):>11s}" for c in ETIQ) + "      n   acierto")
    malos = {}
    for real, qs in conjuntos.items():
        cuenta = {c: 0 for c in ETIQ}
        for q in qs:
            sc = Enrutador.puntajes(q)
            e = Enrutador()
            d = e._elegir(sc, q)
            cuenta[d] += 1
            if d != real:
                malos.setdefault((real, d), []).append(q)
        print(f"{str(real):12s}" + "".join(f"{cuenta[c]:11d}" for c in ETIQ) + f"{len(qs):7d}   {cuenta[real] / len(qs):.1%}")
    for exp in ("codigo", "redaccion"):
        fp = sum(len(v) for (r, d), v in malos.items() if d == exp and r != exp)
        tot = sum(len(v) for v in conjuntos.values()) - len(conjuntos[exp])
        print(f"falsos positivos de {exp}: {fp} de {tot} mensajes que no son suyos ({fp / tot:.2%}); confusión código<->redacción: "
              f"{len(malos.get(('codigo', 'redaccion'), []))} + {len(malos.get(('redaccion', 'codigo'), []))}")
    for (r, d), v in sorted(malos.items(), key=lambda kv: -len(kv[1])):
        print(f"  {str(r)} -> {d}: {len(v)} p. ej. {[q[:55] for q in rng.sample(v, min(3, len(v)))]}")
    # exclusión mutua + histéresis entre dominios
    guion = [("hola, ¿cómo estás?", None), ("¿Qué es la recursión?", "codigo"), ("¿y para qué sirve?", "codigo"),
             ("Corrige la ortografía: ayer fui al mercado y compre berduras", "redaccion"),  # cambio directo código -> redacción
             ("¿y la tilde de compré?", "redaccion"), ("Hazlo más formal: oye, mándame la factura", "redaccion"),
             ("gracias", "redaccion"), ("¿Qué comida me recomiendas para hoy?", None),  # tema nuevo: duerme
             ("¿Cómo se usa merge en pandas?", "codigo"), ("¿Cuál es la diferencia entre porque y por qué?", "redaccion"),
             ("¿Quién fue Gabriela Mistral?", None), ("Ejecuta: sum([x*x for x in range(1, 6)])", "codigo"), ("ok", "codigo"),
             ("cuéntame más", None), ("Explícame el dequeísmo", "redaccion")]
    e, ok = Enrutador(), True
    print("\nGuion multi-dominio (mensaje -> experto):")
    for m, esperado in guion:
        r = e.paso(m)
        ok &= r == esperado and r in ETIQ
        print(f"  {m[:60]!r:64s} -> {r}  {'' if r == esperado else '(esperado ' + str(esperado) + ')'}")
    print("guion multi-dominio correcto:", ok)


if __name__ == "__main__":
    evaluar()


# ---------------------------------------------------------------- enrutador v2 (núcleo v2c; v1 no cambia)
_ARTICULOS_V2 = r"(?:un |una |el |la |los |las )?"
_MARCOS_V2 = [re.compile(p) for p in (
    r"(?:podrias|puedes) (?:explicarme|aclararme|contarme|decirme|resumirme)(?: que (?:es|significa))? (.+)",
    r"necesito (?:entender|comprender|saber que es|que me expliques) (.+)",
    r"(?:cuentame|dime|hablame|explicame)(?: con calma)? (?:que es|que significa|sobre|de que trata|de|algo sobre) (.+)",
    r"(.+?) ?: ?que es", r"que (?:quiere decir|significa|es|se entiende por|se quiere decir con) (?:la palabra )?(.+)",
    r"(?:ponme|dame|muestrame|tienes|quisiera) (?:un )?ejemplo de (.+)", r"(?:me explicas|me aclaras|ayuda con|ayudame con|explicame|ayudame a entender) (.+)",
    r"(?:quisiera|quiero|me gustaria) (?:saber que es|entender|repasar|aprender) (.+)", r"(?:no se|no tengo claro) (?:que es )?(.+?)(?:, me (?:explicas|ayudas))?", r"recuerdame (.+)")]
_CIERRES_V2 = re.compile(r"\s*(?:,? ?por favor|en codigo|en programacion|al programar|en python|en el codigo)$")
_PISTA_CODIGO_V2 = re.compile(r"\b(en codigo|en programacion|al programar|en el codigo|de programacion)\b")
_REDACCION_FRASES_V2 = [re.compile(p) for p in (
    r"\b(dilo|dimelo|hazlo|ponlo|escribelo|explicalo|dame una version|reformulalo|reformula esto|reescribe esto)\b.{0,30}\b(mas (claro|clara|claridad|facil|sencillo|sencilla|simple|corto|breve|formal|cercano|amable|conciso)|palabras (mas )?(simples|sencillas)|se entienda mejor|facil de (leer|entender))\b",
    r"\bmas (claro|clara) ?, por favor\b", r"\b(simplificalo|simplifica|aclara|aclarame) (esto|este texto|el texto|esta frase)\b", r"\bfaltas? de ortografia\b",
    r"\b(esta|estan) (bien|mal) escrit[oa]s?\b", r"\bcorrige (esto|este|esta|mi)\b")]
_LEX = {}


def _lexicos_v2():
    """Términos de conceptos de programación y de gramática del ENTRENAMIENTO de los expertos (nunca de evaluación)."""
    if not _LEX:
        cod, gram = set(), set()
        for archivo, destino, sufijo, tipos in (("experto_train_B2.jsonl", cod, "programacion", ("concepto", "concepto_ejemplo")),
                                                 ("redaccion_train.jsonl", gram, "gramatica", ("gramatica", "gramatica_ejemplo"))):
            ruta = RAIZ / "datos" / archivo
            if ruta.exists():
                for linea in open(ruta, encoding="utf-8"):
                    r = json.loads(linea)
                    if r["tipo"] in tipos and r.get("consulta"):
                        t = _n(r["consulta"]).strip()
                        destino.add(t.removesuffix(" " + sufijo).strip())
        gram |= {_n(f[0]) for f in FICHAS_GRAMATICA}
        _LEX["codigo"], _LEX["gram"] = cod - {""}, gram - {""}
    return _LEX["codigo"], _LEX["gram"]


def _termino_v2(mensaje):
    n = _n(mensaje).strip(" ¿?¡!.\n")
    for m in _MARCOS_V2:
        g = m.fullmatch(n)
        if g:
            t = _CIERRES_V2.sub("", g.group(1)).strip()
            return re.sub(r"^(?:un|una|el|la|los|las) ", "", t), n
    return None, n


class EnrutadorV2(Enrutador):
    """Enrutador para el núcleo v2c: las mismas reglas de v1 + formulaciones naturales que antes se escapaban a charla.

    Código: pregunta de definición («¿Podrías explicarme X?», «Necesito entender X», «¿Qué quiere decir X en código?», «Cuéntame qué es X», «X: ¿qué es?»,
    «Ponme un ejemplo de X») donde X es un concepto de programación conocido o la frase trae una pista («en código», «al programar»): +3.
    Redacción: reescrituras de tono/claridad («Dilo de forma más clara», «Hazlo más fácil de leer»…), faltas de ortografía y definiciones de gramática conocidas: +3.
    Los negativos de v1 (listas de compras, «¿Qué es un árbol genealógico?»…) no cambian: X debe estar en el léxico de entrenamiento o llevar pista explícita."""

    @staticmethod
    def puntajes(mensaje):
        sc = Enrutador.puntajes(mensaje)
        cod, gram = _lexicos_v2()
        t, n = _termino_v2(mensaje)
        if t:
            if t in cod or _PISTA_CODIGO_V2.search(n):
                sc["codigo"] += 3
            if t in gram:
                sc["redaccion"] += 3
        if any(p.search(n) for p in _REDACCION_FRASES_V2):
            sc["redaccion"] += 3
        return sc
