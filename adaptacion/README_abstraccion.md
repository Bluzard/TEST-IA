# Abstracción estructural desde éxitos propios (Frente #4)

`abstraccion_estructural.py` · resultados en `resultados_abstraccion.txt` / `.json`
· pruebas en `test_abstraccion.py`.

```powershell
.\.venv\Scripts\python.exe adaptacion\abstraccion_estructural.py --rep 100
```

## Pregunta

Tras armar por sí solo dos puentes en mundos distintos, sin plano al nacer,
¿puede el sujeto extraer lo común y armar el tercero más rápido? ¿Y cuánto de
eso lo hace la comparación entre casos, y cuánto un sesgo innato?

## Diseño

- **Mundos que impiden la copia.** Cada mundo tiene su propio río y re-mapea
  en secreto qué significa cada código de pieza. La física del puente es la
  misma, pero sus códigos cambian. En todos los mundos hay la misma cantidad de
  arreglos válidos, así que la búsqueda a ciegas es igual de difícil.
- **Lo que guarda de un éxito.** Cuando una configuración alcanza el 90 %,
  estima por mínimos cuadrados (norma mínima, sin transiciones recortadas) cómo
  influyen entre sí las variables que percibe del entorno: río R y piezas P. El
  cuerpo queda fuera. La firma es el conjunto de ciclos dirigidos de largo ≥ 2
  del grafo con |influencia| > 0,5, descritos por sus tipos y por su signo.
- **Abstracción.** Intersección de las firmas de los mundos 1 y 2, tomando el
  éxito más sostenido de cada uno.
- **Uso en el mundo 3, sin predicción.** La exploración sigue siendo al azar.
  Cuando el arreglo presente calza con la abstracción, las piezas de los ciclos
  que calzan se bloquean y se abre una ventana de acoplamiento (modo C,
  `R_max` = 20). Si la ventana se agota, ese arreglo no vuelve a reconocerse.

Se comparan dos variantes de lo que significa «calzar»:

| Variante | Firma que se usa | Cuándo reconoce |
|---|---|---|
| Con sesgo de agencia | solo ciclos que pasan por piezas | si está presente algún rasgo de la abstracción |
| Sin sesgo de agencia (`*_sin_agencia`) | todos los ciclos, también los del río solo | si está presente la abstracción completa |

Sin el sesgo de agencia, la firma de un solo éxito arrastra los accidentes de
su río y de su arreglo. Solo la comparación entre dos éxitos puede filtrarlos.

**Sesgos que quedan en ambas variantes:** la representación (grafo con signo,
ciclos, umbral), que el sujeto distinga sus sensores de río de los de sus
piezas, y que el experimentador decida cuándo se abstrae (al entrar al mundo 3).

## Resultados (100 vidas pareadas; fuentes de 100.000 pasos; mundo 3 de 60.000)

Fuentes: 76 y 78 de 100 vidas arman puente propio. 56 vidas tienen un éxito
con firma en ambos mundos; en 40 de ellas, los dos éxitos usaron piezas. En las
otras 16, uno era un «salto» sin piezas, y entonces lo común no tiene piezas.

Pasos hasta el primer puente estable en el mundo 3. Mediana; las vidas que no
lo logran cuentan como 60.000.

| Condición | Todas (100) | Dos éxitos (56) | Ambos con piezas (40) |
|---|---:|---:|---:|
| Sin memoria | 8.046 | 6.384 | 7.544 |
| Copiar W+P | 11.665 | 8.936 | 9.991 |
| Agencia, 1 ejemplo | **2.814** | **2.046** | **1.466** |
| Agencia, 2 ejemplos | 4.362 | 3.030 | 1.732 |
| Agencia, firma invertida (control) | 6.886 | 5.200 | 3.988 |
| Sin agencia, 1 ejemplo | 3.649 | 2.973 | 2.244 |
| Sin agencia, 2 ejemplos | 4.362 | 3.030 | 2.038 |
| Sin agencia, firma invertida (control) | 6.886 | 5.200 | 3.988 |
| Firma escrita a mano (techo) | 1.704 | 1.580 | 1.580 |

Comparaciones pareadas clave (pasos censurados, prueba de signo):

