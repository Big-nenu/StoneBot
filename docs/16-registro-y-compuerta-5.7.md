# Ampliación de 5.7 · Registro de llamadas y entrega de respuestas

`record_evidence` enriquecía resultados de algunos ejecutores. Una llamada descartada antes del ejecutor podía quedar fuera de la evidencia que recibe el cierre ordinario. La traza de evaluación mostraba la propuesta y el error, pero la presentación final seguía dependiendo de interpretar texto del modelo. El registro de propuestas de este cambio vive dentro del turno compartido por Desktop y CLI.

## Contrato

1. Numerar cada propuesta al recibirla, antes de aplicar el presupuesto y validar su esquema. Registrar las propuestas de cierre, las de control y las que quedan detrás de una transición o de una interrupción. Las llamadas internas de continuación conservan una referencia distinta si pasan por el bucle.
2. Resolver cada propuesta con un estado del motor. Distinguir argumento inválido, herramienta no disponible, omisión, límite, denegación, reutilización, observación, fallo y efecto pendiente de verificación. La reutilización apunta a su observación original. El resultado de la herramienta viaja separado del estado que asigna el motor.
3. El diario conserva únicamente los pasos que le corresponden, incluidos los efectos despachados que requieren conciliación. El registro del turno no guarda argumentos nuevos ni convierte omisiones en efectos pendientes. Las trazas exponen número, herramienta del catálogo, estado, código y motivo con el filtrado existente. Los nombres ajenos al catálogo del turno se ocultan. El resultado íntegro conserva el ámbito de privacidad de su ejecutor.
4. Antes de publicar, comprobar las operaciones pendientes, sus recuperaciones y la evidencia que respalda el cierre. Las llamadas de control y los descartes previos al despacho quedan registrados en su propia clase. Ante una operación pendiente, conservar los datos disponibles con su procedencia y límites. La compuerta también se aplica cuando el modelo responde sin proponer llamadas en un turno que requiere una operación. El cierre conserva el motivo del presupuesto y los IDs conocidos.

## Comprobación

- Proveedor simulado con texto incorrecto tras validación, límites, omisiones, denegación, reutilización, fallo, efecto incierto y ejecución verificada. Incluir una tanda mixta y un turno interrumpido. Revisar estado emitido, texto final, diario y número de despachos.
- Regresiones de Desktop, CLI, permisos, aislamiento, privacidad, continuidad, supervisor y presupuesto. Usar los mismos ejecutores y controles de autorización.
- Conservar los resultados históricos de 5.8. La matriz con Ollama queda fuera de esta ampliación y 5.8 permanece abierto.

## Implementación

Cada petición se registra antes de recortar la tanda. `ejecucion_propuesta` enlaza el estado final con el número de `llamada_propuesta`. El evento `resultado` incluye ese número cuando el bucle procesa la llamada. Los resultados en JSON conservan el formato estructurado y llevan el objeto `ejecucion`. Los resultados de texto llevan el estado del motor por separado. Los errores previos al despacho quedan fuera del diario de efectos.

Cada recibo distingue operación, efecto, control y descarte. La compuerta mantiene separados el estado de ejecución, la cobertura y la relación con cualquier llamada posterior que aporte nueva evidencia. Una respuesta observada acredita que se recibieron datos. Solo el ejecutor puede aportar cobertura completa explícita o confirmar un efecto. La consulta de un proceso puede acreditar su estado terminal, incluso con salida distinta de cero o cancelación. El código y el estado se muestran según lo observado por el supervisor.

La recuperación conserva el fallo original y apunta a una llamada posterior equivalente. Para lecturas se exige la misma herramienta y los mismos argumentos validados y normalizados, con cobertura completa explícita en la nueva lectura. Para efectos se requiere confirmación del ejecutor. La consulta verificada del mismo ID puede resolver el estado de un lanzamiento en curso o sin confirmar. Para resolver una cancelación pendiente, ese mismo ID debe aparecer como cancelado. La clave de equivalencia se calcula en memoria con una clave aleatoria por turno. Los argumentos y esa clave se mantienen fuera de las trazas nuevas. La reutilización de una respuesta, una lectura parcial, otra operación y una denegación se mantienen diferenciadas de la recuperación. Las lecturas por páginas conservan las comprobaciones de versión y continuidad del registro de evidencia. Al reanudar un encargo, se conserva su comprobación de cobertura sobre las lecturas actuales y las guardadas. El diario y las autorizaciones conservan sus controles sobre los efectos.

