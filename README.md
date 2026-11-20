# TEST-IA

Un modelo de lenguaje en español de **48 M de parámetros** (BitNet, 41 MB, ~111 MB de RAM, corre en CPU con un motor C++ propio) que no intenta memorizar el mundo: **sabe cuándo buscar, lee lo que encuentra y admite cuándo no sabe**.
Sobre ese núcleo congelado se montan dos expertos LoRA de 2,62 MB que se conmutan por puntero (código y redacción) y una capa de Python con memoria externa, herramientas y enrutador.

```
 mensaje ──► capa 1 (sin IA: cuentas, mayúsculas, «Recuerda/Olvida…»)
         └─► enrutador de 3 estados ─► núcleo base | + experto_codigo | + experto_redaccion   (1 solo activo por turno)
                                         │  B: consulta ─► memoria del usuario ─► fichas locales ─► ddgs (internet)
                                         └  E: código   ─► sandbox de Python
```

## Estado del proyecto (cerrado hasta la Etapa 3)
| Etapa | Qué es | Resultado clave |
|---|---|---|
| 1 | Núcleo base: preentrenamiento + ajuste fino para buscar/leer/abstenerse + motor C++ | hechos 71,6 % · abstención 98,1 % · conversación 100 % (ddgs real) |
| 2 | Experto de código (LoRA, base local de 107 fichas, sandbox) | 82,2 % · +2,6 MB de RAM · dormido = núcleo idéntico |
| 3 | Memoria con enfriamiento, experto de redacción, enrutador de 3 estados, caché de 2 ranuras, capa determinista (corrector ortográfico, búsqueda difusa de fichas) | cambio de experto 0,4 µs · 116,0 MB de RAM · 0 colisiones · ortografía 76,6 % (el modelo: 14 %) |

Informes: [estudios/ETAPA3_CIERRE.md](estudios/ETAPA3_CIERRE.md) (consolidado y conclusiones) · [RESUMEN_ETAPA1](estudios/RESUMEN_ETAPA1.md) · [ETAPA2_PASO3](estudios/ETAPA2_PASO3_experto_final.md) ·
[ETAPA3_PASO1](estudios/ETAPA3_PASO1_memoria_externa.md) · [ETAPA3_PASO2](estudios/ETAPA3_PASO2_multi_experto.md).

## Uso rápido (Windows, Python 3.13, `pip install -r requirements.txt`, `ddgs`, `psutil`)
Chat multi-experto con memoria (motor C++, sin preguntas por argumento abre un chat interactivo):
```
python inferir.py --motor --experto modelos/experto_codigo.lora --redaccion modelos/experto_redaccion.lora
```
Una sola pregunta, o con PyTorch (un solo experto): `python inferir.py "¿Qué es el Teide?"` · `python inferir.py --experto modelos/experto_codigo.lora.pt ...`
Dentro del chat: «Corrige: tambien quiero un cafe» (corrector determinista, sin red neuronal), «Recuerda que mi proyecto se llama X», «Recuerda siempre que…» (permanente), «Olvida que…», «¿Cómo se llama mi proyecto?», «Ejecuta: sum(range(5))», «Corrige: …», «Hazlo más formal: …», «¿Qué es un hiato?».
Verificaciones: `python verificar_multiexperto.py` (6 métricas de la Etapa 3) · `python probar_memoria.py [--motor]` · `python probar_pulido.py` (memoria limpia, búsqueda difusa y corrector, en vivo) · `python enrutador.py` · `python sandbox.py` · `python corrector.py`.
Recompilar el motor: `compilar_motor.bat` (MSVC, AVX2 + OpenMP).

## Pesos y datos
`modelos/` contiene solo producción congelada, en solo lectura y con SHA-256 en sus JSON: `nucleo_sft_v3.{pt,bin,vocab.json}`, `experto_codigo.lora`, `experto_redaccion.lora`.
`modelos/experimentos/` recibe todo experimento nuevo; `modelos/archivo/` guarda variantes descartadas. Los pesos grandes (`.pt` de 192 MB, `nucleo_es_bitnet.pt`) y los datos pesados no están en el repositorio de GitHub (ver `.gitignore`):
se regeneran con los scripts de `estudios/` o se piden aparte.

## Mapa de archivos
| Grupo | Archivos |
|---|---|
| Núcleo y motor | `modelo.py`, `preentrenar.py`, `ajustar.py`, `exportar_cpp.py`, `motor.cpp`, `motor_cpp.py`, `compilar_motor.bat` |
| Inferencia | `inferir.py` (bucle, `Sesion`), `protocolo.py`, `herramientas.py` (capa 1, búsqueda), `enrutador.py` |
| Memoria | `memoria.py`, `probar_memoria.py` |
| Capa determinista | `corrector.py` + `construir_lexico.py` (ortografía determinista, 76,6 % exacta), `probar_pulido.py` |
| Experto de código | `experto_fichas.py`, `experto_datos.py`, `sandbox.py`, `lora.py`, `entrenar_lora.py`, `exportar_lora_cpp.py`, `evaluar_experto.py` |
| Experto de redacción | `redaccion_fichas.py`, `redaccion_datos.py`, `recolectar_redaccion.py`, `evaluar_redaccion.py` |
| Verificación | `verificar_multiexperto.py`, `verificar_lora_motor.py`, `benchmark_motor.py` |
| Informes | `estudios/`, `resultados/` |

