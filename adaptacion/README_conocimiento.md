# Adquisición y uso de conocimiento estructurado

Prototipo acotado, sin LLM, preentrenamiento ni dependencias nuevas. Diseño y
revisión del código anterior en [DISENO_conocimiento.md](DISENO_conocimiento.md).
Se conserva el controlador anterior sin cambios. Este experimento prueba una
extensión cognitiva aislada; todavía no demuestra su integración con la dinámica
continua del núcleo W/P. El 90 % se conserva como criterio de evaluación, sin
reproducir ni ajustar el mecanismo de aspiración del controlador anterior.

## Reproducir

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s adaptacion -p "test_*.py" -v
.\.venv\Scripts\python.exe adaptacion\experimento_conocimiento.py --rep 40 --pasos 160 --semilla 0 --salida adaptacion\resultados_conocimiento.json
```

Para conservar una vida en SQLite y recibir un archivo externo, el ejemplo usa
los roles del catálogo generado por la semilla 0:

```powershell
.\.venv\Scripts\python.exe adaptacion\experimento_conocimiento.py --db adaptacion\memoria_relacional.sqlite --importar adaptacion\relaciones_ejemplo.json --semilla 0 --pasos 160 --salida adaptacion\vida_relacional.json
# Otra vida: sin reimportar, reutiliza la misma biblioteca.
.\.venv\Scripts\python.exe adaptacion\experimento_conocimiento.py --db adaptacion\memoria_relacional.sqlite --semilla 0 --pasos 160 --salida adaptacion\vida_relacional_2.json
```

La comparación usa bases nuevas en memoria, aisladas por semilla y condición;
no lee la base persistente de esos ejemplos. Las ejecuciones individuales pueden
tener experiencia previa: no son controles A. Las bases relacionales son distintas
de `memoria_planos.sqlite`. Una nueva semilla genera otros roles, que no coinciden
necesariamente con el ejemplo; no se supone equivalencia semántica entre ellos.

## Mecanismo

`conocimiento_relacional.py` recibe únicamente observaciones, necesidades,
acciones públicas, contexto y deriva observable. Elige un candidato según la
reducción del déficit total prevista a un paso, menos coste e incertidumbre. Puede
esperar y explora con probabilidad 0,15. Sin modelos explora cuando hay déficit;
puede esperar sin manual cuando no existe necesidad actual o prevista.

Una relación describe selector de entidad, operación, contexto, intervalos de
aplicación y efectos aditivos. Las claves `$atributo` se enlazan a propiedades de
la entidad elegida. Por ejemplo, `$canal` significa la variable indicada en el
atributo público `canal`, no un nombre de variable fijado en el intérprete.
Las condiciones delimitan validez del modelo; no son prohibiciones físicas:
la exploración puede probar una acción sin modelo aplicable. El catálogo del
adaptador debe ofrecer sólo acciones físicamente permitidas. El presupuesto
filtra todas las acciones, incluida exploración.

SQLite separa hechos de catálogo, relaciones externas inmutables, experiencias,
evidencia externa, hipótesis empíricas y evidencia sobre estas últimas. Se guarda
procedencia, contexto, acción, coste, estados, fondo descontado y error de cada
predicción. `contra > favor` señala relaciones cuestionadas; no demuestra falsedad
universal. Se contrastan también relaciones aplicables que no determinaron la
decisión. El contador de usos externos cuenta decisiones realmente seleccionadas
por el manual, y no se confunde con ese número mayor de contrastes.

Las hipótesis estiman deltas medios por selector público, operación y contexto;
reemplazan nombres de variables por referencias a atributos cuando es posible.
La experiencia local prevalece sobre el manual. La transferencia mueve hipótesis
y tamaños muestrales fuente, pero no testimonios, hechos, experiencias ni evidencia
local. Los tamaños fuente actúan como prior acumulado, no como observaciones
nuevas del destino. No hay olvido rápido: ese supuesto falla en el control adverso.

La implementación elige el último modelo aplicable de cada origen y da prioridad
al empírico. No fusiona fuentes contradictorias ni infiere precondiciones. La
incertidumbre es heurística (0,5 externa; 1/(n+1) empírica), no una probabilidad
calibrada. La tolerancia externa la entrega el documento; se asume confiable como
metadato experimental, aunque sus efectos pueden ser falsos.

## Experimento y resultados

Ejecución del 2026-11-26: **40 semillas pareadas, 160 decisiones por vida,
8 condiciones, 320 vidas evaluadas**. Cada D añade una fuente A de 160 decisiones
por semilla; esa fuente es común a las tres variantes D y se ejecuta aparte de A.
No se ajustaron parámetros después de ver resultados. Tras la primera ejecución
se añadió auditoría de predicciones empíricas, sin cambiar la política: las 320
huellas de trayectoria coincidieron exactamente con la ejecución previa. Se
conservan en [auditoria_trazas_conocimiento.json](auditoria_trazas_conocimiento.json).

La cámara tiene tres variables, doce componentes y cuatro roles opacos. Hay dos
contextos, con cambio a mitad de vida, efectos de distinta magnitud y coste, ruido
acotado y deriva pública. La misma semilla fija física, ruido, estado inicial,
catálogo y azar de decisión entre A/B/C. Los documentos describen efectos por rol
y contexto, sin secuencias de acciones. El generador de documentos conoce la
física verdadera para construir B y su inversión C; el intérprete no la consulta.

D cambia IDs, orden de componentes, estado inicial y magnitud de deriva, y recibe
sólo hipótesis adquiridas explorando en la fuente A. Los efectos y roles se
conservan. El control permutado mantiene la física del destino y cambia la
correspondencia entre roles y efectos, sin advertirlo al agente.

La satisfacción exige **todas** las variables en [-0,25, 0,25] tras la decisión.
Coste es gasto acumulado; el presupuesto por decisión es 1, renovable, sin depósito
agotable. «Exploración» es selección al azar, no número de acciones ni coste.

| Condición | Satisfacción | Primeros 20 pasos | Últimos 40 | Exploraciones | Coste |
|---|---:|---:|---:|---:|---:|
| A: sin información externa | 47,66 % | 33,38 % | 51,69 % | 25,10 | 50,82 |
| B: información correcta | 62,11 % | 67,75 % | 55,81 % | 23,55 | 50,54 |
| C: efectos invertidos | 46,45 % | 22,88 % | 53,00 % | 23,55 | 54,98 |
| B sin actualización empírica | 57,16 % | 65,25 % | 49,06 % | 23,55 | 50,48 |
| C sin actualización empírica | 0,05 % | 0,38 % | 0,00 % | 23,55 | 123,23 |
| D: transferencia por roles | 52,84 % | 64,38 % | 42,81 % | 23,55 | 58,85 |
| D: memoria vacía | 36,16 % | 24,13 % | 35,69 % | 25,15 | 59,48 |
| D: roles permutados | 0,64 % | 0,38 % | 0,00 % | 23,55 | 82,51 |

Medias entre semillas. El coste adicional de adquirir la fuente D es 50,82 y
25,10 exploraciones de media: no debe omitirse al comparar gasto total.

| Diferencia pareada | Satisfacción, puntos porcentuales | IC bootstrap descriptivo 95 % |
|---|---:|---:|
| B − A | +14,45 | [+11,00; +18,03] |
| C − A | −1,20 | [−4,75; +2,47] |
| C − C sin actualización | +46,41 | [+43,36; +49,23] |
| D − D vacío | +16,69 | [+12,12; +21,53] |

Se remuestrean diferencias por semilla (2.000 muestras), no pasos correlacionados.
Son intervalos exploratorios de esta familia, sin corrección por comparaciones
múltiples. B no muestra una reducción clara de coste: diferencia −0,28,
intervalo [−0,97; +0,63]. La reducción de exploración es pequeña (1,55 decisiones);
conocer relaciones cambia sobre todo la elección de acciones, no la tasa fija
de exploración. No hay mejora fuerte en número de componentes distintos probados.

B priorizó acciones mediante testimonio 4,63 veces por vida de media, pasando
después a modelos empíricos. C lo hizo 4,08 veces. B tuvo 0 contradicciones entre
4.179 contrastes externos; C, 4.126 entre 4.126. Esto mide detección en efectos
invertidos, de gran magnitud y ruido pequeño: no sensibilidad general a errores
sutiles ni inferencia causal en presencia de confusión. La ablación sin aprendizaje
continúa auditando, pero no modifica sus predicciones ni decisiones por esa evidencia.

**Ninguna vida de ninguna condición alcanzó el 90 % de satisfacción.** El mecanismo
mejora elecciones, pero no logra el objetivo de viabilidad provisional. Tampoco
resiste el cambio oculto de semántica en D: detectó 5.063 contradicciones en 5.568
predicciones empíricas, pero sus promedios heredados se corrigen demasiado despacio.
Detectar no basta para actuar adecuadamente sobre esa evidencia. Se conserva este
fallo, sin introducir olvido ni cambios de política después de observarlo.

Los registros de cada vida, tamaños de muestra, usos, contrastes, intervalos,
semillas y hashes de código están en
[resultados_conocimiento.json](resultados_conocimiento.json). Las 24 pruebas
pasaron: 10 nuevas y las 14 pruebas de planos existentes, sin repetir sus estudios.

## Alcance de la conclusión

Hay evidencia de uso de relaciones externas antes de experimentar sus efectos,
corrección local frente a testimonio falso y transferencia por una ontología
pública estable. No se almacenan secuencias resueltas ni se buscan configuraciones
W/P. El mismo intérprete sirve para propiedades arbitrarias; las pruebas incluyen
enlace de una relación aprendida de presión a voltaje con nuevos identificadores.

Pero los roles públicos, sus correspondencias con canales, las necesidades y las
unidades están definidos por nosotros. Los componentes con un mismo rol tienen
efectos equivalentes; no se aprende esa equivalencia desde percepción cruda. Los
efectos son aditivos e inmediatos; la deriva es observable; no hay cadenas de
prerrequisitos, planificación multietapa, objetivos emergentes ni variables ocultas.
Las condiciones se interpretan y prueban por contrato, pero el experimento sólo
varía el contexto, no exige descubrir precondiciones numéricas. Tampoco se ensaya
la combinación de fuentes incompatibles. La selección usa un criterio programado
de déficit: podría describirse como un pequeño planificador basado en modelos.
Llamarlo «comprensión» excedería esta evidencia.

La pregunta central queda **respaldada sólo en esta familia restringida**, y su
versión amplia sigue abierta. El siguiente paso justificado es diseñar revisión
de hipótesis con evidencia local y comprobarla con un protocolo nuevo y semillas
reservadas; después abordar efectos condicionados y consecuencias diferidas.
La conexión con el núcleo continuo original requiere otro experimento específico.