| Comparación | Vidas | Resultado | p |
|---|---|---|---:|
| agencia 2 ejemplos contra sin memoria | 100 | más rápida en 16, más lenta en 4 | 0,012 |
| agencia 2 ejemplos contra firma invertida | 100 | más rápida en 19, más lenta en 5 | 0,007 |
| **sin agencia: 2 ejemplos contra 1** | 40 con piezas | **2 más rápida en 10, más lenta en 2** | **0,039** |
| sin agencia: 2 ejemplos contra 1 | 100 | 2 más rápida en 14, más lenta en 10 | 0,54 |
| agencia 1 ejemplo contra sin agencia 2 ejemplos | 100 | agencia más rápida en 22, más lenta en 7 | 0,008 |
| agencia 1 ejemplo contra sin agencia 2 ejemplos | 40 con piezas | agencia más rápida en 8, más lenta en 4 | 0,39 |

Desglose de las 40 vidas con dos éxitos con piezas, sin agencia, según lo que
la intersección quitó de la firma de un solo ejemplo:

| Lo que filtró la intersección | Vidas | 1 ejemplo | 2 ejemplos | 2 más rápida / más lenta |
|---|---:|---:|---:|---:|
| nada (las firmas ya coincidían) | 13 | 1.936 | 1.936 | 0 / 0 |
| ciclos accidentales con piezas | 18 | 2.008 | 1.701 | 6 / 2 |
| ciclos accidentales del río | 9 | 19.840 | 13.113 | 4 / 0 |

## Lectura

1. **El sujeto extrae la relación correcta por sí solo.** Cuando sus dos éxitos
   fueron puentes, arma el tercero tan rápido como con la firma escrita a mano
   (1.732 contra 1.580 pasos). Importa el contenido y no solo el mecanismo: con
   la firma invertida no hay ganancia clara.
2. **Copiar la configuración concreta no sirve** en mundos re-mapeados.
3. **Comparar dos casos sí filtra accidentes, pero solo cuando falta el sesgo de
   agencia.** Sin él, la intersección quita lo accidental y gana en 10 de las 12
   vidas donde hubo diferencia (p = 0,039). Donde más importa es cuando un
   accidente del río quedaba en la firma: con un ejemplo, el reconocimiento casi
   nunca calzaba (19.840 pasos) y la intersección lo rescata (13.113).
4. **El sesgo de agencia rinde más que la comparación.** Un ejemplo con agencia
   (1.466 pasos) es más rápido que dos ejemplos sin ella (2.038). Sobre todas
   las vidas la diferencia es significativa (p = 0,008); en las 40 vidas con
   dos éxitos con piezas, no (p = 0,39). El sesgo de agencia hace casi todo el
   filtrado sin pedir un segundo ejemplo, y por eso también se salva de su modo
   de fallar.
5. **La intersección tiene un modo de fallar propio.** Si uno de los dos éxitos
   fue un salto, lo común queda sin piezas y no sirve para nada. Esto pasa en 16
   de 56 vidas. Sobre todas las vidas, por esa razón dos ejemplos no superan a
   uno.
6. **La prueba de filtrado es débil.** Solo 9 de 40 abstracciones de un ejemplo
   traían accidentes del río (con el umbral 0,5 los ciclos del río son raros), y
   las 18 con accidentes de piezas miden también el efecto de exigir que calce
   todo. El efecto de la comparación es real, pero chico y se apoya en pocas
   vidas.

**Respuesta a la pregunta de los sesgos mínimos:** en esta familia, un sesgo
estructural innato («lo que pasa por lo que yo controlo es lo relevante») más un
solo ejemplo rinde más que la inducción entre dos casos sin ese sesgo. La
comparación entre casos cumple su papel (filtra accidentes), pero solo se nota
cuando el sesgo falta.

## Límites y siguientes pasos

- Un solo tipo de relación posible (el lazo de 3); mundos lineales; umbral fijo.
- Abstraer con lo frecuente en muchos éxitos, en vez de la intersección de los
  mejores, resistiría mejor un éxito tipo salto.
- El momento de abstraer lo fija el experimentador. Falta que ocurra solo, por
  ejemplo al consolidar cada nuevo éxito.
- Para medir mejor el filtrado por comparación hacen falta mundos con más
  accidentes del río (umbral menor o ríos más acoplados), con semillas
  reservadas.
