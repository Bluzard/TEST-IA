# Etapa 4 · Fase 1 — Tokenizador 24k y corpus de 4.000 M de tokens

Estado: **completada, pendiente de aprobación para pasar al piloto en GPU.** Todo es reproducible con `fase1_datos.py` (ver §7). Los datos viven en `datos/v2/` (ignorado por git, 7,5 GB de shards).
Pesos congelados (`nucleo_sft_v3.pt/.bin`, `experto_codigo.lora`, `experto_redaccion.lora`): no se han tocado. SHA-256 comprobado al cierre:

| archivo | SHA-256 |
|---|---|
| nucleo_sft_v3.pt | a867d741e0e65aa752757080fd4957abb871df6de75c0ef3e3a8fbd1c176717d |
| nucleo_sft_v3.bin | 17ecdbdaafba9c61ad0f08a633982118c0e205b130839b27fa5fc27204e0b540 |
| experto_codigo.lora | b57032631efdcdb6eec0c883207bad64a23e91f65eb21792095bdfb2110278c6 |
| experto_redaccion.lora | 3ec614b0ba4ecd5538d2557730c914506054adfd618c77711b19e3ed54696018 |

## 1. Fuentes y licencias (verificadas en las fichas de cada dataset)

| fuente | uso | licencia | condiciones / salvedades |
|---|---|---|---|
| `wikimedia/wikipedia` 20231101.es | enciclopédico (600 M tok) | GFDL + CC BY-SA 3.0 | Atribución y *share-alike*: los textos derivados de Wikipedia heredan la obligación de atribuir; hay que revisarlo antes de **redistribuir** el corpus o los pesos. Para uso interno de entrenamiento no hay restricción práctica. |
| `HuggingFaceFW/fineweb-2` spa_Latn | web en español (3.000 M tok) | ODC-By 1.0 | Sujeto además a los Términos de Uso de CommonCrawl. Emails e IPs públicas anonimizados por el propio dataset; existe formulario de *opt-out*. Riesgo residual de datos personales en texto libre. |
| `codeparrot/github-code-clean` | código y documentación (400 M tok) | La ficha dice Apache-2.0, pero cada archivo conserva su licencia de origen | Solo se aceptan archivos con licencia permisiva: mit, apache-2.0, bsd-2-clause, bsd-3-clause, isc, unlicense, cc0-1.0, 0bsd. Se descartaron por licencia 402.893 archivos en la pasada final. |
| Textos propios del proyecto (protocolo B:/E:/R:, gramática técnica) | solo entran en la muestra del tokenizador, no en el corpus de 4.000 M | propios | — |

Alternativas revisadas y descartadas: The Stack v2, StarCoderData y CulturaX (acceso con aceptación de términos), OSCAR (acceso manual), smollm-corpus (ODC-By, pero `python-edu` exige bajar blobs externos).

## 2. Tokenizador v2 (24.000 + 4 etiquetas = 24.004)

ByteLevel BPE (`tokenizers`) entrenado sobre una muestra balanceada de 374 MB: Wikipedia 100 MB, web 140 MB, código 88 MB, protocolo del proyecto 40 MB y gramática técnica 0,5 MB. Archivos: `datos/v2/tokenizador_v2.json` (24.000) y `tokenizador_v2_sft.json` (con `<usuario> <asistente> <herramienta> <fin>`).

Tokens por palabra sobre texto **reservado** (que no vio el entrenamiento del tokenizador), v1 (16k) frente a v2 (24k):

| dominio | docs | v1 tok/palabra | v2 tok/palabra | cambio |
|---|---|---|---|---|
| Wikipedia | 300 | 1,599 | 1,571 | −1,8 % |
| Web | 300 | 1,512 | 1,422 | −5,9 % |
| Python | 22 | 6,012 | 3,275 | −45,5 % |
| JS / SQL / shell | 63 | 5,700 | 3,013 | −47,1 % |
| Markdown | 28 | 3,948 | 2,740 | −30,6 % |
| Conversación del proyecto | 400 | 1,761 | 1,540 | −12,5 % |

Lo que ganamos es sobre todo en código y en conversación; en español de prosa la mejora es pequeña, que es lo esperable con solo 8.000 tokens más.

Verificación de casos (20 cadenas: operadores, llaves, indentación, tabuladores, tildes, ñ, ü, ¿¡, URL, backticks…): **los 20 reproducen el texto exacto al decodificar** y ninguno necesita más tokens que v1. Ejemplos: `x**2` → `x`, `**`, `2` (3 tokens, v1: 4); `**`, `==`, `!=`, `->` son tokens únicos; la indentación de 4 espacios es un solo token (`ĊĠĠĠ`); `    return x  # comentario` pasa de 11 a 6 tokens; `TEST-IA` de 5 a 3.

## 3. Corpus: composición final

**4.000.004.920 tokens de entrenamiento + 8,16 M de validación** (0,2 %, documentos con hash%500==0), en 41 shards `uint16` de ≤100 M tokens, con `<|fin|>` como separador de documento. Tiempo del empaquetado: 4.006 s.

