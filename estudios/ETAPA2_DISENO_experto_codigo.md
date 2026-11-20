# Etapa 2 — Diseño del primer experto modular: `experto_codigo.lora`

Estado: **propuesta, nada implementado todavía.** Núcleo Base congelado (ver [RESUMEN_ETAPA1.md](RESUMEN_ETAPA1.md)).

## Regla de qué va en el experto

| Va en el LoRA (conocimiento estable, se memoriza) | Queda afuera (se consulta con `B:` / `E:`) |
|---|---|
| Conceptos: variable, función, tipos, listas/diccionarios, pila/cola, árbol, recursión, bucles, POO, herencia, polimorfismo, excepciones | Sintaxis de librerías, frameworks y APIs que cambian: Angular, pandas, numpy, requests… |
| El **protocolo**: cuándo consultar documentación, cuándo ejecutar, cómo leer el resultado | Firmas exactas, parámetros, versiones |
| Abstenerse si la función o librería no existe | Cualquier dato que pueda haber cambiado |

## Dónde se inyecta el LoRA

El núcleo tiene 10 capas, cada una con 4 matrices: `qkv` (512→1536), `proy` (512→512), `fc1` (512→2048), `fc2` (2048→512).
LoRA agrega `y = BitLinear(x) + (α/r)·B·A·x` en paralelo, con A (r×in) y B (out×r) en precisión normal. Los pesos
ternarios del núcleo **no se tocan** (no se podría fusionar: sumar una matriz decimal rompería el {-1,0,+1}), por eso el
adaptador queda separado y se puede cargar y descargar.

| Dónde | r=4 | r=8 | r=16 |
|---|---|---|---|
| Solo atención (`qkv`+`proy`), 10 capas | 0,25 MB | 0,49 MB | 0,98 MB |
| Solo MLP (`fc1`+`fc2`), 10 capas | 0,41 MB | 0,82 MB | 1,64 MB |
| **Las 4 matrices, 10 capas** | 0,66 MB | **1,31 MB** | 2,62 MB |

(fp16; α = 2r.) **Propuesta: las 4 matrices en las 10 capas con r=8 → 655 mil parámetros, 1,31 MB**, dentro del
presupuesto de 1–3 MB. Razón: lo que se memoriza (conceptos) vive sobre todo en el MLP, y el protocolo (cuándo consultar)
en la atención. Ablaciones previstas, con el mismo dataset: r=4, r=16 y solo-atención, para ver cuánto aporta cada parte.
Embeddings, salida y LayerNorm quedan congelados (si hiciera falta vocabulario de código, un LoRA no lo agrega).

Coste en el motor: 655 mil parámetros extra sobre ~31 M ternarios = **~2,1 % más multiplicaciones** y +1,3 MB de RAM.

## Protocolo de herramientas (sin tokens nuevos)

Se reutiliza `<herramienta>` y se distingue por el prefijo, así el motor y el núcleo no cambian:

```
<usuario> ¿Cómo uso ngFor en Angular? <asistente> B: Angular ngFor documentación <herramienta> resultados <asistente> R: …<fin>
<usuario> ¿Qué imprime print(sum(range(5)))? <asistente> E: print(sum(range(5))) <herramienta> 10 <asistente> R: Imprime 10.<fin>
```

`E:` ejecuta código en un sandbox de Python: proceso aparte con timeout de 3 s, salida recortada a 200 caracteres, solo
`math` permitido (AST con lista blanca: sin `open`, `exec`, `eval`, `__`, `import` salvo `math`). Una excepción vuelve
como texto («ZeroDivisionError: division by zero») y el modelo la explica en `R:`.

## Dataset (≈ 40.000 ejemplos, generado por código)

| Tipo | % | Cómo se genera la verdad |
|---|---|---|
| **Conceptos** (`R:` directo) | 25 | ~90 fichas escritas a mano (concepto, definición en 1–2 frases, ejemplo de 1–3 líneas) × ~10 formas de preguntar. Se reservan formulaciones y ~15 % de conceptos para evaluar (los reservados deben salir por búsqueda) |
| **Documentación externa** (`B:` → `R:`) | 25 | Nombres reales de funciones sacados de `inspect` sobre paquetes instalados + librerías comunes; resultados **reales de ddgs** con la misma limpieza que en producción; respuesta aceptada solo si la oración aparece en un resultado (como en la Etapa 1) |
| **Ejecutar y verificar** (`E:` → `R:`) | 20 | Fragmentos generados por plantillas (aritmética, bucles, listas, diccionarios, cadenas, recursión, clases con herencia y polimorfismo, `try/except`); la salida es la **ejecución real** en el sandbox, incluidos errores |
| **Abstención** | 15 | Funciones o librerías inventadas: `B:` con resultados vacíos o irrelevantes → «No tengo información suficiente»; `E:` con `NameError` → informa que no existe |
| **Escribir código corto** | 5 | Especificación mínima → código (suma, máximo, invertir, factorial), verificada ejecutándola. Opcional; con 48 M se espera poco |
| **Repaso de la Etapa 1** | 10 | Conversación, hechos con ddgs y abstención generales, para no degradar el comportamiento con el experto activo |

