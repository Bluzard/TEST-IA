# Recursos de los modelos (40 preguntas, una a la vez)

## Memoria

| Modelo | Parámetros | Mínimo necesario | Ocupa hoy al cargarlo |
|---|---|---|---|
| normal | 833,920 | 1.67 MB | 3.34 MB |
| bitnet (archivo de entrenamiento) | 833,920 | 0.29 MB | 3.34 MB |
| bitnet empaquetado | 833,920 | 0.29 MB | 3.34 MB |
| bucle | 439,808 | 0.88 MB | 1.76 MB |

## Tiempo

| Dispositivo | Modelo | Una pasada | Respuesta completa (mediana) | Respuesta lenta (p90) |
|---|---|---|---|---|
| cpu | normal | 1.31 ms | 33 ms | 43 ms |
| cpu | bitnet (archivo de entrenamiento) | 2.73 ms | 60 ms | 86 ms |
| cpu | bitnet empaquetado | 1.25 ms | 31 ms | 46 ms |
| cpu | bucle | 1.37 ms | 30 ms | 43 ms |
| mps | normal | 1.03 ms | 31 ms | 43 ms |
| mps | bitnet (archivo de entrenamiento) | 1.21 ms | 40 ms | 57 ms |
| mps | bitnet empaquetado | 0.71 ms | 30 ms | 45 ms |
| mps | bucle | 0.72 ms | 29 ms | 43 ms |
