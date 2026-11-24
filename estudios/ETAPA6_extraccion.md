# Etapa 6: experto de extracción de escena (núcleo v2c + LoRA)

Datos: 382 turnos sintéticos no explícitos generados con Mistral (4 preguntas por turno → 1.248 ejemplos de entrenamiento, 58 turnos de evaluación posteriores en el tiempo).
Variantes: A (8 épocas, lr 1e-3, 74 min), B (16 épocas, lr 6e-4). Artefactos congelados verificados: 5, ninguno alterado.

| campo | A | B | copiar estado anterior |
|---|---|---|---|
| char.posture | 79,3 % | 79,3 % | 79,3 % |
| char.support | 13,8 % | 29,3 % | 89,7 % |
| relacion.arrangement | 19,0 % | 25,9 % | 75,9 % |
| relacion.contactos (exacto) | 13,8 % | 3,4 % | 31,0 % |
| char.action F1 | 47,0 % | 7,5 % | 86,2 % |
| user.action F1 | 43,4 % | 4,0 % | 96,6 % |
| escena exacta | 87,9 % | 89,7 % | 89,7 % |

Latencia: 3,5–4,4 s por turno en CPU (Mistral: 31–44 s).

## Conclusión
Con estos datos el experto NO supera ni a la línea base trivial «copiar el estado anterior»; B memoriza (action/contactos peores). La velocidad es buena, la calidad insuficiente.
`SCENE_EXTRACTOR=core` queda desactivado (por defecto `llm`); no cambia nada en b_chat.

## Siguientes pasos posibles
Mucho más dato (turnos reales del usuario, también explícitos), entrada con el estado anterior como diff, y campos libres (action/expression) resueltos de forma determinista en lugar de generados.

## Prueba 2: formato delta (solo lo que cambia)
5 épocas, 2,6 s/turno. El experto colapsó a contestar siempre «-» (sin cambios): iguala la línea base copiar-anterior (postura +7 y +7 puntos sobre ella) pero nunca predice un cambio real (acierto en turnos con cambio: contactos exacto 13 %, expresión 4–33 %).
Las etiquetas de Mistral (gesto reescrito, contactos con wording variable) no son deducibles de forma consistente con ~1.200 ejemplos; en el 80 % de los turnos algo «cambia» solo por la reescritura de gesto.
