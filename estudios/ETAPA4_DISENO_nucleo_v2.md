# Etapa 4 — Diseño del Núcleo Base v2 (propuesta, sin entrenar todavía)

Fecha: 2026-11-20. Estado: **diseño aprobado (decisiones en §12)**. No se entrena nada hasta pasar la «Fase 0» (benchmark del motor con pesos aleatorios, §9).
Punto de partida congelado: tag `etapa3-cierre` (núcleo v1 de 48 M + expertos de código y redacción). v1 se conserva como respaldo; ningún peso congelado se toca.

## 0. Resumen
| | Núcleo v1 (hoy) | **v2-A (recomendado para empezar)** | v2-B (techo del rango) |
|---|---|---|---|
| Parámetros totales | 48 M | **≈ 158 M** | ≈ 235 M |
| Arquitectura | 10 capas, d=512, 8 cabezas, ff 2048 | **22 capas, d=768, 12 cabezas (4 KV), ff 3072** | 19 capas, d=1024, 16 cabezas (4 KV), ff 4096 |
| Ventana | 512 tokens | **1.024** | 1.024 |
| Vocabulario | 16.004 | **24.004** (los 4 especiales conservan sus nombres) | 24.004 |
| En disco (.bin) | 41 MB | **≈ 55 MB** (≈ 74 MB con embedding fp16) | ≈ 79 MB (≈ 104 MB con fp16) |
| RAM del proceso en C++ (núcleo + 2 LoRA + herramientas) | 116 MB | **≈ 141–160 MB** | ≈ 166–190 MB |
| Velocidad en CPU (todos los hilos / 1 hilo) | 1,46 ms/tok (685 tok/s) / 6,4 ms | **≈ 5,8 ms (≈ 170 tok/s) / ≈ 25 ms** | ≈ 8,6 ms (≈ 115 tok/s) / ≈ 38 ms |
| Preentrenamiento estimado (1 GPU, RTX 5060 Ti) | 164 min, 0,9 B tokens | **≈ 2 días, 4 B tokens** | ≈ 4,4 días, 6 B tokens |

**Propuesta:** construir v2-A primero (cabe con 40–60 MB de holgura bajo 200 MB y se entrena en días en la GPU actual; v2-B queda ajustado con embedding fp16); pasar a v2-B solo si v2-A supera los criterios de la §7 pero se queda corto en fluidez.
Las dos opciones exigen **tres cambios en `motor.cpp`** sin los cuales el techo de 200 MB no se cumple (KV en fp16, atención con grupos de KV y prefill por bloques, §3.2). Todo lo demás —protocolo `B:` / `E:` / `R:`, capa 1, memoria, enrutador, fichas, sandbox, corrector, LoRA— se reutiliza tal cual (§8).

## 1. Lo que sabemos del núcleo v1 (medido)
- 48 M parámetros: 10 capas, d=512, 8 cabezas, ff=2048, vocabulario 16.004, BitNet en las capas lineales de los bloques (31,4 M ternarios); embeddings de entrada y **cabeza de salida separados** (2 × 16.004 × 512 en fp16).
- Disco 41,25 MB: **32,8 MB (80 %) son los dos embeddings en fp16**, 7,9 MB los pesos ternarios a 2 bits, 0,5 MB las posiciones. Es decir: en v1 el vocabulario pesa más que el «cerebro».
- RAM del proceso 110,6 MB sin adaptadores y 116,0 MB con dos (cada LoRA r=16 suma 2,6 MB). Línea base del proceso (Python + tokenizador + DLL) ≈ 28 MB; caché de claves/valores en fp32 y sin grupos: 10 capas × 2 × 512 × 512 × 4 B = 21 MB.
- Velocidad (Ryzen 7 7800X3D, 8 núcleos/16 hilos, 31 GB): 1,46 ms/token con todos los hilos (685 tok/s), 6,39 ms con 1 hilo, prefill de un prompt de 119 tokens en 51 ms. Trabajo por token ≈ 39,6 M MAC (31,4 M ternarios + 8,2 M de la cabeza).
- Entrenamiento: 27.960 pasos × 32.768 tokens = 916 M tokens en 164 min ⇒ ≈ 93.000 tokens/s en la RTX 5060 Ti (bf16, BitNet con STE).
- Resultados a superar (ddgs real): hechos 71,6 % exacta, abstención 98,1 %, conversación 100 %. Los modelos pequeños escriben español gramatical pero rígido: respuestas cortas, plantilladas, sin hilo conversacional (la memoria de trabajo de 80 tokens es un parche).

