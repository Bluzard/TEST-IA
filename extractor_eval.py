"""Evalúa el experto de extracción de estado (núcleo v2c + LoRA) contra las etiquetas de Mistral+reducer en los turnos de evaluación (los últimos en el tiempo, no vistos al entrenar).

  python extractor_eval.py PARES.jsonl --lora modelos/experimentos/experto_extraccion_a_v2.lora [--n 120] [--salida resultados/ETAPA6_extraccion.json]

Mide por campo y, como referencia, la línea base trivial «copiar el estado anterior» (muchos campos no cambian de un turno a otro: el experto debe ganarle donde SÍ cambian).
También mide la latencia (4 preguntas por turno) para compararla con los 31-44 s de Mistral.
"""
import argparse
import collections
import json
import re
import time
from pathlib import Path

import extractor_datos as E
from inferir import _texto, generar_lote
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2

RAIZ = Path(__file__).parent


def toks(t):
    return re.findall(r"\w+", str(t).lower())


def f1(a, b):
    a, b = toks(a), toks(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    c = collections.Counter(a) & collections.Counter(b)
    n = sum(c.values())
    if not n:
        return 0.0
    p, r = n / len(b), n / len(a)
    return 2 * p * r / (p + r)


def tupla(c):
    return (c["actor"], c["act"], c.get("part") or "", c["target"], c.get("targetPart") or "")


def base_copiar(par, pregunta):
    """Predicción trivial: el estado ANTERIOR sin cambios (lo que ya está en el prompt)."""
    req = json.loads(par["request"])
    ps = req.get("previousState")
    if pregunta in ("char", "user"):
        p = (ps or {}).get(pregunta) or {}
        return {"posture": p.get("posture", "unspecified"), "support": p.get("support", ""), "asleep": bool(p.get("asleep")), "restraint": p.get("restraint", ""),
                "action": "", "expression": "", "heldObjects": []}
    if pregunta == "relacion":
        return {"arrangement": (ps or {}).get("arrangement", "unspecified"), "contacts": [{k: v for k, v in c.items() if k != "index"} for c in req.get("previousContacts") or []]}
    return {}


def comparar(pregunta, pred, oro, acum):
    def anota(campo, ok):
        acum[f"{pregunta}.{campo}"].append(float(ok))
    if pregunta in ("char", "user"):
        for campo in ("posture", "asleep"):
            anota(campo, pred.get(campo) == oro.get(campo))
        anota("support", E._limpio(pred.get("support")).lower() == E._limpio(oro.get("support")).lower())
        anota("restraint", bool(E._limpio(pred.get("restraint"))) == bool(E._limpio(oro.get("restraint"))))
        for campo in ("action", "expression"):
            anota(campo + "_F1", f1(oro.get(campo, ""), pred.get(campo, "")))
    elif pregunta == "relacion":
        anota("arrangement", pred.get("arrangement") == oro.get("arrangement"))
        a, b = {tupla(c) for c in oro.get("contacts", [])}, {tupla(c) for c in pred.get("contacts", [])}
        anota("contactos_exacto", a == b)
        anota("contactos_F1", 1.0 if not a and not b else (2 * len(a & b) / (len(a) + len(b)) if a or b else 1.0))
    else:
        anota("escena_exacta", {k: E._limpio(v).lower() for k, v in pred.items()} == {k: E._limpio(v).lower() for k, v in oro.items()})
        anota("escena_vacia_acierto", (not pred) == (not oro))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pares")
    ap.add_argument("--lora", default=None)
    ap.add_argument("--bin", default=str(RAIZ / "modelos" / "nucleo_v2c_sft.bin"))
    ap.add_argument("--n", type=int, default=120, help="turnos de evaluación (4 preguntas cada uno)")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--prop-eval", type=float, default=0.12)
    a = ap.parse_args()
    pares = E.cargar(a.pares)
    _, ev = E.partir(pares, a.prop_eval)
    ev = ev[: a.n]
    fmt, motor = FormatoV2(), MotorCpp(a.bin)
    if a.lora:
        motor.cargar_lora(a.lora)
    acum, base = collections.defaultdict(list), collections.defaultdict(list)
    tiempos, ejemplos, largos = [], [], []
    for par in ev:
        t0 = time.time()
        for q in E.PREGUNTAS:
            ids = fmt.ids_prompt(E.prompt(par, q)) + fmt.texto(" R:")
            largos.append(len(ids))
            nuevo, _ = generar_lote(motor, fmt, [ids], "cpu", 1.0, max_nuevos=190)[0]
            texto = _texto(fmt, nuevo)
            pred, oro = E.parsear(q, texto), E.parsear(q, E.respuesta(par, q))
            comparar(q, pred, oro, acum)
            comparar(q, base_copiar(par, q), oro, base)
            if len(ejemplos) < 12 and q in ("char", "relacion"):
                ejemplos.append({"pregunta": q, "oro": E.respuesta(par, q)[:300], "pred": texto[:300]})
        tiempos.append(time.time() - t0)
    resumen = {}
    print(f"{len(ev)} turnos de evaluación | latencia por turno (4 preguntas, CPU): media {sum(tiempos) / len(tiempos):.1f} s | prompt máx {max(largos)} tokens")
    print(f"{'campo':26s} {'experto':>8s} {'copiar-anterior':>16s}")
    for k in sorted(acum):
        m = sum(acum[k]) / len(acum[k])
        b = sum(base[k]) / len(base[k]) if base.get(k) else None
        resumen[k] = {"experto": round(m, 3), "base_copiar": None if b is None else round(b, 3), "n": len(acum[k])}
        print(f"{k:26s} {m:8.1%} {('—' if b is None else f'{b:16.1%}')}")
    if a.salida:
        Path(a.salida).write_text(json.dumps({"turnos": len(ev), "latencia_media_s": sum(tiempos) / len(tiempos), "campos": resumen, "ejemplos": ejemplos}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
