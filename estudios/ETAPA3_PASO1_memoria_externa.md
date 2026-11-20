# Etapa 3 · Paso 1 — Memoria externa con enfriamiento

Fecha: 2026-11-20. Solo capa de Python: no hay LoRA de memoria y ningún peso fue tocado o reentrenado.
SHA-256 antes y después de las pruebas (verificado dentro de `probar_memoria.py` y con `sha256sum -c`):

| Archivo | SHA-256 |
|---|---|
| `nucleo_sft_v3.pt` | `a867d741e0e65aa7…` (intacto) |
| `nucleo_sft_v3.bin` | `17ecdbdaafba9c61…` (intacto) |
| `experto_codigo.lora` | `b57032631efdcdb6…` (intacto) |

## Por qué no es un LoRA
La memoria es transversal a toda la conversación: un LoRA tendría que estar activo en todos los turnos y colisionaría con `experto_codigo`
(un solo experto activo por turno). Además, como en las Etapas 1 y 2, los datos declarativos viven fuera de los 48 M de parámetros: en `datos/memoria.json`.

## Orden de `modelos/`
Quedan solo los archivos de producción: `nucleo_sft_v3.{pt,bin,vocab.json}`, `NUCLEO_BASE.json`, `experto_codigo.lora`, `EXPERTO_CODIGO.json` (+ `README.md`).
- `modelos/archivo/`: las ablaciones y variantes descartadas (`experto_atencion`, `r4`, `r8_*`, `r16*`, `B_e3/e6`, `B2_e3`, `f27_*`) y `nucleo_es_bitnet.pt`.
  Se **movieron** (no se borraron): sus resultados están en `estudios/etapa2/` y `experto_r16_B2_e3.lora.pt` es el origen del experto final (`entrenado_desde`).
  Su `.lora` es idéntico byte a byte a `experto_codigo.lora`; la prueba PyTorch lo usa de ahí.
- `modelos/experimentos/`: destino de todo experimento nuevo. `entrenar_lora.py` y `ajustar.py` ya escriben ahí; solo el ganador exportado se promueve a `modelos/`.

## Qué se implementó

**`memoria.py`** — almacén en `datos/memoria.json` (escritura atómica). Campos: `id, clave_o_entidad, contenido (≤150), temperatura, creado_en, ultimo_uso`.
- Guardar: temperatura 10 (si la clave ya existe se reemplaza el dato y se reinicia).
- Enfriar: cada turno todos los activos bajan 1; al llegar a 0 pasan a `archivados` y dejan de recuperarse.
- Reforzar: cada recuperación sube 3 (tope 15).
- Búsqueda léxica (< 1 ms): palabras sin acentos ni artículos/interrogativos, plural simple, cobertura ≥ 50 % de la consulta; devuelve hasta 2.
- `MemoriaTrabajo`: buffer de los 2 últimos turnos con tope de 80 tokens.

**`herramientas.py`** — `capa1(pregunta, memoria=None)` detecta «Recuerda/Guarda/Anota/Apunta/Memoriza que…» y «Mi X es/se llama/son/está/tiene…»
(solo oraciones afirmativas, sin `?`), guarda con temperatura 10 y confirma («Anotado: …») sin red neuronal. `buscar_web(consulta, modo, memoria)`:
**memoria → base local de 107 fichas (modo código) → ddgs**. Sin `memoria` el comportamiento anterior es idéntico (las evaluaciones no escriben nada).

**`inferir.py`** — nueva clase `Sesion` (enrutador + experto + memorias; la usan el CLI, el chat interactivo y las pruebas), con `--motor` y PyTorch.
Orden de cada turno: enfriar memoria → enrutador → capa 1 / núcleo → registrar en memoria de trabajo. `--sin-memoria` la desactiva.
El tope de tokens de los resultados baja dinámicamente según lo que ya ocupe el contexto (ventana de 512).

