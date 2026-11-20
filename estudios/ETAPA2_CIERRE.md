# Etapa 2 — Cierre (experto de código)

Fecha de cierre: 2026-11-20. Modelos congelados: `nucleo_sft_v3` + `experto_codigo.lora` (sin reentrenar). Todo lo de esta ronda es capa de Python.

## Qué se cambió tras las pruebas en vivo

| Archivo | Cambio | Motivo |
|---|---|---|
| `enrutador.py` | Puntaje por **sintaxis de Python** (+2 cada una): llamadas `sum/len/range/print/...(…)`, `**`, comprensiones `[… for x in …]`, `for x in y`, `f(1, 2)`, indexado, «ejecuta…:». Sinónimos de fichas (**recursividad**, lambda, stack, queue, bucles…). Palabra ambigua (pila, cola, árbol…) cuenta doble si hay contexto de programación («en programación», «algoritmo», «python»…). | «¿Qué es la recursividad?» y «Ejecuta esto: sum(…)» no despertaban al experto. |
| `sandbox.py` | `math` disponible sin `import` y `sqrt, factorial, sin, cos, tan, log, pi, e, ceil, floor` como globales. `pow` ya es el builtin (se deja, porque devuelve enteros). | El modelo emitió `E: sqrt(144) + math.factorial(5)` (sin el primer `math.`). |
| `inferir.py` | Sin preguntas por argumento: **chat interactivo** con `input()` (`salir` o Ctrl+C/Ctrl+Z termina). El enrutador conserva su estado entre turnos. | Pruebas en terminal sin reiniciar el programa. |

Uso: `python inferir.py --motor --experto modelos/experto_codigo.lora`

## Verificación

- `python enrutador.py`: cobertura **81,4 % → 82,3 %** (conceptos 65 → 67 %, ejemplos de concepto 72 → 74 %); falsos positivos **sin cambio, 17 de 3.230 (0,5 %)**, precisión 99,2 %; guion de histéresis 12/12.
- `python sandbox.py`: **28/28** (incluye 3 casos nuevos de `math` sin prefijo); los ataques siguen bloqueados.
- En vivo (motor C++ + `experto_codigo.lora`):
  - «¿Qué es la recursividad?» → **experto despierto** (antes dormido). Emite `B: recursbilidad programación` (error de tipeo propio del modelo), la búsqueda devuelve resultados sobre recursividad, pero el núcleo se abstiene («No tengo información suficiente»).
  - «math.sqrt(144) + math.factorial(5)» → `E: math.sqrt(144) + math.factorial(5)` → `132.0` → «Imprime 132.0.» ✔
  - «Ejecuta esto: sum([x**2 for x in range(1, 6)])» → **experto despierto** (antes dormido), pero con el adaptador final el modelo degenera (`E:atasatas…`) y no llega al sandbox. Con «Ejecuta: sum([x*x for x in range(1, 6)])» → `55` ✔, y con `experto_r16_B_e3.lora` la frase original también da `55` ✔.

## Límites que quedan abiertos (no se resuelven en capa Python)

1. La combinación `x**2` + «Ejecuta esto:» hace que el adaptador final degenere. Es un fallo del modelo/adaptador (el candidato `B_e3` no lo tiene); corregirlo exige datos de entrenamiento con `**` o reentrenar, fuera del alcance acordado.
2. Errores de tipeo en la consulta de búsqueda (`recursbilidad`) y abstención aunque haya resultados útiles: mismo origen.
3. Conceptos sin contexto («Cuéntame qué es una pila») siguen sin detectarse solos; la histéresis los cubre dentro de una conversación de código.
4. Los falsos positivos restantes son títulos de Wikipedia con palabras como «Librería» o «Árbol de Navidad».

## Estado

Etapa 2 **cerrada** con estos límites documentados. Detalle de diseño, datos, LoRA y ablaciones en `ETAPA2_DISENO_experto_codigo.md`, `ETAPA2_PASO1…3`.
