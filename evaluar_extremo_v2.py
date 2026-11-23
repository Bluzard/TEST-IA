"""Evaluación extremo a extremo de v2c: el ENRUTADOR decide el experto de cada pregunta (en vez de forzar el adaptador del tipo), como en una sesión real.

Misma lógica de fases que evaluar_experto (fase 1: B:/E:/R:; fase 2: resultados guardados -> respuesta) y mismas métricas; la diferencia es que
para cada pregunta se consulta EnrutadorV2 (sin histéresis, mensaje aislado), se activa solo ese adaptador (o ninguno) y la penalización es 1.0
con experto y 1.1 sin él, como en inferir.responder.

  python evaluar_extremo_v2.py [--v1]      # --v1 usa el Enrutador de v1 para medir el efecto del enrutador nuevo
"""
import argparse
import difflib
import json
import time
from pathlib import Path

from enrutador import Enrutador, EnrutadorV2
from evaluar_experto import PRINCIPAL, _texto
from inferir import generar_lote
from motor_cpp import MotorCpp
from protocolo_v2 import FormatoV2

RAIZ = Path(__file__).parent
EXP = RAIZ / "modelos" / "experimentos"


def evaluar(motor, fmt, clase, ruta, maxn=None):
    filas = [json.loads(l) for l in open(ruta, encoding="utf-8")]
    por = {}
    for r in filas:
        por.setdefault(r["tipo"], []).append(r)
    res = {}
    for tipo, rs in por.items():
        rs = rs[:maxn] if maxn else rs
        c = dict(n=len(rs), exacta=0, sim95=0, busca=0, ruteado=0)
        for r in rs:
            modo = clase().paso(r["pregunta"])
            motor.seleccionar(modo)
            pen = 1.0 if modo else 1.1
            p = fmt.ids_prompt(r["pregunta"])
            nuevo, parada = generar_lote(motor, fmt, [p], "cpu", pen, max_nuevos=140)[0]
            t = _texto(fmt, nuevo)
            uso = parada == fmt.herramienta
            c["busca"] += uso and t.startswith("B:")
            c["ruteado"] += modo is not None
            if "consulta" not in r:
                if not uso:
                    t = t.removeprefix("R:").strip()
                    c["exacta"] += t == r["respuesta"]
                    c["sim95"] += difflib.SequenceMatcher(None, t, r["respuesta"]).ratio() >= 0.95
                continue
            if uso and t.startswith(r["pref"] + ":"):
                n2, _ = generar_lote(motor, fmt, [p + nuevo + fmt.ids_tras_herramienta(r["resultados"], r.get("tope"))], "cpu", pen, max_nuevos=120)[0]
                s = _texto(fmt, n2).removeprefix("R:").strip()
                c["exacta"] += s == r["respuesta"]
                c["sim95"] += difflib.SequenceMatcher(None, s, r["respuesta"]).ratio() >= 0.95
        n = c["n"]
        res[tipo] = {k: (v / n if k != "n" else v) for k, v in c.items()}
    res["_puntaje"] = sum(res[t][PRINCIPAL[t]] for t in PRINCIPAL if t in res) / sum(t in res for t in PRINCIPAL)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", action="store_true", help="enrutador de v1 en vez del ampliado")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()
    clase = Enrutador if a.v1 else EnrutadorV2
    fmt, motor, t0 = FormatoV2(), MotorCpp(EXP / "nucleo_v2c_sft.bin"), time.time()
    for i, (nombre, ruta) in enumerate((("codigo", EXP / "experto_codigo_g_v2.lora"), ("redaccion", EXP / "experto_redaccion_f_v2.lora"))):
        motor.registrar_experto(nombre, str(ruta), i)
        motor.cargar_ranura(str(ruta), i)
    out = {}
    for nombre, f in (("codigo", "experto_eval_B2.jsonl"), ("redaccion", "redaccion_eval.jsonl")):
        out[nombre] = evaluar(motor, fmt, clase, RAIZ / "datos" / f)
        print(f"{nombre}: puntaje {out[nombre]['_puntaje']:.1%} ({'enrutador v1' if a.v1 else 'enrutador v2'})", flush=True)
    out["segundos"] = round(time.time() - t0)
    salida = a.salida or str(RAIZ / "resultados" / ("ETAPA4_extremo_v2c_enrutador_v1.json" if a.v1 else "ETAPA4_extremo_v2c.json"))
    Path(salida).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({n: round(out[n]["_puntaje"], 4) for n in ("codigo", "redaccion")}))


if __name__ == "__main__":
    main()
