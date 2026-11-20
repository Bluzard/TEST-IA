# modelos/

Solo producción congelada (solo lectura; SHA-256 en los JSON):
- `nucleo_sft_v3.pt` (base para futuros LoRA), `nucleo_sft_v3.bin`, `nucleo_sft_v3.vocab.json` — `NUCLEO_BASE.json`
- `experto_codigo.lora` — `EXPERTO_CODIGO.json`
- `experto_redaccion.lora` — `EXPERTO_REDACCION.json` (6 épocas, r=16; límite conocido: ortografía exacta 14 %, delegable a una herramienta léxica)

- `experimentos/`: salida de cualquier experimento o ablación intermedia. Solo el ganador final exportado se promueve a esta carpeta.
- `archivo/`: checkpoints de ablaciones y variantes descartadas de la Etapa 1-2 (documentadas en `estudios/`).
