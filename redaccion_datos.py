"""Genera el dataset del experto de redacción (experto_redaccion.lora). Etapa 3, paso 2.

Todo lo que el experto debe escribir se VERIFICA por construcción (sin LLM ni red): las correcciones parten de oraciones reales
del corpus en español a las que se les introducen errores conocidos, así que la respuesta correcta es la oración original.

Dominios y proporciones (sobre --total):
  ortografia 30 %  «Corrige…»: tildes perdidas, h omitida, b/v cambiadas, ¿ ¡ ausentes, sin punto final, sin mayúscula inicial
                   (10 % de ese cupo ya está bien escrito: R: «El texto ya está bien escrito.», para no inventar errores)
  tono       28 %  formal (plantillas informal -> formal), conciso (quitar muletillas), claro (conectores rebuscados -> simples),
                   cercano (formal -> cotidiano)
  gramatica  20 %  Opción B: B: «<tema> gramática» -> base local de fichas (redaccion_fichas.py) -> R: copiar la regla / el ejemplo
  cola        6 %  temas poco comunes: B: -> «Sin resultados.» -> R: abstención (los resultados reales de ddgs se agregan en el paso siguiente)
  repaso     12 %  conversación, hechos y abstención de la Etapa 1, para no degradar el núcleo
(el 4 % restante son duplicados de la cuota de ortografía «ya está bien»).

Presupuesto de contexto (512 tokens): igual que el experto de código; lo que no cabe se DESCARTA, nunca se trunca.
Evaluación: oraciones de la última décima parte del corpus, fichas y temas reservados por hash y formulaciones distintas.

  python redaccion_datos.py [--total 12000]
"""
import argparse
import json
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

from experto_datos import _relevante, completar, fila, muestrear
from protocolo import SIN_INFO, TOPE_EXPERTO, Formato
from redaccion_fichas import (COLA_GRAMATICA, FICHAS_GRAMATICA, FRASES_ANTI_RELLENO, SIMPLIFICACIONES, es_eval, linea_ficha_gramatica)
from herramientas import SIN_RESULTADOS, _limpio, formatear_resultados, preparar_resultados
from sft_datos import primera_oracion

RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
YA_BIEN = "El texto ya está bien escrito."
TOPE_REDACCION = 360  # tope estricto de tokens por ejemplo completo (contexto de 512)

# ---------------------------------------------------------------- preguntas
Q_ORT_TRAIN = ["Corrige la ortografía: {x}", "Corrige este texto: {x}", "Arregla los errores de este texto: {x}",
               "Revisa la ortografía y la puntuación: {x}", "Corrige esto, por favor: {x}"]
Q_ORT_EVAL = ["Corrígeme este texto: {x}", "¿Puedes corregir lo siguiente? {x}", "Revisa y corrige: {x}"]
Q_FORMAL_TRAIN = ["Hazlo más formal: {x}", "Reescribe en tono formal: {x}", "Pasa a un tono formal: {x}"]
Q_FORMAL_EVAL = ["Escríbelo de forma más formal: {x}", "Dale un tono formal: {x}"]
Q_CERCANO_TRAIN = ["Hazlo más cercano: {x}", "Reescribe en tono cotidiano: {x}"]
Q_CERCANO_EVAL = ["Escríbelo de manera más informal: {x}"]
Q_CONCISO_TRAIN = ["Hazlo más conciso: {x}", "Quita lo que sobra: {x}", "Reescríbelo más corto: {x}"]
Q_CONCISO_EVAL = ["Acórtalo sin cambiar el sentido: {x}", "Hazlo más directo: {x}"]
Q_CLARO_TRAIN = ["Hazlo más claro: {x}", "Reescríbelo con palabras más simples: {x}", "Simplifica este texto: {x}"]
Q_CLARO_EVAL = ["Explícalo con más claridad: {x}", "Escríbelo de forma más sencilla: {x}"]
Q_GRAM_TRAIN = ["Explícame {u}.", "Dime cuál es la regla de {u} en español.", "Ayúdame con {u}.", "Háblame de {u} en español.",
                "¿Cómo funciona {u}?", "Quiero repasar {u}."]
