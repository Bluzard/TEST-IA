# Etapa 4 — Cierre oficial: núcleo v2c en producción

**Estado:** cerrada. El núcleo **v2c** (v2-A, 157,7 M de parámetros, BitNet ternario, tokenizador de 24 k, embeddings atados en int8) con sus dos expertos LoRA
(código y redacción) y el enrutador ampliado es el modelo por defecto de `inferir.py`. **v1 queda como respaldo íntegro** (`python inferir.py --v1 …`).
Fecha de cierre: 2026-11-23.

## 1. Resultado frente a v1

Todas las cifras salen del **motor C++ con los .bin/.lora exportados** (el camino de producción), con los mismos conjuntos de evaluación reservados que v1.

| métrica | v1 | **v2c** | nota |
|---|---|---|---|
| hechos, ddgs real (respuesta exacta) | 71,6 % | **83,3–84,7 %** | núcleo solo 83,3 %; con LoRA de código 83,8 %; con el de redacción 84,7 % |
| abstención (irrelevante / vacío) | 98,1 % | **100 %** | también con cualquiera de los dos adaptadores activos |
| experto de código (adaptador forzado) | 82,2 % | **82,7 %** | `ejec_ok` 99,3 % (v1 95,3 %), `ejec_error` 100 % (v1 93,8 %), `doc_abst` 98,3 % (v1 79,8 %) |
| experto de redacción (adaptador forzado) | 56,2 % | **64,2 %** | `gramatica` 100 % (v1 92 %), `gramatica_reservada` 88,9 % (v1 75,9 %), `tono_claro` 62,5 % (v1 40 %), `tono_cercano` 95 % (v1 32,5 %) |
| **código, extremo a extremo (enrutador activo)** | — | **80,3 %** | con el enrutador de v1: 79,3 % |
| **redacción, extremo a extremo (enrutador activo)** | — | **63,9 %** | con el enrutador de v1: 63,2 % |
| enrutador → código (preguntas de código) | 78,0 % | **91,5 %** | `EnrutadorV2` |
| enrutador → redacción (preguntas de redacción) | 94,4 % | **96,5 %** | `EnrutadorV2` |
| falsos positivos del enrutador | 7/30 · 11/339 · 2/287 | **7/30 · 11/339 · 2/287** | negativos difíciles · charla · hechos: sin ninguno nuevo |
| charla (339 frases reservadas, media por intención) | 100 % en 18 saludos (no comparable) | **79,9 %** | 39 intenciones; 0 fugas de protocolo |
| perplejidad de validación (8,2 M tokens) | — | **20,26** (fp32) · **20,27** (int8 atado) | el atado en int8 no pierde calidad |

Las cifras de v1 de los expertos son con el adaptador forzado (como en la Etapa 3); en uso real v1 también pierde algo por su propio enrutador, así que la
comparación más justa es «forzado frente a forzado» (82,7 frente a 82,2 y 64,2 frente a 56,2).

### Dónde v2c todavía NO supera a v1 (límites conocidos)

- **`doc_ok` (código): 23,7 % forzado / 22,0 % extremo a extremo, frente a 59,3 % de v1.** En crudo: el enrutamiento ya funciona (57 de 59 emiten `B:`) y la frase esperada está
  en los resultados, pero el núcleo copia mal los términos técnicos ingleses raros (p. ej. `ngIf` → «NgModel») o se abstiene. No lo arregla un LoRA: lo limita la tabla de embeddings.
- **`tono_conciso` (redacción): 22,5 % frente a 37,5 % de v1.** **Ortografía exacta ≈ 15 %** (como v1: 14 %): sigue siendo candidata a una herramienta léxica determinista.
- **`concepto_reservado`** (conceptos de programación que el enrutador no ha visto): 40,8 % extremo a extremo (53,1 % forzado). Sin una pista como «en código», el enrutador no
  sabe que un término raro es de programación; no se añadieron reglas laxas para no generar falsos positivos.