## 2. Objetivos y no-objetivos
**Objetivos**
1. *Fluidez conversacional y personalidad propia:* diálogo natural en español (registro latinoamericano neutro, tono cercano y claro), explicaciones en 3–6 oraciones, síntesis de los resultados de `B:` con palabras propias cuando conviene (hoy copia la primera oración) y coherencia en conversaciones de varios turnos.
2. *Compatibilidad total:* mismos protocolos y mismas herramientas (§8); v2 es un reemplazo de pesos, no una reescritura.
3. *Presupuesto:* < 200 MB de RAM total en C++ con núcleo + 2 adaptadores + herramientas; respuesta de 60 tokens en < 0,5 s en CPU.
4. *Sin regresión:* igualar o superar a v1 en hechos, abstención y conversación con las mismas evaluaciones (§7).

**No-objetivos:** razonamiento complejo, matemáticas, código largo (eso es del experto + sandbox), multimodalidad, memorizar conocimiento (sigue viviendo en herramientas), cambiar el formato de turnos.

## 3. Arquitectura propuesta

### 3.1 Dimensionamiento
Parámetros ternarios por capa: sin GQA 12·d²; con GQA (kv_dim = 256) `2d² + 2·d·256 + 8d²` ⇒ 6,29 M (d=768) y 11,0 M (d=1024). Embeddings **atados** (entrada = salida): V·d una sola vez.

| | d | capas | cabezas / KV | ff | ternarios | embedding (atado) | total |
|---|---|---|---|---|---|---|---|
| v1 | 512 | 10 | 8 / 8 | 2048 | 31,5 M | 2 × 8,2 M (separados) | 48 M |
| **v2-A** | 768 | 22 | 12 / 4 | 3072 | 138,4 M | 24.004 × 768 = 18,4 M | ≈ 158 M (con posiciones y LN) |
| v2-B | 1024 | 19 | 16 / 4 | 4096 | 209 M | 24.004 × 1024 = 24,6 M | ≈ 235 M |

Elecciones y por qué:
- **Más profundidad que anchura** (22 capas de d=768 en vez de 14 de d=1024): a igual tamaño suele dar mejor modelado de lenguaje en modelos chicos; el costo es latencia por token, que ya cabe en el presupuesto.
- **Se mantiene** lo que el motor ya hace bien: LayerNorm, GELU, posiciones aprendidas (tabla de 1.024 × d: 1,6 MB), BitNet ternario en qkv/proy/fc1/fc2, `vueltas = 1`. Cambiar a RMSNorm/SwiGLU/RoPE puede mejorar algo la perplejidad, pero cada cambio exige nuevos kernels y verificación; se deja como mejora opcional de una v2.1.
- **Vocabulario 24.004** (v1: 16.004): más cobertura de español (acentos, plurales, conjugaciones) acorta las secuencias ≈ 8–10 %, lo que compensa el costo de la cabeza. Las 4 etiquetas `<usuario> <asistente> <herramienta> <fin>` más `<|relleno|>` se buscan **por nombre** (`protocolo.Formato` ya lo hace), así que el cambio de ids no rompe nada.
- **Embeddings atados + int8:** ahorra 18–25 MB frente a dos tablas fp16. Cuantizar el embedding a int8 (escala por fila) ahorra otros 18–25 MB; se decide en la Fase 0 según el impacto medido en perplejidad.

### 3.2 Cambios requeridos en `motor.cpp` (los únicos «grandes»)
Sin ellos el techo de RAM no se cumple. Con ventana de 1.024 la caché KV es el consumidor dominante:

| Caché KV (v2-A: 22 capas, d=768) | Tamaño |
|---|---|
| fp32, sin grupos (como v1) | 22 × 2 × 1024 × 768 × 4 B = **138 MB** ✗ |
| fp16, sin grupos | 69 MB |
| **fp16 + 4 cabezas KV (GQA, kv_dim=256)** | **23 MB** ✓ |
| int8 + GQA (opcional) | 12 MB |

