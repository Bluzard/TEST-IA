# Etapa 3 · Paso 2 — Segundo experto (redacción) y conmutación multi-experto

Fecha: 2026-11-20. Estado: **cerrado** (promoción, enrutador de 3 estados, caché de 2 ranuras y las 6 métricas medidas; ver §7).
Restricción permanente: `nucleo_sft_v3.{pt,bin}` y `experto_codigo.lora` no se tocan (SHA-256 verificado al cerrar cada hito).

## 0. Ajustes previos de memoria (hechos)
- **Olvido explícito** (`memoria.py`, vía `capa1()`): «Olvida que…», «Olvídate de…», «Borra / Elimina / Quita…» archivan al tiro el recuerdo que mejor coincide
  (motivo «olvidado por el usuario», sin reforzar), sin inferencia. «Olvida» siempre responde (si no hay nada: «No tengo nada guardado sobre eso.»);
  «Borra/Elimina/Quita» solo actúan si hay un recuerdo coincidente, así «Borra el archivo temporal» sigue su camino normal.
- **Recuerdo permanente**: «Recuerda siempre que…» guarda con `permanente=True`: `enfriar()` no le resta temperatura. «Recuerda que…» sigue enfriándose −1 por turno.
  Volver a decir un dato permanente con «Recuerda que…» no le quita la condición; solo «Olvida» lo archiva.
- Verificado en `memoria.py` (autopruebas) y en el escenario 5 de `probar_memoria.py` (motor C++ y PyTorch): tras 12 turnos el temporal se archiva y el permanente
  sigue en T=10 y se recupera; tras «Olvida que mi alergia es el maní» el núcleo se abstiene. Pesos congelados intactos.
- Hallazgo: el núcleo congelado se abstiene con «Mi ciudad es Valdivia.» aunque la memoria la entregue bien (con «alergia», «color favorito» o «proyecto» responde).
  Es un sesgo del núcleo con la palabra «ciudad»; por eso la prueba usa «alergia».

## 1. Experto de redacción (`experto_redaccion.lora`)
Mismo molde que `experto_codigo`: LoRA r=16, alpha 32, en las 4 matrices (qkv, proyección, MLP arriba y abajo) → ~2,62 MB; se entrena **desde el núcleo base**, no desde el
experto de código, para que los dos adaptadores sean independientes. Los datos declarativos van **fuera de los pesos** (Opción B): las reglas gramaticales se leen de una base local
(`redaccion_fichas.py`, < 1 ms) y los temas raros se buscan en ddgs o se abstiene; el LoRA solo aprende el *oficio*: copiar la regla correcta y reescribir texto.

### 1.1 Qué cubre y cómo se verifica cada respuesta
| Dominio | Cuota | Respuesta correcta (por construcción) | Métrica de evaluación |
|---|---|---|---|
| Ortografía y puntuación | 30 % | La oración original del corpus; el modelo recibe una versión con 1–3 errores conocidos (tildes, h omitida, b/v, ¿¡, punto final, mayúscula inicial, espacio antes de coma). 10 % ya están bien → «El texto ya está bien escrito.» | coincidencia exacta y similitud de caracteres |
| Tono | 28 % | formal (plantillas cotidiano→formal), cercano (formal→cotidiano), conciso (se quitan muletillas añadidas), claro (conectores rebuscados → simples) | exacta (formal/cercano/conciso/claro son transformaciones deterministas) |
| Gramática (Opción B) | 20 % | `B: <tema> gramática` → ficha local → copiar la regla / el ejemplo | similitud ≥ 95 % con la ficha |
| Temas de cola | 6 % | `B:` → «Sin resultados.» → «No tengo información suficiente…» | tasa de abstención |
| Repaso Etapa 1 | 12 % | conversación, hechos y abstención del núcleo | regresión general |

Los resultados reales de ddgs para los temas de cola (y para gramática fuera de la base) se agregan en el paso de entrenamiento con `recolectar_docs.py` adaptado; hoy la cola solo entrena la abstención.