- **La charla es de plantillas** (39 intenciones con 40–51 frases base y 2–5 respuestas cada una). No es conversación abierta; para eso haría falta un modelo auxiliar y verificación automática.
- **Temperatura exacta:** ddgs devuelve páginas de pronóstico sin una cifra legible; la consulta mixta «hora + temperatura» responde la hora (reloj del equipo) y cita la fuente del clima, pero no da el número.
- **El evaluador de conceptos y gramática no reservados comparte conceptos con el entrenamiento por diseño** (mide reformulaciones); las medidas más honestas son los tipos `*_reservado/a`.

## 2. Benchmarks de sistema (CPU, motor C++, 25 prompts reales de ddgs, mismas preguntas, 3 de calentamiento)

| | v1 | v2c |
|---|---|---|
| núcleo `.bin` en disco | 41,3 MB | 54,9 MB |
| cada LoRA | 2,6 MB | 7,9 MB |
| RAM pico, núcleo solo | 110 MB | **127 MB** |
| RAM pico, con 1 LoRA | 112 MB | 136 MB |
| RAM pico, 2 LoRA en caché (código activo) | 115 MB | **143 MB** |
| carga del núcleo | 0,08 s | 0,02 s |
| prefill (~115 tokens) | 50 ms | 202 ms |
| ms/token | 1,52 | 5,58 |
| tokens/s | 656 | **179** |
| palabras/s (todos los hilos) | 427 | **118** |
| palabras/s (1 hilo) | 100 | 26 |
| palabras por token (respuestas en español) | 0,65 | 0,66 |

v2c es **≈ 3,7 veces más lento** y usa **≈ 28 MB más de RAM** que v1, y la mejora de palabras por token en español es mínima; la ganancia del vocabulario de 24 k está en código
(3,3 tokens por palabra en Python frente a 6,0). 118 palabras/s sigue siendo muy superior a la lectura humana. Detalle: `resultados/ETAPA4_benchmark_v1_v2c.md` y `.json`.

## 3. Cómo se llegó (resumen por fase)

1. **Datos (Fase 1):** tokenizador ByteLevel BPE de 24.000 (+4 etiquetas = 24.004) y corpus de **4.000 M de tokens** (wiki 600 M, web latam 1.350 M, web otras 1.650 M, código 400 M) con descontaminación
   (0 coincidencias de 13 gramas con los conjuntos de evaluación). Licencias en `estudios/ETAPA4_FASE1_datos.md`.
2. **Preentrenamiento (Fase 2):** v2-A (22 capas, d = 768, GQA 12/4, ff 3072, contexto 1.024, embeddings atados int8 por fila), **122.069 pasos = 4.000 M de tokens, una época**, currículo 512 → 1.024,
   ≈ 56 h en una GPU de 16 GB. Documento: `estudios/ETAPA4_FASE2_pretrain.md`.
3. **SFT conjunto → v2b:** 158.885 ejemplos (hechos/búsqueda, abstención, **charla ampliada de 39 intenciones**) + 11.280 filas de copia técnica, 3 épocas, lr 2e-4. Resolvió el techo de los LoRA
   de la primera versión (los LoRA no podían mover los embeddings de salida de los tokens raros; con los embeddings entrenables una prueba de sobreajuste bajaba de 0,96 a 0,000).
4. **Micro-SFT → v2c:** 53.131 filas (42 % habilidades de copia y transformación: «Imprime X», bloques con sangría, errores de ejecución, tono, ortografía, documentación; 58 % repaso de hechos,
   abstención, charla y gramática), 2 épocas, lr 1e-4, **0 fugas verificadas**. `ejec_ok` pasó de 0 % a 99,3 %. Salvo la etiqueta, no se tocó nada del protocolo.
5. **Expertos LoRA sobre v2c:** r = 16, α = 32, lr 1e-3, en qkv/proy/fc1/fc2 de las 22 capas. Código (`codigo_g`): 26.293 filas con **formulaciones variadas** y repaso, parada temprana desde el paso 1.000.
   Redacción (`redaccion_f`): 21.015 filas con formulaciones variadas, 4 épocas. Las formulaciones del evaluador **no** se copiaron al entrenamiento (se usaron sinónimos cercanos) para que siga midiendo generalización.
6. **Integración:** `inferir.py` usa v2c por defecto (motor C++, caché de 2 ranuras, `EnrutadorV2`, `tiempo_real.py` para hora/fecha del reloj, clima con lugar y datos en vivo vía búsqueda). `--v1` abre el respaldo.

