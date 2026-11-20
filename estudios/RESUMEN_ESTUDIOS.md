# Resumen de estudios (prototipo 0,4–0,8 M parámetros, mundo inventado)

Archivo de las pruebas hechas hasta 2026-11-19. Las tablas completas están en esta misma carpeta.
Los modelos entrenados se borraron; se regeneran con `comparar.py` (~6 min cada uno en la RTX 5060 Ti con 10.000 pasos).

## Qué se probó
Núcleo diminuto (Transformer por caracteres) que responde la categoría de una palabra, busca en un diccionario SQLite cuando no la conoce y responde «no sé» si no hay resultado.

Variantes: `normal` (4 capas), `bitnet` (4 capas, pesos -1/0/+1), `chico` (2 capas), `bucle` (2 capas usadas 2 veces), `bitnet_bucle` (las dos ideas).

## Conclusiones
1. **Buscar en vez de memorizar funciona:** con palabras inventadas, el modelo que busca llega a ~99 % y el que memoriza queda en azar (17 %).
2. **«No sé» funciona:** 94–100 % con palabras que no están en el diccionario.
3. **No sabe leer definiciones con otra redacción** hasta que se entrena con variedad y definiciones «mezcladas»; aun así llegó a ~60–68 % (azar 17 %).
4. **BitNet rinde casi igual que normal** (pocos puntos de diferencia, dentro de la variación entre semillas) y empaquetado pesa 0,31 MB contra 1,67 MB.
5. **Bucle (2 capas ×2) rinde cerca de normal con la mitad de parámetros** y le gana ~14 puntos a `chico` del mismo tamaño (2.000 pasos). No ahorra cálculo.
6. **bitnet_bucle** (10.000 pasos, 3 semillas): 5–8 puntos bajo `bitnet` y `bucle`, dentro del ruido; es el más inestable; pesa 0,20 MB empaquetado.
7. **Sin resolver:** el modelo busca de más cuando la combinación sí calza (62–85 %), probablemente porque aprende «frase nueva → busco» y no «esto contradice lo que sé».

## Límites
- BitNet aquí solo cuantiza pesos y multiplica normal: **aprende igual**, pero no se ahorra RAM/VRAM ni cálculo (al cargar se desempaquetan los pesos). El ahorro real está en el archivo en disco.
- Mundo inventado de ~100 palabras: demuestra el mecanismo, no el manejo de español real.

## Resultados 10.000 pasos, 3 semillas (comparacion_pc.md)
| Grupo | bitnet | bucle | bitnet_bucle |
|---|---|---|---|
| inventadas_nuevas | 65,9 % | 67,9 % | 60,1 % |
| inventadas_mezcladas | 61,6 % | 63,8 % | 56,3 % |
| compatibles_nuevas | 42,1 % | 34,7 % | 43,1 % |
| no_calzan_nuevas | 56,8 % | 58,8 % | 53,1 % |
| inexistentes | 94,4 % | 94,4 % | 94,7 % |
| Peso empaquetado | 0,31 MB | 0,88 MB | 0,20 MB |