### 1.2 Lo construido en este paso
- `redaccion_fichas.py`: **71 fichas** (acentuación, homófonos, ortografía, puntuación, mayúsculas, concordancia, dequeísmo/queísmo/laísmo/leísmo, tiempos y modos, funciones sintácticas,
  estilo formal/claro/conciso), **40 temas de cola**, 15 muletillas y 18 simplificaciones de conectores. `buscar_ficha_gramatica()` es la herramienta local (misma interfaz que `buscar_ficha`).
  Partición estable por hash: 18 fichas y 7 temas de cola quedan **reservados** para evaluar.
- `redaccion_datos.py` → `datos/redaccion_train.jsonl` (**10.266** ejemplos, media 83 tokens, máx. 360, 0 descartados) y `datos/redaccion_eval.jsonl` (**507**, 0 filtraciones de preguntas).
  Oraciones: 60.000 de entrenamiento y 60.000 de evaluación tomadas de zonas distintas del corpus (90 % / 10 %).
  Composición del entrenamiento: ortografía 3.600, gramática 2.400, tono 2.106, repaso 1.440, cola 720.
- Límite conocido del dataset: tono formal/cercano está limitado por las plantillas (213 + 213 pares únicos de ~1.080 previstos) y claro por las oraciones del corpus que contienen
  conectores rebuscados (720 de 1.720 usables). Antes de entrenar se ampliarán plantillas a ≥ 40 y se revisará a mano una muestra de 100 pares por dominio.

## 2. Enrutador multi-dominio (`enrutador.py`)
Tres estados exclusivos: `None` (núcleo base), `"codigo"`, `"redaccion"`. Un solo experto activo por turno.
- Puntaje por dominio (`puntaje_codigo`, `puntaje_redaccion`). Señales de redacción: verbos de edición (corrige, revisa, reescribe, redacta, acorta, simplifica, «hazlo más formal/conciso/claro»),
  vocabulario (ortografía, tilde, puntuación, coma, gramática, concordancia, tono, formal) y los nombres de las 71 fichas, con el mismo filtro de palabras ambiguas que el de código.
- Arbitraje: gana el de mayor puntaje si supera el umbral (2); empate o diferencia < 2 → se **mantiene el experto actual** (histéresis) y, si no había, gana el de la señal más específica
  (verbo de edición > vocabulario). Un mensaje que activa a los dos con puntajes altos (p. ej. «corrige este código») se resuelve por el verbo de edición *más* un patrón de código:
  gana `codigo`, porque el código a corregir es el objeto y no el estilo.
- Reposo: igual que hoy (2 turnos sin señal del dominio activo; un tema nuevo sin señal duerme al tiro). Cambiar de experto no pasa por «dormido»: es un cambio directo de puntero.
- Evaluación: conjunto etiquetado de 3 clases (códigos de `experto_eval*.jsonl`, `redaccion_eval.jsonl`, `sft_eval.jsonl` como negativos). **Metas**: cobertura de código ≥ 82,3 % (sin bajar), redacción ≥ 85 %,
  falsos positivos ≤ 0,5 %, confusiones código↔redacción ≤ 1 %, histéresis en un guion de 15 turnos con cambios de dominio.

## 3. Caché multi-slot con enfriamiento en `motor.cpp`
Hasta **2 adaptadores en RAM**. Estados por ranura: **Activo** (en el forward) → **Tibio** (cargado en RAM, desconectado del forward, con vida que decae por turno sin uso) → **Frío** (descargado).
```
struct Ranura { std::shared_ptr<Lora> L; std::string nombre; int estado; int vida; };   // estado: 0 frío, 1 tibio, 2 activo
Modelo: Ranura ranuras[2]; Lora* act = nullptr;       // el forward usa solo `act` (nullptr = núcleo base, idéntico bit a bit)
```
API C (compatible con la actual; las funciones viejas operan sobre la ranura 0):
- `nucleo_lora_cargar_ranura(h, ruta, nombre)` → id 0|1 o código de error; si ambas están ocupadas libera primero la tibia con menos vida.
- `nucleo_lora_seleccionar(h, id)` → `act = ranuras[id].L.get()`; la que estaba activa pasa a tibia (vida = `VIDA_TIBIA`, 6 turnos); `id = -1` duerme todo. **Es una asignación de puntero.**
- `nucleo_lora_turno(h)` → un turno: cada tibia pierde 1 de vida; al llegar a 0 pasa a frío y libera su memoria.
- `nucleo_lora_estado(h, id)` y `nucleo_lora_bytes(h)` para observabilidad.
`motor_cpp.py`: `cargar_lora(ruta, nombre)`, `seleccionar(nombre)`, `turno()`; si el experto pedido está frío lo recarga desde su ruta (1,4–7 ms ya medidos, aceptable porque ocurre solo tras ≥ 6 turnos sin uso).
`Sesion` llama a `turno()` cada turno junto con `memoria.enfriar()` y a `seleccionar()` con lo que decida el enrutador.