Si una tanda contiene estados pendientes o parciales, el motor presenta los datos observados y los recibos correspondientes con sus límites. Incluye hasta tres extractos recientes de hasta 1200 caracteres cada uno y conserva los estados, códigos e IDs de procesos en la evidencia estructurada. El acuse de un efecto pendiente se identifica como dato sin confirmación del efecto. Cuando hay una recuperación equivalente y ya se cumplieron las condiciones del cierre, el agente puede entregar su síntesis.

## Limitaciones de la revisión

- La ausencia de evidencia se detecta primero mediante la intención operativa del turno y los recibos del motor. Una señal complementaria reconoce algunas afirmaciones de acción en español e inglés en turnos ordinarios. La compuerta no verifica semánticamente cada afirmación de texto libre. Una reformulación ambigua o una afirmación sobre un efecto distinto después de otra operación verificada pueden escapar a esa comprobación.
- La recuperación se limita a las equivalencias que el motor puede comprobar dentro del turno. Dos herramientas, rutas alternativas o argumentos distintos pueden producir el mismo resultado en la práctica y seguir apareciendo por separado. La cobertura depende de lo que acredita cada ejecutor, por lo que un resultado observado con alcance indeterminado no acredita una enumeración completa.
- Cuando persisten estados parciales, inciertos o fallidos, la presentación por recibos puede perder matices de la síntesis libre. Los extractos son acotados y la consulta de procesos sigue su propia presentación con ID, estado y código. El motor mantiene las autorizaciones, el presupuesto y el diario vigentes.


## Verificación de la ampliación

Pasaron las 38 suites de Windows con `python -B`, Qt fuera de pantalla, descubrimiento MCP activo y conexiones a Ollama bloqueadas. `test_execution_gate.py` simuló un proveedor que declara éxito tras propuestas inválidas, limitadas, omitidas, denegadas, fallidas o sin confirmación. Cubrió además la reutilización, la interrupción en el ejecutor, los controles de tarea, el estado activo y la cancelación de procesos, y el contraste con un efecto verificado.

La prueba de paridad de la rama de evidencias de 5.8 pasó con esta revisión. Desktop y CLI coincidieron en la consulta directa, cadena, autorización, denegación, interrupción, pausa, reanudación y reapertura. El prompt común conserva el texto de la referencia. La comparación de modelos con Ollama y el cierre de 5.8 quedan pendientes.


## Verificación de la revisión de la compuerta

Pasaron las 38 suites de Windows con `python -B`, Qt fuera de pantalla, descubrimiento MCP activo y el acceso a Ollama bloqueado. La suite de la compuerta cubrió un fallo recuperado con los mismos argumentos, un fallo junto a una lectura distinta, afirmaciones sin llamadas, tandas mixtas y resultados parciales o sin confirmar. También comprobó que un acuse incierto se reutiliza sin duplicar el despacho y que solo el mismo ID del supervisor puede aportar el estado terminal de una ejecución anterior.

Las pruebas de tareas confirmaron la pausa y reanudación con lecturas guardadas, el descarte de lecturas obsoletas y la continuidad de páginas. La prueba de paridad con proveedor simulado volvió a pasar en Desktop y CLI para consulta directa, cadena, permisos, detención, pausa, reanudación y reapertura. Se comprobó que el prompt común permanece idéntico a `1cf9596`. El paso 5.8 sigue abierto y se conservan sus mediciones con Ollama.


## Ajustes tras la evaluación de 808af84

En N02, el motor vació el catálogo tras las seis denegaciones de la escritura. En D06, los seis procesos registrados por el supervisor terminaron con código 7, mientras que la compuerta añadió un aviso de ejecución sin acreditar. La comparación se realizó con Nemotron y Qwen a 8192 tokens. D08 se trató después en la revisión de continuidad MCP descrita abajo.

