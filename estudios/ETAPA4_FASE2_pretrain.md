# Etapa 4 · Fase 2 — Preentrenamiento del núcleo v2-A

Documento generado automáticamente al terminar `pretrain_v2.py` (métricas en `resultados/ETAPA4_pretrain_final.json`, curva en `resultados/ETAPA4_pretrain_curva.jsonl`).

## Resumen
- Modelo: v2-A, 157.7 M parámetros (22 capas, d=768, GQA 12/4, ff 3072, embeddings atados, BitNet ternario en qkv/proy/fc1/fc2).
- Tokens entrenados: **4.000 B** en 122,069 pasos de 32.768 tokens (una época exacta del corpus de la Fase 1) — **52.2 h** de entrenamiento.
- Curriculum: tramo 1 97,655 pasos a 512 tokens (23150 tok/s mediana); tramo 2 24,414 pasos a 1.024 tokens (17908 tok/s mediana).
- Optimización: AdamW (β 0,9/0,95, wd 0,1), lr pico 6.0e-04 con calentamiento de 1000 pasos y coseno hasta 10 %, recorte de gradiente 1,0, bf16 + torch.compile + SDPA.
- VRAM pico: 11.94 GB (tope impuesto: 13.0 GB).
- Estabilidad: loss final 2.944 (mínimo 2.916); norma de gradiente media 0.66, máxima en una ventana de 100 pasos 23.81; picos de loss detectados: 0.

## Curva de entrenamiento (cada ≈ 8,700 pasos)
| paso | tokens (M) | ventana | loss | gnorm | lr |
|---|---|---|---|---|---|
| 100 | 3 | 512 | 8.428 | 3.81 | 6.00e-05 |
| 8,800 | 288 | 512 | 3.540 | 0.46 | 5.93e-04 |
| 17,500 | 573 | 512 | 3.397 | 0.49 | 5.73e-04 |
| 26,200 | 858 | 512 | 3.325 | 0.55 | 5.41e-04 |
| 34,900 | 1,144 | 512 | 3.288 | 0.54 | 4.98e-04 |
| 43,600 | 1,429 | 512 | 3.221 | 0.55 | 4.47e-04 |
| 52,300 | 1,714 | 512 | 3.212 | 0.58 | 3.90e-04 |
| 61,000 | 1,999 | 512 | 3.184 | 0.62 | 3.30e-04 |
| 69,700 | 2,284 | 512 | 3.149 | 0.67 | 2.70e-04 |
| 78,400 | 2,569 | 512 | 3.110 | 0.71 | 2.13e-04 |
| 87,100 | 2,854 | 512 | 3.095 | 0.76 | 1.62e-04 |
| 95,800 | 3,139 | 512 | 3.031 | 0.80 | 1.19e-04 |
| 104,500 | 3,424 | 1024 | 2.973 | 0.81 | 8.71e-05 |
| 113,200 | 3,709 | 1024 | 2.932 | 0.84 | 6.70e-05 |
| 121,900 | 3,994 | 1024 | 2.950 | 0.88 | 6.00e-05 |

## Validación rápida (1 M tokens fijos, ventanas de 512) en cada checkpoint
| paso | tokens (M) | nll | ppl |
|---|---|---|---|
| 3,000 | 98 | 3.9311 | 50.96 |
| 6,000 | 197 | 3.6493 | 38.45 |
| 9,000 | 295 | 3.5388 | 34.43 |
| 12,000 | 393 | 3.4712 | 32.18 |
| 15,000 | 492 | 3.4315 | 30.92 |
| 18,000 | 590 | 3.3955 | 29.83 |
| 21,000 | 688 | 3.3708 | 29.10 |
| 24,000 | 786 | 3.3498 | 28.50 |
| 24,359 | 798 | 3.3460 | 28.39 |
| 27,000 | 885 | 3.3310 | 27.97 |
| 30,000 | 983 | 3.3122 | 27.45 |
| 33,000 | 1,081 | 3.2983 | 27.07 |
| 36,000 | 1,180 | 3.2865 | 26.75 |
| 39,000 | 1,278 | 3.2718 | 26.36 |
| 42,000 | 1,376 | 3.2611 | 26.08 |
| 45,000 | 1,475 | 3.2469 | 25.71 |
| 48,000 | 1,573 | 3.2375 | 25.47 |
| 51,000 | 1,671 | 3.2273 | 25.21 |
| 54,000 | 1,770 | 3.2150 | 24.90 |
| 57,000 | 1,868 | 3.2053 | 24.66 |
| 60,000 | 1,966 | 3.1928 | 24.36 |
| 63,000 | 2,064 | 3.1803 | 24.06 |
| 66,000 | 2,163 | 3.1709 | 23.83 |
| 69,000 | 2,261 | 3.1597 | 23.56 |
| 72,000 | 2,359 | 3.1497 | 23.33 |
| 75,000 | 2,458 | 3.1382 | 23.06 |
| 78,000 | 2,556 | 3.1300 | 22.87 |
| 81,000 | 2,654 | 3.1171 | 22.58 |
| 84,000 | 2,752 | 3.1053 | 22.32 |
| 87,000 | 2,851 | 3.0941 | 22.07 |
| 90,000 | 2,949 | 3.0841 | 21.85 |
| 93,000 | 3,047 | 3.0751 | 21.65 |
| 96,000 | 3,146 | 3.0631 | 21.39 |
| 99,000 | 3,244 | 3.0573 | 21.27 |
| 102,000 | 3,342 | 3.0526 | 21.17 |
| 105,000 | 3,441 | 3.0413 | 20.93 |
| 108,000 | 3,539 | 3.0338 | 20.78 |
| 111,000 | 3,637 | 3.0270 | 20.64 |
| 114,000 | 3,736 | 3.0218 | 20.53 |
| 117,000 | 3,834 | 3.0204 | 20.50 |
| 120,000 | 3,932 | 3.0180 | 20.45 |

## Validación completa (8.2 M tokens): embedding atado fp32 vs fp16 vs int8 por fila
| embedding | nll | ppl | Δ ppl vs fp32 |
|---|---|---|---|
| fp32 (master) | 3.0084 | 20.255 | +0.000 % |
| fp16 | 3.0084 | 20.255 | +0.000 % |
| int8 por fila | 3.0093 | 20.273 | +0.091 % |

La validación sale del mismo reparto de fuentes que el entrenamiento (wiki, web, código), no de un conjunto fuera de dominio; la decontaminación contra las evaluaciones de las Etapas 1–3 está en `estudios/ETAPA4_FASE1_datos.md`.

## Archivos
- Pesos: `modelos/experimentos/pretrain_v2/nucleo_v2_pretrain.pt` (fp32, sin exportar al motor C++; el empaquetado NUCL0002 con embedding int8 es el paso siguiente) y los 3 últimos checkpoints `ckpt_*.pt`.
- Reanudar: `python pretrain_v2.py --reanudar`.

## Siguiente paso
SFT (conversación, protocolo B:/E:/R:, identidad TEST-IA) y evaluación contra v1 (71,6 % / 98,1 % / 100 %). Pendiente: exportar a NUCL0002 y verificar logits del motor contra PyTorch.