## 4. Métricas de éxito obligatorias y cómo se medirán
| Métrica | Meta | Medición |
|---|---|---|
| Cambio entre dos expertos tibios | **< 0,1 ms** | 10.000 alternancias `seleccionar(a)`/`seleccionar(b)` con `perf_counter_ns`, mediana y p99 (incluye el costo de la llamada ctypes) |
| RAM del proceso con ambos cargados | **≤ 118 MB** | `medir_recursos.py` (working set pico). Base medida: núcleo solo 110 MB, +1 adaptador 112 MB (+2–3 MB); estimación con dos ≈ 114–115 MB |
| Núcleo base sin degradación | **71,6 % / 98,1 % / 100 %** | `inferir.py --evaluar` con el motor, y verificación bit a bit de logits con adaptadores dormidos/tibios (`verificar_lora_motor.py` ampliado) |
| `experto_codigo` sin degradación | **82,2 %** | `evaluar_experto.py` con `experto_codigo.lora` activo *y* `experto_redaccion` tibio en la otra ranura |
| Cero colisiones | 0 turnos con 2 expertos activos | aserción en `Sesion` + guion multi-dominio de 30 turnos |
| Congelados | SHA-256 idéntico | `probar_memoria.py` / nueva prueba multi-experto, antes y después |

Nota sobre las cifras de referencia: 82,2 % es el puntaje de `experto_codigo` registrado en `EXPERTO_CODIGO.json` (0,822) y 71,6 % / 98,1 % / 100 % es la evaluación general de la Etapa 1
(hechos / abstención / conversación) con el adaptador **dormido**, tal como quedó documentado en `ETAPA2_PASO2`. «Cero degradación sobre el núcleo base» se mide, por tanto, con los
adaptadores dormidos o tibios (debe dar exactamente esas cifras y logits idénticos bit a bit). Con un experto *activo* el rendimiento general cambia, como ya ocurrió con el de código
(hechos 73,9 % en la evaluación final); eso se reporta aparte para redacción, pero no es la meta de «cero degradación».

## 5. Plan de trabajo
1. ✅ Memoria: olvido y permanente.
2. ✅ Fichas gramaticales y generador de datos de redacción (este documento, §1.2).
3. ☐ Ampliar plantillas de tono y revisar muestras a mano; recolectar resultados reales de ddgs para la cola.
4. ☐ `evaluar_redaccion.py` (exacta / similitud / abstención) + `buscar_ficha_gramatica` conectada a `buscar_web(modo="redaccion")`.
5. ☐ Entrenar r=16 desde el núcleo (3 y 6 épocas, semillas) → `modelos/experimentos/`; promover el ganador exportado a `modelos/experto_redaccion.lora` con `EXPERTO_REDACCION.json` (SHA-256).
6. ☐ Enrutador de 3 estados + evaluación.
7. ☐ `motor.cpp` multi-slot + `motor_cpp.py` + `Sesion`; recompilar con `compilar_motor.bat`.
8. ☐ Medir las 6 métricas y cerrar el paso.

## Estado y riesgos
- **Hecho y verificado hoy:** olvido/permanente (autopruebas + prueba en vivo en ambos motores), fichas, dataset de redacción (generación sin errores, 0 filtraciones, todo ≤ 360 tokens).
- **No hecho:** ningún entrenamiento, ni cambios en el enrutador o `motor.cpp`; por lo tanto **ninguna de las métricas de la sección 4 está medida todavía**.
- Riesgo principal: que el LoRA de redacción no generalice a oraciones fuera del corpus de Wikipedia (registro enciclopédico); mitigación: plantillas de tono cotidiano y ejemplos de mensajes breves en la evaluación.
- Riesgo de solape de señales (código vs. redacción): «comentario», «función», «error», «texto» existen en ambos; se mantiene el filtro de ambiguas y la evaluación de confusiones.
- Riesgo de RAM: la estimación (≈ 114–115 MB) deja ~3 MB de holgura; si la medición supera 118 MB, se baja `VIDA_TIBIA` a 0 (descargar al cambiar) y se mantiene un solo adaptador.