- Una denegación conserva el bloqueo de la fuente rechazada y de las operaciones con efectos durante el resto del turno. Una lectura MCP de otra fuente puede continuar cuando el usuario identifica directamente la herramienta y el servidor, los argumentos son valores escalares literales de esa misma solicitud y no reutilizan datos rechazados. Se aplican el esquema, el alcance vigente, el control de rutas y la autorización normal de la lectura, incluida una confirmación específica si hace falta. La excepción se limita a los destinos ya disponibles. Las lecturas protegidas, los adjuntos, los efectos inciertos y el proveedor en la nube conservan el bloqueo. La excepción se limita al turno actual y el diario guarda el alcance cerrado si es preciso reanudar.
- El recibo del supervisor conserva el inicio confirmado, el estado del proceso y el código de terminación por separado. Una terminación con código distinto de cero acredita el inicio cuando así lo confirma el supervisor y conserva el resultado de error. Una terminación sin código registrado tampoco acredita un resultado exitoso. La consulta de un proceso distinto no acredita el lanzamiento solicitado. La salida, el ID y el código se siguen mostrando con la evidencia del supervisor.
- La autorización posterior de una lectura mantiene la denegación registrada. Los controles de memoria, privacidad y permisos por operación siguen usando ese estado. Las solicitudes ambiguas o cuyos argumentos deban inferirse quedan fuera de la excepción.

Las pruebas simuladas cubren la lectura independiente en la misma tanda y en la siguiente, la autorización automática y la explícita, el intento de escritura alternativa y el reenvío de un dato rechazado. Para procesos se comprobaron códigos cero, distinto de cero y ausente, además de la correlación con el ID del supervisor.
La verificación del núcleo incluye las suites automatizadas de Windows y la paridad Desktop–CLI con el proveedor simulado. Se conservó el prompt de 808af84. La matriz con Ollama de esta revisión queda pendiente y 5.8 sigue abierto.


## Continuidad de páginas MCP

En D08, el reintento de la primera página funcionó en los seis intentos de 808af84. En cinco, el modelo respondió sin solicitar la continuación que ya había devuelto el conector. En el sexto, la segunda página quedó observada y el cierre todavía mostraba el cursor anterior como pendiente.

El motor registra las continuaciones dentro del turno mediante el alias resuelto, los argumentos de la consulta que permanecen fijos, el parámetro del cursor y su valor. Un cursor debe encajar en el esquema MCP. Una respuesta recibida para la misma consulta y el cursor exacto enlaza la observación de origen con la observación nueva. Un cursor de respuesta que contradice al cursor solicitado deja la continuación pendiente. El historial de cursores visitados detecta repeticiones inmediatas y ciclos de varias páginas, y detiene esa consulta sin bloquear las consultas distintas de la herramienta.

Si el modelo intenta cerrar antes de obtener una página solicitada, puede recibir una sola ronda de trabajo orientada a la continuación. Se ofrecen únicamente las herramientas de lectura que siguen disponibles en el alcance del turno y solo se admite una propuesta que mantenga la consulta y use un cursor pendiente. La lectura usa el presupuesto normal y la autorización de ese despacho. El cierre posterior sintetiza los datos sin nuevas herramientas. Si el modelo no propone una continuación válida o el turno llega a un límite, se conservan los datos observados y el cierre indica lo pendiente. El evento `continuacion_mcp` registra la oportunidad y el número de candidatos en la traza filtrada.

El registro distingue resolver un enlace entre páginas de acreditar la cobertura del conjunto. Una página posterior o un cursor final nulo no acreditan un total ni demuestran que se observaron todas las páginas. Los resultados permanecen parciales cuando el conector no aporta esa garantía. La corrección conserva el contenido de `SYSTEM` y usa una instrucción temporal solo en la ronda de continuación.

La ronda adicional se activa ante un objetivo explícito de paginación, como una página numerada, ordinal, siguiente o todas las páginas. Se limita a conectores de lectura que declaran un parámetro reconocible en el esquema y a las consultas observadas en el turno. Los esquemas ambiguos, las continuaciones que requieren modificar otros filtros y los pedidos implícitos conservan el cierre parcial y el control ordinario del agente. El registro no añade cursores a la traza pública ni cambia cómo el diario existente conserva el avance de un encargo.

Las pruebas automatizadas cubren el reintento transitorio seguido de una página nueva, la separación entre herramientas y filtros, la discrepancia de cursores, los ciclos, la solicitud de una sola página y el cierre por presupuesto, permiso o argumentos incompatibles. Pasaron las 38 suites automatizadas de Windows con Ollama bloqueado, incluida la verificación aislada de adjuntos. También se verificó la paridad entre Desktop y CLI con el proveedor simulado. La comprobación con Nemotron y Qwen queda pendiente y 5.8 sigue abierto.
