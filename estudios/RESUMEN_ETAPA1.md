# Resumen técnico — Etapa 1: Núcleo Base (cerrada 2026-11-20)

Núcleo de 48 M parámetros, BitNet, preentrenado en español, ajustado para **buscar, leer y abstenerse**, y
ejecutable en C++ nativo. Continúa el formato de [RESUMEN_ESTUDIOS.md](RESUMEN_ESTUDIOS.md) (prototipos de 0,4–0,8 M).
Registros y tablas originales: [etapa1/](etapa1/).

## Núcleo Base congelado (no se vuelve a entrenar)

| Archivo | Tamaño | SHA-256 |
|---|---|---|
| `modelos/nucleo_sft_v3.pt` (entrenamiento, pesos en decimales) | 192,5 MB | `A867D741…176717D` |
| `modelos/nucleo_sft_v3.bin` (empaquetado, motor C++) | 41,3 MB | `17ECDBDA…0E540` |
| `modelos/nucleo_sft_v3.vocab.json` (tokenizador) | 1,1 MB | `7F35E88D…D13E2` |

Hashes completos en `modelos/NUCLEO_BASE.json`; los tres archivos quedaron en solo lectura. `nucleo_es_bitnet.pt` es el
preentrenado sin ajuste fino (punto de partida; se conserva).

Arquitectura: Transformer de 10 capas, d=512, 8 cabezas, contexto 512, vocabulario BPE de 16.004 (16.000 + 4 etiquetas
de turno). Capas lineales de los bloques en BitNet (pesos {-1,0,+1} × escala por matriz); embeddings y salida en
precisión normal.

## 1. Preentrenamiento en español

- **Corpus:** 336 M tokens = Wikipedia en español (700 MB) + FineWeb-2 español filtrado a dominios latinoamericanos
  (.cl, .mx, .ar, .co, .pe…, 700 MB). Tokenizador BPE de 16 k entrenado sobre ese texto.
- **Entrenamiento:** 27.960 pasos × 32.768 tokens = 916 M tokens (≈2,7 vueltas al corpus), 164 min en la RTX 5060 Ti, bf16.
- **Resultado:** pérdida de validación 3,48, **perplejidad 32,4**.
- **Comprobación de que necesita herramientas:** escribe español gramatical con el estilo de páginas web, pero no sabe
  hechos y los inventa con seguridad. «Un banco de arena es…» → «un lugar para el turismo»; «La capital de Chile es…» →
  «la ciudad más poblada del país, con una población de aproximadamente 1.000 habitantes». Se repite en textos largos.
  Esto es lo esperable a 48 M y respalda la tesis: el núcleo aporta lenguaje, el conocimiento viene de fuera.

## 2. Ajuste fino (SFT): v1 → v3

Protocolo: `<usuario> pregunta <asistente> B: consulta <herramienta> resultados <asistente> R: respuesta <fin>` (o
`R:` directo). Solo se entrena lo que escribe el asistente. La parada del modelo es `<fin>` o `<herramienta>`; la
penalización por repetición (1,1) solo actúa sobre lo generado en el turno.

| Versión | Datos de entrenamiento | Evaluación simulada | Evaluación con ddgs **real** (287 casos) |
|---|---|---|---|
| v1 | 48.000 ejemplos con resultados simulados (artículos de Wikipedia como fragmentos limpios) | hechos 80,7 % exacta, abstención 95–100 % | **hechos 18,0 % exacta**, abstención 98,1 % / 100 % |
| v2 | + 1.293 ejemplos reales de ddgs ×3, tareas mecánicas fuera | hechos 83,3 %, abstención 98–100 %, directo 100 % | hechos 70,7 % exacta |
| **v3** | igual que v2, con el formato idéntico al de producción (título recortado a 60, tope de 330 tokens de resultados, filtro de alfabetos no latinos) | hechos 83,7 %, abstención 99–100 %, directo 100 % | **hechos 71,6 % exacta**, abstención **98,1 %** (otro tema) y **100 %** (sin resultados) |

Fidelidad de copia de v3 con ddgs real (similitud de texto frente a la oración correcta): **≥ 95 %: 86,5 %**,
**≥ 85 %: 91,9 %**, < 60 %: 6,8 %. Solo el 2 % de las respuestas fueron abstenciones indebidas. La métrica «exacta»
(71,6 %) es estricta: la mayoría de los fallos son copias con una palabra deformada («transfiánico» por
«transoceánico»), y algunos son variantes legítimas porque el fragmento de ddgs difiere del artículo.