## 6. Entrenamiento de `experto_redaccion` (r=16, 4 matrices, 2,62 MB) — resultados
Datos: `redaccion_train.jsonl` 11.189 ejemplos (máx. 322 tokens), `redaccion_eval.jsonl` 570. Tonos formal/cercano: 960/840 pares en entrenamiento (revisión manual de 25 pares: se corrigieron concordancias «de el», plurales y un verbo).
ddgs: de 221 consultas solo 164 se recolectaron (57 fallaron por cortes de conexión); la mayoría de los resultados reales eran vacíos o en otro idioma, así que `cola_ok` tiene solo 6 ejemplos de
entrenamiento y 0 de evaluación; la cola entrena sobre todo abstención con resultados reales irrelevantes (264). La lectura de resultados reales se apoya en 892 ejemplos de repaso de la Etapa 1.
Todo en `modelos/experimentos/`; núcleo intacto tras entrenar (suma de pesos idéntica) y SHA-256 de `nucleo_sft_v3.{pt,bin}` y `experto_codigo.lora` idénticos.

| Métrica (evaluación reservada) | Núcleo solo | e3 (3 épocas) | e6 (6 épocas) |
|---|---|---|---|
| **Puntaje global** | 18,1 % | 51,2 % | **56,2 %** |
| Ortografía y puntuación (exacta) | 0 % | 12 % (sim≥95: 36 %) | 14 % (sim≥95: 43 %) |
| Tono formal / cercano | 0 / 0 % | 62 / 33 % | **85 / 33 %** |
| Tono conciso / claro | 0 / 0 % | 25 / 23 % | 38 / 40 % |
| Gramática local: regla (reservadas / vistas) | 15 / 6 % | 76 / 89 % (sim) | 76 / 92 % |
| Gramática: ejemplo | 0 % | 82 % | 89 % |
| Abstención (inexistentes / sin respuesta) | 100 / 93 % | 100 / 97 % | 100 / 100 % |
| General Etapa 1 con el adaptador activo (hechos) | 71,6 % | 73,0 % | 70,3 % |
| General con el adaptador **dormido** | 71,6 / 98,1 / 100 % | idéntico | idéntico |

Lectura: el adaptador aprende bien gramática, abstención y tono formal; **la corrección ortográfica es débil** (el núcleo de 48 M reescribe oraciones largas con errores a la primera; solo 14 % exactas) y el tono cercano
no pasa de 33 %. e6 supera a e3 en todo salvo hechos generales (−2,7 puntos con el adaptador activo, como ocurrió con el experto de código). Con el adaptador dormido el núcleo da exactamente 71,6 / 98,1 / 100 %.
**Pendiente de decisión:** no se promovió nada a `modelos/experto_redaccion.lora` (ver conclusión de la sesión).

## 7. Cierre del Paso 2 (2026-11-20)
**Promoción.** Se promovió el ganador de 6 épocas (decisión del usuario, sin reentrenar): `modelos/experto_redaccion.lora` (2.621.472 bytes, solo lectura) con
`EXPERTO_REDACCION.json` (SHA-256 `3EC614B0BA4ECD5538D2557730C914506054ADFD618C77711B19E3ED54696018`). Es idéntico byte a byte a `modelos/experimentos/experto_redaccion_e6.lora`.
**Límite conocido:** la ortografía exacta es del 14 % (similitud ≥ 95 %: 43 %); la corrección de tildes, `h`, `b/v` y signos es tarea para una herramienta léxica determinista en Python
(diccionario + reglas), no para 1,3 M de parámetros de LoRA. El adaptador se conserva por gramática (92 %), abstención (100 %) y tono formal (85 %).

**Enrutador de 3 estados** (`enrutador.py`, `python enrutador.py`). `Enrutador.paso()` devuelve `None`, `"codigo"` o `"redaccion"`: un solo valor, así que nunca hay dos activos.
El cambio de dominio es directo (sin pasar por dormido) si el otro puntaje supera el umbral y al activo. En mensajes «instrucción: texto» manda la instrucción: el texto a trabajar solo cuenta como
código si trae sintaxis inequívoca (`def`, `print(`, `=`, `for … in`…), lo que evitó que las oraciones de Wikipedia con puntos o paréntesis se las llevara el experto de código.

