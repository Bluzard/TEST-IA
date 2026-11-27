# Vidas sucesivas: memoria persistente, deducción y abducción

`vidas_sucesivas.py` · resultados en `resultados_vidas.txt` · pruebas en `test_vidas.py` · los registros por vida (`resultados_vidas/`, un JSON por condición, ≈5 MB) ya no se actualizan en el repositorio (los 4 que quedan son de la corrida del PR #4, sin los campos nuevos): `comparar --rep 100` los regenera en unos 15 minutos.

```powershell
# Un sujeto real: cada ejecución es una vida; la memoria queda en el archivo.
.\.venv\Scripts\python.exe adaptacion\vidas_sucesivas.py vivir --db adaptacion\memoria_vidas.sqlite --vida 1
.\.venv\Scripts\python.exe adaptacion\vidas_sucesivas.py vivir --db adaptacion\memoria_vidas.sqlite --vida 2
# Comparación: 100 sujetos × 10 vidas × 4 condiciones, en bases temporales.
.\.venv\Scripts\python.exe adaptacion\vidas_sucesivas.py comparar --rep 100
```

## Qué cambia respecto de lo anterior

Antes, cada corrida era nacer desde cero. Aquí, un sujeto vive una vida por
ejecución: abre su archivo SQLite, vive, deja su legado y lo cierra. **El cuerpo
(W) nace de nuevo cada vida; solo persiste la memoria.** Cada vida ocurre en un
mundo de la familia re-mapeada (río propio y códigos de pieza con otro
significado). La secuencia es 0, 1, 2, 0, 3, 1, 4, 2, 5, 0: las vidas 4, 6, 8 y
10 vuelven a un mundo ya vivido, sin aviso.

La memoria guarda lo aprendido, no configuraciones:

- **esquemas:** los ciclos con piezas del éxito más sostenido de cada vida, con
  su soporte (en cuántas vidas aparecieron);
- **roles:** lo que el sujeto vio hacer a cada código de pieza en cada vida.

## El ciclo de las tres inferencias

| Inferencia | Qué hace aquí |
|---|---|
| Abducción de roles | Con un arreglo puesto, explica la influencia observada de cada pieza con la hipótesis más simple: «el código c en esta ranura siente el canal k» o «empuja el canal j con signo s, alimentado por el ancla f». Basta una observación. |
| Abducción de mundo | Si los roles vistos coinciden con los de una vida pasada, postula «estoy otra vez en ese mundo» y adopta sus roles no vistos. Una contradicción, o un plan fallido con esos roles, la descarta. |
| Deducción | Con los roles conocidos y los esquemas, compone en memoria el arreglo que contendría un esquema y lo arma **sin haberlo probado**. Lo pone ante una caída (necesidad) y abre la ventana de acoplamiento para el cuerpo. |
| Inducción | La tasa del 90 % dentro de la vida y el soporte de los esquemas entre vidas. |

No hay predicción de valores ni de trayectorias: la memoria elige qué armar.

**Sesgos que puse yo:** el espacio de hipótesis de roles (qué siente y qué empuja
cada pieza), la forma de las firmas (ciclos con signo, sesgo de agencia) y el
umbral de influencia. Lo que el sujeto aprende es qué rol tiene cada código y
qué esquemas sirven; la forma en que puede expresarlo está dada.

## Resultados (100 sujetos pareados, 10 vidas de 40.000 pasos)

Pasos hasta el primer puente estable, mediana por vida:

| Vida | Mundo | Tipo | Desde cero | Esquemas | Deducción | Completo |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 0 | nuevo | 10.804 | 10.804 | 10.804 | 10.804 |
| 2 | 1 | nuevo | 9.102 | 4.077 | 2.702 | 2.771 |
| 3 | 2 | nuevo | 18.625 | 7.184 | 5.782 | 5.782 |
| 4 | 0 | revisita | 7.795 | 4.656 | 2.248 | 2.043 |
| 5 | 3 | nuevo | 7.483 | 4.168 | 2.668 | 2.422 |
| 6 | 1 | revisita | 9.934 | 2.573 | 2.044 | 1.842 |
| 7 | 4 | nuevo | 5.583 | 2.816 | 1.711 | 2.029 |
| 8 | 2 | revisita | 13.210 | 4.330 | 2.051 | 1.810 |
| 9 | 5 | nuevo | 11.074 | 3.585 | 2.486 | 2.178 |
| 10 | 0 | revisita | 7.886 | 3.028 | 2.280 | 1.953 |

Comparaciones pareadas por sujeto (media de sus vidas 2–10, prueba de signo):

| Comparación | Mundos nuevos | Revisitas |
|---|---|---|
| esquemas contra desde cero | más rápida en 80, más lenta en 19 (p < 0,001) | 73 contra 26 (p < 0,001) |
| deducción contra esquemas | 77 contra 14 (p < 0,001) | 75 contra 17 (p < 0,001) |
| completo contra deducción | 18 contra 28 (p = 0,18) | 51 contra 41 (p = 0,35) |

Las medias por sujeto (unos 10.000 pasos con deducción) son mucho mayores que
las medianas por vida, porque las vidas sin puente cuentan como 40.000.

¿Dónde se va el tiempo con deducción? Hasta la primera deducción pasan 972 pasos
(652 con abducción de mundo); de ahí al puente estable, unos 1.100 pasos más.

## Lectura

1. **Ahora sí aprende entre vidas.** Desde cero no hay curva: cada vida tarda lo
   mismo. Con memoria persistente y deducción, desde la segunda vida el sujeto
   arma el puente entre 3 y 6 veces más rápido (mediana por vida), en mundos
   cuyos códigos nunca vio.
2. **La deducción aporta sobre recordar esquemas.** Componer el arreglo desde
   roles abducidos antes de probarlo le gana a esperar a toparse con él
   (p < 0,001). Con deducción, el 70 % de los puentes acoplados en ventana
   vienen de arreglos deducidos.
3. **La abducción de mundo acierta, pero no acelera.** En las revisitas, 323 de
   359 adopciones fueron correctas (90 %), y adelanta la primera deducción de
   972 a 652 pasos. Pero en mundos nuevos adopta erróneamente 83 veces, y el
   total no mejora frente a deducción sola.
4. **Tras deducir quedan unos 1.100 pasos, y no se deben a roles mal
   abducidos.** Una versión anterior de este README lo atribuía al acoplamiento
   de un cuerpo recién nacido. El diagnóstico de abajo muestra que el
   conocimiento acierta y que lo que falla es la atribución del fallo.

## Diagnóstico de los planes deducidos

Con el oráculo (solo para medir) se registra si cada arreglo deducido es de
verdad un puente. Vidas 2–10 con deducción:

| | Se acopla | Se agota |
|---|---:|---:|
| El arreglo deducido es un puente | 1.534 | **1.334** |
| No es un puente | 23 | 125 |

- **La deducción acierta:** el 95 % de los arreglos deducidos son puentes. Los
  roles abducidos son buenos.
- **Pero casi la mitad de los puentes deducidos correctos se agota** (1.334 de
  2.868): el cuerpo recién nacido no se acopla dentro de `R_max` = 20, y el
  fallo se atribuye al plano. Un arreglo agotado queda bloqueado por el resto de
  la vida. En 23 vidas que terminaron sin puente, la deducción había dado con
  el puente correcto y se descartó.

Es el mismo problema que resolvió `atribucion_fallo.py`, pero ahora en el
conocimiento propio: **la paciencia no depende de cuán seguro está el sujeto de
su plano.** Un plano deducido desde esquemas con soporte y roles vistos merece
más paciencia que un arreglo al azar.

## Cuerpo persistente

| Mediana de la media por sujeto, vidas 2–10 | Cuerpo nuevo | Heredado de la vida anterior | Recuperado del mundo abducido |
|---|---:|---:|---:|
| Sin conocimiento | 17.797 | 19.614 | — |
| Deducción | 9.982 | 14.190 | — |
| Completo | 10.320 | 13.103 | 10.499 |

- **Heredar el cuerpo de la vida anterior empeora** en mundos nuevos y en
  revisitas: las 6 comparaciones pareadas favorecen al cuerpo nuevo (p entre
  0,021 y < 0,001). La vida anterior siempre es de otro mundo: un cuerpo adaptado
  a otro mundo resulta peor que uno al azar (rigidez).
- **Recuperar el cuerpo del mundo abducido** (`completo_cuerpo_mundo`): nace con
  cuerpo nuevo y, si la abducción de mundo concluye «estoy en el mundo de la
  vida L», recupera el cuerpo de L. En revisitas recuperó 359 cuerpos, 321 del
  mundo correcto; en mundos nuevos, 88 equivocados. Las medianas por vida bajan
  (revisitas: 1.605–1.976 contra 1.810–2.043 de `completo`), pero la prueba
  pareada por sujeto no es significativa (revisitas 55 contra 44, p = 0,32;
  nuevos 35 contra 27, p = 0,37). El tiempo tras deducir apenas baja (1.038
  contra 1.102 pasos).

El cuerpo no es el cuello de botella principal. Lo es la paciencia con un plano
correcto.

## Paciencia según la confianza en el plano (resultado negativo)

Condiciones `*_paciencia`: la ventana de un plano deducido solo con roles vistos
en esta vida tiene presupuesto `R_max × (1 + soporte del esquema)`; con roles
adoptados, `R_max`.

| Vidas 2–10 | Deducción | Deducción + paciencia | Completo | Completo + paciencia |
|---|---:|---:|---:|---:|
| Puentes deducidos correctos que se agotan | 1.334 | 700 | 1.394 | 879 |
| Puentes deducidos que se acoplan | 1.534 | 1.746 | 1.537 | 1.718 |
| Vidas sin puente (de 900) | 172 | 165 | 182 | 168 |
| Pasos desde la deducción hasta el puente | 1.106 | 1.274 | 1.102 | 1.220 |
| Mediana de la media por sujeto | 9.982 | 10.081 | 10.320 | 10.017 |

La paciencia hace lo que promete, porque descarta la mitad de puentes correctos,
pero **no acelera ni rescata vidas**: las 4 comparaciones pareadas no son
significativas (p entre 0,16 y 1,0). Descartar un puente correcto casi no
costaba, porque la deducción proponía enseguida otro arreglo equivalente (hay
varios códigos que forman puente). El tiempo que se ahorra en planes descartados
se gasta esperando a que el cuerpo se acople al plan retenido.

**Lo que esto deja en claro:** el diagnóstico anterior mostraba un mecanismo
real (planos correctos descartados), pero no era el cuello de botella. Los
~1.100 pasos tras deducir y las ~170 vidas sin puente (19 %) siguen sin
explicarse.

## Límites y siguientes pasos

- **Explicar las vidas sin puente:** solo 23 de 172 se explican por un puente
  deducido y descartado. Hay que ver si en las demás faltan roles, esquemas o
  acoplamiento.
- **El acoplamiento del cuerpo es búsqueda a ciegas:** tras fijar las piezas, W
  se reorganiza al azar como en el homeostato original. Ni la memoria ni la
  deducción guían esa parte.
- Falta aprender de lo observado en otro (el ejemplo del fuego): peligros como
  firmas, vistos en otro sujeto y nunca probados por el propio.
- La abducción de mundo debería pesar hipótesis rivales (cuántos roles explica
  cada mundo pasado) en vez de adoptar la primera consistente.
- Una sola familia de mundos, un solo esquema útil y roles de forma dada.