## Hallazgos que cambiaron el diseño
1. **Formato del resultado.** Con `1. [memoria] mi proyecto se llama TEST-IA` el núcleo congelado se abstuvo en todas las variantes probadas con la etiqueta como inicio.
   Probé 6 formatos con 4 formulaciones de pregunta: solo responde si el *título* es la entidad por la que preguntó:
   `1. Mi proyecto: Mi proyecto se llama TEST-IA.` → respondió 4 de 4; `1. [memoria] Mi proyecto: …` → 3 de 4; los demás → 0 de 4 (o texto degenerado
   al mezclar con otro resultado). Se adoptó el título-entidad; la etiqueta `[memoria]` quedó solo en el nombre de la función y la documentación.
2. **El núcleo emite `B: mi proyecto`** (o `B: mi proyecto programación` con el experto activo) para datos personales: no hizo falta forzar nada, el mecanismo `B:` ya existente basta.
3. **Fallo previo en el bucle de código.** Con el experto activo el modelo a veces escribe `R: …` y cierra con `<herramienta>`; el bucle lo trataba como otra búsqueda y
   terminaba en «No tengo información suficiente». Ahora un texto que empieza con `R:` es respuesta final.
4. **Adaptador pegado.** Una sesión sin experto reutilizando el mismo motor después de una con experto seguía con el LoRA despierto (agregaba «programación» a las consultas).
   `Sesion` ahora duerme el adaptador explícitamente.

## Prueba automatizada (`probar_memoria.py`)
Búsqueda web simulada (sin red) para que sea determinista; núcleo y experto reales. Dos corridas, **ambas con todos los chequeos correctos**:
`resultados/ETAPA3_PASO1_prueba_motor.log` (motor C++) y `resultados/ETAPA3_PASO1_prueba_pytorch.log` (PyTorch/CUDA).

| Escenario | Resultado |
|---|---|
| 1. Experto dormido | «Recuerda que mi proyecto se llama TEST-IA» → capa 1, 0 IA, T=10. «¿Cómo se llama mi proyecto?» → `B: mi proyecto` → memoria → **«Mi proyecto se llama TEST-IA.»**; T = 10 − 1 + 3 = 12 |
| 2. Experto activo | «En Python, ¿cómo se llama mi proyecto?» → enrutador despierta el experto → **recupera el dato**; «Ejecuta: sum([x*x for x in range(1, 6)])» → `E:` → 55 en el turno siguiente. Sin colisión |
| 3. Enfriamiento | 2 datos guardados, 10 turnos de otros temas. El dato no mencionado: 10 → 9 → … → **0 (archivado) al décimo turno tras guardarlo**; el consultado en el turno 4 (con refuerzo) sigue vivo en T=3. Preguntar por el proyecto → **«No tengo información suficiente para responder eso.»** |
| 4. Memoria de trabajo | Tras «¿Quién fue Gabriela Mistral?», «¿y cuándo nació?» llega al núcleo como «¿Quién fue Gabriela Mistral? ¿y cuándo nació?» (17 tokens) y busca `B: Gabriela Mistral`. Con turnos gigantes el contexto se recorta a 72 ≤ 80 tokens; peor caso de la ventana: 500 < 512 |

Regresión: `sandbox.py` 28/28; `enrutador.py` 82,3 % de cobertura y 17 falsos positivos (sin cambio); capa 1 aritmética intacta.

## Límites
- La recuperación es léxica: «¿cómo se llama mi mascota?» no encuentra «mi gato se llama Michi». Sinónimos requerirían embeddings (otro paso).
- El núcleo tiene que emitir `B:` para consultar la memoria; si responde sin buscar, ignora el dato. No ocurrió en las pruebas.
- Con la fecha, el caso 4 responde copiando la primera frase del resultado (que ya traía 1889); el núcleo no extrae «solo la fecha». Es el comportamiento del núcleo congelado.
- «Mi X es…» guarda cualquier afirmación personal; no hay comando de olvidar (el enfriamiento es la única vía de borrado).
- Las respuestas del núcleo no se ajustan a persona gramatical («Mi proyecto se llama…» en vez de «Tu proyecto…»).
- El dato refuerza al recuperarse aunque la respuesta final del núcleo sea incorrecta: el refuerzo mide recuperación, no utilidad.