---

# Etapa 0 — Prototipos: núcleo pequeño que sabe cuándo buscar


Prueba de la idea: **un modelo no necesita memorizar todo; necesita reconocer lo que no sabe, buscarlo, usarlo, y admitir cuando no lo encuentra.**

## Qué aprende el modelo

Un mundo inventado en español con 6 categorías (mueble, animal, comida, herramienta, lugar, ropa):

| Situación | Comportamiento esperado |
|---|---|
| Palabra conocida («silla») | Responde directo, sin buscar |
| Combinación que calza («mesa de mimbre») | Responde directo: los muebles pueden ser de mimbre |
| Palabra desconocida («pludos») | `B:` busca en el diccionario, lee la definición, responde |
| Combinación que **no calza** («banco de arena») | Busca: un banco-mueble no se hace de arena |
| Palabra que no está en el diccionario | Busca, recibe «sin resultados» y responde **«no sé»** en vez de inventar |

La evaluación usa solo palabras, combinaciones y **redacciones de definiciones que el modelo nunca vio** (plantillas y rasgos separados para prueba, sinónimos, y definiciones «mezcladas» con rasgos de otra categoría para obligarlo a leer).

## Archivos

| Archivo | Rol |
|---|---|
| `datos.py` | Genera el mundo, los ejemplos y el diccionario (`datos/diccionario.sqlite`). **Regenerarlo borra lo agregado con `ampliar_diccionario.py`.** |
| `herramientas.py` | Capa 1 sin IA (cuentas exactas) y el diccionario externo. |
| `modelo.py` | Núcleo: Transformer diminuto por caracteres. `--bitnet` (pesos -1/0/+1) y `--vueltas N` (reusa las mismas capas N veces). |
| `entrenar.py` | Entrena un modelo. |
| `evaluar.py` | Mide uno o más modelos y muestra la traza de «banco de arena». |
| `comparar.py` | Entrena varias variantes × semillas y resume promedios en `resultados/`. |
| `exportar_bitnet.py` | Empaqueta un modelo BitNet a 2 bits por peso (~0,3 MB) y verifica que responde igual. |
| `ampliar_diccionario.py` | Agrega palabras al diccionario **sin reentrenar**. |
| `conversar.py` | Prueba interactiva. |
| `preparar_pc.ps1` | Instala y lanza todo en Windows + NVIDIA. |

Variantes de `comparar.py`:

| Variante | Qué es |
|---|---|
| `normal` | 4 capas, pesos en decimales |
| `bitnet` | 4 capas, pesos ternarios (~6× más liviano) |
| `chico` | 2 capas (mitad de parámetros) |
| `bucle` | 2 capas usadas 2 veces: mitad de parámetros, mismo cálculo que `normal` |
| `bitnet_bucle` | Las dos ideas juntas |

## En el Mac

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datos.py
.venv/bin/python comparar.py --variantes normal bitnet chico bucle --sufijo v3
.venv/bin/python exportar_bitnet.py modelos/cmp_bitnet_s0_v3.pt --verificar
.venv/bin/python conversar.py "banco de arena" "mesa de mimbre" "1244123/2344"
```

Para entrenamientos largos, lanzarlo desde la Terminal para que no dependa de otra app y el Mac no se duerma:

```bash
nohup caffeinate -i .venv/bin/python -u comparar.py ... > resultados/log.txt 2>&1 &
```

## En el PC (Windows + RTX 5060 Ti)

1. Copia la carpeta **sin** `.venv` ni `__pycache__` (son del Mac y no sirven en Windows). `modelos/` es opcional.
2. Driver de NVIDIA actualizado (570 o superior).
3. En PowerShell, dentro de la carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1              # instala PyTorch CUDA 12.8 y verifica la GPU
powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1 -Entrenar    # comparación larga (10.000 pasos, 3 semillas)
```

Opciones: `-Pasos 20000`, `-Semillas "0 1 2 3 4"`, `-Variantes "bitnet bitnet_bucle"`, `-Sufijo nombre`. El script evita que Windows se suspenda mientras entrena (sin cambiar la configuración de energía) y guarda el registro en `resultados\`.

## Límites honestos

- El mundo es inventado y pequeño: demuestra el **mecanismo**, no que el modelo hable español.
- La regla de «qué calza» la definimos nosotros; en el mundo real tendría que aprenderla del idioma.
- BitNet aquí solo cuantiza los pesos (no las activaciones) y los cálculos siguen siendo multiplicaciones normales: se comprobó que **aprende igual**, no que **consuma menos al ejecutarse**. Para eso haría falta un motor de sumas/restas como `bitnet.cpp`.
- Con 2.000 pasos los modelos están subentrenados y varían bastante entre semillas.