Q_GRAM_EVAL = ["Necesito entender {u}.", "¿Podrías explicarme {u}?", "Recuérdame {u}."]
Q_GRAM_EJ_TRAIN = ["Dame un ejemplo de {u}.", "Muéstrame {u} con un ejemplo."]
Q_GRAM_EJ_EVAL = ["Ponme un ejemplo de {u}."]
Q_COLA = ["¿Qué es {n} en gramática?", "Explícame {n} en español.", "Háblame de {n} en lengua española."]
Q_COLA_EVAL = ["¿En qué consiste {n}?", "Necesito saber qué es {n} en español."]

# ---------------------------------------------------------------- oraciones del corpus
_SEP = re.compile(r"(?<=[.])\s+(?=[A-ZÁÉÍÓÚÑ])")
_MAL = re.compile(r"[\d()\[\]{}\"“”«»;:=/\\|_*&%$#@<>]|\bpág\b|\bvéase\b|\bp\.\s|\b[A-Z]\.", re.I)
_TILDE = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def oraciones_corpus(rng, n_max=60000):
    """(train, eval): oraciones limpias de 6 a 22 palabras; la última décima parte del corpus se reserva para evaluar."""
    texto = (DATOS / "corpus_es.txt").read_text(encoding="utf-8")
    corte = int(len(texto) * 0.9)
    salida = []
    for trozo in (texto[:corte], texto[corte:]):
        vistas, lista = set(), []
        for par in trozo.split("\n"):
            for o in _SEP.split(par.strip()):
                o = o.strip()
                p = o.split()
                if not (6 <= len(p) <= 22 and 45 <= len(o) <= 150) or _MAL.search(o) or not o.endswith(".") or not o[0].isupper():
                    continue
                if o[:40] in vistas:
                    continue
                vistas.add(o[:40])
                lista.append(o)
        rng.shuffle(lista)
        salida.append(lista[:n_max])
    return salida


PREGUNTAS_Y_EXCLAMACIONES = [
    "¿Cómo te llamas?", "¿Dónde vives?", "¿Qué hora es?", "¿Cuándo llegas a casa?", "¿Quién te ayudó con la tarea?", "¿Por qué no viniste ayer?",
    "¿Cuánto cuesta este libro?", "¿Puedes cerrar la ventana?", "¿Qué quieres comer hoy?", "¿Cuál es tu color favorito?", "¿Vamos al cine el sábado?",
    "¿Has terminado el informe?", "¿Con quién fuiste a la fiesta?", "¿Qué día es la reunión?", "¿Me prestas tu cuaderno?", "¿Cómo se llama tu hermana?",
    "¡Qué bonito día!", "¡Felicidades por tu cumpleaños!", "¡Cuidado con el escalón!", "¡Qué sorpresa verte aquí!", "¡No puedo creerlo!",
    "¡Gracias por tu ayuda!", "¡Bienvenidos a nuestra casa!", "¡Qué rico huele la comida!", "¡Por fin llegó el verano!", "¡Mucho éxito en tu examen!",
    "¿Dónde dejaste las llaves?", "¿Cuántos años tiene tu perro?", "¿Quieres un vaso de agua?", "¿Qué te pareció la película?",
    "¡Ven rápido, que empieza el partido!", "¡Qué frío hace esta mañana!", "¡Hasta luego, nos vemos mañana!", "¿Sabes cómo llegar al museo?",
]


