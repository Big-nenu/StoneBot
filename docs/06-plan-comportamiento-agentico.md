# Plan del paso 5 · Comportamiento agéntico de StoneBot

- **Estado** — Pasos 5.1, 5.2, 5.2.1, 5.3A, 5.4, 5.6 y 5.5 completados. Siguiente paso planificado 5.7.
- **Fecha** — 27 de noviembre de 2026.
- **Base** — `refactor/stonebot-core` en `307b40a`, con los pasos 0 a 4 completados.
- **Objetivo** — Que un turno normal pueda descubrir recursos, ejecutar pasos autorizados, recuperarse de fallos y entregar una respuesta comprobable. StoneBot CLI servirá para medir los cambios con Nemotron y Qwen. Desktop y CLI seguirán usando el mismo `ChatSession`, `Worker` y `ToolLoop`.

## 1. Punto de partida

La comparación de Claude con Hermes Agent en el commit `93dd2a4e` señala puntos que conviene comprobar en StoneBot, como la validación de llamadas, los límites del bucle y el catálogo visible para el modelo. El resumen histórico menciona hasta 500 iteraciones en Hermes y una mejora pequeña al reforzar el prompt de Nemotron. Ambas cifras sirven como contexto de aquella investigación. Los límites y criterios de StoneBot se fijarán con sus propias pruebas. [Comparación original](04-plan-separar-nucleo-de-interfaz.md#2-por-qué-resumen-de-la-comparación-con-hermes-agent)

| Componente actual | Hallazgo en la rama | Cambio propuesto |
|---|---|---|
| `ChatSession.begin_turn`, `chat_preferences.py`, `ChatContext` | La sesión añade preferencias y contexto de proyecto. El alcance y el estado previo ya existen en el diario. El motor agrega instrucciones según el recorrido. | Construir una vista operativa por turno y conservar sus restricciones durante la compactación y reanudación. |
| `request_routing.py`, `Worker.chat_with_tools`, `TurnTools` | Las expresiones de intención influyen en el descubrimiento de MCP y memoria. El chat puede ofrecer lecturas locales, procesos y controles según el alcance actual. `limit_to` restringe por intersección y algunas restricciones quedan guardadas. | Hacer explícitas las diferencias entre intención, disponibilidad, relevancia y autorización. Ofrecer descubrimiento por capacidad y reevaluar el catálogo con las restricciones vigentes. |
| `mcp_client.py`, `mcp_permissions.py`, `ToolLoop` | Los alias MCP son largos. MCP valida su esquema y rutas antes del envío. El tratamiento de errores depende del ejecutor. Una tanda enteramente repetida conduce al cierre sin herramientas. | Dar al modelo alias breves, validar con reglas comunes y entregar errores y opciones de recuperación. |
| `process_tools.py`, `managed_process.py` | El modelo debe aportar un ejecutable absoluto y un directorio. Hay tres herramientas de proceso. El diario ya conserva ID y cursores, y el supervisor de Windows controla el árbol. | Simplificar la interfaz para el modelo sobre el supervisor actual y distinguir lanzamiento, resultado y cancelación confirmada. |
| `Worker.request_round`, `ToolLoop`, `TurnOutcome` | El chat ordinario tiene seis rondas en el recorrido habitual de Ollama. Las tareas tienen doce. Algunas peticiones de reparación, síntesis o cambio de fuente ocurren dentro o alrededor del bucle. | Usar un presupuesto por turno que contabilice todas las peticiones y permita un cierre a tiempo con resultados parciales. |
| `SYSTEM`, `tasks.py` y `ChatExecution` | El prompt ya contiene reglas de privacidad y algunas obligaciones de verificación. Las tareas guardadas tienen comprobaciones de cobertura. El chat ordinario ya puede encadenar herramientas y guardar efectos pendientes. | Aplicar un criterio común de progreso y evidencia para el chat y las tareas. Conservar la semántica de guardar, pausar y reanudar un encargo. |
| `stonebot_cli.py`, `cli_turn_runner.py`, `qt_turn_runner.py` | La CLI selecciona modelo por invocación y observa el turno desde el motor. Desktop traduce los eventos al hilo de Qt. | Extender los eventos del núcleo y medir por CLI. Los adaptadores presentan resultados y resuelven confirmaciones. |

### 1.1 Revisión independiente del 27 de noviembre

Claude contrastó el plan con Hermes Agent y con el código de `ae7deab`, y reportó una revisión de los 252 registros de las dos campañas. Se conserva su diagnóstico como evidencia de auditoría, no como nueva ejecución ni recalificación definitiva. Véanse la [línea base](07-linea-base-comportamiento-agentico.md) y su [ampliación](5.1-ampliacion/README.md).

- D04, D08 y V02 tuvieron cero aciertos en 63 intentos. Según la auditoría, el catálogo inicial de esos intentos ofrecía elegir_fuente y herramientas locales/de procesos, pero no herramientas MCP; elegir_fuente se invocó una sola vez. En 252 intentos solo se ofrecieron herramientas MCP en nueve, con doce llamadas; inspect_local_files se invocó 217 veces.
- D03 sigue sin explicación: se ofreció MCP en 6/6 intentos de los dos modelos originales y en 0/15 de las configuraciones adicionales. No se puede distinguir retrospectivamente entre fallo de arranque, entorno y exclusión por el motor. Registrar la causa antes de clasificar. Una denegación no ejercitada no acredita el control.
- Los 19 cierres por límite de rondas reportados se concentran en recorridos sin herramientas pertinentes; aumentar las rondas no es la primera intervención. V01 también señala un problema de diseño de herramienta: la búsqueda por nombre no es recursiva por defecto. No corregir únicamente las frases de la matriz.
- Corrección sobre Hermes, según la nueva lectura de Claude: tool_search, tool_describe y tool_call están siempre activos y presentan un inventario acotado de herramientas diferidas (mínimo de 4000 tokens y 5% del contexto); las herramientas núcleo no se difieren. Lo importante es que el modelo sabe qué capacidades existen, no replicar literalmente sus límites.
- Las calificaciones adicionales son provisionales y mezclan condiciones de ejecución. No usar el ranking para concluir qué modelo es superior ni atribuir las diferencias al contexto.

**Decisión:** medir primero, hacer visibles las capacidades, recuperar errores reales, ajustar el presupuesto y después simplificar procesos y resultados. Posponer el rediseño amplio del registro y el prompt. No reducir los controles de seguridad.

## 2. Diseño del núcleo compartido

### 2.0 Instrumentación y evaluación (nuevo paso 5.2.1)

- Añadir trazas redactadas de descubrimiento MCP: servidor habilitado, intento de conexión, éxito/error/timeout, cantidad de herramientas descubiertas, exclusiones por política y motivo de no oferta al modelo. Registrar catálogo efectivo por ronda y llamadas sin exponer datos privados.
- Clasificar separadamente: (a) fallo de infraestructura cuando una fixture/servidor no arranca o no cumple sus precondiciones por causas externas al motor; (b) fallo del motor cuando una capacidad habilitada y disponible no se descubre, no se ofrece ni es localizable mediante el mecanismo previsto; (c) fallo de selección/ejecución del modelo cuando la capacidad sí es accesible y no la utiliza correctamente. Si la causa es desconocida, registrar diagnóstico pendiente; no excluir automáticamente una medición del denominador porque no se ofreció MCP.
- Introducir calificadores deterministas por caso para hechos comprobables (trazas, efectos, códigos, cobertura y respuestas esperadas). Cuando la semántica no se pueda calificar de forma fiable, dejar revisión manual explícita, con rúbrica única. D03 exige propuesta de llamada y denegación comprobadas, sin efecto; V04 exige evidencia del cursor repetido y cierre parcial correcto. Conservar los registros históricos y las calificaciones anteriores sin sobrescribirlos.
- Añadir V05–V08: descubrimiento de fuente por formulación distinta, recuperación de error transitorio, recuperación de evidencia truncada y cobertura de búsqueda con múltiples coincidencias. Variar fixtures y mantener los casos nuevos fuera del ajuste. Los casos V01–V04 usados para diagnóstico dejan de ser validación independiente. Predefinir expectativas y reservar los casos nuevos para la evaluación de candidatos, sin adaptar el motor a sus textos.
- Medir y documentar una política explícita de contexto por modelo (máximo, valor configurado, valor solicitado y valor observado, diferenciados), incluyendo tokens de entrada/salida cuando Ollama los informe. Revisar la decisión de 5.2 antes de cambiar comportamiento: un valor fijo demasiado pequeño también puede truncar herramientas y resultados. Mantener configuración de Ollama y compactación actuales mientras se instrumenta; cualquier cambio funcional de contexto tendrá prueba separada, valor configurable, límites del modelo y reserva de salida. No afirmar que se conoce la VRAM libre a partir de /api/ps.
- Entrega: pruebas simuladas de clasificación y trazas, calificadores, fixtures nuevas y piloto acotado de Nemotron/Qwen que permita diagnosticar D03 y verificar la medición. Sin cambios de catálogo, permisos, enrutamiento ni bucle durante este subpaso.

La implementación, la rúbrica y los resultados de los tres intentos del piloto están registrados por separado de la línea base. [Informe de instrumentación y evaluación](08-instrumentacion-evaluacion-agentica.md)

### 2.1 Contexto operativo y prompt

- Construir el contexto a partir de `TurnPlan` y las capacidades confirmadas del turno. Incluir objetivo actual, alcance del proyecto, directorio de trabajo autorizado cuando corresponda, proveedor, restricciones de datos, tarea o diario recuperable y resumen de los pasos pendientes. Determinar las capacidades efectivas después de aplicar la política del proveedor y las restricciones de privacidad.
- Separar reglas del sistema, preferencias de usuario, contexto persistido y datos devueltos por herramientas. Incorporar solo campos necesarios y poner límites explícitos de tamaño. Evitar volcar variables de entorno, credenciales, listados del perfil y rutas privadas en el prompt o la traza. Conservar objetivo, límites y referencias de evidencia al compactar. Una instrucción encontrada en un archivo, salida MCP o resultado de proceso se trata como dato.
- Revisar el prompt al final del trabajo estructural. Mantener idioma, identidad y restricciones vigentes. Pedir al modelo que complete los pasos disponibles dentro del alcance, use resultados actuales para comprobarlos, se recupere de errores corregibles y consulte al usuario cuando falte un requisito indispensable. Las confirmaciones se tramitan por el adaptador. El cierre explica resultados, omisiones y bloqueos relevantes para el usuario.
- El chat ordinario usa el bucle para encargos de varios pasos sin requerir `/tarea`. Reservar `/tarea`, `/reanudar` y `/cancelar` para el ciclo de vida de tareas guardadas. Una pregunta simple puede terminar con una respuesta directa. Evitar reglas basadas en frases de los casos de evaluación o instrucciones distintas para cada modelo.

#### Decisión y validación de 5.2

La [ampliación de la línea base](5.1-ampliacion/README.md) registró siete configuraciones sin medidas de contexto efectivo por petición. La diferencia de puntuación de `nemotron-8k` frente al original queda como observación provisional. La concurrencia, los límites y la rúbrica también variaron entre campañas.

- `ChatSession` prepara un contexto compartido con modo, proveedor, proyecto y preferencias acotadas. La solicitud actual conserva su rol de usuario. El núcleo agrega automáticamente carpeta y continuidad del proyecto solo tras verificar Ollama local. El historial abreviado conserva las reglas, la solicitud vigente, los pares llamada/resultado y las referencias recuperables. El diario conserva su formato y su comprobación de alcance.
- StoneBot dejó de enviar `num_ctx` calculado a partir de los caracteres. Ollama aplica la configuración del servidor y del modelo. La vista del historial usa una cota heurística en caracteres basada en el menor valor aplicable entre el `num_ctx` del modelo y su máximo publicado, con referencia conservadora de 4096 tokens cuando faltan datos y límite superior de 48 000 caracteres. Esa cota regula la compactación. El mensaje actual y la estructura de las llamadas se conservan aunque la entrada resulte larga. [Contexto en Ollama](https://docs.ollama.com/context-length) · [Metadatos del modelo](https://docs.ollama.com/api-reference/show-model-details)
- `--verbose` registra por separado el máximo anunciado, el `num_ctx` declarado y la cota de historial. Después de responder, consulta `/api/ps` y registra la ventana y la VRAM asignada si hay una coincidencia inequívoca del modelo cargado. Esa lectura es una observación del servidor y puede reflejar concurrencia. La VRAM asignada tampoco mide VRAM libre. [Modelos cargados en Ollama](https://docs.ollama.com/api/ps)
- Pasaron 32 suites en Windows, incluidas las 31 de la línea base, y se repitieron las pruebas de contexto, proyecto y recuperación. Un turno real con cada uno de Nemotron y Qwen observó 8192 tokens, con máximos anunciados de 65 536 y 262 144 respectivamente. La variante `nemotron-8k` anunció una configuración de 8192 y completó el turno. En esa observación el servidor no identificó inequívocamente el alias cargado. La prueba con Ollama real recuperó el marcador sintético después de abreviar el historial.
- En el control D02, ambos modelos encadenaron el ranking y las lecturas, identificaron la ruta de la copia y comprobaron los 613 bytes. Estas comprobaciones puntuales validan el recorrido de 5.2. La comparación completa de resultados se conserva para 5.8.

### 2.2 Catálogo y descubrimiento

**5.3A (prioridad):** ofrecer un manifiesto compacto y acotado de fuentes habilitadas y un mecanismo de descubrimiento siempre localizable, sin depender de que el usuario mencione MCP ni de expresiones regulares para hacer visible una capacidad. Mostrar servidor y nombre de herramienta inequívocos; preparar/cachar el grupo MCP al iniciar la sesión con espera acotada y aislamiento de fallos, sin ejecutar herramientas ni conceder permisos. La elección de fuente y la promoción a tarea no serán requisitos para usar una capacidad pertinente en chat ordinario; conservar las tareas guardadas y los controles explícitos del usuario. Implementar detrás de una bandera configurable para comparación A/B, sin bifurcar Desktop y CLI. La visibilidad no equivale a autorización; excluir metadatos cuya exposición vulnere privacidad y validar cada llamada.

La [evaluación de 5.3A](09-visibilidad-mcp.md) documenta las 60 ejecuciones definitivas, la comparación de visibilidad y los fallos de recuperación observados.

**5.3B (diferido y condicionado a evidencia):** las propuestas de registro canónico, migración de alias y límites persistidos que siguen son un diseño de referencia, no requisitos para 5.3A. Implementar únicamente lo que los datos posteriores justifiquen. No ampliar alcance por una migración.

- Definir un registro de herramientas con identificador canónico, alias de presentación, familia, descripción, esquema, proveedor o servidor, requisitos de disponibilidad, clase de efecto, política de confirmación y clasificación de entrada y salida. Reutilizar los ejecutores existentes. Mantener una distinción verificable entre herramienta registrada, habilitada, ofrecida y autorizada para la llamada concreta.
- Ofrecer un conjunto inicial acotado de herramientas nativas y un mecanismo para descubrir herramientas habilitadas por capacidad y fuente, con resultados paginados o limitados. Descubrir servidores bajo demanda con `McpPool` y su caché. Una búsqueda puede sugerir una herramienta y ofrecerla en la ronda siguiente si es compatible. Descubrir, cargar una Skill y elegir una fuente nunca conceden un permiso.
- Usar las reglas de intención actuales como pistas para ordenar candidatos y conservar los controles explícitos del usuario. Los recursos habilitados podrán encontrarse ante distintas formulaciones. Reevaluar relevancia por ronda y conservar las exclusiones de seguridad aplicables durante todo el turno. Tras leer datos privados, impedir que esos datos o su contexto lleguen a destinos incompatibles. Las tandas vuelven a validar permisos y privacidad por llamada, incluso si la herramienta se ofreció al inicio.
- Probar alias breves y deterministas, acotados al catálogo, con detección de colisiones entre nativas y servidores. En permisos, efectos, caché, recuperación y diario usar la identidad canónica. Leer alias anteriores y migrar límites persistidos de forma conservadora. Si una identidad antigua no se puede resolver con seguridad, pedir una nueva selección en vez de ampliar el alcance o repetir un efecto.

### 2.3 Terminal y procesos gestionados

- Probar dos operaciones de cara al modelo. **Ejecutar** recibe un programa y una lista de argumentos. **Gestionar ejecución** consulta el estado, lista ejecuciones del chat o solicita cancelar por ID. Traducir ambas a `process_tools.py` y conservar las identidades históricas de lanzamiento, consulta y cancelación. Mantener el supervisor, el diario, los cursores y el aislamiento por chat, perfil y alcance.
- Conservar inicialmente el requisito de ruta absoluta. Diferir la resolución por nombre de ejecutable mediante ubicaciones confiables hasta demostrar que es necesaria; si se implementa, será determinista y no ampliará permisos. Un nombre ambiguo o ausente devuelve un error corregible. Usar el directorio vinculado al proyecto solo si existe y está autorizado para esa operación. En los demás casos se exige un directorio explícito. Confirmar el ejecutable resuelto, los argumentos exactos y el directorio antes de lanzar. No interpretar cadenas como comandos de shell ni convertir automáticamente listas, redirecciones o tuberías en comandos. Mantener los controles de autorización y las restricciones actuales de procesos y archivos.
- Después del lanzamiento autorizado, esperar durante una ventana corta, limitada por el tiempo restante del turno. Si el supervisor confirma que el comando terminó en esa ventana, devolver directamente su salida acotada, el estado y el código de terminación en la misma llamada. El diario conserva el ID y contabiliza el cursor de la salida entregada. Si vence la espera, devolver el ID y el estado observado para consultar la ejecución larga por separado. La espera no cancela el proceso ni habilita otro lanzamiento.
- Cada resultado distingue entre inicio confirmado, ejecución activa, salida parcial o truncada, terminación con código, cancelación solicitada y estado sin confirmar. Consultar por ID también admite una espera breve y acotada. Si el proceso sigue activo al cerrar el turno, informar su ID y el estado conocido. Tras una interrupción, comprobar el ID existente antes de considerar un nuevo lanzamiento. Cancelar sigue siendo una operación con efecto y confirmación.

El [informe de 5.5](12-interfaz-procesos.md) documenta el contrato de procesos y la evaluación de D06, D07 y V03 con ambos modelos y descubrimiento MCP activo.

### 2.4 Validación y recuperación

Validar el nombre contra el catálogo efectivo y los argumentos contra su esquema antes de pedir autorización o ejecutar. Conservar las validaciones de dominio de cada herramienta, como ruta, cursor, firma y destino. Las correcciones automáticas deben estar definidas por campo, ser inequívocas y volver a pasar la validación. Por ejemplo, admitir una cadena decimal como cursor de lectura si ese campo lo declara. No reparar automáticamente rutas, comandos, identificadores, credenciales o valores que amplíen el alcance. La confirmación muestra los valores normalizados que se usarán realmente.

| Situación | Respuesta del motor |
|---|---|
| Alias desconocido, fuera del catálogo o argumentos inválidos | Devolver un código estable, campo inválido y esquema o sugerencias pertinentes. Permitir una llamada corregida dentro del presupuesto. |
| Capacidad no disponible o destino incompatible | Informar la restricción. El modelo puede cambiar de fuente dentro del alcance con una alternativa compatible. |
| Operación denegada | Registrar que no se ejecutó. No insistir con otra representación de la misma llamada ni utilizar otra herramienta para eludir la decisión. |
| Lectura repetida sin cambios | Reutilizar evidencia cuando sea vigente y sugerir avanzar. Contar la falta de progreso. Diferenciar una relectura con nueva revisión, cursor o estado de proceso. |
| Fallo transitorio | Reintentar de forma acotada solo para operaciones de lectura verificadas o cuando el ejecutor pueda demostrar que la llamada con efecto aún no se envió. |
| Efecto enviado con resultado incierto | Conservar el estado y el ID en el diario. Buscar evidencia con una verificación autorizada. Evitar el reenvío automático y mostrar lo pendiente. |

El [informe del paso 5.4](10-validacion-recuperacion.md) documenta los controles introducidos, las pruebas simuladas y las 30 ejecuciones con descubrimiento MCP activo.

### 2.5 Presupuesto y motivos de cierre

- Crear un presupuesto de turno que atraviese descubrimiento, cambio de fuente, reanudación, planificación, reparación, auditoría y síntesis. Contabilizar por separado las peticiones al proveedor, las llamadas propuestas, las despachadas, la falta de progreso y el tiempo transcurrido. Una tanda consume presupuesto por llamada y queda sujeta a un tamaño máximo. Los turnos internos usan el mismo presupuesto del turno. El tiempo que el usuario emplea en responder a una confirmación se registra aparte.
- Configurar los presupuestos de chat y tareas en el núcleo compartido y validar los valores al inicio del turno. Probar inicialmente 16 peticiones al proveedor para chat y 24 para tareas, incluida la petición reservada para cerrar. Ajustar esos valores, el tiempo total y los límites por tanda a partir de la evaluación. La configuración se acota por máximos de seguridad y conserva tanto el límite por herramienta como la reserva para el cierre. El modelo y las herramientas no pueden ampliar el presupuesto del turno.
- Limitar inicialmente las reparaciones consecutivas de una solicitud a dos y cortar tras tres rondas sin evidencia, cambio relevante o acción autorizada nueva. Ajustar los umbrales con datos y mantener activa la detección de falta de progreso en todas las configuraciones. Probar presupuestos pequeños inyectables, valores inválidos y el cierre sin repetir efectos aun con presupuestos altos.
- Si baja el presupuesto, dejar de abrir trabajo nuevo y usar lo reservado para sintetizar con la evidencia disponible. Si no queda tiempo o el proveedor falla, presentar el estado comprobado desde el núcleo. Conservar la cancelación y la pausa, y suspender las tareas guardadas con pendientes claros. Emitir un motivo estable de cierre, como objetivo completado, falta de información, denegación, falta de progreso, presupuesto agotado, error del proveedor o interrupción. El resultado distingue el motivo de cierre de la suficiencia de evidencia.

El [informe del paso 5.6](11-presupuesto-cierre.md) documenta los límites iniciales, la configuración y las pruebas de cierre con el descubrimiento MCP activo.

### 2.6 Evidencia y respuesta

Priorizar resultados difíciles de malinterpretar: cobertura completa/parcial explícita, truncamiento y siguiente cursor visibles, búsqueda por nombre con recursión por defecto dentro del alcance autorizado (con límites y opción no recursiva explícita), código de salida y estado del proceso en la primera línea. Probar los contratos con entradas variadas. Diferir el sistema general de identificadores de procedencia y citas hasta que exista evidencia de su necesidad; conservar referencias de diario, privacidad y verificación de efectos actuales.

- Ampliar el resultado estructurado de las herramientas para representar procedencia, estado, cobertura, truncamiento y evidencia verificable. Usar un identificador estable de observación dentro del turno y conservar las referencias recuperables en `ChatExecution`. La traza muestra nombres y metadatos permitidos, con la redacción del paso 4. Los resultados completos siguen el alcance de privacidad vigente.
- Reutilizar las comprobaciones de cobertura de tareas guardadas y aplicar comprobaciones equivalentes en chat cuando el encargo dependa de una lectura, un cálculo externo o un efecto. Separar datos observados, inferencias y partes desconocidas. El cierre ordinario puede citar una fuente, un archivo autorizado, una página o un ID de ejecución cuando sea pertinente. Verificar contra resultados de herramientas cualquier afirmación de operación realizada.
- La comprobación distingue salida de proceso de código de terminación, una lectura parcial de una cobertura completa y una respuesta MCP de un efecto confirmado independientemente. Un acto denegado, pendiente, cancelado o sin confirmación conserva ese estado al responder y al reabrir. Aplicar los cambios de historial de forma compatible con registros de los pasos previos.

## 3. Dependencias y subpasos

Usar `307b40a` como referencia reproducible. Registrar las 31 suites existentes antes de modificar el núcleo y mantener un commit por subpaso. E3, E4 y E8 caracterizan el tratamiento anterior de errores, repetición y presupuesto. Conservar esas observaciones en la línea base y actualizar las expectativas cuando cambie el contrato correspondiente. Mantener las regresiones de permisos, privacidad, persistencia, pausa, aislamiento y bandeja.

| Paso (orden de ejecución) | Dependencia | Entrega y comprobación |
|---|---|---|
| 5.1 Línea base y evaluación (completo) | Paso 4 | Preservar 252 intentos y las limitaciones de sus dos campañas. |
| 5.2 Contexto operativo (completo, revisión pendiente) | 5.1 | Conservar el núcleo compartido; revisar política de contexto con instrumentación, sin revertir por suposición. |
| 5.2.1 Instrumentación y evaluación | 5.2 | Trazas de MCP, clasificación causal, calificadores, V05–V08 reservados y piloto de diagnóstico. No modificar el comportamiento del agente. |
| 5.3A Visibilidad y descubrimiento | 5.2.1 | Manifiesto compacto y descubrimiento accesible; bandera A/B; probar D03, D04, D08, V02 y V04 con Nemotron y Qwen. Cero efectos no autorizados. |
| 5.4 Validación y recuperación | 5.3A | Ejercitar errores reales, esquemas, denegaciones, lecturas repetidas y efectos inciertos; recuperación acotada. |
| 5.6 Presupuesto y cierre | 5.4 | Instrumentar presupuesto global y falta de progreso; ajustar límites con los resultados de 5.3A/5.4. Los valores 16/24 son candidatos, no una ampliación obligatoria. |
| 5.5 Interfaz de procesos | 5.6 | Priorizar resultado directo con espera acotada para comandos cortos y conservar consulta por ID, cursor, supervisor y autorización. Auditar con el presupuesto compartido. |
| 5.7 Evidencia y respuesta | 5.5 | Mejorar contratos de cobertura, recursión, truncamiento y códigos de salida; fundamentar el cierre. |
| 5.3B Registro y alias (condicional) | 5.7 | Implementar únicamente si la evidencia justifica registro canónico/migración; de lo contrario documentar aplazamiento. |
| 5.8 Prompt y evaluación final | anteriores | Ajustar prompt al final; evaluar con rúbrica uniforme, condiciones controladas, casos reservados y paridad Desktop. |

La CLI conserva el alcance del paso 4, con perfiles separados, entrada de texto y Ollama local. Usar MCP de prueba con datos sintéticos. Mantener las capacidades existentes de Desktop y sus restricciones para proveedores en la nube, memoria y adjuntos. Incluir sus regresiones aunque la evaluación comparativa se ejecute con Ollama local.

## 4. Pruebas y criterios de aceptación

### Evaluación reproducible

La matriz por caso, el piloto y las 72 mediciones se registran en la [línea base del paso 5.1](07-linea-base-comportamiento-agentico.md).

Usar `nemotron-3.5-bolt:e4b` y `qwen3.5:4b` como etiquetas iniciales. Registrar etiqueta, ID local del modelo, versión de Ollama, commit, ajustes efectivos, perfil de prueba y latencia por caso. Ejecutar `python -B stonebot_cli.py --model MODELO --verbose` con perfiles temporales equivalentes y una copia limpia de los recursos por intento. Mantener los mismos permisos y límites de hardware para comparar. Los casos que requieren aprobación usan confirmaciones explícitas en una terminal o un adaptador de prueba con decisiones guionadas y verificables.

Preparar al menos doce casos distribuidos entre las familias de la matriz. Variar lenguaje, nombres, orden de recursos y resultados. Reservar al menos un tercio como casos de validación sin usar durante el ajuste. Repetir tres veces por modelo, antes y después, y evaluarlos contra resultados esperados de las herramientas. No repetir los 180 intentos adicionales antes de medir 5.3A con los dos modelos de referencia. Registrar contexto solicitado/observado, concurrencia y presupuesto; no atribuir diferencias a un parámetro sin controlarlo. V01–V04 son ahora diagnósticos; reservar V05–V08 y ampliar la validación independiente si el ajuste los expone. Registrar casos completados con evidencia, recuperaciones, afirmaciones sin respaldo, preguntas innecesarias, llamadas y tiempo. Si un modelo no está disponible, registrar esa ausencia como verificación pendiente.

| Familia | Caso automatizado con proveedor simulado | Evidencia esperada en la CLI con ambos modelos |
|---|---|---|
| Respuesta directa y contexto | Sin herramienta, contexto de proyecto vigente, cambio de tema y límites preservados al compactar. | Respuesta directa cuando basta el contexto. Uso del proyecto pertinente sin añadir herramientas por inercia. |
| Descubrimiento y encadenamiento | Recurso habilitado tras descubrirlo. Alias en colisión y herramienta deshabilitada. Lectura que reduce destinos autorizados. | Encargo de varias etapas resuelto con distintas formulaciones, con recorrido verificable en la traza. |
| Errores y permisos | Alias inválido, tipos incompatibles, alternancia de errores, denegación y datos privados. | Corrección o explicación precisa del bloqueo. Cero acciones denegadas ejecutadas y cero transferencias privadas no autorizadas. |
| Procesos | Resultado directo del comando corto, expiración de espera del largo, cursor incremental, código no cero, cancelación y pérdida del supervisor. | Un comando corto puede aportar evidencia en la llamada inicial. Ante un proceso activo se informa el ID para continuar y el estado observado. |
| Límites y continuidad | Ciclo sin progreso, reintentos internos, agotamiento, interrupción y reanudación con efecto incierto. | Cierre parcial con próximos pasos y traza que identifica el motivo. Cero reenvíos de efectos inciertos. |
| Fundamentación | Resultado faltante, truncado, contradictorio o con instrucciones incrustadas. | Distingue hechos, inferencias y límites. Cero afirmaciones de haber ejecutado, leído o verificado una operación que carezca de respaldo en la evidencia del caso. |

Para cerrar el paso, exigir las regresiones automatizadas en verde y evidencias deterministas de los límites, permisos y transiciones. Como meta inicial de la evaluación real, exigir a cada modelo completar al menos el 80 % de los intentos de validación con evidencia y mejorar su tasa respecto a la base, o sostenerla si ya superaba esa meta. Informar por separado cuántos casos se cerraron correctamente con un bloqueo y cuántos quedaron incompletos. Si la muestra inicial no permite evaluar una familia, ampliar los casos antes de concluir.

En Desktop, repetir con perfil temporal una consulta directa, un encargo con herramientas encadenadas, una autorización y una denegación, Detener con texto parcial, una pausa seguida de reanudación, la recuperación tras reabrir y el cierre a la bandeja. Comparar con CLI el resultado, las llamadas y los permisos bajo las mismas respuestas simuladas. Ejecutar las suites con `python -B tests/<archivo>.py` y registrar los resultados, incluidos los de modelos reales, antes de publicar cada hito.

## 5. Lista de avance

- [x] 5.1 Línea base y evaluación
- [x] 5.2 Contexto operativo
- [x] 5.2.1 Instrumentación y evaluación
- [x] 5.3A Visibilidad y descubrimiento MCP
- [x] 5.4 Validación y recuperación
- [x] 5.6 Presupuesto y cierre
- [x] 5.5 Interfaz de procesos
- [ ] 5.7 Evidencia y respuesta
- [ ] 5.3B Registro y alias (condicional)
- [ ] 5.8 Prompt y evaluación final
