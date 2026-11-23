# Etapa 4 · Fase 4 — Núcleo v2b (SFT conjunto: charla ampliada + copia técnica)

Generado por `cadena_v2b.py` el 2026-11-23 13:00:14. Nada se promovió a `modelos/`.

## Etapas
| etapa | estado | tiempo |
|---|---|---|
| sft_humo | ok | 9 s |
| sft | ok | 4681 s |
| exportar | ok | 17 s |
| evaluar | ok | 578 s |
| lora_codigo | ok | 691 s |
| lora_redaccion | ok | 294 s |
| verificar_lora_codigo | ok | 4 s |
| verificar_lora_redaccion | ok | 4 s |
| expertos | ok | 1515 s |

## Comparativa v1 · v2 anterior · v2b
| métrica | v1 (producción) | v2 anterior | **v2b** |
|---|---|---|---|
| hechos (ddgs real, respuesta exacta) | 71,6 % | 83,3 % | 83,8% |
| abstención (irrelevante/vacío) | 98,1 % | 99,0 % | 99,0% |
| charla, 339 frases únicas (media por intención, con equivalentes) | 100 % en 18 saludos (no comparable) | 53,6 % | 79,7% |
| charla estricta (media por intención) | — | — | 79,7% |
| experto código (puntaje, 9 tipos) | 82,2 % | 45,6 % | 54,5% |
| experto redacción (puntaje) | 56,2 % | 45,5 % | 38,8% |
| abstención «irrelevante» con LoRA código, activo / dormido | 98,1 % (dormido) | 92,3 % / 98,1 % | 98,1% / 98,1% |
| abstención «irrelevante» con LoRA redacción, activo / dormido | 100 % / 98,1 % | 94,2 % / 98,1 % | 98,1% / 98,1% |

Última pérdida: SFT `época 3: pérdida de evaluación 0.0344` · LoRA código `época 5/5 paso 1050/1065 | pérdida 0.2424 | 674s` · LoRA redacción `época 5/5 paso 550/595 | pérdida 0.0008 | 266s`
(el techo de los LoRA con el núcleo anterior era ≈ 0,96 en código).

Detalle: `resultados/ETAPA4_eval_v2b.json`, `ETAPA4_expertos_v2b.json`, logs `resultados/ETAPA4_v2b_*.log`.