def corromper(o, rng, solo=None):
    """Introduce 1-3 errores conocidos en la oración. Devuelve (texto_con_errores, tipos) o None si no se pudo cambiar nada."""
    ops = [solo] if solo else rng.sample(["tilde", "h", "bv", "punto", "mayus", "coma_espacio"], rng.randint(1, 3))
    t, hechos = o, []
    for op in ops:
        n = t
        if op == "tilde":
            palabras = t.split(" ")
            idx = [i for i, w in enumerate(palabras) if w != w.translate(_TILDE)]
            if idx:
                for i in rng.sample(idx, min(len(idx), rng.randint(1, 3))):
                    palabras[i] = palabras[i].translate(_TILDE)
                n = " ".join(palabras)
        elif op == "h":
            palabras = t.split(" ")
            idx = [i for i, w in enumerate(palabras) if re.match(r"^[hH][aeiouáéíóú]\w{2,}", w)]
            if idx:
                i = rng.choice(idx)
                palabras[i] = palabras[i][1:]
                if i == 0:
                    palabras[i] = palabras[i].capitalize()
                n = " ".join(palabras)
        elif op == "bv":
            palabras = t.split(" ")
            idx = [i for i, w in enumerate(palabras) if len(w) > 4 and re.search(r"[bv]", w) and w.lower() not in ("también", "porque")]
            if idx:
                i = rng.choice(idx)
                w = palabras[i]
                posiciones = [j for j, c in enumerate(w) if c in "bv"] or [j for j, c in enumerate(w.lower()) if c in "bv"]
                j = rng.choice(posiciones)
                palabras[i] = w[:j] + ("v" if w[j] in "bB" else "b") + w[j + 1:]
                n = " ".join(palabras)
        elif op == "punto" and t.endswith((".", "?", "!")):
            n = t[:-1]
        elif op == "mayus" and t[0].isupper():
            n = t[0].lower() + t[1:]
        elif op == "coma_espacio" and ", " in t:
            n = t.replace(", ", " ,", 1)
        elif op == "inicio" and t[0] in "¿¡":
            n = t[1:]
        if n != t:
            t, hechos = n, hechos + [op]
    return (t, hechos) if t != o else None


# ---------------------------------------------------------------- tono
OBJETOS = ["el informe", "los documentos", "la factura", "el contrato", "la presentación", "el presupuesto", "las fotos", "el archivo",
           "la cotización", "el calendario", "las cifras", "el borrador", "la lista de asistentes", "el acta", "los resultados",
           "el cronograma", "la agenda", "el reporte mensual", "la propuesta", "los planos", "el certificado", "la reserva", "el pedido",
           "la tarea", "el examen", "las notas", "el manual", "la receta", "el plan de trabajo", "los comprobantes", "la inscripción",
           "el formulario", "la carta", "las instrucciones", "el diseño", "el boletín", "la minuta", "el balance", "los pagos pendientes",
           "la solicitud", "el expediente", "el catálogo", "la muestra", "los datos", "el itinerario"]
CUANDO = ["hoy", "mañana", "el lunes", "esta tarde", "el viernes", "esta semana", "el martes por la mañana", "a primera hora",
          "después del almuerzo", "el próximo miércoles"]
