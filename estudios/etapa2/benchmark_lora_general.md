# Benchmark: motor C++ vs PyTorch (25 prompts reales, 3 de calentamiento)

| Backend | RAM pico (proceso) | RAM del modelo* | VRAM pico | Carga | Carga del .lora | Prefill (prompt ~119 tok) | ms/token | tokens/s | Respuesta idéntica a cpp |
|---|---|---|---|---|---|---|---|---|---|
| cpp | 111 MB | 82 MB | 0 MB | 0.09 s | — | 50.5 ms | 1.47 ms | 678 | 100% |
| cpp_dormido | 114 MB | 85 MB | 0 MB | 0.09 s | 1.5 ms (2.62 MB) | 49.1 ms | 1.64 ms | 611 | 100% |
| cpp_lora | 114 MB | 85 MB | 0 MB | 0.09 s | 1.5 ms (2.62 MB) | 52.2 ms | 1.64 ms | 611 | 84% |

\* RAM del modelo = pico del proceso menos la RAM antes de cargar el modelo (incluye activaciones y caché de claves/valores). La RAM pico del proceso en PyTorch incluye las bibliotecas de torch y CUDA.
PyTorch no usa caché de claves/valores (como en inferir.py): recalcula toda la secuencia en cada token. El motor C++ sí la usa.
