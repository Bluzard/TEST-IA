"""Evaluador dedicado del experto de redacción (datos/redaccion_eval.jsonl: todo reservado, nunca visto al entrenar).

Mide por separado, con herramientas simuladas con los resultados guardados (base local de fichas y ddgs real recolectado):
  ortografia   corrección ortográfica y de puntuación (ortografia, ortografia_signos) y «ya está bien» (ortografia_ok): exacta
  tono         formal / cercano / conciso / claro: exacta (las transformaciones son deterministas)
  gramatica    reglas de la base local (gramatica, gramatica_reservada: similitud >= 95 %; gramatica_ejemplo: exacta)
  ddgs         temas de cola con respuesta en internet (cola_ok): busca y copia la oración correcta (similitud >= 95 %)
  abstencion   temas inexistentes o sin resultados (cola_inexistente, cola_abst, cola_sin_resultados): exacta (= «No tengo información…»)
  general      repaso de la Etapa 1 (sft_eval_real.jsonl, ddgs real): hechos / abstención / conversación

  python evaluar_redaccion.py --cargar modelos/experimentos/experto_redaccion_e3.lora.pt [--sin-general]
  python evaluar_redaccion.py --base          # núcleo solo (línea base: sin adaptador)
"""
import argparse
import json
from pathlib import Path

import lora
from evaluar_experto import evaluar_experto, imprimir
from inferir import cargar, evaluar as evaluar_general
from modelo import elegir_dispositivo

RAIZ = Path(__file__).parent
GRUPOS = {
    "ortografia": ("ortografia", "ortografia_signos", "ortografia_ok"),
    "tono": ("tono_formal", "tono_cercano", "tono_conciso", "tono_claro"),
    "gramatica": ("gramatica", "gramatica_reservada", "gramatica_ejemplo"),
    "ddgs": ("cola_ok",),
    "abstencion": ("cola_inexistente", "cola_abst", "cola_sin_resultados"),
}


def por_grupo(res):
    """Promedio ponderado por número de ejemplos de la métrica principal de cada tipo del grupo."""
    from evaluar_experto import PRINCIPAL

    out = {}
    for g, tipos in GRUPOS.items():
        t = [x for x in tipos if x in res]
        n = sum(res[x]["n"] for x in t)
        out[g] = {"n": n, "puntaje": (sum(res[x][PRINCIPAL[x]] * res[x]["n"] for x in t) / n) if n else None,
                  "tipos": {x: round(res[x][PRINCIPAL[x]], 4) for x in t}}
    return out


def evaluar_todo(modelo, fmt, disp, ruta_eval, general=True):
    res = evaluar_experto(modelo, fmt, disp, ruta=ruta_eval, pen=1.0)
    salida = {"experto": res, "grupos": por_grupo(res)}
    if general:
        salida["general"] = evaluar_general(modelo, fmt, disp, ruta=RAIZ / "datos" / "sft_eval_real.jsonl", n_por_tipo=300, penalizacion=1.1)
    return salida


def imprimir_grupos(salida):
    imprimir(salida["experto"])
    print("\nPor grupo (métrica principal, ponderada):")
    for g, d in salida["grupos"].items():
        if d["n"]:
            print(f"  {g:11s} n={d['n']:4d}  {d['puntaje']:6.1%}   {d['tipos']}")
    for t, m in salida.get("general", {}).items():
        print(f"  general/{t:12s}", "  ".join(f"{k}={v:.1%}" for k, v in m.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cargar", default=None, help="adaptador .lora.pt a evaluar")
    ap.add_argument("--base", action="store_true", help="núcleo solo, sin adaptador")
    ap.add_argument("--eval", default=str(RAIZ / "datos" / "redaccion_eval.jsonl"))
    ap.add_argument("--sin-general", action="store_true", help="omite el repaso de la Etapa 1 (usa ddgs real)")
    ap.add_argument("--salida", default=None, help="JSON de resultados (por defecto resultados/redaccion_<nombre>.json)")
    args = ap.parse_args()
    disp = elegir_dispositivo()
    modelo, fmt = cargar(RAIZ / "modelos" / "nucleo_sft_v3.pt", disp)
    nombre = "base"
    if args.cargar and not args.base:
        lora.cargar_lora(modelo, args.cargar)
        modelo.to(disp).eval()
        nombre = Path(args.cargar).name.removesuffix(".lora.pt")
    salida = evaluar_todo(modelo, fmt, disp, args.eval, general=not args.sin_general)
    imprimir_grupos(salida)
    ruta = Path(args.salida) if args.salida else RAIZ / "resultados" / f"redaccion_{nombre}.json"
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print("guardado en", ruta)


if __name__ == "__main__":
    main()