| real \ decidido | núcleo | código | redacción | n | acierto |
|---|---|---|---|---|---|
| núcleo (general + difíciles) | 3.232 | 18 | 2 | 3.252 | 99,4 % |
| código | 459 | 2.136 | 0 | 2.595 | 82,3 % (igual que antes) |
| redacción | 82 | 2 | 2.001 | 2.085 | 96,0 % |

Falsos positivos: código 20 de 5.337 (0,37 %), redacción 2 de 5.847 (0,03 %); confusión código↔redacción: 0 + 2 (ambas «la regla de el condicional»). Guion de 15 turnos con cambios de dominio: correcto.
Salvedad: las reglas de redacción se afinaron mirando estos mismos conjuntos (no hay un conjunto separado), así que 96 % es optimista para frases nuevas.

**Caché de 2 ranuras** (`motor.cpp`, `motor_cpp.py`, `Sesion` en `inferir.py`). Estados Activo → Tibio → Frío. El forward solo mira el puntero `act` (null = núcleo base). `nucleo_lora_seleccionar` reasigna ese puntero;
`nucleo_lora_turno` resta 1 de vida a cada tibio (6 turnos por defecto) y descarga el que llega a 0; un experto frío se recarga solo al pedirlo (1,1 ms). La API de una ranura sigue funcionando (compatibilidad).
`python inferir.py --motor --experto modelos/experto_codigo.lora --redaccion modelos/experto_redaccion.lora` (PyTorch admite un solo experto).

**Las 6 métricas** (`python verificar_multiexperto.py`, log en `resultados/ETAPA3_PASO2_multiexperto.log`; 26 chequeos, todos OK):
| # | Métrica | Meta | Resultado |
|---|---|---|---|
| 1 | Cambio entre expertos tibios | < 0,1 ms | **0,4 µs** de mediana, p99 0,6 µs (20.000 cambios; con el envoltorio Python p99 0,5 µs) |
| 2 | RAM pico del proceso con ambos cargados | ≤ 118 MB | **116,0 MB** (núcleo solo 110,6; con 1 experto 113,2; el segundo suma 2,6 MB). Holgura de 2 MB |
| 3 | Núcleo base | 71,6 / 98,1 / 100 % | **71,6 / 98,1 / 100 %** con ambos expertos tibios; logits idénticos bit a bit (diferencia máxima 0,0 en 92 prompts) |
| 4 | `experto_codigo` | 82,2 % | **82,3 %** con redacción tibio en la otra ranura (logits idénticos al motor de la Etapa 2) |
| 5 | Colisiones en conversación multi-dominio | 0 | **0** en 30 turnos (usa núcleo, código y redacción; máximo 1 activo simultáneo) |
| 6 | SHA-256 de congelados | idéntico | `nucleo_sft_v3.{pt,bin}`, `experto_codigo.lora` y `experto_redaccion.lora` intactos |
Además: `experto_redaccion` activo con código tibio da 55,6 % en C++ (56,2 % en PyTorch; diferencia de redondeo bf16/fp32).

**Correcciones encontradas al integrar** (afectaban a la conversación real):
- `buscar_ficha_gramatica` no normalizaba las consultas por un marcador de palabra de la expresión regular (el carácter de escape se había guardado como backspace) en la expresión regular: «porque y por qué gramática» no encontraba su ficha. Corregido.
- La memoria de trabajo trataba «el», «este» y «esta» como señal de seguimiento y anteponía la pregunta anterior a «Explícame el dequeísmo». Ahora solo cuentan eso, esto, él, ella, ello, su(s), «lo mismo», allí/aquí.
- Con cualquier experto activo (no solo código) se usa penalización 1.0 y el experto de redacción consulta primero su base local de gramática.

**Límites observados en la conversación de prueba (calidad del modelo, no de la infraestructura):** «Reescribe en tono formal: Dame el archivo ya.» → «Siendo el archivo ya.»; «Corrige: el ni;o juga en la plasa» →
devuelve el texto sin corregir; «¿y la tilde de compré?» mezcla la pregunta con el texto anterior. Son coherentes con las métricas de §6.
