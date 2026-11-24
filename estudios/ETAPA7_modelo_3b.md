# Etapa 7: cambio del núcleo propio por qwen2.5:3b

Fecha: 2026-11-24. Decisión: usar solo el modelo de 3B (Ollama), sin modelos mayores. El núcleo v2c (158 M) y todos sus pesos, datos de entrenamiento y scripts se eliminaron; el código sigue en la etiqueta git `nucleo-propio-v2c`.

## Qué cambió
- `inferir.py` nuevo: capa 1 -> prompts de imagen deterministas -> hora/clima -> LLM con herramientas (`buscar_web`, `recordar`, `ejecutar_python`). Cliente en `llm.py`.
- Raíz: de 88 a 24 archivos .py. `modelos/` de 11 GB a 0; `datos/` de 35 GB a 62 MB.
- `servicio_escenas.py` conserva `/escena`; `/extraer` se quitó (b_chat usa `SCENE_EXTRACTOR=llm`).

## Medida (`evaluar_3b.py`, casos reservados de ddgs real, resultados de búsqueda dados, temperatura 0)
| tipo | 3B | núcleo v2c (respuesta exacta) |
|---|---|---|
| buscar_ok (222) | 91,9 % (menciona el dato) | 83,3-84,7 % |
| irrelevante (52) | 98,1 % se abstiene (88,5 % sin filtro) | 100 % |
| vacío (13) | 100 % | 100 % |

Las cifras no son directamente comparables: la del 3B es más permisiva (basta con mencionar el dato esperado). Sin filtro, el 3B respondía con lo primero que veía aunque no tratara de la consulta («brilibri» -> «Bribri»). `relevancia.py` exige que una raíz de 5 letras de algún término de la consulta aparezca en los resultados; si no, se ordena abstenerse sin gastar una llamada al modelo (no pierde ningún caso con respuesta). Un simple «Sin resultados» no bastaba: el 3B lo ignoraba (irrelevante 71,2 %).

## Limitaciones vistas
- Con búsqueda abierta, el 3B llegó a afirmar un dato falso (ganador del mundial 2022: «Francia»); con instrucciones de citar tal cual se abstiene.
- Ignora la fecha del contexto («¿cuántos días faltan para Navidad?» pide la fecha).
- Pendiente: evaluar charla, código y redacción de extremo a extremo; el LoRA con PEFT sobre el 3B no se hizo.