1. **KV en fp16** (conversión al escribir/leer; el cómputo de atención sigue en fp32).
2. **Atención con grupos de consulta (GQA):** `n_kv_heads` < `n_heads`; cada grupo de 3 cabezas comparte K y V. La proyección qkv pasa de salida 3d a `d + 2·kv_dim`.
3. **Prefill por bloques de 128 tokens:** hoy el prefill materializa activaciones de todo el prompt (n × ff × 4 B = 12 MB por buffer con 1.024 tokens y ff=3.072; varios buffers ⇒ ~50 MB). En bloques de 128 cabe en ~8 MB sin cambiar el resultado numérico.
4. **Formato `.bin` NUCL0002:** cabecera con `n_kv_heads`, vocabulario, embedding atado (`cab` ausente) y tipo de embedding (fp16 | int8). El cargador sigue aceptando NUCL0001 (v1 funciona sin cambios).
5. **Formato `LORA0002`:** hoy `LORA0001` supone qkv de salida 3d; con GQA la salida es `d + 2·kv_dim`. El nuevo formato guarda las dimensiones por matriz; la lógica de caché multi-slot (Activo/Tibio/Frío) no cambia.
La verificación sigue el método de la Etapa 2: logits del motor vs PyTorch fp32 (diferencia máxima < 0,01 y mismo token siguiente en 100 % de los prompts) y bit-exactitud entre configuraciones de adaptadores.

## 4. Estimaciones de tamaño, RAM y velocidad
Supuestos explícitos (a validar en la Fase 0 con pesos aleatorios, antes de gastar horas de GPU): embedding atado, KV fp16 + GQA, prefill por bloques, ternarios a 2 bits + escalas, adaptadores LoRA r=16 en fp16, línea base del proceso ≈ 28 MB.

### 4.1 En disco
| | v1 | v2-A | v2-B |
|---|---|---|---|
| Pesos ternarios (2 bits) | 7,9 MB | 34,6 MB | 52 MB |
| Embedding atado | 32,8 MB (2 tablas fp16) | 36,9 MB fp16 / **18,4 MB int8** | 49,2 MB fp16 / **24,6 MB int8** |
| Posiciones + LN + escalas | 0,6 MB | ≈ 2 MB | ≈ 2,5 MB |
| **.bin total** | **41,3 MB** | **≈ 55 MB (int8) – 74 MB (fp16)** | **≈ 79 MB – 104 MB** |
| Cada LoRA r=16 (4 matrices, fp16) | 2,6 MB | ≈ 7,9 MB | ≈ 9,1 MB |
(LoRA r=16 = 16·(entrada + salida) por matriz: 180 k parámetros por capa en v2-A y 238 k en v2-B; con r=8 se reduce a la mitad.)

### 4.2 RAM del proceso en C++ (pico)
| Componente | v1 (medido) | v2-A | v2-B |
|---|---|---|---|
| Proceso base (Python + tokenizador + DLL) | ≈ 28 MB | 28 MB | 28 MB |
| Pesos ternarios | 8 MB | 35 MB | 52 MB |
| Embedding | 33 MB | 18–37 MB (int8–fp16) | 25–49 MB |
| Caché KV | 21 MB (fp32, 512) | 23 MB (fp16 + GQA, 1024) | 20 MB |
| Activaciones / buffers | ≈ 12 MB | ≈ 12 MB (prefill en bloques) | ≈ 14 MB |
| 2 LoRA (Activo + Tibio) | 5,2 MB | 16 MB | 18 MB |
| Memoria externa, fichas, léxico del corrector, sandbox | ≈ 9 MB | ≈ 9 MB | ≈ 9 MB |
| **Total** | **≈ 116 MB (medido 116,0)** | **≈ 141–160 MB** | ≈ 166–190 MB |
Techo: 200 MB ⇒ holgura de 40–60 MB en v2-A y de 10–35 MB en v2-B (que con embedding fp16 queda al límite: se exigiría int8). **Sin GQA ni KV fp16 el total de v2-A sería ≈ 255–275 MB: por eso van en el diseño base.** (Suma de componentes: las cifras son estimaciones, no mediciones.)