| fuente | tokens | % | shards | filtros que más descartaron |
|---|---|---|---|---|
| Wikipedia es | 600 M | 15,0 % | 6 | cortos (<500 car.) 135.243; contaminados 12.888; título reservado 813 |
| Web LatAm (URL con TLD de 19 países hispanoamericanos: .cl .mx .ar .co .pe .ve .ec .bo .py .uy .cr .pa .gt .hn .ni .sv .do .cu .pr) | 1.350 M | 33,7 % | 14 | cortos 81.879; listas 12.113; idioma 4.380; duplicados 1.006 |
| Web resto | 1.650 M | 41,2 % | 17 | cortos 85.908; listas 21.354; idioma 10.961; duplicados 396 |
| Código y documentación | 400 M | 10,0 % | 4 | licencia 402.893; cuota de lenguaje 375.470; tamaño 67.075; autogenerado 35.537; secretos 414 |

Caracteres de código por lenguaje: Python 282 M, JavaScript 202 M, Markdown 167 M, HTML 101 M, Java 101 M, C# 67 M, TypeScript 57 M, C++ 50 M, C 50 M, CSS 50 M, Go 50 M, PHP 34 M, Shell 17 M, SQL 12 M.

Historia honesta: la primera pasada solo llegó a 3.357 M (se agotaron los 2 shards de FineWeb-2 y los 6 de código: web LatAm 780/1.350 M, código 327/400 M). Se bajaron 2 shards más de FineWeb-2 y 6 de código y se rehízo el empaquetado completo; la pasada final cumple los cuatro presupuestos exactos. El resultado de la primera pasada se conserva en `resultados/ETAPA4_fase1_corpus_pasada1.json`.

Filtros aplicados: web (language_score ≥ 0,9, longitud, longitud media de palabra 3–10, proporción de letras, palabras vacías del español, líneas repetidas, listas/menús, puntuación, símbolos, relleno/lorem); código (licencia permisiva, 200–60.000 car., longitud de línea, proporción alfanumérica, autogenerado, regex de secretos/claves, cuota por lenguaje); deduplicación exacta (md5 de los primeros 2.000 caracteres) entre todas las fuentes.

## 4. Descontaminación

Conjuntos de evaluación cubiertos (10 archivos, 40.572 textos): `evaluacion.jsonl`, `evaluacion_ampliada.jsonl`, `experto_eval.jsonl`, `experto_eval_B.jsonl`, `experto_eval_B2.jsonl`, `redaccion_eval.jsonl`, `sft_eval.jsonl`, `sft_eval_real.jsonl`, `ddgs_raw_eval.jsonl` y la copia en `etapa1/`. Se extraen todas las cadenas de texto de cada registro.

Método: (a) cada documento candidato se tokeniza y se descarta si comparte **algún n-grama de 13 tokens** (hash polinomial de 64 bits) con los 231.422 n-gramas de evaluación; (b) se excluyen 2.798 títulos reservados (fichas y consultas de evaluación) de Wikipedia. Descartes por contaminación en el corpus final: Wikipedia 12.888, web LatAm 708, web resto 1.005, código 27.

**Verificación independiente** sobre los 4,008 B tokens ya empaquetados (`verificar_descontaminacion`, resultados en `resultados/ETAPA4_fase1_descontaminacion.json`), con control positivo (un texto de evaluación insertado se detecta):

| n | n-gramas de evaluación | coincidencias en el corpus |
|---|---|---|
| 13 | 231.422 | **0** (wiki 0, web 0, código 0, validación 0) |
| 8 | 242.814 | 327.848 (solo informativo) |

Las coincidencias de 8 tokens son frases comunes del español («es un municipio de», «de acuerdo con la»…), 230.549 de ellas en Wikipedia; no son fuga de evaluación. Se reportan para transparencia, no como criterio.

## 5. Limitaciones y riesgos conocidos

1. **Las evaluaciones de la Etapa 4 aún no existen.** Cuando se creen, deben dejarse en `datos/eval_v2/*.jsonl` (o `datos/v2/eval/`) y repetir `empaquetar` (≈ 67 min) o, más barato, `verificar_descontaminacion` y eliminar los shards afectados.
2. Textos de evaluación de menos de 13 tokens (consultas cortas) no pueden detectarse por n-grama; solo se protege su coincidencia exacta de título en Wikipedia.
3. La descontaminación es léxica: una paráfrasis de una pregunta de evaluación no se detecta.
4. Wikipedia: obligación de atribución/share-alike al redistribuir. FineWeb-2: posibles datos personales residuales en web; hay formulario de opt-out.
5. Las cuotas de código usan 4,2 caracteres/token como estimación; los reales son ≈ 3,3, así que la mezcla efectiva de lenguajes difiere algo de la nominal (Python .30, JS .12, Markdown .12…). Python y JS siguen dominando.
6. La validación es solo el 0,2 % (8,2 M tokens) y sale de las mismas distribuciones que el entrenamiento; sirve para perplejidad, no para medir generalización fuera de dominio.
7. Web: 3.000 M tokens salen de 6 shards de FineWeb-2; si el piloto indica que hace falta más diversidad, hay más shards disponibles.

## 6. Pendiente antes del piloto en GPU

- Aprobación del usuario para empezar el piloto (0,5–1 B tokens) con el motor y el diseño v2-A.
- Definir y generar los conjuntos de evaluación de la Etapa 4 y volver a pasar la verificación.
- Decidir si se hace commit/push de `fase1_datos.py`, `resultados/ETAPA4_fase1_*` y este documento.

## 7. Reproducción

```
python fase1_datos.py muestra
python fase1_datos.py tokenizador
python fase1_datos.py comparar
python fase1_datos.py empaquetar            # 4.000 M tokens, ~67 min
python fase1_datos.py estadisticas
python fase1_datos.py verificar_descontaminacion
```
(usar `.venv/Scripts/python.exe`; el `python` del sistema no tiene numpy.)