Lección principal: **evaluar con resultados simulados engaña.** v1 parecía bueno (81 %) y con ddgs real caía a 18 %. Lo
que arregló la copia fue entrenar con resultados reales y ruidosos, tratados con la misma limpieza que en producción.

Datos reales: 2.350 consultas a ddgs (15 % con palabras inventadas), 1.295 ejemplos utilizables
(1.065 con respuesta, 180 irrelevantes, 50 vacíos), repetidos ×3. Evaluación sobre artículos reservados que el entrenamiento nunca vio
(partición por hash del título).

## 3. Búsqueda limpia y capa 1

- **`buscar_web` (ddgs, sin clave):** pide 8 resultados y entrega los 3 mejores con título + fragmento de ~200
  caracteres. Limpia fechas sueltas, etiquetas PDF, pronunciaciones y notas `[3]`; descarta inglés/francés/portugués,
  alfabetos no latinos, otras ediciones de Wikipedia y duplicados; pone Wikipedia en español primero. Un reintento ante
  timeout y, si falla, devuelve «Sin resultados.» (el modelo se abstiene; un timeout se ve igual que una búsqueda vacía).
- **`capa1()` (Python, sin red neuronal):** cuentas, mayúsculas, minúsculas, repetir, contar, ordenar e invertir. Estas
  tareas salieron del SFT: el modelo las aprendía mal (producía «BOSGER A PARTE…» con mayúsculas) y no hay motivo para
  gastar parámetros en lo que Python hace exacto. El SFT queda solo para lectura de resultados y conversación.

## 4. Motor C++ nativo vs PyTorch

`motor.cpp` (MSVC 2019, AVX2 + OpenMP, 142 KB de DLL), formato binario propio NUCL0001: pesos ternarios a 2 bits,
embeddings y salida en fp16, caché de claves/valores. Verificación: logits coinciden con PyTorch fp32 (diferencia
máxima 0,006 sobre escala ~19) y el mismo token siguiente en 80/80 prompts; en la evaluación con ddgs real da exactamente
71,6 % / 98,1 % / 100 %, igual que PyTorch.

25 preguntas reales (prompts de ~119 tokens), cada backend en un proceso aparte:

| Backend | RAM pico (proceso) | VRAM | ms/token | tokens/s | Prefill |
|---|---|---|---|---|---|
| PyTorch GPU (bf16) | 1.535 MB | 233 MB | 11,5 | 87 | 9,7 ms |
| PyTorch CPU (fp32) | 1.116 MB | — | 35,7 | 28 | 33,3 ms |
| **C++ (todos los hilos)** | **111 MB** | **0** | **1,46** | **685** | 51,4 ms |
| C++ (1 hilo) | 108 MB | 0 | 6,39 | 156 | 154 ms |

Las respuestas fueron idénticas a PyTorch CPU en los 4 backends (25/25).

Cuidado al leer la tabla: (1) PyTorch recalcula toda la secuencia en cada token, como `inferir.py`; el motor C++ usa
caché de claves/valores. Con caché PyTorch bajaría. (2) El C++ es más lento al procesar el prompt (prefill): el matmul
desempaqueta cada fila y no está optimizado por bloques. En una respuesta de ~40 tokens el total sigue ganando.
(3) «RAM» es la memoria de trabajo del proceso; en PyTorch incluye las bibliotecas de torch y CUDA.

## Límites y pendientes (decididos: no se atacan ahora)

- 8 % de las respuestas deforman una palabra al copiar; límite de 48 M parámetros.
- Los resultados cuyo fragmento empieza por un pie de foto producen respuestas fieles pero inútiles («banco de arena en
  el mar de Frisia…»).
- 32 de los 41 MB del `.bin` son embeddings y salida en fp16; los pesos ternarios son 7,8 MB.
- Prefill del C++ sin optimizar. El tokenizador sigue en Python (el motor recibe ids).
- BitNet aquí cuantiza solo pesos; el ahorro real de RAM llega con el motor C++ (empaquetado en memoria), no con PyTorch.
