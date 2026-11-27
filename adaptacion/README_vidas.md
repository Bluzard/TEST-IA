# Vidas sucesivas: memoria persistente, deducción y abducción

`vidas_sucesivas.py` · resultados en `resultados_vidas.txt` y `resultados_vidas/` (un JSON por condición) · pruebas en `test_vidas.py`.

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
4. **El límite ya no es el conocimiento, sino el cuerpo.** Tras deducir, quedan
   unos 1.100 pasos de acoplamiento de un cuerpo que nació de nuevo, y ahí la
   memoria no ayuda. Ahorrar unos 300 pasos de conocimiento casi no se nota.

## Límites y siguientes pasos

- Falta aprender de lo observado en otro (el ejemplo del fuego): peligros como
  firmas, vistos en otro sujeto y nunca probados por el propio.
- La abducción de mundo debería pesar hipótesis rivales (cuántos roles explica
  cada mundo pasado) en vez de adoptar la primera consistente.
- Si el cuerpo es el cuello de botella, hay que probar la otra opción que
  dejamos abierta: que el cuerpo también persista (el mismo organismo).
- Una sola familia de mundos, un solo esquema útil y roles de forma dada.