## 4. Rutas de producción y respaldo

| | ruta |
|---|---|
| núcleo v2c (producción) | `modelos/nucleo_v2c_sft.bin` (+ `nucleo_v2c_sft.vocab.json`; el tokenizador que usa `FormatoV2` es `datos/v2/tokenizador_v2_sft.json`, idéntico) |
| experto de código | `modelos/experto_codigo_g_v2.lora` |
| experto de redacción | `modelos/experto_redaccion_f_v2.lora` |
| respaldo íntegro de v1 | `modelos/v1_respaldo/` (copias; los originales siguen en `modelos/` sin tocar) |
| checkpoint PyTorch de v2c y de v2b (para seguir entrenando) | `modelos/experimentos/nucleo_v2c_sft.pt` · `nucleo_v2b_sft.pt` (no versionados: pesan > 600 MB) |
| preentrenado v2-A | `modelos/experimentos/pretrain_v2/nucleo_v2_pretrain.pt` (no versionado) |

Uso: `python inferir.py` (chat con v2c) · `python inferir.py "pregunta"` · `python inferir.py --v1 --motor --experto modelos/experto_codigo.lora` (respaldo).

## 5. SHA-256 congelados

**v2c (producción):**

| archivo | SHA-256 |
|---|---|
| `modelos/nucleo_v2c_sft.bin` | `4c0772e6dec81df863ddf27ab00838ea2242add0ebd1f3acee154d022bb3bc41` |
| `modelos/nucleo_v2c_sft.vocab.json` | `7a3375c1482c57cc25d90b15ed043927d81e260784b1a0f40909f9a200e2aab4` |
| `modelos/experto_codigo_g_v2.lora` | `e70d28fecbe2e5d98cd7a1530ce5756ac46e1d1706c9ce263ee76ef27ea82d3a` |
| `modelos/experto_redaccion_f_v2.lora` | `21b8beb3558111a7d4ded9936e3f6f0208fbaa25fa046f82f80f0ab741b614b4` |
| `modelos/experimentos/nucleo_v2c_sft.pt` | `2f572f166d3a6afb9180129dcafb970b827c818dbf3dc3f45eec2357c821a648` |

**v1 (respaldo, verificado intacto antes y después de copiar a `modelos/v1_respaldo/`):**

| archivo | SHA-256 |
|---|---|
| `nucleo_sft_v3.pt` | `a867d741e0e65aa752757080fd4957abb871df6de75c0ef3e3a8fbd1c176717d` |
| `nucleo_sft_v3.bin` | `17ecdbdaafba9c61ad0f08a633982118c0e205b130839b27fa5fc27204e0b540` |
| `experto_codigo.lora` | `b57032631efdcdb6eec0c883207bad64a23e91f65eb21792095bdfb2110278c6` |
| `experto_redaccion.lora` | `3ec614b0ba4ecd5538d2557730c914506054adfd618c77711b19e3ed54696018` |

Los hashes están además en `resultados/ETAPA4_v2c_congelados.json`, `modelos/NUCLEO_V2C.json` y `modelos/v1_respaldo/SHA256_v1.json`.

## 6. Trabajo pendiente (fuera de la Etapa 4)

1. `doc_ok` y términos técnicos ingleses: un micro-SFT con más inglés técnico, o una herramienta de copia exacta de fragmentos.
2. Ortografía exacta y `tono_conciso`: herramienta léxica determinista para la ortografía; datos para el tono conciso.
3. Enrutador: reconocer conceptos de programación fuera del léxico de entrenamiento sin falsos positivos (p. ej. con una señal del propio núcleo).
4. Conversación abierta: generar datos con un modelo auxiliar abierto y verificarlos automáticamente; hoy la charla es de plantillas.
5. Velocidad: v2c es 3,7× más lento que v1; revisar la caché de claves/valores y el prefill por bloques del motor si se quiere acercar a v1.
6. Temperatura exacta: leer el contenido de la página de pronóstico (no solo el fragmento de ddgs).

## 7. Reproducción (resumen)

