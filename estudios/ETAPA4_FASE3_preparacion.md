# Etapa 4 · Fase 3 — Preparación del SFT, los expertos y la exportación (hecha mientras entrena el preentrenamiento)

Todo lo de abajo se escribió y probó **sin usar la GPU** (solo CPU, con el checkpoint del piloto `modelos/experimentos/piloto_v2.pt`, un v2-A con 30 M tokens). Los pesos congelados no se tocaron; `lora.py` solo ganó una rama para los bloques de v2 (los de v1 siguen por el mismo camino).

## Qué hay listo y cómo se verificó
| pieza | archivo | verificación |
|---|---|---|
| Exportador a NUCL0002 (ternarios 2 bits, embedding atado int8 por fila, KV fp16) | `exportar_v2.py` | modelo real exportado: PyTorch ↔ .bin 1e-4 relativo, .bin ↔ motor C++ 1e-5, **mismo token siguiente en 8/8 prompts** (10–361 tokens); el motor genera español con el modelo del piloto a ≈ 4,4 ms/token (con la CPU compartida con el entrenamiento) |
| Protocolo v2 (tokenizador 24.004, contexto 1.024) | `protocolo_v2.py` | las 4 etiquetas y `<|relleno|>` se resuelven por nombre |
| SFT | `sft_v2.py` | prueba en CPU de punta a punta; pérdida solo sobre lo que escribe el asistente; filas de las etiquetas (ids 24000–24003) reiniciadas a media + ruido |
| Datos de SFT | `sft_datos_v2.py`, `charla_v2.py` → `datos/v2/sft/` | **153.885 ejemplos de entrenamiento** (88.182 buscar_ok, 20.527 irrelevante, 20.176 vacío, 25.000 charla, incl. 1.295 reales de ddgs ×3); 145,6 tokens/ejemplo, 0 descartados por largo, 22,4 M tokens/época (≈ 67 M en 3 épocas) |
| Persona TEST-IA | `charla_v2.py` | 36 intenciones, 279 frases de usuario (51 reservadas para evaluar), 109 respuestas; humor sutil solo en charla ligera (saludos, cumplidos, chistes), nunca ante tristeza ni en respuestas informativas |
| Evaluación en producción | `evaluar_v2.py` | corre `inferir.evaluar` sobre el **motor C++**; mismas pruebas de v1 (ddgs real: hechos 71,6 %, abstención 98,1 %) + charla + simulado |
| Expertos LoRA v2 | `entrenar_lora_v2.py`, `exportar_lora_v2.py`, `verificar_lora_v2.py` | LORA0002 con qkv de salida d+2·kv: PyTorch(+LoRA) ↔ motor 1e-4 relativo, el LoRA cambia los logits, mismo token siguiente; el núcleo queda intacto (suma de pesos) |

## Decontaminación de los datos de SFT
Los artículos de entrenamiento excluyen los títulos reservados de todas las evaluaciones de las Etapas 1–4 (22 títulos del pool de 200.000) y la partición de evaluación es por hash del título (5 %, 10.175 artículos). Las frases de charla de evaluación son frases del usuario que no están en entrenamiento.

## Orden de ejecución cuando termine el preentrenamiento
```
.venv/Scripts/python.exe sft_v2.py --eval datos/v2/sft/sft_eval.jsonl      # ≈ 1–2 h (3 épocas, lote 32.768 tokens)
.venv/Scripts/python.exe exportar_v2.py modelos/experimentos/nucleo_v2_sft.pt --verificar
.venv/Scripts/python.exe evaluar_v2.py modelos/experimentos/nucleo_v2_sft.bin
.venv/Scripts/python.exe entrenar_lora_v2.py --nombre codigo --datos datos/experto_train_B2.jsonl --epocas 3
.venv/Scripts/python.exe entrenar_lora_v2.py --nombre redaccion --datos datos/redaccion_train.jsonl --epocas 6
.venv/Scripts/python.exe verificar_lora_v2.py modelos/experimentos/nucleo_v2_sft.pt modelos/experimentos/nucleo_v2_sft.bin modelos/experimentos/experto_codigo_v2.lora.pt
```

## Límites y pendientes
1. **La charla es de plantillas** (36 intenciones). Da identidad, tono y no buscar de más, pero no la conversación abierta y fluida que pide el diseño; eso necesita el modelo auxiliar abierto con verificación automática (decisión §12), que usa GPU y se hará después del preentrenamiento.
2. El pool de artículos son los 200.000 primeros de la lectura de los parquet (orden del archivo): conviene muestrear aleatoriamente si el SFT muestra sesgo temático.
3. Los datos de los expertos (código, redacción) son los de v1 reutilizados; hay que reevaluarlos con el núcleo nuevo antes de aceptar los LoRA (`evaluar_experto.py` aún usa el camino PyTorch de v1).
4. La evaluación contra v1 (71,6 / 98,1 / 100 %) solo tiene sentido con el modelo con SFT; aquí el piloto sin SFT da 0 %, como corresponde.
5. `sft_v2.py` no usa `torch.compile` (lotes de longitud variable); si el SFT resulta lento se agrupa por cubos de longitud.