### 4.3 Velocidad en CPU (Ryzen 7 7800X3D)
Extrapolación lineal desde lo medido en v1 (≈ 39,6 M MAC/token ⇒ 1,46 ms con 16 hilos y 6,39 ms con 1). MAC/token = ternarios + cabeza (+ atención, que a 1.024 tokens de contexto añade ≈ 15–20 %).
| | MAC/token | Decodificación, todos los hilos | 1 hilo | Prefill (≈ ×4–6 por token) |
|---|---|---|---|---|
| v1 (medido) | 39,6 M | 1,46 ms (685 tok/s) | 6,4 ms (156 tok/s) | 0,43 ms/tok (119 tok: 51 ms) |
| v2-A | ≈ 157 M | **≈ 5,8 ms (≈ 170 tok/s)** | ≈ 25 ms (≈ 40 tok/s) | ≈ 1,7 ms/tok ⇒ 300 tok ≈ 0,5 s; 1.000 tok ≈ 1,7 s (+ atención) |
| v2-B | ≈ 234 M | ≈ 8,6 ms (≈ 115 tok/s) | ≈ 38 ms (≈ 26 tok/s) | ≈ 2,5 ms/tok ⇒ 1.000 tok ≈ 2,5 s (+ atención) |
Una respuesta de 60 tokens: v2-A ≈ 0,35 s (decodificación) + prefill del prompt; con memoria externa y fichas, un turno típico de 300 tokens de contexto ≈ 0,9 s en total. Es una **extrapolación** (±30 %): la decodificación está limitada por ancho de banda y caché, no solo por MAC.
Los dos adaptadores siguen conmutándose por puntero (< 1 µs): el costo por token del LoRA activo era +1 % en v1 y escala con r·d, es decir ≈ +2–3 % en v2.

## 5. Datos
Meta: **≈ 4 B tokens** para v2-A (≈ 25 tokens por parámetro no embebido) y ≈ 6 B para v2-B. El corpus actual (336 M tokens: Wikipedia es + FineWeb-2 latam, 1,4 GB) es ≈ 12× más chico y se reutiliza como núcleo de calidad. Fuentes y licencias **deben verificarse una por una antes de usarse**; lo siguiente es la lista candidata, no una afirmación de cifras.

### 5.1 Preentrenamiento (texto)
| Fuente | Rol | Notas |
|---|---|---|
| Wikipedia en español (+ Wikisource, Wikilibros) | base factual y formal | ya procesada (≈ 0,2 B tokens) |
| FineWeb-2 español (`spa_Latn`), filtrado | volumen, español actual | ya usado con filtro de dominios latinoamericanos; ampliar a más dominios y a las particiones de mayor calidad |
| Otros corpus web multilingües (CulturaX/OSCAR es) | volumen adicional | con deduplicación contra FineWeb |
| Libros y prensa de dominio público (Gutenberg es, bibliotecas digitales, legislación y documentos oficiales abiertos) | registro cuidado, narración | pequeña proporción |
| Subtítulos y diálogos transcritos (p. ej. OpenSubtitles es) | ritmo conversacional | **riesgo de licencia/ruido**: usar solo si la licencia lo permite, con filtrado |
Mezcla objetivo: ≈ 15 % Wikipedia/enciclopédico, ≈ 60 % web filtrada, ≈ 10 % libros/prensa, ≈ 10 % diálogos, ≈ 5 % texto de protocolo (resultados de búsqueda tipo ddgs, definiciones). Filtros: idioma (fastText/heurística actual), longitud, deduplicación por hash de n-gramas, eliminación de plantillas y spam, **descontaminación** contra todos los conjuntos de evaluación del proyecto (sft_eval*, experto_eval*, redaccion_eval) por solapamiento de 13-gramas.
Almacenamiento: 4 B tokens en `uint16` (vocabulario < 65.536) ≈ 8 GB; el texto crudo ≈ 18 GB.

