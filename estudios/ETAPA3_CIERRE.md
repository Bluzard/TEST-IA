# Etapa 3 — Cierre formal (2026-11-20)

Cierra la arquitectura de TEST-IA: un **núcleo congelado de 48 M parámetros** que sabe cuándo buscar, dos **expertos LoRA de 2,62 MB** que se conmutan por puntero y una **capa de Python** (capa 1, memoria, herramientas, enrutador) que concentra todo lo que no debe vivir en los pesos.
Detalle por paso: [ETAPA3_PASO1_memoria_externa.md](ETAPA3_PASO1_memoria_externa.md) · [ETAPA3_PASO2_multi_experto.md](ETAPA3_PASO2_multi_experto.md).

## 1. Ajustes finales de esta ronda
- **Memoria de trabajo** (`memoria.py`, usada desde `inferir.py`): un seguimiento corto que ya nombra por sí solo un término de las fichas locales (código o gramática: «tilde», «hiato», «pila»…)
  **no** arrastra el turno anterior, aunque empiece por «¿y…?». «¿y la tilde de compré?» y «¿y el hiato?» llegan limpios al núcleo; «¿y cuándo nació?» sigue recibiendo su referente.
  Verificado en el escenario 4 de `probar_memoria.py` (motor C++ y PyTorch).
- **Orden del repositorio:** `motor_etapa2_ref.dll` (motor de la Etapa 2, usado como referencia de bit-exactitud y ya documentado en el Paso 2) pasó a `modelos/archivo/`; `verificar_multiexperto.py` apunta ahí.
- Tras los cambios se re-ejecutaron `verificar_multiexperto.py` (26 chequeos), `probar_memoria.py` en ambos motores, `sandbox.py` (28/28) y `memoria.py`: todo correcto, con los SHA-256 de los pesos congelados idénticos.

## 2. Resultados consolidados

### Etapa 1 — Núcleo Base (congelado)
| | |
|---|---|
| Arquitectura | Transformer BitNet de 10 capas, d=512, 8 cabezas, contexto 512, BPE de 16.004; 48 M parámetros |
| Preentrenamiento | 336 M tokens de español (Wikipedia + FineWeb-2 latinoamericano), perplejidad 32,4 |
| Ajuste fino v3 (ddgs **real**) | hechos 71,6 % exacta (fidelidad de copia ≥ 95 %: 86,5 %) · abstención 98,1 % · conversación 100 % |
| Motor C++ | 41,3 MB empaquetado, 111 MB de RAM, 1,46 ms/token (685 tokens/s), respuestas idénticas a PyTorch en 100 % |
Lección: evaluar con resultados simulados engaña (81 % simulado → 18 % con ddgs real); se entrenó con resultados reales y ruidosos.

### Etapa 2 — Experto de código (`experto_codigo.lora`, r=16, 4 matrices, 3 épocas)
| | |
|---|---|
| Opción A (memorizar definiciones) | no llegó al umbral (53 % < 60 %) y inventa más |
| Opción B (base local de 107 fichas + LoRA solo de protocolo) | conceptos 79 %, ejemplos 100 %, ejecución 95 %, **puntaje global 82,2 %** |
| Herramientas | `B:` (fichas + ddgs) y `E:` (sandbox de Python con lista blanca por AST, proceso aislado, 3 s, 256 MB) |
| Enrutador | cobertura 82,3 %, falsos positivos 0,5 % |
| Costo en el motor | +2,6 MB de RAM, ≈ +1 % de tiempo por token; adaptador dormido = núcleo base bit a bit |
Límite: con el experto activo el rendimiento general cambia (hechos 73,9 %); `x**2` con «Ejecuta esto:» hace degenerar al adaptador final.

