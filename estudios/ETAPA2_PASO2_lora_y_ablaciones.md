# Etapa 2 · Paso 2 — LoRA de `experto_codigo` y ablaciones (2026-11-20)

Núcleo Base (`nucleo_sft_v3.pt`) **congelado**. Implementación en `lora.py` (adaptador `y = BitLinear(x) + (α/r)·B·A·x`, α=2r,
B inicia en cero), `entrenar_lora.py` (entrenamiento + evaluación), `evaluar_experto.py` y `tabla_lora.py`. Datos: los 13.999 ejemplos del
Paso 1; evaluación: 1.007 casos reservados. 3 épocas, lote 64, lr 1e-3, bf16, ~2,5 min de entrenamiento por corrida. Resultados completos
en `resultados/experto_comparacion.md` y `resultados/experto_*.json`.

## Verificaciones de integridad (todas las corridas)
- **Núcleo intacto:** la suma de verificación de todos sus pesos es idéntica antes y después de entrenar.
- **Adaptador dormido = núcleo base:** la evaluación general de la Etapa 1 con el adaptador apagado dio exactamente 71,6 % / 98,1 % / 100 %.

## Comparación (puntaje = promedio de la métrica principal de 9 tipos de caso)

| Variante | MB (fp16) | Puntaje | Ejecución ok / error | Documentación ok / abst. | Conceptos | Abstención NameError | General: hechos | General: abstención |
|---|---|---|---|---|---|---|---|---|
| Núcleo solo | 0 | 12,5 % | 0 % / 0 % | 7 % / 67 % | 0 % | 0 % | 71,6 % | 98,1 % |
| Solo atención, r=8 | 0,49 | 41,7 % | 59 % / 68 % | 42 % / 87 % | 0 % | 0 % | 56,3 % | 88,5 % |
| 4 matrices, r=4 | 0,66 | 52,6 % | 95 % / 85 % | 27 % / 72 % | 8 % | 30 % | 59,9 % | 98,1 % |
| **4 matrices, r=8** (principal) | **1,31** | **64,3 %** (semilla 1: 68,2 %) | 97 % / 88 % | 37 % / 78 % | 19 % | 70 % | 63,5 % | 92,3 % |
| **4 matrices, r=16** | **2,62** | **73,3 %** | 98 % / 92 % | 46 % / 81 % | 16 % | 100 % | 66,7 % | 98,1 % |

"Documentación ok" = similitud ≥ 95 % con la oración correcta; "General" = evaluación de la Etapa 1 con ddgs real y el adaptador **activo**.

## Conclusiones
1. **El puntaje crece con el tamaño del adaptador y no se ha estancado:** 41,7 → 52,6 → 64–68 → 73,3. El ruido entre semillas (r=8: 64,3 y 68,2) es de ~4
   puntos, menor que los saltos entre variantes, salvo quizá r=8 → r=16 (+5 a +9), que es real pero moderado.
2. **Solo atención no alcanza** (41,7 %, y 0 % en conceptos): lo que se memoriza vive en el MLP, como se esperaba. Las matrices de atención solas bastan para el
   protocolo (87 % de abstención con documentación) pero no para ejecutar código ni aprender conceptos.
3. **La ejecución verificada se satura pronto:** con r=8 ya está en 97 % (códigos correctos) y 88 % (errores). El protocolo `E:` es barato de aprender.
4. **Ganador por precisión dentro del presupuesto (1–3 MB): 4 matrices, r=16, 2,62 MB.** Es el único que además mantiene la abstención general en 98,1 %
   y llega a 100 % en nombres inexistentes. La mejor relación puntaje/MB es r=4 (79 puntos por MB) pero con un puntaje bajo.
5. **El experto activo cuesta rendimiento general:** con el adaptador despierto, la respuesta exacta en hechos cae de 71,6 % a 56–67 %. **No se cumple el criterio
   de ≤ 2 puntos en ninguna variante** (r=16 es la mejor: −4,9). Esto hace imprescindible el enrutador: con el adaptador dormido no hay pérdida alguna, y una
   pregunta general mal enrutada al experto sí pierde calidad.

## Dónde falla (y por qué): conceptos
Los conceptos fundamentales son lo peor (16–22 % de respuesta exacta en todas las variantes). Diagnóstico con r=16 sobre 200 casos de evaluación:
43 % de las veces **busca** en vez de responder y, cuando responde directo, la similitud media con la definición correcta es solo **0,55**: mezcla definiciones
(«Una es un es un conjunto de funciones y funciones que permite que un programa use los servicios de otro»). Las 7 formulaciones de entrenamiento no
alcanzan: el modelo reconoce la forma de la pregunta, no el concepto, y con una formulación nueva («booleano: ¿qué es?») se pierde. Lo mismo explica que
`concepto_nuevo` (que debe buscar) solo busque entre el 54 % y el 67 %: cuanto más memoriza, más inventa con conceptos que no conoce (las variantes
más chicas buscan un 87 % porque buscan casi todo).

Es el mismo resultado de la Etapa 1 visto desde otro ángulo: **memorizar conocimiento es caro y frágil; usar el protocolo es barato y robusto.**

## Otros puntos débiles
- Documentación con respuesta: 27–46 % de similitud ≥ 95 % (el núcleo solo tenía 71,6 % en español de Wikipedia; el inglés técnico con símbolos es más difícil de copiar).
- Interpretación de errores pegados por el usuario (sin herramienta): 58–75 %.
- La consulta `B:` exacta («pandas merge») solo coincide el 14–37 % de las veces; es informativa, la respuesta final puede estar bien igual.

## Próximos pasos posibles
1. **Antes de exportar:** una ronda de datos para conceptos (≥ 20 formulaciones de pregunta en vez de 7, más épocas) o, alternativamente, **sacar las
   definiciones del LoRA y que el experto las busque**. Es barato (≈ 8 min por corrida) y ataca lo más débil.
2. Exportar el ganador (hoy r=16, 2,62 MB) al formato `.lora` del motor C++ y medir el coste real (ms/token y RAM extra: ~4,2 % más cálculo y +2,6 MB en fp16).
3. Enrutador (Capa 1) y su evaluación.
