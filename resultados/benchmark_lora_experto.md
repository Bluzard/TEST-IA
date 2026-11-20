# Benchmark: motor C++ vs PyTorch (40 prompts reales, 3 de calentamiento)

| Backend | RAM pico (proceso) | RAM del modelo* | VRAM pico | Carga | Carga del .lora | Prefill (prompt ~68 tok) | ms/token | tokens/s | Respuesta idéntica a cpp |
|---|---|---|---|---|---|---|---|---|---|
| cpp | 110 MB | 79 MB | 0 MB | 0.10 s | — | 39.7 ms | 1.77 ms | 565 | 100% |
| cpp_dormido | 112 MB | 82 MB | 0 MB | 0.10 s | 1.4 ms (2.62 MB) | 36.4 ms | 1.36 ms | 734 | 100% |
| cpp_lora | 112 MB | 82 MB | 0 MB | 0.09 s | 1.4 ms (2.62 MB) | 37.8 ms | 1.52 ms | 659 | 5% |
| cpp_1hilo | 106 MB | 77 MB | 0 MB | 0.09 s | — | 104.7 ms | 5.81 ms | 172 | 100% |
| cpp_lora_1hilo | 109 MB | 79 MB | 0 MB | 0.10 s | 1.5 ms (2.62 MB) | 110.0 ms | 5.87 ms | 170 | 5% |

\* RAM del modelo = pico del proceso menos la RAM antes de cargar el modelo (incluye activaciones y caché de claves/valores). La RAM pico del proceso en PyTorch incluye las bibliotecas de torch y CUDA.
PyTorch no usa caché de claves/valores (como en inferir.py): recalcula toda la secuencia en cada token. El motor C++ sí la usa.
