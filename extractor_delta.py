"""Experto de extracción en formato DELTA: el núcleo contesta solo LO QUE CAMBIA respecto al estado anterior ("-" si nada).
El prompt es el mismo de extractor_datos (estado anterior + mensajes + pregunta); la respuesta es la diferencia, no el estado completo.

  python extractor_delta.py datos             # construye datos/extractor_delta/{train,eval}.jsonl
  python extractor_delta.py eval --lora ...   # evalúa (aplica el delta al estado anterior y compara con el estado final de Mistral)
"""
import argparse
import collections
import json
import time
from pathlib import Path

import extractor_datos as E
import extractor_eval as V

RAIZ = Path(__file__).parent
SAL = RAIZ / "datos" / "extractor_delta"
CLAVES_P = ("postura", "soporte", "dormido", "sujecion", "accion", "gesto", "objetos")


def _req(par):
    return json.loads(par["request"]) if isinstance(par.get("request"), str) else par["request"]


def _previo(par, q):
    """Estado anterior en el mismo formato de campos que la etiqueta."""
    req = _req(par)
    ps = req.get("previousState") or {}
    if q in ("char", "user"):
        p = ps.get(q) or {}
        return E._persona({"posture": p.get("posture", "unspecified"), "support": p.get("support", ""), "asleep": p.get("asleep"), "restraint": p.get("restraint", ""),
                           "action": p.get("action", ""), "expression": p.get("expression", ""), "heldObjects": []})
    contactos = [{k: v for k, v in c.items() if k != "index"} for c in req.get("previousContacts") or []]
    return f"disposicion={ps.get('arrangement', 'unspecified')} | contactos={E._contactos(contactos)}"


def _campos(texto):
    return {k.strip(): v.strip() for k, _, v in (t.partition("=") for t in texto.split(" | ")) if k.strip()}


def delta(par, q):
    if q == "escena":
        return E.respuesta(par, q)
    nuevo, viejo = _campos(E.respuesta(par, q)), _campos(_previo(par, q))
    cambios = [f"{k}={v}" for k, v in nuevo.items() if viejo.get(k) != v]
    return " | ".join(cambios) if cambios else "-"


def aplicar(par, q, texto):
    """Estado final = estado anterior + delta (lo que el núcleo no menciona se queda igual)."""
    if q == "escena":
        return E.parsear(q, texto)
    campos = _campos(_previo(par, q))
    if E._limpio(texto) not in ("", "-"):
        campos.update(_campos(E._limpio(texto)))
    return E.parsear(q, " | ".join(f"{k}={v}" for k, v in campos.items()))


def construir():
    pares = E.cargar(str(RAIZ / "datos" / "extractor" / "pares.jsonl"))
    train, ev = E.partir(pares, 0.15)
    SAL.mkdir(parents=True, exist_ok=True)
    cambian = collections.Counter()
    with open(SAL / "train.jsonl", "w", encoding="utf-8") as f:
        for par in train:
            for q in E.PREGUNTAS:
                r = delta(par, q)
                cambian[q] += r != "-"
                f.write(json.dumps({"tipo": f"extraccion_{q}", "pregunta": E.prompt(par, q), "respuesta": r, "pregunta_id": q}, ensure_ascii=False) + "\n")
    print(len(train), "turnos de entrenamiento |", len(ev), "de evaluación | respuestas con cambio:", dict(cambian))


def evaluar(a):
    from inferir import _texto, generar_lote
    from motor_cpp import MotorCpp
    from protocolo_v2 import FormatoV2
    pares = E.cargar(str(RAIZ / "datos" / "extractor" / "pares.jsonl"))
    _, ev = E.partir(pares, 0.15)
    fmt, motor = FormatoV2(), MotorCpp(str(RAIZ / "modelos" / "nucleo_v2c_sft.bin"))
    motor.cargar_lora(a.lora)
    acum, base, cuando = (collections.defaultdict(list) for _ in range(3))
    tiempos, ejemplos = [], []
    for par in ev:
        t0 = time.time()
        for q in E.PREGUNTAS:
            ids = fmt.ids_prompt(E.prompt(par, q)) + fmt.texto(" R:")
            nuevo, _ = generar_lote(motor, fmt, [ids], "cpu", 1.0, max_nuevos=120)[0]
            texto = _texto(fmt, nuevo)
            pred, oro = aplicar(par, q, texto), E.parsear(q, E.respuesta(par, q))
            V.comparar(q, pred, oro, acum)
            V.comparar(q, V.base_copiar(par, q), oro, base)
            real = delta(par, q)
            if q != "escena" and real != "-":  # solo los turnos donde ALGO cambió de verdad
                V.comparar(q, pred, oro, cuando)
            if len(ejemplos) < 14 and real != "-" and q != "escena":
                ejemplos.append({"q": q, "oro": real[:200], "pred": texto[:200]})
        tiempos.append(time.time() - t0)
    print(f"{len(ev)} turnos | {sum(tiempos) / len(tiempos):.1f} s/turno")
    print(f"{'campo':26s} {'experto':>8s} {'copiar':>8s} | solo turnos con cambio real: {'experto':>8s}")
    for k in sorted(acum):
        m = sum(acum[k]) / len(acum[k])
        b = sum(base[k]) / len(base[k]) if base.get(k) else 0
        c = f"{sum(cuando[k]) / len(cuando[k]):8.1%} (n={len(cuando[k])})" if cuando.get(k) else "      —"
        print(f"{k:26s} {m:8.1%} {b:8.1%} | {c}")
    print(json.dumps(ejemplos, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("datos", "eval"))
    ap.add_argument("--lora")
    a = ap.parse_args()
    construir() if a.modo == "datos" else evaluar(a)