### 5.2 SFT conversacional y de protocolo (≈ 150–300 k ejemplos, 3–4 épocas)
| Bloque | Contenido | Fuente / generación |
|---|---|---|
| Protocolo (≈ 50 %) | `buscar_ok`, `irrelevante`, `vacio`, `directo`, memoria (`[memoria]`), abstención honesta | **los generadores actuales** (`sft_datos.py`, resultados reales de ddgs), regenerados con tope de contexto 1.024 y con más variedad de formulaciones |
| Diálogo multi-turno (≈ 25 %) | 2–6 turnos con anáfora, aclaraciones, cambio de tema, seguimientos («¿y eso?») | conversaciones humanas abiertas en español (p. ej. OpenAssistant/oasst2 y el Aya Dataset, **verificando licencia y calidad**) + diálogos construidos por plantillas sobre las herramientas del proyecto |
| Explicación y síntesis (≈ 15 %) | pasar de «copiar la primera oración» a resumir 2–3 resultados en 2–4 oraciones propias, con tope de longitud | pares (resultados reales de ddgs → síntesis) cuya síntesis se **verifica** contra los resultados (cada afirmación debe estar en ellos); sin verificación no entra |
| Personalidad (≈ 10 %) | identidad, tono, límites («no sé», «eso lo busco»), humor suave, cómo habla de sus herramientas | guion de persona escrito a mano (§5.3) + variaciones |
Reglas: ninguna respuesta de entrenamiento se genera con modelos propietarios cuyos términos lo impidan; si se usa un modelo abierto como asistente de redacción de datos, debe ser de licencia permisiva, y cada lote queda registrado (modelo, versión, fecha). El texto de síntesis y de diálogo se **audita por muestreo** (100 ejemplos por bloque antes de entrenar, como se hizo con los tonos).

### 5.3 Personalidad propia
Se define en un documento `persona.md` versionado (nombre, voz, valores, límites) y se aprende **solo por SFT**, sin añadir un rol «sistema» (el protocolo de turnos no cambia). Los hechos de identidad sensibles a deriva (nombre, versión, qué herramientas tiene) se responden desde la **capa 1** de forma determinista, igual que las cuentas; el modelo aporta el tono. Decisiones abiertas para el dueño del proyecto: nombre, registro (neutro vs. chilenismos moderados), nivel de humor, longitud típica de respuesta.

### 5.4 Contexto de 1.024 y formato
- Multi-turno literal con las mismas etiquetas: `<usuario> q1 <asistente> R: a1 <fin> <usuario> q2 <asistente> B: … <herramienta> resultados <asistente> R: a2 <fin>`; la pérdida solo cuenta lo que escribe el asistente (la máscara de `Formato.ejemplo` ya lo hace).
- Presupuestos nuevos (`protocolo.py`): resultados `B:` 330 → **600** tokens, experto 200 → **400**, salida de `E:` 80 → **150**, ejemplo completo 440 → **900**, respuesta máxima 100/140 → **220** tokens. La memoria de trabajo pasa de 80 tokens a **≈ 400** (3–4 turnos literales), que **reemplaza el parche** de concatenar la pregunta anterior.

## 6. Entrenamiento
- **Receta:** la de v1 (BitNet con straight-through, copia en precisión normal, bf16, AdamW, coseno con calentamiento), con `lr` y tamaño de lote reajustados por una corrida corta; embedding atado; `n_kv_heads` en el modelo de PyTorch (`modelo.py`). Reanudable por checkpoints (como `lanzar_preentreno.ps1`).
- **Tiempo estimado** (escalando por MAC/token desde las 93.000 tok/s medidas): v2-A ≈ 23.500 tok/s ⇒ 4 B tokens ≈ **47 h**; v2-B ≈ 15.800 tok/s ⇒ 6 B tokens ≈ **105 h** en la RTX 5060 Ti. SFT: horas. Reentrenar los dos LoRA: ≈ 15–40 min cada uno (v1: 3–8 min).
- **Fases:** (a) *piloto* de 0,5–1 B tokens para validar datos, pérdida y motor (≈ 6–12 h); (b) preentrenamiento completo; (c) SFT de protocolo + diálogo; (d) SFT de persona/síntesis con mezcla de repaso; (e) re-entrenar expertos (código, redacción) sobre v2.
- **Qué se congela y cuándo:** v2 se congela con su SHA-256 (`NUCLEO_V2.json`, solo lectura) solo tras pasar la §7; hasta entonces vive en `modelos/experimentos/`.

