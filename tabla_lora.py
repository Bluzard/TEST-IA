"""Tabla comparativa de las corridas del experto (lee resultados/experto_*.json) -> resultados/experto_comparacion.md"""
import json
from pathlib import Path

RAIZ = Path(__file__).parent
ORDEN = ["base", "atencion", "r4", "r8_todas", "r8_semilla1", "r16"]
ETIQ = {"base": "Núcleo solo (sin LoRA)", "atencion": "Solo atención, r=8", "r4": "4 matrices, r=4", "r8_todas": "**4 matrices, r=8** (principal)",
        "r8_semilla1": "4 matrices, r=8, semilla 1", "r16": "4 matrices, r=16"}
TIPOS = ["concepto", "concepto_ejemplo", "concepto_nuevo", "doc_ok", "doc_abst", "ejec_ok", "ejec_error", "ejec_nameerror", "error_interp"]
PRIN = {"concepto_nuevo": "busca", "doc_ok": "sim95"}

res = {n: json.loads((RAIZ / "resultados" / f"experto_{n}.json").read_text(encoding="utf-8")) for n in ORDEN if (RAIZ / "resultados" / f"experto_{n}.json").exists()}
f = ["| Variante | MB (fp16) | Parámetros | **Puntaje** | " + " | ".join(TIPOS) + " | General: hechos exacta | General: abstención (otro tema) |",
     "|" + "---|" * (len(TIPOS) + 6)]
for n, r in res.items():
    e = r["experto"]
    celdas = [f"{e[t][PRIN.get(t, 'exacta')]:.0%}" if t in e else "—" for t in TIPOS]
    g = r["general"]
    f.append(f"| {ETIQ[n]} | {r.get('mb_fp16', 0):.2f} | {r.get('parametros', 0):,} | **{e['_puntaje']:.1%}** | " + " | ".join(celdas) +
             f" | {g['buscar_ok']['respuesta_exacta']:.1%} | {g['irrelevante']['se_abstuvo']:.1%} |")
tabla = "\n".join(f)
nota = ("\n\nMétrica principal por columna: *exacta* (respuesta idéntica a la esperada); concepto_nuevo = % que **busca** en vez de inventar; "
        "doc_ok = similitud ≥ 95 % con la oración correcta. Puntaje = promedio de las 9 columnas. «General» = evaluación de la Etapa 1 con "
        "ddgs real y el adaptador **activo** (núcleo solo: 71,6 % y 98,1 %). Con el adaptador dormido el resultado fue idéntico al núcleo "
        "en todas las corridas.\n")
(RAIZ / "resultados" / "experto_comparacion.md").write_text("# Experto de código: configuración principal y ablaciones\n\n" + tabla + nota, encoding="utf-8")
print(tabla)
for n, r in res.items():
    if "general_dormido" in r:
        g, d = r["general"], r["general_dormido"]
        print(f"{n:12s} dormido idéntico al núcleo: {d['buscar_ok']['respuesta_exacta'] == 0.716 or abs(d['buscar_ok']['respuesta_exacta'] - 0.716) < 0.002}; núcleo intacto: {r.get('nucleo_intacto')}")
