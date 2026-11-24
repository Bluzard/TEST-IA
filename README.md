# TEST-IA

Asistente en español sobre un **modelo base de 3B** (`qwen2.5:3b` en Ollama) con una capa propia de herramientas, memoria y expertos deterministas.
Antes tenía un núcleo propio de 158 M entrenado desde cero (Etapas 1-4); se sustituyó en la Etapa 7 (ver `estudios/ETAPA7_modelo_3b.md`). El código antiguo está en la etiqueta git `nucleo-propio-v2c`.

```
 mensaje ──► capa 1 (sin IA: cuentas, mayúsculas, «Recuerda/Olvida…»)
         ├─► ¿pide un prompt de imagen? ─► traducción + ficha del modelo destino (determinista; el LLM solo es respaldo)
         ├─► hora / clima / datos en vivo ─► reloj del equipo o búsqueda + respuesta del LLM
         └─► LLM 3B con herramientas: buscar_web (fichas locales + ddgs) · recordar (memoria) · ejecutar_python (sandbox)
```

## Uso
```
ollama pull qwen2.5:3b
pip install -r requirements.txt
python inferir.py                       # chat
python inferir.py "¿Quién escribió Rayuela?" "prompt para flux: un gato dormido en una ventana lluviosa"
python evaluar_3b.py                    # casos reservados de ddgs real
python servicio_escenas.py              # servicio HTTP local de escenas para b_chat (POST /escena)
```
Variables: `TEST_IA_MODELO` (defecto `qwen2.5:3b`), `OLLAMA_URL`.

## Archivos
| Archivo | Para qué |
|---|---|
| `inferir.py` | sesión de chat: capa 1, imagen, tiempo real y bucle de herramientas |
| `llm.py` | cliente de Ollama con llamadas a herramientas |
| `herramientas.py`, `corrector.py`, `sandbox.py`, `tiempo_real.py`, `memoria.py` | capa 1, búsqueda, corrector ortográfico, ejecución segura, reloj/clima, memoria con enfriamiento |
| `enrutador.py` | detecta pedidos de prompt de imagen (`EnrutadorV3`) |
| `imagen_*.py`, `escena_*.py`, `servicio_escenas.py` | experto de prompts de imagen y redactor de escenas (traductor opus-mt + fichas) |
| `experto_*.py`, `redaccion_*.py`, `sft_datos.py`, `protocolo.py`, `construir_lexico.py` | fichas locales y léxico que consulta `herramientas.py` |
| `estudios/` | informes y transcripción de todas las etapas |
