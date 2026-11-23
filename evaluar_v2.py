"""Evaluación del núcleo v2 por el camino de producción (motor C++ con el .bin exportado), con las mismas pruebas que v1.

  python evaluar_v2.py modelos/experimentos/nucleo_v2_sft.bin [--n 300]

Mide:
  1. Etapa 1 (ddgs real, datos/sft_eval_real.jsonl): hechos (respuesta exacta), abstención (irrelevante / vacío). Línea base v1: 71,6 % / 98,1 %.
  2. Charla (datos/v2/sft/sft_eval.jsonl, tipo «charla», frases reservadas): no busca y responde con una de las respuestas válidas de su intención.
     La conversación de v1 era 18 saludos exactos (100 %); la de v2 es más amplia, no comparable palabra por palabra.
  3. Simulado con artículos reservados (datos/v2/sft/sft_eval.jsonl): buscar_ok / irrelevante / vacio.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from inferir import _texto, evaluar, generar_lote
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2
import charla_v2

RAIZ = Path(__file__).parent


EQUIVALENTES = [{"saludo", "buenos_dias", "buenas_tardes", "buenas_noches"}, {"afirmacion", "estado_usuario_bien"}, {"nombre", "quien_eres"}]


def frases_charla_unicas():
    """Cada frase base reservada UNA vez (me_llamo con 3 nombres): lista de dicts {intencion, pregunta}."""
    filas = []
    for i, (fs, _) in charla_v2.INTENCIONES.items():
        for f in fs:
            if charla_v2.es_eval(f):
                for n in (charla_v2.NOMBRES[:3] if "{n}" in f else [None]):
                    filas.append({"intencion": i, "pregunta": f.format(n=n) if n else f})
    return filas


def evaluar_charla(motor, fmt, filas=None, n=0):
    """Una vez por frase única reservada. Estricta: la respuesta es de la intención correcta; con equivalentes: acepta intenciones
    naturalmente intercambiables (saludos entre sí, afirmación/«estoy bien», nombre/quién eres). Métrica principal: media por intención."""
    filas = filas or frases_charla_unicas()
    validas = {i: set(r) for i, (_, r) in charla_v2.INTENCIONES.items()}

    def quien(t):
        return [i for i, v in validas.items() if t in v or any("{n}" in x and t.startswith(x.split("{n}")[0]) for x in v)]

    por = {}
    malas, buscaron, fugas = [], 0, 0
    for a in range(0, len(filas), 50):
        grupo = filas[a:a + 50]
        sal = generar_lote(motor, fmt, [fmt.ids_prompt(r["pregunta"]) for r in grupo], "cpu", 1.1)
        for r, (nuevo, parada) in zip(grupo, sal):
            d = por.setdefault(r["intencion"], {"n": 0, "estricta": 0, "equiv": 0})
            d["n"] += 1
            if parada == fmt.herramienta:
                buscaron += 1
                continue
            t = _texto(fmt, nuevo).removeprefix("R:").strip()
            fugas += any(x in t for x in ("B:", "E:", "<|"))
            q = quien(t)
            eq = next((g for g in EQUIVALENTES if r["intencion"] in g), {r["intencion"]})
            d["estricta"] += r["intencion"] in q
            d["equiv"] += bool(eq & set(q))
            if not (eq & set(q)) and len(malas) < 12:
                malas.append((r["intencion"], r["pregunta"], t, q))
    N = len(filas)
    macro = lambda k: sum(d[k] / d["n"] for d in por.values()) / len(por)
    return {"n_frases": N, "no_busco": 1 - buscaron / N, "fugas": fugas,
            "estricta_micro": sum(d["estricta"] for d in por.values()) / N, "estricta_macro": macro("estricta"),
            "equivalentes_micro": sum(d["equiv"] for d in por.values()) / N, "equivalentes_macro": macro("equiv"),
            "por_intencion": {i: round(d["equiv"] / d["n"], 3) for i, d in sorted(por.items(), key=lambda x: x[1]["equiv"] / x[1]["n"])},
            "respuesta_valida": sum(d["equiv"] for d in por.values()) / N, "ejemplos_malos": malas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--eval_sft", default="sft_eval.jsonl", help="archivo de datos/v2/sft/ con la evaluación simulada")
    ap.add_argument("--solo_charla", action="store_true")
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "ETAPA4_eval_v2.json"))
    a = ap.parse_args()
    fmt = FormatoV2()
    motor = MotorCpp(a.bin)
    t0 = time.time()
    res = {"bin": a.bin}
    a.salida = a.salida if not a.solo_charla else str(Path(a.salida).with_name("ETAPA4_charla_v2.json"))
    if not a.solo_charla:
        print("== 1. Etapa 1 · ddgs real (línea base v1: hechos 71,6 %, abstención 98,1 %)", flush=True)
        res["real"] = evaluar(motor, fmt, "cpu", ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=a.n, penalizacion=1.1)
        for t, m in res["real"].items():
            print(f"  {t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()), flush=True)
        ev = [json.loads(l) for l in open(RAIZ / "datos" / "v2" / "sft" / a.eval_sft, encoding="utf-8")]
        sim = [r for r in ev if r["tipo"] != "charla"]
        tmp = RAIZ / "datos" / "v2" / "sft" / "_tmp_eval_sim.jsonl"
        tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sim), encoding="utf-8")
        print("== 2. Simulado con artículos reservados", flush=True)
        res["simulado"] = evaluar(motor, fmt, "cpu", ruta=tmp, n_por_tipo=a.n, penalizacion=1.1)
        tmp.unlink()
        for t, m in res["simulado"].items():
            print(f"  {t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()), flush=True)
    print("== 3. Charla de TEST-IA (frases reservadas)", flush=True)
    res["charla"] = evaluar_charla(motor, fmt)
    c = res["charla"]
    print(f"  {c['n_frases']} frases únicas | no busca {c['no_busco']:.1%} | fugas {c['fugas']} | estricta micro {c['estricta_micro']:.1%} macro {c['estricta_macro']:.1%} | con equivalentes micro {c['equivalentes_micro']:.1%} macro {c['equivalentes_macro']:.1%}", flush=True)
    for i_, p, t, q_ in res["charla"]["ejemplos_malos"]:
        print(f"    mal [{i_}]: {p!r} -> {t!r} ({q_})", flush=True)
    res["segundos"] = round(time.time() - t0)
    Path(a.salida).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo en {res['segundos']} s -> {a.salida}", flush=True)


if __name__ == "__main__":
    main()
