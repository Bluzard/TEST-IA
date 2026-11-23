# modelos/

Solo producción congelada (solo lectura; SHA-256 en los JSON).

## Producción actual: v2c (Etapa 4, cerrada el 2026-11-23)
- `nucleo_v2c_sft.bin`, `nucleo_v2c_sft.vocab.json` — núcleo v2-A 157,7 M (BitNet ternario, tokenizador 24 k, embeddings atados int8) — `NUCLEO_V2C.json`
- `experto_codigo_g_v2.lora` (82,7 % forzado / 80,3 % extremo a extremo) y `experto_redaccion_f_v2.lora` (64,2 % / 63,9 %), formato LORA0002
- `python inferir.py` abre v2c por defecto. Detalle y límites: `estudios/ETAPA4_CIERRE.md`.

## Respaldo: v1 (Etapa 3)
- `v1_respaldo/`: copias verificadas de v1 (`SHA256_v1.json`); los originales siguen aquí sin cambios:
  - `nucleo_sft_v3.pt` (base para futuros LoRA de v1), `nucleo_sft_v3.bin`, `nucleo_sft_v3.vocab.json` — `NUCLEO_BASE.json`
  - `experto_codigo.lora` — `EXPERTO_CODIGO.json`; `experto_redaccion.lora` — `EXPERTO_REDACCION.json`
- `python inferir.py --v1 --motor --experto modelos/experto_codigo.lora` abre v1. Los LoRA de v1 y de v2 NO son intercambiables.

- `experimentos/`: salida de cualquier experimento o ablación intermedia (incluye los checkpoints PyTorch de v2c/v2b/preentrenado, no versionados).
- `archivo/`: checkpoints de ablaciones y variantes descartadas de la Etapa 1-2 (documentadas en `estudios/`).
