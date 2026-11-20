# Etapa 2 · Paso 1 — Generador de datos y sandbox (2026-11-20)

Cumple el [diseño](ETAPA2_DISENO_experto_codigo.md) con los dos ajustes pedidos: **presupuesto estricto de 512 tokens** y
**sin generación libre de código** (su 5 % pasó a documentación y ejecución verificada). Nada de esto toca el Núcleo Base.

## Qué se construyó

| Archivo | Función |
|---|---|
| `sandbox.py` | Ejecuta código de Python del modelo (`E:`). Solo `math`. 25/25 pruebas propias (13 ejecuciones correctas y 12 ataques bloqueados) |
| `experto_fichas.py` | 107 fichas de conceptos, 65 conceptos de cola, 175 APIs (Angular, pandas, numpy, React, SQL, git…) y generador de nombres inventados |
| `recolectar_docs.py` | 402 consultas **reales** a ddgs (APIs, conceptos de cola, funciones inventadas) |
| `experto_datos.py` | Genera `datos/experto_train.jsonl` y `datos/experto_eval.jsonl` |
| `herramientas.py` | `buscar_web(consulta, modo="codigo")`: acepta inglés técnico, fragmentos de 150 caracteres, español antes que inglés |
| `protocolo.py` | Prefijo `E:` además de `B:` y topes de tokens por herramienta |

## Presupuesto de contexto (512 tokens)

El tokenizador nunca vio código: 1,8 caracteres por token contra 4,7 en español. Por eso:

| Pieza | Tope | Cómo se cumple |
|---|---|---|
| Resultados de documentación (`B:`) | 200 tokens | 3 resultados con fragmento de 150 caracteres; si no caben se quitan resultados desde el final, conservando el que trae la respuesta |
| Salida del sandbox (`E:`) | 80 tokens, 100 caracteres | Solo el resultado o la **última línea** de la excepción, sin traza |
| Ejemplo completo | 440 tokens | Se mide cada ejemplo; los que exceden se **descartan** (nunca se truncan en silencio) |

Resultado medido en el dataset: **media 128 tokens, p99 265, máximo 315** (contexto 512). Solo 1 de 14.000 ejemplos se descartó.

## Sandbox

Capas: (1) lista blanca por AST (solo `import math`; sin `open`, `exec`, `eval`, `getattr`, `__import__`, atributos con `__`,
`str.format`, async, enteros o potencias enormes); (2) proceso hijo con builtins mínimos y un `__import__` que solo deja pasar `math`;
(3) timeout de 3 s y, en Windows, objeto Job con tope de 256 MB y sin procesos hijos. Respuestas: resultado impreso, valor de la
última expresión, o `NombreDelError: mensaje`.

Dos tropiezos corregidos: el lanzador del venv crea un segundo proceso y chocaba con el límite de procesos del Job (se usa el intérprete
base), y había que declarar los tipos de las funciones de ctypes.

## Dataset (14.000 ejemplos de entrenamiento, 1.007 de evaluación)

| Dominio | Ejemplos | Qué enseña |
|---|---|---|
| Conceptos (25 %) | 3.500 | 81 fichas entrenadas (26 reservadas) × 7 formas de preguntar, más ejemplos de código. `R:` directo |
| Documentación (27,5 %) | 3.850 | `B:` con resultados reales de ddgs → copiar la oración correcta (726 casos distintos × 6 formulaciones) |
| Ejecución (22,5 %) | 3.150 | `E:` con resultado real del sandbox: salidas correctas, errores y su interpretación, y explicar un error pegado sin herramienta |
| Abstención (15 %) | 2.100 | 828 búsquedas reales con funciones/librerías inventadas → «no tengo información»; `NameError` de funciones inexistentes; código no permitido |
| Repaso Etapa 1 (10 %) | 1.399 | Conversación, hechos y abstención generales |

Evaluación (solo reservado): conceptos conocidos con formulaciones nuevas (477), **conceptos reservados que el experto debe buscar** (52),
documentación real con APIs no vistas (59 con respuesta, 119 de abstención) y 290 casos de ejecución con códigos que no aparecen en el
entrenamiento. Comprobado: **0 códigos, 0 consultas, 0 preguntas y 0 definiciones reservadas en común** entre entrenamiento y evaluación.

## Lo que hay que saber

- **Las oraciones de documentación están, en su mayoría, en inglés** (la documentación técnica casi siempre lo está). El experto aprenderá a
  copiar la oración correcta, no a traducirla. Los resultados en español van primero cuando existen. Si se prefiere respuesta en español,
  habría que traducir o escribir las respuestas a mano.
- **Evaluación de documentación pequeña** (59 casos con respuesta). Sirve para detectar problemas grandes, no diferencias de pocos puntos.
- **La evaluación no incluye código no permitido** (`ejec_noperm`): las variantes disponibles se agotaron contra el entrenamiento; queda cubierto
  por las pruebas de `sandbox.py`.
- **Datos de documentación repetidos ×5,3** en promedio (726 casos reales para 3.850 ejemplos), igual que en la Etapa 1 (×3 de lo real).
- **Los ejemplos ya vienen medidos**, pero `ajustar.py` aún no entrena LoRA: es el Paso 2 (`lora.py`, `--lora`).
- `ajustar.py` ya acepta filas con `pref` (B/E) y `tope`, así que el formato nuevo se puede entrenar sin más cambios.
