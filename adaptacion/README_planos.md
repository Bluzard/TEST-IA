# Biblioteca persistente de planos

Implementación de la propuesta final de la transcripción del 25 de noviembre
de 2026: un núcleo de adaptación pequeño y una biblioteca externa que crece
en SQLite. No requiere LLM, embeddings ni entrenamiento de modelos.
Usa `sqlite3` de Python y NumPy, ya utilizado por el laboratorio.

## Ejecutar en Windows

Desde la raíz del repositorio, con el entorno virtual existente:

```powershell
# Primera vida: recibe un plano que especifica piezas, no conexiones del cuerpo.
.\.venv\Scripts\python.exe adaptacion\experimento_planos.py vivir --db adaptacion\memoria_planos.sqlite --plano correcto --vida 15000

# Cerrar y volver a ejecutar: conserva la biblioteca, con un cuerpo nuevo.
.\.venv\Scripts\python.exe adaptacion\experimento_planos.py vivir --db adaptacion\memoria_planos.sqlite --vida 15000

# Cambiar de terreno y estado inicial; busca evidencia en contextos similares.
.\.venv\Scripts\python.exe adaptacion\experimento_planos.py vivir --db adaptacion\memoria_planos.sqlite --semilla 100 --vida 15000

# Incorporar un archivo externo, también compatible con planos abstractos almacenados.
.\.venv\Scripts\python.exe adaptacion\experimento_planos.py vivir --db adaptacion\memoria_planos.sqlite --importar adaptacion\planos_ejemplo\parcial.json --vida 15000

# Comparación con bibliotecas nuevas e independientes para cada vida y variante.
.\.venv\Scripts\python.exe adaptacion\experimento_planos.py comparar --rep 8 --vida 15000 --salida adaptacion\resultados_planos_corta.json

# Pruebas.
.\.venv\Scripts\python.exe -m unittest discover -s adaptacion -p test_planos.py -v
```

`vivir` crea la base si no existe y guarda cada actualización durante la vida.
La segunda ejecución no necesita volver a importar el plano. `sin_plano` significa
que no se añade uno nuevo: una base reutilizada puede contener planos externos.
Para un control sin experiencia previa, usar una ruta de base nueva o `comparar`.
`comparar` conserva resultados en JSON y elimina sus bases temporales al terminar;
`vivir` mantiene la biblioteca indicada en `--db`. `--salida` también funciona con
`vivir`. Las semillas deben ser no negativas y la vida, de al menos 256 pasos.

## Qué guarda y cómo lo usa

| Tabla | Contenido |
|---|---|
| `contextos` | Vector binario float64, dimensión y versión de los rasgos |
| `planos` | Contenido JSON, tipo concreto/abstracto, origen propio/externo y firma para evitar duplicados |
| `confianza` | Intentos, logros y confianza reciente por plano y contexto |

La huella usa los primeros 256 pasos de observación de los dos canales del río:
media absoluta, desviación, cambio entre pasos y correlación. Son siete rasgos
acotados, calculados sin consultar la matriz del mundo, sus parámetros ni su
semilla. El sujeto continúa adaptándose durante esta ventana; desde el paso 256
puede recuperar planos. La búsqueda exacta usa distancia RMS, radio 0,25 y hasta
cinco contextos vecinos. Se recuperan hasta 32 planos, ponderados por confianza y
proximidad. Son parámetros iniciales explícitos, pendientes de calibración.

Una solución propia entra en SQLite tras 400 pasos estables. Se conserva su
asociación al contexto aunque aún no tenga un intento completo de 1.000 pasos.
Los planos recuperados compiten con la exploración usando las reglas del sujeto
«satisfecho 90 %». Un fallo reduce a la mitad la confianza; los éxitos la elevan
cuando se alcanza la aspiración, como en el núcleo original.

La evidencia de un vecino sirve de prior al elegir una opción; sus contadores
no se escriben como experiencia del contexto actual. Tras el primer resultado
local se utilizan los contadores locales. Un fallo aquí no modifica la evidencia
de otros contextos. Los planos externos empiezan sin logros y con confianza 0,5.
No se borran por fallar: pierden prioridad y pueden volver a probarse.

## Formato externo

