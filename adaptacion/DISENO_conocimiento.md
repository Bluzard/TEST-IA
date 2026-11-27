# Conocimiento relacional: diseño previo al prototipo

Fecha: 2026-11-26. Hipótesis exploratoria, sin exigir resultado positivo.

## Revisión y reutilización

`homeostato.py` integra dinámica continua; `Aspiracion` y `Satisfecho`
añaden repertorio y aspiración 0,90. `entorno_componible.Sujeto` codifica una
configuración como conexiones W y colocaciones P. `SujetoPersistente` añade
observación y recuperación; `Biblioteca` conserva planos, contextos y confianza.
Los JSON abstractos se almacenan, pero se excluyen de los candidatos ejecutables.
La confianza actual atribuye al plano el resultado completo de una configuración;
no contrasta efectos individuales ni descubre relaciones.

Reutilizaremos el patrón de almacenamiento externo, evidencia local y semillas
separadas, y la aspiración provisional de 0,90. No reutilizaremos matrices W/P,
huellas de río ni planos concretos como si fueran conocimiento relacional.
El intérprete nuevo tendrá interfaz observación/necesidades/acciones y será un
prototipo de extensión cognitiva: NO una integración ya demostrada con el
controlador continuo original. Todos sus archivos permanecen intactos.

## Arquitectura mínima

1. JSON declarativo: selector por propiedades de entidad, operación, condiciones
   sobre estado y contexto, efectos aditivos sobre propiedades observables,
   procedencia y tolerancia. Sin IDs de soluciones, secuencias, eval ni código.
2. Intérprete: enlaza selectores con componentes disponibles, verifica condiciones
   y presupuesto, proyecta consecuencias y prioriza reducción del déficit de
   necesidades menos coste e incertidumbre. Exploración común a A/B/C.
3. SQLite: hechos recibidos, relaciones inmutables, experiencias completas,
   evidencia por relación/contexto e hipótesis empíricas separadas del testimonio.
   Contradicción significa error de predicción, no falta de satisfacción global.
   Observaciones corrigen la predicción local sin borrar la afirmación original.
4. Entorno separado: cámara de regulación con variables, deriva, ruido y módulos
   de efectos desconocidos. El agente sólo recibe estado y catálogo público;
   únicamente el entorno y el generador de documentos conocen los efectos reales.

## Generalidad y supuestos impuestos

El intérprete no conocerá temperatura, canales concretos ni componentes: opera
sobre claves, intervalos, selectores y deltas. Los nombres, roles públicos,
observabilidad, unidades, necesidades, suma de efectos, horizonte de un paso,
condiciones y semántica de acciones son definidos por nosotros. Transferir por
roles públicos comprueba enlace relacional bajo esa ontología, no descubrimiento
de conceptos, comprensión natural ni analogía libre. Las hipótesis empíricas
generalizan sobre el selector público; esa generalización puede ser falsa.

Riesgos: roles que revelan efectos, simulador compartiendo predicciones privadas,
entregar una política resuelta, favorecer B mediante presupuestos distintos,
confundir supervivencia con confirmación, contaminar transferencia con IDs o
testimonio reimportado. Controles: roles opacos aleatorios, tablas físicas privadas,
mismo intérprete y recursos, documentos sin secuencias, comparación residual de
efectos, memorias aisladas, transferencia sólo de hipótesis aprendidas y control
con roles permutados. El simulador es deliberadamente pequeño y de efectos
aditivos: un éxito queda limitado a esa familia.

## Plan y validación fijados antes de ejecutar

- Implementar memoria/intérprete, entorno y CLI separados con biblioteca estándar.
- Pruebas de formato, condiciones, recursos, procedencia, persistencia,
  contradicciones locales, selección con propiedades arbitrarias, enlace a nuevos
  IDs y ausencia de acceso a física privada; comprobar reproducción.
- 40 semillas 0–39, 160 decisiones cada una; mismos estados iniciales, catálogo,
  deriva, costes y perturbaciones exógenas por semilla. No ajustar parámetros a
  resultados. A sin documentos, B correctos, C signos invertidos.
- D: entrenar con exploración A, exportar sólo hipótesis observadas, sustituir
  IDs/orden y cambiar estado inicial y deriva. Comparar memoria abstracta,
  memoria vacía y roles permutados sobre el mismo destino. Coste de adquisición
  fuente se reporta aparte; no atribuirlo gratis a D.
- Métricas por vida: proporción de pasos con TODAS las necesidades satisfechas,
  primeros 20 pasos y últimos 40, decisiones exploratorias, acciones inéditas,
  coste total, uso externo/empírico, contradicciones entre predicciones probadas,
  error de predicción y logro de aspiración 90 % de pasos.
- Reportar registros individuales, medias e intervalos bootstrap pareados al 95 %
  por semilla para B−A, C−A y D−control, sin seleccionar sólo éxitos. Intervalos
  descriptivos, sin corrección por múltiples comparaciones ni prueba confirmatoria.
- Añadir ablación de B sin actualización: separa consulta de corrección empírica;
  C sin actualización permite ver si contrastar tiene utilidad operacional.

La etapa termina con resultados reproducibles y límites explícitos, incluso si
no mejora la satisfacción o falla la transferencia. No se repiten barridos ni
experimentos anteriores; sólo se ejecutan sus pruebas de regresión existentes.
