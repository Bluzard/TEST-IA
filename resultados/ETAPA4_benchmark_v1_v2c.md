# Benchmark v1 vs v2c (motor C++, CPU, 25 prompts reales, 3 de calentamiento)

## Rendimiento y RAM

| versión | configuración | hilos | RAM pico | carga | prefill | tokens de prompt | ms/token | tokens/s | palabras/s | palabras/token |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 | núcleo solo (general) | all | 110 MB | 0.08 s | 50.1 ms | 119 | 1.52 | 656 | 427 | 0.65 |
| v2c | núcleo solo (general) | all | 127 MB | 0.02 s | 201.9 ms | 114 | 5.58 | 179 | 118 | 0.66 |
| v1 | núcleo solo (general) | 1 | 105 MB | 0.01 s | 159.7 ms | 119 | 6.50 | 154 | 100 | 0.65 |
| v2c | núcleo solo (general) | 1 | 123 MB | 0.02 s | 637.1 ms | 114 | 25.05 | 40 | 26 | 0.66 |
| v1 | núcleo + LoRA código (experto) | all | 112 MB | 0.01 s | 44.6 ms | 71 | 1.93 | 518 | 354 | 0.68 |
| v2c | núcleo + LoRA código (experto) | all | 136 MB | 0.02 s | 150.7 ms | 63 | 5.94 | 168 | 120 | 0.72 |
| v1 | núcleo + 2 LoRA en caché (código activo) (experto) | all | 115 MB | 0.01 s | 40.1 ms | 71 | 1.58 | 633 | 433 | 0.68 |
| v2c | núcleo + 2 LoRA en caché (código activo) (experto) | all | 143 MB | 0.02 s | 153.2 ms | 63 | 5.93 | 169 | 121 | 0.72 |

## Disco

| artefacto | v1 | v2c |
|---|---|---|
| núcleo .bin | 41.3 MB | 54.9 MB |
| LoRA código | 2.6 MB | 7.9 MB |
| LoRA redacción | 2.6 MB | 7.9 MB |