Evaluación: conjuntos reservados por tipo; para `E:` se mide con el sandbox (¿la respuesta contiene el resultado real?);
para `B:`, con ddgs real sobre APIs reservadas.

## Enrutador (Capa 1, `enrutador.py`)

Puntaje por reglas, sin red neuronal: bloque de código ``` o patrones `def `, `class `, `import`, `=>`, `()` (+2);
palabras de dominio (función, clase, variable, bucle, array, excepción, herencia, Python, Angular, API, error…) (+1 cada
una). **Activa** con puntaje ≥ 2; **duerme** tras 2 turnos seguidos con puntaje 0 (histéresis, para no parpadear en una
charla de código). Un solo experto activo por turno; con el adaptador dormido el núcleo responde exactamente igual que en
la Etapa 1. Se evalúa con un conjunto etiquetado (código / no código) tomado de los datasets, meta ≥ 95 % de precisión y
cobertura.

## Entrenamiento (PyTorch)

Núcleo congelado (incluida su cuantización BitNet), solo A y B entrenables; B inicia en cero, así que parte idéntico al
base. bf16, lr ~5e-4, 3 épocas, mismos utilidades de la Etapa 1 (`protocolo.py`, `ajustar.py` extendido con
`--lora`). Se guarda solo el LoRA (~1,3 MB) en `experto_codigo.lora`.

## Soporte en el motor C++

Formato `LORA0001`: rango, α, y por cada (capa, matriz) A y B en fp16. Funciones nuevas en `motor.cpp`:
`nucleo_lora_cargar`, `nucleo_lora_activar(idx | -1)` y descarga. En el forward, tras cada `matmul_bit` se calcula `y += (α/r)·B(Ax)`
(dos matmul pequeños). Medición prevista, igual que en la Etapa 1: ms/token, RAM, tiempo de carga del `.lora` y de
activar/dormir, frente al núcleo solo. Meta: **< 10 % de aumento en ms/token y < 3 MB de RAM extra.**

## Criterios de éxito

1. Con el experto dormido: salida idéntica al Núcleo Base (se verifica bit a bit).
2. Con el experto activo: la evaluación general de la Etapa 1 no cae más de 2 puntos.
3. Ejecución: ≥ 90 % de respuestas que contienen el resultado real del sandbox.
4. Abstención ante funciones inexistentes ≥ 95 %.
5. Enrutador ≥ 95 %.
6. Motor: LoRA sobre C++ coincide con PyTorch (mismo token siguiente) y cumple la meta de coste.

## Riesgos (honestos)

- **Tokenizador:** medido, el código cuesta 1,8 caracteres por token contra 4,7 del español. Con contexto de 512 caben
  ~900 caracteres de código incluyendo la pregunta y los resultados. Un LoRA no puede cambiarlo.
- **El núcleo nunca vio código** en el preentrenamiento (solo Wikipedia y páginas web). Un adaptador de ~0,65 M
  parámetros tiene que enseñar sintaxis, conceptos y protocolo a la vez. Esperamos que aprenda bien el protocolo y los
  conceptos, y poco a escribir programas. Si «Escribir código» sale mal se deja fuera y el experto se limita a
  conceptos, consultas y ejecución de código dado.
- **Ejecutar código** del modelo en tu equipo: por eso el sandbox con lista blanca y timeout; no se habilita ninguna
  librería con acceso a archivos o red.
- **Alucinación sobre APIs:** la evaluación decisiva es la de funciones inexistentes; si el experto «recuerda» firmas
  que no debería, se recortan las fichas de conceptos.

## Orden de trabajo

1. `experto_datos.py`: fichas de conceptos, generador de ejecuciones, recolección de ddgs para documentación, sandbox.
2. `lora.py` y entrenamiento (`ajustar.py --lora`), con las 3 ablaciones.
3. `enrutador.py` y su evaluación.
4. Exportación `.lora` + soporte en `motor.cpp`, verificación contra PyTorch y benchmark.
5. Resumen técnico de la Etapa 2 en `estudios/`.