```
python fase1_datos.py …                      # tokenizador y corpus
python pretrain_v2.py [--reanudar]           # 122.069 pasos, checkpoints cada 3.000
python sft_datos_v2.py --charla 30000 --sufijo _v2b && python cadena_v2b.py     # SFT conjunto -> v2b
python microsft_datos_v2.py && python cadena_v2c.py 1                            # micro-SFT -> v2c
python variedad_v2.py && python entrenar_lora_v2.py --nombre codigo_g … --min_pasos 1000   # LoRA
python evaluar_expertos_v2.py · evaluar_extremo_v2.py · evaluar_enrutador_v2.py · benchmark_v2.py
```
Cada paso está documentado en `estudios/ETAPA4_FASE*.md` y sus logs en `resultados/ETAPA4_*`.

## 8. Addendum (misma fecha): reglas de búsqueda de respaldo en la capa de inferencia

Solo para v2c y solo en el flujo interactivo (`inferir.responder(..., extras=True)`); los evaluadores no pasan por ahí y sus métricas no cambian
(`evaluar_v2.py` sobre producción: hechos 83,3 %, abstención 100 %/100 %, simulado 91,0 %, charla 79,9 %, idénticas a antes del cambio; `resultados/ETAPA4_eval_v2c_final.json`).

1. **Abstención sin búsqueda previa** → se fuerza una búsqueda en ddgs con la pregunta limpia de rodeos («quería saber…», «me gustaría saber…», «sabes…», «dime…») y se le devuelven los resultados
   al núcleo; si tras buscar no hay evidencia, se mantiene la abstención.
2. **Orden de buscar sobre el turno anterior** («¿puedes buscarlo?», «búscalo», «investígalo», «búscalo en internet») → busca la última consulta informativa de la sesión; sin tema previo pide el tema.
3. En esas búsquedas forzadas se restauran **tildes y mayúsculas con evidencia de los resultados** (el núcleo se abstiene con «ley de morgan en matematicas» y responde con «ley de Morgan en matemáticas») y se aplica una
   **reparación de cita**: la respuesta se sustituye por la oración exacta de los resultados más parecida; si ninguna se parece (< 0,75) se mantiene la abstención. Motivo: tras un fragmento truncado el núcleo cambiaba
   palabras («formuladas» → «ordenadas») y seguía con texto incoherente.

4. **Extensión a todas las búsquedas de v2c** (también cuando el propio núcleo emite `B:`): se restauran tildes/mayúsculas (evidencia de los resultados y, sin ella, el corrector determinista del proyecto)
   y se repara la cita; una respuesta que ya es una cita literal de los resultados no se toca. Medido sobre las 287 preguntas reales de ddgs pasando por `responder()` completo:

   | | sin reglas (v1 y base) | con reglas (v2c) |
   |---|---|---|
   | hechos (respuesta exacta, 222) | 185 (83,3 %) | **208 (93,7 %)** |
   | abstención en irrelevantes (52) y vacíos (13) | 52 + 13 | **52 + 13 (100 %)** |
   | abstenciones indebidas | 0 | 3 |

5. **Hallazgo — la charla ampliada interfiere con preguntas de contenido con otra forma.** «¿Cuál es la capital de Perú?» (incluso con tildes perfectas) recibía la plantilla `tiempo_real` («No tengo datos en vivo…») y
   «¿Quién fue Gabriela Mistral?» recibía la presentación de TEST-IA; los benchmarks no lo veían porque las preguntas de hechos usan «Explícame…» / «¿Qué es…?». Mitigación en la capa de inferencia: si el núcleo responde
   una plantilla de charla a una **pregunta de contenido sobre el mundo** (marcos «qué/cuál es…», «quién fue…», «dónde queda…», «cuántos … tiene…», «dime la/el…»; no sobre el propio asistente ni clima sin lugar) sin haber buscado, se fuerza la búsqueda.
   De las 339 frases de charla reservadas, solo 5 disparan búsqueda y las 5 son datos en vivo legítimos (dólar, resultados, inflación). **La causa de fondo está en los datos del SFT y se corregiría con un micro-SFT que añada preguntas de
   contenido con esas formas** (queda como trabajo pendiente).

Nota: ddgs devuelve resultados distintos entre llamadas; con resultados sin evidencia el núcleo se abstiene (comportamiento correcto), así que la misma pregunta puede responder o abstenerse según el momento.
