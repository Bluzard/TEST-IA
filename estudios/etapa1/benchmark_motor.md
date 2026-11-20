# Benchmark: motor C++ vs PyTorch (25 prompts reales, 3 de calentamiento)

| Backend | RAM pico (proceso) | RAM del modelo* | VRAM pico | Carga | Prefill (prompt ~119 tok) | ms/token | tokens/s | Respuesta idéntica a torch_cpu |
|---|---|---|---|---|---|---|---|---|
| torch_gpu | 1535 MB | 1506 MB | 233 MB | 1.76 s | 9.7 ms | 11.47 ms | 87 | 100% |
| torch_cpu | 1116 MB | 1088 MB | 0 MB | 1.64 s | 33.3 ms | 35.68 ms | 28 | 100% |
| cpp | 111 MB | 82 MB | 0 MB | 0.10 s | 51.4 ms | 1.46 ms | 685 | 100% |
| cpp_1hilo | 108 MB | 79 MB | 0 MB | 0.09 s | 154.4 ms | 6.39 ms | 156 | 100% |

\* RAM del modelo = pico del proceso menos la RAM antes de cargar el modelo (incluye activaciones y caché de claves/valores). La RAM pico del proceso en PyTorch incluye las bibliotecas de torch y CUDA.
PyTorch no usa caché de claves/valores (como en inferir.py): recalcula toda la secuencia en cada token. El motor C++ sí la usa.