## 7. Evaluación y criterios de aceptación
Mismas evaluaciones que v1 (resultados reales de ddgs, evaluaciones reservadas por hash) más las nuevas. v2 se acepta solo si cumple **todo** lo obligatorio:
| Criterio | v1 | Meta v2 | Obligatorio |
|---|---|---|---|
| Hechos con ddgs real (exacta) | 71,6 % | ≥ 78 % | ≥ 71,6 % |
| Abstención (irrelevante / vacío) | 98,1 / 100 % | ≥ 98 / 100 % | ≥ 98 / 100 % |
| Validez del protocolo (B:/R:/E: bien formados) | ≈ 100 % | ≥ 99,5 % en multi-turno | ≥ 99 % |
| Conversación directa (saludos, identidad, tareas de lenguaje) | 100 % | 100 % | ≥ 98 % |
| Coherencia multi-turno (anáfora, 3–5 turnos; evaluación ciega de 100 conversaciones) | no medida | ≥ 70 % «natural y coherente» | superar a v1 por ≥ 20 puntos |
| Síntesis fiel (toda afirmación está en los resultados) | n/a | ≥ 90 % | ≥ 85 % |
| Repetición / degeneración (distinct-2, bucles de tokens) | repite en textos largos | sin bucles en 1.000 respuestas | 0 bucles |
| Persona (sondeos de identidad y tono, 100 preguntas) | n/a | ≥ 95 % | ≥ 90 % |
| Experto de código sobre v2 | 82,2 % | ≥ 82,2 % | ≥ 82,2 % |
| Experto de redacción sobre v2 | 56,2 % | ≥ 56,2 % | ≥ 56,2 % |
| Adaptadores dormidos/tibios = núcleo (bit a bit) | cumple | cumple | cumple |
| RAM total en C++ con núcleo + 2 LoRA | 116 MB | ≤ 165 MB | **< 200 MB** |
| Cambio entre expertos tibios | 0,4 µs | < 10 µs | < 100 µs |
| 60 tokens de respuesta (CPU, todos los hilos) | ≈ 0,1 s | ≤ 0,5 s | ≤ 1 s |
Evaluación humana: ciega y por pares frente a v1 (misma pregunta, orden aleatorio), con rúbrica de 4 ejes (naturalidad, claridad, fidelidad a la fuente, tono). Se publica con tamaño de muestra y criterio de desempate, como en las etapas anteriores (sin cifras «a ojo»).

## 8. Plan de migración compatible
**Principio:** v2 es un reemplazo de pesos detrás de la misma interfaz. Nada del sistema actual cambia de nombre ni de protocolo.
| Pieza | Qué pasa con v2 |
|---|---|
| Protocolo `B:` / `E:` / `R:`, `<fin>`, `<herramienta>`, abstención honesta | **igual**; las etiquetas se resuelven por nombre; solo cambian los topes de tokens (`protocolo.py`) |
| `capa1()` (cuentas, mayúsculas, guardar/olvidar, **corrector ortográfico**) | **igual** (puro Python, no depende del modelo) |
| Memoria externa con enfriamiento (`memoria.py`, `datos/memoria.json`) | **igual**; la memoria de trabajo crece a ≈ 400 tokens con turnos literales |
| Enrutador de 3 estados, fichas locales (107 + 71), búsqueda difusa, sandbox, léxico | **igual** |
| Herramientas (`buscar_web`: memoria → fichas → ddgs) | **igual** |
| `motor.cpp` | + KV fp16, GQA, prefill por bloques, NUCL0002/LORA0002; **sigue cargando NUCL0001/LORA0001** (v1 y sus LoRA funcionan sin cambios) |
| Caché de 2 ranuras (Activo/Tibio/Frío) | **igual** (la API C no cambia) |
| Adaptadores LoRA | **se reentrenan** sobre v2 (las dimensiones cambian), con los mismos datasets y evaluadores; `experto_codigo` y `experto_redaccion` v1 quedan archivados |
| `inferir.py` / `Sesion` | `--nucleo v1|v2` (por defecto v1 hasta aprobar v2); mismo `generar_lote` y mismo `MotorCpp.generar` |
| Scripts de datos (`sft_datos.py`, `experto_datos.py`, `redaccion_datos.py`) | se re-ejecutan con los nuevos topes y el nuevo tokenizador |