PLANTILLAS_FORMAL = [  # (cotidiano, formal); ninguna conjuga un verbo que dependa del número de {o}
    ("Oye, mándame {o} cuando puedas.", "Le solicito que me envíe {o} cuando le sea posible."),
    ("Necesito {o} ya.", "Requiero {o} a la brevedad posible."),
    ("No puedo ir {c}, lo siento.", "Lamento informarle que no podré asistir {c}."),
    ("¿Me ayudas con {o}?", "¿Podría ayudarme con {o}, por favor?"),
    ("Avísame si hay algún problema con {o}.", "Le ruego que me informe si surge algún inconveniente con {o}."),
    ("Quiero hablar contigo sobre {o}.", "Desearía conversar con usted sobre {o}."),
    ("Te paso {o} {c}.", "Le haré llegar {o} {c}."),
    ("Perdón por la demora con {o}.", "Le ofrezco disculpas por la demora con {o}."),
    ("Revisa {o} y dime qué opinas.", "Le agradeceré que revise {o} y me comunique su opinión."),
    ("Mira {o}, creo que hay un error.", "Le sugiero revisar {o}, pues considero que contiene un error."),
    ("Gracias por enviar {o}.", "Le agradezco el envío de {o}."),
    ("Nos vemos {c} para ver {o}.", "Le propongo reunirnos {c} para revisar {o}."),
    ("Dime cuándo tienes {o}.", "Le consulto cuándo dispondrá de {o}."),
    ("Oye, ¿puedes revisar {o} {c}?", "¿Sería tan amable de revisar {o} {c}?"),
    ("Ya terminé con {o}.", "Le informo que he concluido lo relacionado con {o}."),
    ("No entendí lo de {o}, ¿me explicas?", "No comprendí lo relativo a {o}; ¿podría explicármelo?"),
    ("Hay que cambiar {o}.", "Es necesario modificar {o}."),
    ("Mándame {o} por correo.", "Le solicito que me remita {o} por correo electrónico."),
    ("{c} no estoy.", "Le comunico que {c} no me encontraré disponible."),
    ("Quiero saber qué pasó con {o}.", "Quisiera conocer la situación de {o}."),
    ("Tengo una duda sobre {o}.", "Quisiera plantearle una consulta sobre {o}."),
    ("Dame {o} cuando termines.", "Le solicito que me entregue {o} una vez que concluya."),
    ("Cuéntame del avance de {o}.", "Le agradecería que me informara sobre el avance de {o}."),
    ("Te llamo {c} por {o}.", "Me comunicaré con usted {c} respecto de {o}."),
    ("Perdón, olvidé {o}.", "Le pido disculpas por haber olvidado {o}."),
    ("No recibí {o}.", "Le informo que no he recibido {o}."),
    ("Manda {o} otra vez, por favor.", "Le ruego que vuelva a enviar {o}."),
    ("Necesito cambiar {o}, ¿se puede?", "Quisiera modificar {o}; ¿sería posible?"),
    ("Estoy esperando {o}.", "Me encuentro a la espera de {o}."),
    ("Pásame {o} {c}, por fa.", "Le agradecería que me hiciera llegar {o} {c}."),
    ("No tengo {o}.", "No dispongo de {o}."),
    ("Estoy revisando {o} ahora.", "En este momento me encuentro revisando {o}."),
    ("Vamos a entregar {o} {c}.", "Hemos previsto entregar {o} {c}."),
    ("¿Tienes tiempo {c}? Quiero ver {o}.", "¿Dispone de tiempo {c}? Quisiera revisar {o} con usted."),
    ("Confírmame si recibiste {o}.", "Le ruego confirmar la recepción de {o}."),
    ("Ayúdame a preparar {o}.", "Le solicito su colaboración para preparar {o}."),
    ("Eso de {o} no me convence.", "Tengo reservas respecto de {o}."),
]


def pares_formal(rng, reservar):
    """Todos los pares únicos (cotidiano, formal) mezclados; `reservar` separa objetos/momentos de evaluación por hash."""
    objs = [o for o in OBJETOS if es_eval(o) == reservar]
    cuand = [c for c in CUANDO if es_eval(c) == reservar] or CUANDO
    out = set()
    for a, b in PLANTILLAS_FORMAL:
        for o in objs:
            for c in (cuand if "{c}" in a else [None]):
                out.add(tuple(x.format(o=o, c=c).replace(" de el ", " del ").replace(" a el ", " al ") for x in (a, b)))
    out = sorted(out)
    rng.shuffle(out)
    return out


def con_relleno(o, rng):
    f = rng.choice(FRASES_ANTI_RELLENO)
    cuerpo = o[0].lower() + o[1:]
    if rng.random() < 0.5:
        return f"{f[0].upper() + f[1:]}, {cuerpo}"
    if "," in o:  # relleno en medio: tras la primera coma
        a, b = o.split(",", 1)
        return f"{a}, {f},{b}"
    return f"{f[0].upper() + f[1:]}, {cuerpo}"


def simplificar(o):
    """Cambia conectores rebuscados por simples. Devuelve None si la oración no contiene ninguno."""
    t = o
    for dificil, simple in SIMPLIFICACIONES:
        if dificil in ("sin embargo", "no obstante"):
            nuevo = re.sub(rf"^{dificil.capitalize()},?\s+", "Pero ", t)
            nuevo = re.sub(rf",?\s*\b{dificil},?\s+", ", pero ", nuevo)
        else:
            nuevo = re.sub(rf"\b{dificil}\b", simple, t)
            nuevo = re.sub(rf"\b{dificil.capitalize()}\b", simple.capitalize(), nuevo)
        t = nuevo
    return None if t == o else t


