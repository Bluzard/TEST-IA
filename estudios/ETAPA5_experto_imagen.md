# Experto de prompts de imagen (EXPERIMENTAL) — estado, medidas y uso

**Estado:** experimental. No está en `modelos/` ni en producción; se activa con `--imagen`. Fecha: 2026-11-23.

## Qué hace
Recibe una petición de prompt para un generador de imágenes (texto libre mal redactado, JSON, YAML, viñetas, etiquetas, español o inglés), detecta el modelo destino y devuelve un prompt **en inglés con el formato de ese modelo**:
Flux, Z-Image Turbo, Z-Image Base, Qwen-Image (lenguaje natural) y SDXL, SD 1.5, Pony, Illustrious (etiquetas con prefijo de calidad y `Negative prompt:`). Sin censura añadida.

## Arquitectura (qué hace cada capa)
| capa | archivo | qué hace |
|---|---|---|
| fichas por modelo | `imagen_fichas.py` | cómo se escribe a cada modelo (estructura, negativos, parámetros «orientativos»: las fuentes públicas se contradicen) |
| enrutador de 3 dominios | `enrutador.py` (`EnrutadorV3`) | decide código / redacción / imagen; 93,6 % de los pedidos de imagen, 0 falsos positivos en 656 negativos, sin cambiar código (91,5 %) ni redacción (96,5 %) |
| idea del usuario | `imagen_idea.py` | extrae lo que se quiere ver, traduce al inglés (opus-mt-es-en, Apache-2.0), respeta lo que va entre comillas, enriquece con estilo/luz/cámara curados y coherentes con el tipo de imagen |
| entradas largas | `imagen_compactar.py` | JSON/especificaciones que no caben en el núcleo (1.024 tokens): se COMPONEN de forma determinista con sus campos (cámara → sujeto/ropa → acción → entorno/luz), sin instrucciones para otros modelos, sin participantes no visibles |
| formato final | `imagen_formato.py` | prefijos de calidad y línea de prompt negativo por modelo; limpieza de duplicados y fugas de español |
| adaptador | `modelos/experimentos/experto_imagen_d_v2.lora` | LoRA r=16 sobre el núcleo v2c; hoy solo enruta/formatea el caso «sin modelo» y la continuación experimental |

## Datos (todos con licencia abierta; `imagen_datos.py`, `imagen_traducir.py`)
`igor-im/flux_prompt_expander` (MIT), `k-mktr/improved-flux-prompts` (MIT), `Aconexx/CivitAI-Flux-Prompts` (Apache-2.0), `ChrisGoringe/flux_prompts` (Apache-2.0), `poloclub/diffusiondb` (CC0)
+ escenas sintéticas bilingües. Las entradas en español de los datos reales se fabricaron traduciendo con `Helsinki-NLP/opus-mt-en-es` (Apache-2.0; solo para generar datos).
Higiene mínima: normalizar artefactos, descartar enlaces/duplicados/no-inglés y todo contenido sexual con menores. No hay otro filtro. 73.364 filas de entrenamiento, 3.824 reservadas.

## Qué se midió y qué se aprendió
- **El núcleo v2c no es fiable generando prompts largos a partir de una idea.** Con entradas reales largas casi ignora lo que se pide (ganancia de pérdida al usar su entrada: 0,11-0,26 nats; en entradas sintéticas cortas 0,75-1,43).
  Ejemplos reales: «gato dormido en una ventana lluviosa» -> gato en un campo de lavanda; cartel «LA NONNA» -> retrato de un hombre.
- El evaluador (`evaluar_imagen.py`: enrutamiento, formato, inglés, bucles, ruido) daba 89 % de éxito, pero **no mide fidelidad a la idea**; por eso no es la métrica que decide.
- **Opción B (la que se usa):** la idea no pasa por el modelo. Medido sobre 400 entradas reservadas: 100 % de las palabras de la idea llegan al prompt, formato correcto 100 %, restos de español 1,4 %, 157 ms por pedido.
- Para especificaciones largas (JSON de escena de 1.659 tokens) el sistema antes fallaba con «prompt demasiado largo»; ahora las compone sin pasar por el núcleo.

## Uso
```
.venv\Scripts\python.exe inferir.py --sin-memoria --imagen          # chat; ejemplos: «prompt para flux: un gato dormido en una ventana lluviosa», «otra versión más oscura», «ahora para sdxl»
```
Opciones: `--sin-traductor` (no carga el traductor: usa solo la generación del núcleo, peor fidelidad), `--continuacion-nucleo` (el núcleo continúa la idea en vez del enriquecimiento curado; incoherente), `--imagen_lora RUTA`.
Dependencia opcional: `pip install transformers sentencepiece sacremoses`. Sin ella la idea no se traduce y se usa el camino anterior.

## Límites conocidos
- **RAM:** el traductor suma ≈ 520 MB al proceso (578 -> 1.096 MB) la primera vez que se pide un prompt en español; el motor C++ del núcleo sigue en 127-143 MB. Se carga solo cuando hace falta.
- **No es creativo:** el enriquecimiento es vocabulario curado (luz, composición, calidad), no imaginación. Quien quiera que el núcleo escriba detalle de verdad necesita mejorar el núcleo (micro-SFT con inglés creativo; obliga a revalidar los LoRA de código y redacción).
- Errores de traducción automática en vocabulario visual raro (se corrigen unos pocos: «elfa» -> elven); `Pony`/`Illustrious` solo tienen datos sintéticos de etiquetas; Z-Image en chino no está cubierto; las cifras de guidance/pasos de las fichas son orientativas.
- «otra versión» cambia luz/composición/calidad pero no reescribe la idea; los seguimientos reconocidos son los de `enrutador._SEGUIMIENTO_IMG`.
- La composición determinista de especificaciones largas no aplica las reglas internas del JSON (las descarta) y deja alguna redundancia.
