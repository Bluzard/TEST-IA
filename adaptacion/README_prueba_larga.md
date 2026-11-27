# Atribución del fallo y prueba larga componible

Dos experimentos sobre `entorno_componible` + `biblioteca_planos`. Continúan
el límite que señalaba `README_planos.md`: un plano de piezas correcto puede
ser castigado porque el cuerpo todavía no se acopla a él.

```powershell
.\.venv\Scripts\python.exe adaptacion\atribucion_fallo.py --rep 40 --vida 15000 --rmax 20
.\.venv\Scripts\python.exe adaptacion\prueba_larga_componible.py --calibrar --rep 20 --semilla 1000
.\.venv\Scripts\python.exe adaptacion\prueba_larga_componible.py --rep 100 --vida 300000
.\.venv\Scripts\python.exe adaptacion\prueba_larga_componible.py --reinformar   # informe desde el JSON
.\.venv\Scripts\python.exe -m unittest discover -s adaptacion -p "test_*.py"
```

## 1. Atribución del fallo (`atribucion_fallo.py`)

Al cargar un plano que deja `W` sin especificar, sus posiciones quedan
bloqueadas y se abre una **ventana de acoplamiento**. Mientras dura, las caídas
reorganizan el cuerpo pero no tocan la confianza en SQLite. Si se agotan `R_max`
reconfiguraciones sin un intento completo (1.000 pasos sin caer), el fallo se
atribuye al plano (`confianza *= 0,5`). Los modos que se comparan:

| Modo | Qué hace |
|---|---|
| A | castigo inmediato (comportamiento anterior; se verificó que la trayectoria es idéntica) |
| B | paciencia fija: ventana de `R_max` caídas |
| C | progreso: el presupuesto se renueva si mejora la mejor racha con ese plano |

40 semillas pareadas, 15.000 pasos, `R_max` = 20 (`resultados_atribucion.txt`):

| Plano | Modo | Puente estable | Descarte prematuro |
|---|---|---:|---:|
| correcto | A / B / C | 24 / 40 / 39 de 40 | 39 / 15 / 6 de 40 |
| incorrecto | A / B / C | 23 / 22 / 19 | sin diferencias significativas |
| parcial | A / B / C | 20 / 25 / 27 | 39 / 32 / 29 |

Lo que más pesa es la ventana (A contra B y C, p < 0,001). Medir el progreso
(C frente a B) no cambia el puente estable con ningún `R_max` probado (3, 5, 20
y 50); solo reduce el descarte prematuro, y más mientras menor sea `R_max`. Un
plano incorrecto agota su ventana en unos 30 pasos, así que la paciencia sale
barata.

## 2. Prueba larga (`prueba_larga_componible.py`)

100 vidas pareadas de 300.000 pasos. El terreno cambia cada 60.000 pasos sin
aviso, con el recorrido 0→1→0→2→1. Saturar cuenta como caída en todas partes.
Cuando el sujeto cae tras 400 o más pasos estables, observa 256 pasos, calcula
la huella y la asigna al contexto más cercano dentro de `RADIO`, o crea uno
nuevo. La confianza y la `mejor_racha` se indexan por (plano, contexto).

| Condición | % tiempo con puente genuino | Saturadas al final | Cambios sin caer | Descarte prematuro en revisita |
|---|---:|---:|---:|---:|
| 1 sin piezas ni SQLite | 0 % | 40/100 | 39/400 | 7/10 |
| 2 modo A, una huella | 65,7 % | 9/100 | 117/400 | 42 % |
| 2b A + contexto | 71,7 % | 13/100 | 167/400 | 22 % |
| 2b sin moratoria | 70,9 % | 12/100 | 150/400 | 47 % |
| 3 C + contexto | 96,3 % | 3/100 | 259/400 | 6 % |
| 3 sin moratoria | 96,1 % | 0/100 | 256/400 | 38 % |

Recuperación del puente tras un cambio (mediana): A tarda 1.056 pasos en un
terreno nuevo y 782 en una revisita; C tarda 400 en ambos, el mínimo medible.

### Cómo leerlo

- **Condicional al plano.** Las condiciones componibles reciben al nacer el
  plano de piezas correcto. Los porcentajes con puente suponen que ese
  conocimiento existe en la biblioteca; no muestran que el sujeto lo descubra.
- **Los cambios de terreno casi no exigen memoria.** El puente es estructural
  y aguanta en los tres terrenos: el 65 % de los cambios en C no produce
  ninguna caída. Por eso nuevo y revisita se comportan igual. Esta prueba
  valida la sostenibilidad, no la memoria por contexto.
- **La huella mide el estado acoplado, no el río.** Se calcula sobre el río
  visto a través de un sujeto que acaba de caer y explora. Al calibrar con
  semillas 1000–1019 (`resultados_calibracion_radio.txt`), las distancias dentro
  de un mismo terreno y entre terrenos se solapan mucho. Con radio 0,15, C
  reconoce 104 de 200 revisitas. El resultado de C casi no depende del radio:
  97,6 % con 0,05, 96,3 % con 0,15 y 96,7 % con 0,25.
- **Moratoria.** Mientras el contexto es incierto no se anota evidencia. En la
  práctica es una ventana de acoplamiento implícita para todo plano. La
  ablación muestra que explica menos de 1 de los 6 puntos que el contexto le
  suma a A (71,7 contra 70,9 %, p = 0,033). El resto viene de re-contextualizar
  (repertorio reconstruido con evidencia fresca), que es una hipótesis todavía
  sin aislar. Lo que sí hace la moratoria es proteger a los planos propios
  consolidados al volver a un terreno.
- **Saturación.** Sin piezas, 40 de 100 vidas terminan saturadas, en línea con
  el ~33 % de `saturacion.py`, que mide otro entorno. Con piezas y plano son
  3 de 100. El efecto mezcla tener piezas con tener el plano.

### Pendientes

- Una huella calculada en períodos de estabilidad, o sobre la relación entre la
  acción y su efecto, en vez de tomarse después de caer.
- Terrenos donde el puente de un terreno no sirva en otro, para que la memoria
  por contexto sea realmente necesaria.
- Aislar qué parte de re-contextualizar ayuda a A.
