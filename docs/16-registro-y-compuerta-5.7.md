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

## Implementación

Cada petición se registra antes de recortar la tanda. `ejecucion_propuesta` enlaza el estado final con el número de `llamada_propuesta`. El evento `resultado` incluye ese número cuando el bucle procesa la llamada. Los resultados en JSON conservan el formato estructurado y llevan el objeto `ejecucion`. Los resultados de texto llevan el estado del motor por separado. Los errores previos al despacho quedan fuera del diario de efectos.

La compuerta es conservadora en tandas mixtas. Si el turno contiene una propuesta fallida o incierta, muestra las observaciones disponibles con su procedencia y conserva los datos confirmados sin publicar la síntesis libre del modelo. También distingue un proceso activo, una cancelación observada y un código de salida distinto de cero. Aplicar un control de conversación o reutilizar una observación queda registrado, con su alcance correspondiente. Las confirmaciones, la recuperación del diario y los límites del presupuesto mantienen sus mecanismos anteriores.

La compuerta toma decisiones sobre las propuestas del turno y los efectos pendientes de su diario. Conserva resultados comprobados de una tanda mixta con su procedencia. La referencia de una llamada describe lo observado en ese momento. Una consulta posterior puede aportar un estado más reciente.

## Verificación de la ampliación

Pasaron las 38 suites de Windows con `python -B`, Qt fuera de pantalla, descubrimiento MCP activo y conexiones a Ollama bloqueadas. `test_execution_gate.py` simuló un proveedor que declara éxito tras propuestas inválidas, limitadas, omitidas, denegadas, fallidas o sin confirmación. Cubrió además la reutilización, la interrupción en el ejecutor, los controles de tarea, el estado activo y la cancelación de procesos, y el contraste con un efecto verificado.

La prueba de paridad de la rama de evidencias de 5.8 pasó con esta revisión. Desktop y CLI coincidieron en la consulta directa, cadena, autorización, denegación, interrupción, pausa, reanudación y reapertura. El prompt común conserva el texto de la referencia. La comparación de modelos con Ollama y el cierre de 5.8 quedan pendientes.
