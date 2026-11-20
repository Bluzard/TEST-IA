# Etapa 2 · Pasos 2b y 3 — Experto de código final, enrutador y LoRA en el motor C++ (2026-11-20)

Continúa [ETAPA2_PASO2_lora_y_ablaciones.md](ETAPA2_PASO2_lora_y_ablaciones.md). Registros y JSON completos en [etapa2/](etapa2/).

## Experto final (congelado)
`modelos/experto_codigo.lora` — 2,62 MB, SHA-256 `B5703263…0278C6` (completo en `modelos/EXPERTO_CODIGO.json`; archivo en solo lectura). El Núcleo Base sigue intacto.
r=16 en las 4 matrices de las 10 capas (qkv, proy, fc1, fc2), α=32, 3 épocas sobre `datos/experto_train_B2.jsonl`. Entrenamiento: `modelos/experto_r16_B2_e3.lora.pt`.

## 1. Opción A (memorizar definiciones, más formulaciones): no superó el umbral
Umbral fijado antes de correr: acierto exacto en conceptos ≥ 60 % (partía de 16 %).

| r=16 | Conceptos (exacta) | Concepto desconocido: busca | General: abstención |
|---|---|---|---|
| 7 formulaciones, 3 ép. | 16 % | 65 % | 98,1 % |
| 27 formulaciones, 3 ép. | 45 % | 52 % | 98,1 % |
| 27 formulaciones, 6 ép. | **53 %** | **48 %** | 96,2 % |

Mejora real (+37 puntos) pero **sin llegar a 60 %**, y con un efecto indeseado: cuanto más memoriza, **menos busca** en conceptos que no conoce (65 % → 48 %), es decir,
inventa más. Memorizar definiciones en un adaptador chico es caro y frágil.

## 2. Opción B (base local + LoRA solo de protocolo): sí funciona
`herramientas.buscar_ficha()` consulta primero las 107 fichas (sub-milisegundo, sin red) cuando el experto está activo; si el concepto no está, `buscar_web` va a ddgs.
El modelo siempre emite `B: <concepto> programación` y copia la definición del resultado; ya no la memoriza.

| Tipo (r=16, 3 épocas) | Opción A (6 ép.) | **Opción B** |
|---|---|---|
| Conceptos entrenados, formulaciones nuevas (exacta) | 53 % | **68 %** → 79 % con los formatos nuevos |
| Ejemplos de código de un concepto | 100 % | 100 % |
| Fichas reservadas (nunca vistas) leídas de la base | — | 42 % (sim ≥ 95 %: 58 %) |
| **General: hechos (Etapa 1, ddgs real)** | 66,2 % | **73,9 %** (núcleo solo: 71,6 %) |
| General: abstención | 96,2 % | 96,2 % |

La regresión general (−5 puntos con el experto activo en el Paso 2) **desaparece**: el repaso de la Etapa 1 más el entrenamiento en lectura de resultados reales
dejan al núcleo igual o mejor.

## 3. Hallazgo al integrar: formatos de entrada
Probando de punta a punta con el motor C++ el experto copiaba mal el código cuando venía **en la misma línea** que la pregunta («¿Qué imprime este código? print(…)»)
y se abstenía con código suelto. Mi dataset siempre ponía el código tras un salto de línea. Se agregaron cuatro formatos (otra línea 45 %, misma línea 22 %, código solo 13 %,
bloque ``` 20 %) y se midió la brecha con la evaluación nueva:

| Evaluación con formatos variados | Ejecución ok | Ejecución con error | Puntaje |
|---|---|---|---|
| Modelo entrenado con un solo formato | 72 % | 60 % | 71,1 % |
| **Modelo con formatos variados (final)** | **95 %** | **94 %** | **82,2 %** |

Resultado final (evaluación reservada, 1.085 casos): conceptos 79 %, ejemplos 100 %, fichas reservadas 51 %, documentación con respuesta 59 % (sim ≥ 95 %),
abstención en documentación 80 %, ejecución correcta 95 %, con error 94 %, `NameError` 100 %, interpretar un error 82 %. Abstención general 98,1 % (igual que el núcleo).
Integridad: el núcleo quedó intacto (suma de verificación idéntica) y con el adaptador dormido la evaluación general es idéntica al núcleo solo.

Con 6 épocas el puntaje bajó (76,9 % contra 79,1 % con 3 en el mismo conjunto; ejecución 95 % → 76 %): sobreajuste. Se usó 3.

## 4. Enrutador (Capa 1, `enrutador.py`)
Puntaje por reglas, un solo experto activo por turno. Activa con puntaje ≥ 2; **reposo tras 2 turnos seguidos sin señal**; un tema nuevo sin señal de código
(mensaje largo o con nombres propios) duerme al tiro.

| Métrica | Resultado |
|---|---|
| Precisión (3.230 mensajes generales) | **99,2 %** (17 falsos positivos, 0,5 %) |
| Cobertura (2.585 mensajes de código) | **81,4 %** — ejecución 100 %, documentación 82–89 %, conceptos 62–72 % |
| Guion de histéresis | 12 de 12 turnos correctos |

Lo que no detecta son conceptos sin contexto («Cuéntame qué es una pila»), genuinamente ambiguos: una vez dentro de una conversación de código, la histéresis los cubre.
Los falsos positivos son títulos de Wikipedia con palabras como «Librería» o «Árbol de Navidad».

## 5. LoRA en el motor C++ (`motor.cpp`, `exportar_lora_cpp.py`)
Formato `.lora` (A en fp16 y B **transpuesta** para sumar de forma vectorizada), API `cargar` / `activar` / `descargar` al vuelo. En decodificación (1 token) se calcula en serie
(OpenMP no compensa el coste de arrancar); en el prefill, en paralelo por token.

Verificación: contra PyTorch fp32, diferencia máxima de logits 0,007 y **mismo token siguiente en 240 de 240** prompts; con el adaptador **dormido el motor es idéntico bit a bit**
al motor sin adaptador, y tras descargarlo también. El `.lora` de 2,62 MB carga en 1,4–7 ms.

Costo medido (40 prompts del experto; prompts de ~68 tokens):

| Configuración | RAM pico | ms/token (todos los hilos) | ms/token (1 hilo) |
|---|---|---|---|
| Núcleo solo | 110 MB | 1,77 | 5,81 |
| Adaptador dormido | 112 MB | 1,36 | — |
| **Adaptador activo** | **112 MB** | **1,52** | **5,87** |

- **RAM:** +2–3 MB (el tamaño del adaptador en fp16). Meta < 3 MB: cumplida.
- **Velocidad:** con 1 hilo, **+1 %**. Con todos los hilos las mediciones de la misma configuración varían ±20 % entre corridas (el núcleo solo dio 1,77 y el dormido 1,36
  haciendo lo mismo), así que ahí el efecto del adaptador queda dentro del ruido. Meta < 10 %: cumplida.
- Con prompts generales (~119 tokens) el resultado fue el mismo: 1,47 / 1,64 / 1,64 ms/token.

## Límites
- Las fichas reservadas (nunca vistas) se copian de la base con 42–51 % de acierto exacto; con más datos mejoraría.
- Documentación con respuesta: sim ≥ 95 % solo en 59 % de 59 casos (evaluación chica). Las respuestas siguen en inglés, sin traducir.
- El sandbox ejecuta solo `math`; la cobertura del enrutador sin contexto es de ~81 %.
- Un ruido de ±20 % en tiempos multihilo impide afirmar diferencias pequeñas en velocidad.
