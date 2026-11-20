"""Compara núcleo normal vs BitNet con varias semillas.

Pregunta: ¿BitNet rinde igual o casi igual pesando mucho menos?
Entrena (si falta) cada combinación variante x semilla con el mismo presupuesto,
evalúa todo y escribe resultados/comparacion.md con promedios y peso.

  python comparar.py                       (normal y bitnet, semillas 0 1 2, 2000 pasos)
  python comparar.py --variantes normal bitnet chico bucle --sufijo v3
  python comparar.py --semillas 0 1 2 3 4 --pasos 10000 --sufijo largo
"""
import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

from evaluar import GRUPOS, cargar_casos, medir
from herramientas import Diccionario
from modelo import BitLinear, elegir_dispositivo

RAIZ = Path(__file__).parent
# Presets de arquitectura. "bucle" usa la mitad de capas pasadas 2 veces:
# mismo cálculo que "normal" con la mitad de parámetros. "chico" es la base
# justa para saber si las vueltas aportan algo.
VARIANTES = {
    "normal": [],
    "bitnet": ["--bitnet"],
    "chico": ["--capas", "2"],
    "bucle": ["--capas", "2", "--vueltas", "2"],
    "bitnet_bucle": ["--bitnet", "--capas", "2", "--vueltas", "2"],
}


def ruta_modelo(variante, semilla, sufijo):
    return RAIZ / "modelos" / f"cmp_{variante}_s{semilla}{sufijo}.pt"


def peso_mb(modelo):
    """Peso para usar el modelo: normal en 16 bits; BitNet con pesos ternarios en 2 bits."""
    total = modelo.parametros()
    if not modelo.cfg.bitnet:
        return total * 2 / 1e6
    tern = sum(m.weight.numel() for m in modelo.modules() if isinstance(m, BitLinear))
    return (tern * 2 / 8 + (total - tern) * 2) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semillas", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--pasos", type=int, default=2000)
    ap.add_argument("--variantes", nargs="+", default=["normal", "bitnet"], choices=list(VARIANTES))
    ap.add_argument("--sufijo", default="", help="para no mezclar con otras corridas (ej. al cambiar los datos)")
    args = ap.parse_args()
    sufijo = f"_{args.sufijo}" if args.sufijo else ""
    variantes = {v: VARIANTES[v] for v in args.variantes}

    rutas = {}
    for semilla in args.semillas:
        for variante, extra in variantes.items():
            ruta = ruta_modelo(variante, semilla, sufijo)
            rutas[(variante, semilla)] = ruta
            if ruta.exists():
                print(f"[ya existe] {ruta.name}", flush=True)
                continue
            print(f"[entrenando] {variante} semilla {semilla} ({args.pasos} pasos)...", flush=True)
            t0 = time.time()
            subprocess.run([sys.executable, "-u", str(RAIZ / "entrenar.py"), "--variante", "B", "--pasos", str(args.pasos),
                            "--semilla", str(semilla), "--salida", str(ruta), *extra], check=True)
            print(f"[listo] {ruta.name} en {time.time() - t0:.0f}s", flush=True)

    print("\nEvaluando...", flush=True)
    dispositivo = elegir_dispositivo()
    casos, diccionario = cargar_casos(), Diccionario()
    res = {v: {"tablas": [], "banco": [], "peso": None, "params": None} for v in variantes}
    for (variante, semilla), ruta in rutas.items():
        tabla, banco, modelo = medir(ruta, casos, diccionario, dispositivo)
        res[variante]["tablas"].append(tabla)
        r, esperado = banco
        res[variante]["banco"].append(r["respuesta"] == esperado)
        res[variante]["peso"] = peso_mb(modelo)
        res[variante]["params"] = modelo.parametros()

    def resumen(variante, grupo, campo):
        valores = [t[grupo][campo] for t in res[variante]["tablas"] if grupo in t]
        if not valores:
            return None
        media = statistics.mean(valores)
        desv = statistics.stdev(valores) if len(valores) > 1 else 0.0
        return media, desv

    nombres = list(variantes)
    n = len(args.semillas)
    lineas = [
        f"# Comparación de variantes ({n} semillas, {args.pasos} pasos{', ' + args.sufijo if args.sufijo else ''})",
        "",
        "Acierto promedio ± desviación entre semillas.",
        "",
        "| Grupo | " + " | ".join(nombres) + " |",
        "|---|" + "---|" * len(nombres),
    ]
    for g in GRUPOS:
        celdas = []
        for v in nombres:
            r = resumen(v, g, "acierto")
            celdas.append(f"{r[0]:.1f}% ± {r[1]:.1f}" if r else "—")
        lineas.append(f"| {g} | " + " | ".join(celdas) + " |")
    busca = [resumen(v, "compatibles_nuevas", "busco") for v in nombres]
    lineas += [
        "",
        "| | " + " | ".join(nombres) + " |",
        "|---|" + "---|" * len(nombres),
        "| Busca de más en compatibles | " + " | ".join(f"{b[0]:.1f}%" if b else "—" for b in busca) + " |",
        "| «banco de arena» correcto | " + " | ".join(f"{sum(res[v]['banco'])}/{n}" for v in nombres) + " |",
        "| Parámetros | " + " | ".join(f"{res[v]['params']:,}" for v in nombres) + " |",
        "| Peso para usarlo | " + " | ".join(f"{res[v]['peso']:.2f} MB" for v in nombres) + " |",
    ]
    texto = "\n".join(lineas)
    (RAIZ / "resultados").mkdir(exist_ok=True)
    salida = RAIZ / "resultados" / f"comparacion{sufijo}.md"
    salida.write_text(texto + "\n", encoding="utf-8")
    print("\n" + texto)
    print(f"\nGuardado en {salida}")


if __name__ == "__main__":
    main()
