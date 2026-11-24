"""Evaluador PRIVADO del redactor determinista sobre TUS escenas (incluidas las explícitas): imprime solo agregados y números de línea; ningún texto de las escenas.
Los archivos de datos viven en `datos/escenas_privadas/` (ignorada por Git). Yo (el asistente) no necesito leerlos: lo ejecutas tú y me pasas los números.

Entrada: un .jsonl, una escena por línea, con la misma forma que usa b_chat (generateSceneImagePrompt):
  {"camera": "pov"|"high-angle-side"|…, "main": {"person": "woman", "wardrobe": "…"}, "partner": {…}?, "location": "…", "time": "…", "lighting": "…",
   "photography": {"viewpoint": "…", "gaze": "…"}, "situation": "MAIN_ADULT … PARTNER_ADULT …", "llm_prompt": "el prompt que escribió Mistral (opcional)"}
Se puede crear con tu pipeline (cualquier escena que quieras medir) o a mano.

  python evaluar_escenas_propias.py datos/escenas_privadas/mis_escenas.jsonl [--detalle datos/escenas_privadas/informe_local.json] [--ids-riesgo]

Qué mide (todo agregado):
  · cuántas cláusulas se descartan y por qué motivo (pasado, intención sin ejecutar, pedido, negación, postura del observador)
  · cuántas escenas traen señales de riesgo (ida y vuelta, posesivo ambiguo, palabras sin traducir) = las que habría que mandar a Mistral en un esquema híbrido
  · con `llm_prompt`: solapamiento de palabras de contenido con el prompt de Mistral (recall: cuánto de lo que dijo Mistral dice también el redactor; precisión: al revés).
    Es una medida de LÉXICO, no de calidad: un prompt distinto no es peor. Sirve para ver dónde divergen, y con --ids-riesgo qué líneas revisar a mano.
"""
import argparse
import collections
import json
import re
import statistics as st
import sys
import time
from pathlib import Path

from escena_prompt import componer, riesgos_escena

ESTILO = set("hyper realistic photograph view first person pov photo image picture natural skin texture pores shallow depth field lighting light room setting scene looking viewer".split())


def contenido(t):
    return {w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 3 and w not in ESTILO}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--detalle", default=None, help="escribe un informe LOCAL con el texto de cada escena (para que tú lo revises; no se imprime)")
    ap.add_argument("--ids-riesgo", action="store_true", help="lista los números de línea con señales de riesgo")
    ap.add_argument("--sin-ida-vuelta", action="store_true", help="omite la retraducción (más rápido)")
    a = ap.parse_args()
    ruta = Path(a.archivo)
    escenas = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
    motivos, ms, con_riesgo, por_motivo = collections.Counter(), [], [], collections.Counter()
    rec, pre, filas = [], [], []
    for n, esc in enumerate(escenas, 1):
        fuente = {k: v for k, v in esc.items() if k != "llm_prompt"}
        t0 = time.time()
        try:
            prompt, traza = componer(fuente)
        except Exception as e:  # una escena rara no debe tumbar la medición
            motivos["ERROR al componer"] += 1
            filas.append({"linea": n, "error": str(e)[:200]})
            continue
        ms.append((time.time() - t0) * 1000)
        for _, motivo in traza["descartadas"]:
            motivos[motivo] += 1
        riesgos = [] if a.sin_ida_vuelta else riesgos_escena(fuente, traza)
        if riesgos:
            con_riesgo.append(n)
            for m, _ in riesgos:
                por_motivo[m] += 1
        fila = {"linea": n, "prompt": prompt, "descartadas": traza["descartadas"], "riesgos": riesgos}
        if esc.get("llm_prompt"):
            a_, b_ = contenido(esc["llm_prompt"]), contenido(prompt)
            if a_ and b_:
                rec.append(len(a_ & b_) / len(a_))
                pre.append(len(a_ & b_) / len(b_))
                fila["recall"], fila["precision"] = round(rec[-1], 2), round(pre[-1], 2)
        filas.append(fila)
    n = len(escenas)
    print(f"{n} escenas | latencia media {st.mean(ms):.0f} ms por escena (CPU, sin GPU)" if ms else f"{n} escenas")
    print("cláusulas descartadas por motivo:", dict(motivos) or "ninguna")
    if not a.sin_ida_vuelta:
        print(f"escenas con señales de riesgo: {len(con_riesgo)}/{n} ({len(con_riesgo) / max(1, n):.0%}) | por motivo: {dict(por_motivo) or '—'}")
        print(f"escenas SIN señales (el redactor determinista bastaría): {n - len(con_riesgo)}/{n}")
        if a.ids_riesgo:
            print("líneas con riesgo:", con_riesgo)
    if rec:
        print(f"solapamiento léxico con tu prompt de Mistral ({len(rec)} escenas): recall medio {st.mean(rec):.0%} | precisión media {st.mean(pre):.0%}")
        malos = [f["linea"] for f in filas if f.get("recall", 1) < 0.4]
        print(f"escenas con recall < 40 % (revisar a mano): {len(malos)} -> líneas {malos[:30]}")
    if a.detalle:
        Path(a.detalle).write_text(json.dumps(filas, ensure_ascii=False, indent=1), encoding="utf-8")
        print("informe local con el texto de cada escena:", a.detalle, "(no lo subas a Git)")


if __name__ == "__main__":
    sys.exit(main())