Los archivos de `planos_ejemplo/` muestran los tres casos. Cada archivo contiene
una lista de objetos con `tipo` y `contenido`. Para el tipo `concreto`, el contenido
incluye `version: "componible-v1"` y `configuracion`, una lista de 44 posiciones:
40 conexiones de `W` aplanadas por filas y cuatro colocaciones de piezas.

`null` deja esa posición sin especificar y conserva su valor al aplicar el plano.
El ejemplo correcto especifica solo `[1, 2, 2, 8]` para las piezas; el incorrecto
invierte los signos con `[1, 2, 1, 7]`; el parcial fija las dos anclas y deja ambos
apoyos sin especificar. Ninguno entrega conexiones internas ya resueltas.
Los valores y las dimensiones se validan antes de importar. Los planos abstractos
se guardan como objetos JSON, pero todavía no se interpretan ni ejecutan.

## Verificación y comparación corta

Las pruebas cubren cierre/reapertura de SQLite, recuperación y uso por un sujeto
nuevo, separación de confianza entre contextos, ausencia de evidencia local
inventada al recuperar vecinos, planos parciales, formatos inválidos, aislamiento
de versiones de huella, exclusión de grafos abstractos y reproducción de vidas.
También se verificó una trayectoria original idéntica durante 3.000 pasos al
comparar el controlador con la versión anterior de `entorno_componible.py`.

Resultados exploratorios: 8 vidas por variante, semillas 0–7, 15.000 pasos.
Las variantes reciben el mismo terreno, estado inicial y perturbaciones. El azar
de las perturbaciones se separa del azar de reorganización; las bibliotecas están
aisladas por vida y variante. El JSON conserva todos los registros individuales.

| Conocimiento | Vidas con puente estable | Mediana de episodios de caída | Tiempo medio con puente armado |
|---|---:|---:|---:|
| Ninguno | 4/8 | 155,5 | 29,6 % |
| Plano correcto | 6/8 | 117,5 | 78,0 % |
| Plano incorrecto | 3/8 | 166,0 | 24,6 % |
| Plano parcial | 4/8 | 128,0 | 54,1 % |

«Puente estable» en esta medición exige una estructura de puente y 400 pasos
consecutivos de viabilidad, sin saturar el río ni las piezas. No demuestra por sí
solo que el puente causara esa viabilidad o que resista perturbaciones posteriores.
«Tiempo con puente armado» solo mide la estructura, incluso durante caídas.
`viable_final` puede ser verdadero sin puente: contempla viabilidad, estabilidad
lineal y ausencia de caídas en el último tramo, independientemente de las piezas.
Los tiempos de llegada sin éxito se guardan como `null`; la mediana de tiempo
publicada en el JSON usa solo éxitos y debe leerse junto a su número de vidas.

## Límites y siguientes pasos

- Es una muestra pequeña, sin prueba larga ni conclusión estadística de mejora.
- La huella depende también de la acción del sujeto. No es una identificación
  independiente del terreno; repetir una semilla verifica recuperación en el mismo
  comienzo, no transferencia a un contexto distinto.
- Se fija una huella por llamada a `vivir`. Un cambio de terreno exige una nueva
  llamada para renovar la observación; no hay detección automática de cambios.
- La confianza evalúa el intento completo: un plano de piezas correcto puede ser
  castigado porque el cuerpo aún falla, aunque sus piezas ayuden después. La prueba
  corta muestra ese efecto. Falta separar la contribución causal del plano de la
  adaptación corporal; no se debe equiparar confianza baja con información falsa.
- Los planos parciales se prueban conservando lo no especificado. Esto permite
  combinarse con exploración, pero todavía no hay un mecanismo dedicado a completar
  planos ni a abstraer automáticamente roles y relaciones.
- Se persisten configuraciones y evidencia; el estado dinámico del cuerpo y del
  mundo no se restaura. Cada ejecución inicia una vida nueva.
- La búsqueda exacta recorre los contextos y la biblioteca crece sin poda. No se
  han medido grandes volúmenes ni implementado `sqlite-vec`.

El siguiente experimento de fondo es una comparación más larga y transferencia
entre terrenos relacionados, junto con una evaluación de la atribución del fallo.