**Pasos de migración, con marcha atrás en cada uno:**
1. Congelar v1 (ya hecho: tag `etapa3-cierre`). Crear `modelos/nucleo_v2/` (experimentos) y la rama `etapa4`.
2. **Fase 0 (sin GPU):** modelo de PyTorch con `n_kv_heads`, vocabulario 24 k, atados; exportar un `.bin` NUCL0002 con **pesos aleatorios**; implementar y verificar en `motor.cpp` KV fp16/GQA/bloques contra PyTorch; medir RAM y velocidad reales. **Puerta:** RAM ≤ 175 MB y ≥ 120 tok/s (v2-A, 22 capas) o se ajusta la arquitectura.
3. Tokenizador de 24 k entrenado sobre la mezcla nueva; verificar que `Formato` encuentra las 5 etiquetas por nombre y que `ids_prompt`/`ids_tras_herramienta` no cambian de forma.
4. Datos: ampliar corpus, descontaminar, regenerar SFT con topes nuevos; auditoría manual por muestreo.
5. Piloto (0,5–1 B tokens) → **puerta:** pérdida de validación por debajo de v1 a igual número de tokens, sin divergencia.
6. Preentrenamiento completo → SFT → evaluación de la §7 → **puerta de aceptación**.
7. Reentrenar LoRA de código y redacción sobre v2; re-ejecutar `verificar_multiexperto.py` (adaptado: techo de RAM 200 MB, mismas 6 métricas) y las baterías `probar_memoria.py` / `probar_pulido.py`.
8. Congelar v2 (SHA-256, solo lectura) y recién entonces cambiar el valor por defecto de `--nucleo`. **Marcha atrás:** volver a `--nucleo v1` (los archivos v1 no se tocaron).

## 9. Cronograma por fases (esfuerzo, no fechas)
| Fase | Contenido | Esfuerzo | Puerta |
|---|---|---|---|
| 0 | motor GQA/KV fp16/bloques + benchmark con pesos aleatorios | 2–4 días de trabajo | RAM y velocidad |
| 1 | tokenizador 24 k + corpus ampliado + descontaminación | 3–5 días (la descarga y el procesado dominan) | datos auditados |
| 2 | piloto 0,5–1 B tokens | 6–12 h de GPU | curva de pérdida sana |
| 3 | preentrenamiento v2-A (≈ 4 B tokens) | ≈ 2 días de GPU | pérdida/perplejidad |
| 4 | SFT protocolo + diálogo + síntesis + persona | 1–2 días (datos) + horas de GPU | §7 |
| 5 | LoRA código/redacción sobre v2 + verificación multi-experto | 1 día | métricas Etapa 3 |
| 6 | (condicional) v2-B si v2-A no alcanza fluidez | ≈ 4,4 días de GPU | §7 |

## 10. Riesgos y mitigaciones
| Riesgo | Mitigación |
|---|---|
| La RAM supera 200 MB por la caché o los buffers | decisión de GQA + KV fp16 + bloques ya en el diseño; Fase 0 mide antes de entrenar; palanca extra: KV int8 y embedding int8 |
| La mayor fluidez trae más alucinación (más capacidad para inventar con seguridad) | el protocolo no cambia: SFT con abstención honesta reforzada (mismas proporciones y evaluación con resultados **reales**); criterio obligatorio de abstención ≥ 98 % |
| La síntesis «con palabras propias» se aparta de la fuente | solo se entrena síntesis verificada contra los resultados; métrica de fidelidad; se mantiene el modo «copiar» como opción de la herramienta |
| 4 B tokens de buena calidad en español son difíciles de reunir/limpiar | empezar con el piloto; FineWeb-2 es muy grande, el cuello es el filtrado; si falta calidad, subir repeticiones de Wikipedia/libros hasta ×3 |
| Fuga de evaluación (contaminación) | descontaminación por 13-gramas contra todos los conjuntos del proyecto y hash de títulos reservados |
| Licencias de datos conversacionales | lista de fuentes con licencia registrada; excluir lo dudoso; auditoría de cada lote generado |
| BitNet ternario de 160–240 M pierde calidad frente a fp16 | comparar en el piloto una copia en precisión normal con los mismos datos para medir la brecha; si es grande, subir a v2-B (más parámetros ternarios) en vez de abandonar el 2 bits |
| El motor `motor.cpp` es un punto único de fallo | verificación contra PyTorch (logits y tokens), bit-exactitud entre configuraciones de adaptadores, v1 sigue cargándose |
| La extrapolación de velocidad falla (±30 %) | puerta de la Fase 0 con medición real; si no se llega, se reduce capas o se pasa a 1 hilo/int8 |
| Se pierde la compatibilidad de los LoRA | no se reutilizan: se reentrenan con los mismos datos y evaluadores; v1 + LoRA v1 quedan como respaldo funcional |

