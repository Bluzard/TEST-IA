# Etapa 4 · Fase 3 — Resultados de la cadena automática (SFT, exportación, evaluación y expertos)

Generado por `cadena_v2.py` el 2026-11-23 08:30:15. **No se promovió nada a `modelos/`**; todo está en `modelos/experimentos/` a la espera de decisión.

## Etapas
| etapa | estado | tiempo |
|---|---|---|
| comprobar | ok | — s |
| sft_humo | ok | 16 s |
| sft | ok | 7317 s |
| exportar | ok | 10 s |
| evaluar | ok | 540 s |
| lora_codigo | ok | 306 s |
| lora_redaccion | ok | 280 s |
| verificar_lora_codigo | ok | 4 s |
| verificar_lora_redaccion | ok | 4 s |

## Núcleo v2 con SFT frente a v1 (evaluación por el motor C++, ddgs real, `datos/sft_eval_real.jsonl`)
| métrica | v1 (producción) | v2-A + SFT |
|---|---|---|
| hechos (respuesta exacta) | 71,6 % | 83.3% |
| abstención (irrelevante / vacío) | 98,1 % | 99.0% |
| charla: no busca / respuesta válida | 100 % (18 saludos exactos) | 100.0% / 46.0% |

Simulado con artículos reservados: {"buscar_ok": {"buscó": 1.0, "respuesta_exacta": 0.9166666666666666}, "irrelevante": {"buscó": 1.0, "se_abstuvo": 0.9966666666666667}, "vacio": {"buscó": 1.0, "se_abstuvo": 1.0}}

Última pérdida del SFT: `época 3: pérdida de evaluación 0.0402`
Última pérdida LoRA código: `época 3/3 paso 600/639 | pérdida 1.1412 | 282s` · redacción: `época 6/6 paso 700/714 | pérdida 0.0258 | 269s`

Notas: la charla de v2 es más amplia que los 18 saludos de v1, así que no es comparable palabra por palabra. Los expertos LoRA aún no se evalúan con sus pruebas propias (`evaluar_experto.py` es de v1): falta portarlo antes de aceptarlos.
Detalle: `resultados/ETAPA4_eval_v2.json` y los logs `resultados/ETAPA4_cadena_*.log`.