# ---------------------------------------------------------------- gramática (Opción B, base local)
def _resultado_local(rng, ficha):
    lineas = [linea_ficha_gramatica(ficha, True)]
    if rng.random() < 0.4:
        otra = rng.choice([f for f in FICHAS_GRAMATICA if f[0] != ficha[0]])
        lineas.insert(rng.randint(0, 1), linea_ficha_gramatica(otra, False))
    return "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lineas))


def filas_gramatica(rng, reservadas, q_def, q_ej):
    out = []
    for f in FICHAS_GRAMATICA:
        nombre, u, regla, ejemplo = f
        if es_eval(nombre) != reservadas:
            continue
        for p in q_def:
            out.append(fila("gramatica", "gramatica_reservada" if reservadas else "gramatica", p.format(u=u), regla, f"{nombre} gramática",
                            _resultado_local(rng, f), "B", TOPE_EXPERTO, local=True))
        if ejemplo:
            for p in q_ej:
                out.append(fila("gramatica", "gramatica_ejemplo", p.format(u=u), f"Por ejemplo: {ejemplo}", f"{nombre} gramática",
                                _resultado_local(rng, f), "B", TOPE_EXPERTO, local=True))
    return out


def filas_cola(fmt, reservadas):
    """Temas de gramática poco comunes con resultados REALES de ddgs (misma limpieza que herramientas.py):
    si algún resultado trata el tema, la respuesta es su primera oración; si no, abstención. Los temas inventados siempre abstienen."""
    out, desc = [], Counter()
    crudo = DATOS / "ddgs_redaccion_raw.jsonl"
    if not crudo.exists():
        print("  (sin datos/ddgs_redaccion_raw.jsonl: la cola entrena solo con «Sin resultados.»)")
        return filas_cola_vacia(reservadas)
    for l in open(crudo, encoding="utf-8"):
        d = json.loads(l)
        if es_eval(d["item"]) != reservadas:
            continue
        falsa = d["tipo"] == "falsa"
        lista = preparar_resultados(d["crudos"], permitir_ingles=False)[:3]
        for x in lista:
            x["body"] = _limpio(x["body"], 150)
        rel = [i for i, x in enumerate(lista) if _relevante(x, d["item"], falsa)]
        qs = Q_COLA_EVAL if reservadas else Q_COLA
        preguntas = [q.format(n=d["item"]) for q in qs]
        resultados = formatear_resultados(lista, max_frag=150) if lista else SIN_RESULTADOS
        if falsa and rel:
            desc["inventado con coincidencia"] += 1
            continue
        if d["tipo"] == "ficha" and not rel:
            continue  # de las fichas locales solo sirven las búsquedas con respuesta real (las demás ya se entrenan con la base local)
        if not rel:  # nada relevante (o nada de nada): abstención honesta con los resultados reales que haya
            while lista and len(fmt.texto(" " + resultados)) > TOPE_EXPERTO:
                lista = lista[:-1]
                resultados = formatear_resultados(lista, max_frag=150) if lista else SIN_RESULTADOS
            tipo = "cola_inexistente" if falsa else "cola_abst"
            out += [fila("cola", tipo, p, SIN_INFO, d["consulta"], resultados, "B", TOPE_EXPERTO, real=True) for p in preguntas]
            continue
        i0 = rel[0]
        frase = primera_oracion(lista[i0]["body"])
        if not frase or not 25 <= len(frase) <= 140:
            desc["sin oración utilizable"] += 1
            continue
        k = len(lista)
        while k > i0 + 1 and len(fmt.texto(" " + formatear_resultados(lista[:k], max_frag=150))) > TOPE_EXPERTO:
            k -= 1
        resultados = formatear_resultados(lista[:k], max_frag=150)
        if len(fmt.texto(" " + resultados)) > TOPE_EXPERTO or frase not in resultados:
            desc["no cabe"] += 1
            continue
        out += [fila("cola", "cola_ok", p, frase, d["consulta"], resultados, "B", TOPE_EXPERTO, real=True) for p in preguntas]
    print(f"  cola ({'evaluación' if reservadas else 'entrenamiento'}): {dict(Counter(r['tipo'] for r in out))}; descartados: {dict(desc)}")
    return out