### Etapa 3 — Memoria, segundo experto y conmutación
| Pieza | Resultado |
|---|---|
| Memoria externa con enfriamiento (`datos/memoria.json`) | guardado en capa 1 sin IA; −1 por turno, +3 al usarse (tope 15); archivado a 0; «Recuerda siempre que…» (permanente) y «Olvida/Borra…» (inmediato); recuperación por `B:`; 10 turnos sin mención → abstención honesta |
| Experto de redacción (`experto_redaccion.lora`, 6 épocas) | gramática 92 %, abstención 100 %, tono formal 85 %, **puntaje 56,2 %**; ortografía exacta 14 % (límite conocido) |
| Enrutador de 3 estados | redacción 96,0 %, código 82,3 %, falsos positivos 0,37 % / 0,03 %, 0 + 2 confusiones entre dominios |
| Caché de 2 ranuras (Activo → Tibio → Frío) | cambio por puntero **0,4 µs** (meta < 100 µs) · RAM pico **116,0 MB** (meta ≤ 118) · núcleo base 71,6 / 98,1 / 100 % y logits idénticos bit a bit · `experto_codigo` 82,3 % · **0 colisiones** en 30 turnos |

## 3. Conclusiones arquitectónicas
1. **Los pesos aprenden el protocolo; los datos viven fuera.** Memorizar definiciones en un LoRA falló dos veces (Etapa 2 opción A, ortografía exacta en la Etapa 3); leerlas de una base local o de internet funcionó en ambas.
   Regla de diseño: todo dato declarativo (fichas, reglas, preferencias del usuario) → herramienta; todo lo determinista (cuentas, mayúsculas, guardar/olvidar, ortografía exacta) → Python.
2. **Un núcleo congelado y adaptadores desmontables.** Dormido o tibio, un adaptador es invisible (logits idénticos bit a bit); activar uno es reasignar un puntero. Así se añaden dominios sin reentrenar ni degradar los anteriores.
3. **Un solo experto por turno.** La exclusión mutua la garantiza el enrutador (devuelve un único estado) y se verifica en tiempo de ejecución (`Sesion.colisiones`). Dos adaptadores sumados al mismo tiempo no se probaron ni se necesitan.
4. **La memoria es transversal, por eso no es un LoRA.** Un adaptador de memoria tendría que estar activo siempre y chocaría con los expertos. En Python cuesta 0 ms y se puede auditar, corregir y olvidar.
5. **Evaluar con lo real.** Los números honestos salieron de resultados reales de ddgs y de evaluaciones reservadas; las simuladas sobreestiman. Cada hito se cerró con SHA-256 de los pesos congelados antes y después.
6. **Presupuesto.** 116 MB de RAM con núcleo + 2 expertos + herramientas; contexto de 512 tokens administrado (memoria de trabajo ≤ 80 tokens, resultados con tope dinámico).

## 4. Límites conocidos (abiertos)
- Ortografía exacta 14 % y tono cercano 33 %: corregir tildes/`h`/`b-v` debe delegarse a una herramienta léxica determinista en Python.
- La búsqueda en memoria es léxica («mi mascota» no encuentra «mi gato»); el núcleo congelado se abstiene con ciertas palabras («ciudad») aunque el dato llegue bien.
- `cola_ok` de redacción: solo 6 ejemplos de entrenamiento y 0 de evaluación con resultado real útil (ddgs devolvió casi todo vacío o en otro idioma).
- La cobertura del enrutador sin contexto es de ~82 % (código) y las reglas de redacción se afinaron con los mismos conjuntos que las evalúan (96 % es optimista).
- Con un experto activo cambia el rendimiento general (en código 73,9 %, en redacción 70,3 % de hechos); solo «dormido o tibio» garantiza cero degradación.
- Margen de RAM de 2 MB bajo el techo de 118 MB.

## 5. Cómo reproducir
```
python inferir.py --motor --experto modelos/experto_codigo.lora --redaccion modelos/experto_redaccion.lora   # chat multi-experto con memoria
python verificar_multiexperto.py          # 6 métricas de la Etapa 3
python probar_memoria.py --motor          # memoria (también sin --motor, con PyTorch)
python enrutador.py                       # enrutador de 3 estados: matriz de confusión
python sandbox.py                         # pruebas de seguridad del sandbox
```
