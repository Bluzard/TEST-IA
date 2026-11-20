"""Evaluación del experto de código sobre datos/experto_eval.jsonl (todo reservado: nunca visto al entrenar).

Mide por tipo (con las herramientas simuladas con los resultados reales guardados):
  concepto / concepto_ejemplo / error_interp   responde directo (R:) y exacto
  concepto_nuevo                               concepto NO entrenado: debe BUSCAR (B:), no inventar
  doc_ok                                       busca (B:) y copia la oración correcta (exacta y similitud >= 95 %)
  doc_abst, ejec_nameerror                     se abstiene / informa que el nombre no existe
  ejec_ok, ejec_error                          emite E: con el código copiado y interpreta la salida o el error
"puntaje" = promedio de la métrica principal de cada tipo (ver PRINCIPAL).
"""
import difflib
import json
from pathlib import Path

from inferir import generar_lote
from protocolo import Formato

RAIZ = Path(__file__).parent
PRINCIPAL = {"concepto_reservado": "exacta", "concepto": "exacta", "concepto_ejemplo": "exacta", "error_interp": "exacta", "concepto_nuevo": "busca",
             "doc_ok": "sim95", "doc_abst": "exacta", "ejec_nameerror": "exacta", "ejec_ok": "exacta", "ejec_error": "exacta",
             # experto de redacción (redaccion_eval.jsonl): los tipos de un conjunto no aparecen en el otro, así que no interfieren
             "ortografia": "exacta", "ortografia_ok": "exacta", "ortografia_signos": "exacta", "tono_formal": "exacta", "tono_cercano": "exacta",
             "tono_conciso": "exacta", "tono_claro": "exacta", "gramatica": "sim95", "gramatica_reservada": "sim95", "gramatica_ejemplo": "exacta",
             "cola_ok": "sim95", "cola_abst": "exacta", "cola_inexistente": "exacta", "cola_sin_resultados": "exacta"}


def _texto(fmt, ids):
    return fmt.tok.decode([i for i in ids if i not in (fmt.fin, fmt.herramienta, fmt.asistente, fmt.usuario)]).strip()


def evaluar_experto(modelo, fmt, disp, ruta=RAIZ / "datos" / "experto_eval.jsonl", pen=1.0, lote=50, max_por_tipo=None):
    filas = [json.loads(l) for l in open(ruta, encoding="utf-8")]
    por_tipo = {}
    for r in filas:
        por_tipo.setdefault(r["tipo"], []).append(r)
    resumen = {}
    for tipo, rs in por_tipo.items():
        rs = rs[:max_por_tipo] if max_por_tipo else rs
        c = dict(n=len(rs), herr=0, consulta=0, exacta=0, sim95=0, busca=0)
        for a in range(0, len(rs), lote):
            grupo = rs[a : a + lote]
            prompts = [fmt.ids_prompt(r["pregunta"]) for r in grupo]
            f1 = generar_lote(modelo, fmt, prompts, disp, pen, max_nuevos=140)
            fase2, idx2 = [], []
            for j, (r, (nuevo, parada)) in enumerate(zip(grupo, f1)):
                t = _texto(fmt, nuevo)
                uso_herr = parada == fmt.herramienta
                c["busca"] += uso_herr and t.startswith("B:")
                if "consulta" not in r:  # debe responder directo
                    if not uso_herr:
                        t = t.removeprefix("R:").strip()
                        c["herr"] += 1
                        c["exacta"] += t == r["respuesta"]
                        c["sim95"] += difflib.SequenceMatcher(None, t, r["respuesta"]).ratio() >= 0.95
                    continue
                pref = r["pref"]
                if uso_herr and t.startswith(pref + ":"):
                    c["herr"] += 1
                    c["consulta"] += t.removeprefix(pref + ":").strip() == r["consulta"].strip()
                    fase2.append(prompts[j] + nuevo + fmt.ids_tras_herramienta(r["resultados"], r.get("tope")))
                    idx2.append(j)
            if fase2:
                for j, (nuevo, _) in zip(idx2, generar_lote(modelo, fmt, fase2, disp, pen, max_nuevos=120)):
                    t = _texto(fmt, nuevo).removeprefix("R:").strip()
                    esp = grupo[j]["respuesta"]
                    c["exacta"] += t == esp
                    c["sim95"] += difflib.SequenceMatcher(None, t, esp).ratio() >= 0.95
        n = c["n"]
        resumen[tipo] = {k: (v / n if k != "n" else v) for k, v in c.items()}
    resumen["_puntaje"] = sum(resumen[t][m] for t, m in PRINCIPAL.items() if t in resumen) / sum(t in resumen for t in PRINCIPAL)
    return resumen


def imprimir(res):
    print(f"{'tipo':18s} {'n':>4s}  herramienta  consulta  exacta  sim>=95  busca")
    for t, m in res.items():
        if t.startswith("_"):
            continue
        print(f"{t:18s} {m['n']:4d}  {m['herr']:10.1%}  {m['consulta']:7.1%}  {m['exacta']:6.1%}  {m['sim95']:7.1%}  {m['busca']:5.1%}")
    print(f"PUNTAJE (promedio de la métrica principal por tipo): {res['_puntaje']:.1%}")
