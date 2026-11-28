# Ampliación de 5.7 · Registro de llamadas y entrega de respuestas

`record_evidence` enriquecía resultados de algunos ejecutores. Una llamada descartada antes del ejecutor podía quedar fuera de la evidencia que recibe el cierre ordinario. La traza de evaluación mostraba la propuesta y el error, pero la presentación final seguía dependiendo de interpretar texto del modelo. El registro de propuestas de este cambio vive dentro del turno compartido por Desktop y CLI.

## Contrato

1. Numerar cada propuesta al recibirla, antes de aplicar el presupuesto y validar su esquema. Registrar las propuestas de cierre, las de control y las que quedan detrás de una transición o de una interrupción. Las llamadas internas de continuación conservan una referencia distinta si pasan por el bucle.
2. Resolver cada propuesta con un estado del motor. Distinguir argumento inválido, herramienta no disponible, omisión, límite, denegación, reutilización, observación, fallo y efecto pendiente de verificación. La reutilización apunta a su observación original. El resultado de la herramienta viaja separado del estado que asigna el motor.
3. El diario conserva únicamente los pasos que le corresponden, incluidos los efectos despachados que requieren conciliación. El registro del turno no guarda argumentos nuevos ni convierte omisiones en efectos pendientes. Las trazas exponen número, estado y causa con el filtrado existente. El resultado íntegro conserva el ámbito de privacidad de su ejecutor.
4. Antes de publicar una respuesta con propuestas de resultado inseguro, sustituir el texto del modelo por estados del motor y evidencia comprobada. En caso de duda, conservar el estado pendiente. Para una tarea guardada, no aceptar un cierre exitoso que dependa de resultados inseguros. Durante una síntesis que sigue a un rechazo o a un efecto incierto, retener el texto provisional hasta aplicar la compuerta. La decisión se basa en estados y no en buscar palabras en la respuesta. El cierre conserva el motivo del presupuesto y los IDs ya conocidos.

## Comprobación

- Proveedor simulado con texto incorrecto tras validación, límites, omisiones, denegación, reutilización, fallo, efecto incierto y ejecución verificada. Incluir una tanda mixta y un turno interrumpido. Revisar estado emitido, texto final, diario y número de despachos.
- Regresiones de Desktop, CLI, permisos, aislamiento, privacidad, continuidad, supervisor y presupuesto. Usar los mismos ejecutores y controles de autorización.
- Conservar los resultados históricos de 5.8. La matriz con Ollama queda fuera de esta ampliación y 5.8 permanece abierto.