def filas_cola_vacia(reservadas):
    return [fila("cola", "cola_sin_resultados", p.format(n=n), SIN_INFO, f"{n} gramática", SIN_RESULTADOS, "B", TOPE_EXPERTO)
            for n in COLA_GRAMATICA if es_eval(n) == reservadas for p in Q_COLA]


# ---------------------------------------------------------------- ensamblado
def filas_edicion(rng, oraciones, n_ort, n_formal, n_cercano, n_conciso, n_claro, q, reservar):
    ort, tono = [], []
    ya_bien = int(n_ort * 0.10)
    for o in oraciones:
        if len(ort) >= n_ort:
            break
        if len(ort) < ya_bien:
            ort.append(fila("ortografia", "ortografia_ok", rng.choice(q["ort"]).format(x=o), YA_BIEN))
            continue
        c = corromper(o, rng)
        if c:
            ort.append(fila("ortografia", "ortografia", rng.choice(q["ort"]).format(x=c[0]), o, tipos=c[1]))
    for o in rng.sample(PREGUNTAS_Y_EXCLAMACIONES, len(PREGUNTAS_Y_EXCLAMACIONES)):
        if es_eval(o) != reservar:
            continue
        c = corromper(o, rng, solo="inicio") or corromper(o, rng, solo="mayus")
        if c:
            for _ in range(2 if not reservar else 1):
                ort.append(fila("ortografia", "ortografia_signos", rng.choice(q["ort"]).format(x=c[0]), o, tipos=c[1]))
    pares = pares_formal(rng, reservar)  # formal y cercano usan pares distintos (no se repite la misma oración)
    for coti, formal in pares[:n_formal]:
        tono.append(fila("tono", "tono_formal", rng.choice(q["formal"]).format(x=coti), formal))
    for coti, formal in pares[n_formal : n_formal + n_cercano]:
        tono.append(fila("tono", "tono_cercano", rng.choice(q["cercano"]).format(x=formal), coti))
    it = iter(oraciones[n_ort * 2:])
    for o in it:
        if sum(r["tipo"] == "tono_conciso" for r in tono) >= n_conciso:
            break
        tono.append(fila("tono", "tono_conciso", rng.choice(q["conciso"]).format(x=con_relleno(o, rng)), o))
    for o in oraciones:
        if sum(r["tipo"] == "tono_claro" for r in tono) >= n_claro:
            break
        s = simplificar(o)
        if s:
            tono.append(fila("tono", "tono_claro", rng.choice(q["claro"]).format(x=o), s))
    return ort, tono


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=12000)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--sufijo", default="")
    args = ap.parse_args()
    rng = random.Random(args.semilla)
    fmt = Formato()
    N = args.total
    tr_or, ev_or = oraciones_corpus(rng)
    print(f"oraciones del corpus: {len(tr_or):,} entrenamiento, {len(ev_or):,} evaluación")
    # las oraciones con conectores rebuscados son raras: se buscan primero para que alcancen
    tr_claras = [o for o in tr_or if simplificar(o)]
    ev_claras = [o for o in ev_or if simplificar(o)]
    print(f"  con conectores simplificables: {len(tr_claras)} / {len(ev_claras)}")

    qtr = dict(ort=Q_ORT_TRAIN, formal=Q_FORMAL_TRAIN, cercano=Q_CERCANO_TRAIN, conciso=Q_CONCISO_TRAIN, claro=Q_CLARO_TRAIN)
    qev = dict(ort=Q_ORT_EVAL, formal=Q_FORMAL_EVAL, cercano=Q_CERCANO_EVAL, conciso=Q_CONCISO_EVAL, claro=Q_CLARO_EVAL)
    ort_tr, tono_tr = filas_edicion(rng, tr_claras[:0] + tr_or, int(N * 0.30), int(N * 0.08), int(N * 0.07), int(N * 0.08), 0, qtr, False)
    # el cupo de «claro» sale de las oraciones simplificables (las primeras pasadas por el filtro)
    tono_tr += [fila("tono", "tono_claro", rng.choice(Q_CLARO_TRAIN).format(x=o), simplificar(o)) for o in tr_claras[: int(N * 0.06)]]
    ort_ev, tono_ev = filas_edicion(random.Random(args.semilla + 1), ev_or, 120, 60, 40, 40, 0, qev, True)
    tono_ev += [fila("tono", "tono_claro", rng.choice(Q_CLARO_EVAL).format(x=o), simplificar(o)) for o in ev_claras[:40]]

    gram_tr = filas_gramatica(rng, False, Q_GRAM_TRAIN, Q_GRAM_EJ_TRAIN)
    gram_ev = filas_gramatica(rng, True, Q_GRAM_EVAL, Q_GRAM_EJ_EVAL) + filas_gramatica(rng, False, Q_GRAM_EVAL, Q_GRAM_EJ_EVAL)[:150]
    cola_tr, cola_ev = filas_cola(fmt, False), filas_cola(fmt, True)
    repaso = [json.loads(l) for l in open(DATOS / "sft_train.jsonl", encoding="utf-8")]
    for r in repaso:
        r["dominio"] = "repaso"

    train = (ort_tr[: int(N * 0.30)] + [r for r in tono_tr if r["tipo"] != "tono_claro"] + [r for r in tono_tr if r["tipo"] == "tono_claro"] +
             muestrear(gram_tr, int(N * 0.20), rng) + (cola_tr if len(cola_tr) <= int(N * 0.08) else rng.sample(cola_tr, int(N * 0.08))) + rng.sample(repaso, int(N * 0.12)))
    rng.shuffle(train)
    evaluacion = ort_ev + tono_ev + gram_ev + cola_ev

    train, desc_tr = completar(train, fmt)
    evaluacion, desc_ev = completar(evaluacion, fmt)
    largos = [r for r in train + evaluacion if r["tokens"] > TOPE_REDACCION]
    train = [r for r in train if r["tokens"] <= TOPE_REDACCION]
    evaluacion = [r for r in evaluacion if r["tokens"] <= TOPE_REDACCION]
    desc_tr += len(largos)
    print(f"descartados por superar {TOPE_REDACCION} tokens: {len(largos)}")
    for nombre, filas in (("redaccion_train" + args.sufijo, train), ("redaccion_eval" + args.sufijo, evaluacion)):
        with open(DATOS / f"{nombre}.jsonl", "w", encoding="utf-8") as f:
            for r in filas:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def resumen(nombre, filas, desc):
        t = sorted(r["tokens"] for r in filas if "tokens" in r)
        print(f"\n{nombre}: {len(filas):,} ejemplos (descartados por exceder 440 tokens: {desc})")
        print("  dominios:", dict(Counter(r["dominio"] for r in filas)))
        print("  tipos:   ", dict(Counter(r["tipo"] for r in filas)))
        if t:
            print(f"  tokens por ejemplo: media {sum(t) / len(t):.0f}, p95 {t[int(len(t) * .95)]}, máximo {t[-1]} (contexto 512)")

    resumen("redaccion_train", train, desc_tr)
    resumen("redaccion_eval", evaluacion, desc_ev)
    vistos = {r["pregunta"] for r in train}
    print("\nfiltración train/eval (preguntas idénticas):", sum(r["pregunta"] in vistos for r in evaluacion))
    for tipo in ("ortografia", "tono_formal", "tono_cercano", "tono_conciso", "tono_claro", "gramatica", "cola_ok", "cola_abst", "cola_inexistente"):
        e = next((r for r in train if r["tipo"] == tipo), None)
        if e:
            print(f"\n[{tipo}] P: {e['pregunta'][:140]}\n        R: {e['respuesta'][:140]}")


if __name__ == "__main__":
    main()
