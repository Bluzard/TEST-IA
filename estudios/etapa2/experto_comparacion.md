# Experto de código: configuración principal y ablaciones

| Variante | MB (fp16) | Parámetros | **Puntaje** | concepto | concepto_ejemplo | concepto_nuevo | doc_ok | doc_abst | ejec_ok | ejec_error | ejec_nameerror | error_interp | General: hechos exacta | General: abstención (otro tema) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Núcleo solo (sin LoRA) | 0.00 | 0 | **12.5%** | 0% | 0% | 38% | 7% | 67% | 0% | 0% | 0% | 0% | 71.6% | 98.1% |
| Solo atención, r=8 | 0.49 | 245,760 | **41.7%** | 0% | 0% | 87% | 42% | 87% | 59% | 68% | 0% | 33% | 56.3% | 88.5% |
| 4 matrices, r=4 | 0.66 | 327,680 | **52.6%** | 8% | 8% | 87% | 27% | 72% | 95% | 85% | 30% | 62% | 59.9% | 98.1% |
| **4 matrices, r=8** (principal) | 1.31 | 655,360 | **64.3%** | 19% | 61% | 54% | 37% | 78% | 97% | 88% | 70% | 75% | 63.5% | 92.3% |
| 4 matrices, r=8, semilla 1 | 1.31 | 655,360 | **68.2%** | 22% | 67% | 67% | 37% | 81% | 97% | 84% | 100% | 58% | 62.2% | 94.2% |
| 4 matrices, r=16 | 2.62 | 1,310,720 | **73.3%** | 16% | 93% | 65% | 46% | 81% | 98% | 92% | 100% | 68% | 66.7% | 98.1% |

Métrica principal por columna: *exacta* (respuesta idéntica a la esperada); concepto_nuevo = % que **busca** en vez de inventar; doc_ok = similitud ≥ 95 % con la oración correcta. Puntaje = promedio de las 9 columnas. «General» = evaluación de la Etapa 1 con ddgs real y el adaptador **activo** (núcleo solo: 71,6 % y 98,1 %). Con el adaptador dormido el resultado fue idéntico al núcleo en todas las corridas.