## 11. Decisiones abiertas (para aprobar antes de la Fase 0)
1. **v2-A (≈ 160 M) primero, con v2-B condicional** (propuesta) o ir directo a ≈ 240 M.
2. **Vocabulario de 24 k** frente a mantener 16 k (mantenerlo ahorra 6 MB de embedding pero alarga las secuencias; implica reutilizar el tokenizador actual).
3. **Embedding en int8** (−18 a −25 MB) frente a fp16: se decide con la medición de la Fase 0.
4. **Persona:** nombre, registro (neutro / chilenismos moderados), humor y longitud típica de respuesta.
5. **Fuentes de datos conversacionales** que se aceptan tras revisar licencias (§5.2) y si se permite un modelo abierto auxiliar para redactar datos sintéticos.
6. **Cambios opcionales de arquitectura** (RMSNorm/SwiGLU/RoPE) en una v2.1: se dejan fuera de la v2 inicial para limitar el riesgo del motor.

## 12. Decisiones aprobadas (2026-11-20)
Respuestas del dueño del proyecto a las decisiones abiertas de §11. Quedan como requisitos de la Etapa 4.
| # | Decisión | Resolución |
|---|---|---|
| 1 | Tamaño | **v2-A**: ≈ 158 M parámetros, 22 capas, d=768, GQA 12/4 cabezas, ventana de 1.024 tokens. v2-B solo si v2-A no alcanza fluidez (§9, fase 6) |
| 2 | Vocabulario | **24.000 tokens** (+ las 4 etiquetas de turno y el relleno, 24.004 en total, buscadas por nombre) entrenado sobre una mezcla de **español conversacional y enciclopédico + símbolos y sintaxis de código**. Objetivo adicional: que `x**2`, `[x for x in …]`, `print(` y similares tokenicen de forma estable (v1 degenera con `x**2`) y ganar compresión dentro de los 1.024 tokens |
| 3 | Embeddings | **atados (tied) e int8 por fila** (escala fp16 por fila); el impacto en perplejidad se verifica en la Fase 0/piloto. Plan B: fp16 atado |
| 4 | Persona | **Nombre: TEST-IA** (identidad fija, resuelta desde `capa1()`). **Registro:** cercano y directo, tuteo natural, conciso, sin frases de relleno. **Humor:** sutil y ligero solo en charla informal y saludos; 100 % sobrio y exacto en datos, código y abstenciones |
| 5 | Datos | Preentrenamiento ≈ 4 B tokens: español web/enciclopédico (Wikipedia es, FineWeb-2 es) **+ código y documentación limpia**, con **descontaminación estricta** contra todos los conjuntos de evaluación del proyecto. SFT 150–300 k ejemplos: **se permite un modelo abierto auxiliar** para generar diálogos multi-turno naturales, personalidad y síntesis sobre resultados de herramientas, **siempre bajo verificación automática de fidelidad** (cero datos inventados fuera del contexto de la herramienta): lo que no pase la verificación no entra al SFT |
Consecuencias para el diseño: (a) el 10 % de código/documentación del preentrenamiento sube a ≈ 8–12 % de los tokens y se limpia con los mismos filtros de licencia/calidad; (b) la mezcla del tokenizador incluye ≈ 10 % de código para que los símbolos tengan tokens propios;
(c) la verificación de fidelidad de la síntesis es un requisito de entrada al dataset (no una métrica posterior); (d) `capa1()` incorpora las respuestas de identidad («¿Cómo te llamas?», «¿Quién eres?») con el nombre TEST-IA; (e) el modelo auxiliar usado, su licencia y versión se registran por lote (§5.2).
