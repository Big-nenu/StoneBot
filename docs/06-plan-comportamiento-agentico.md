# Plan del paso 5 · Comportamiento agéntico de StoneBot

- **Estado** — Plan aprobado. Pasos 5.1 y 5.2 completados.
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

## 2. Diseño del núcleo compartido

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

- Definir un registro de herramientas con identificador canónico, alias de presentación, familia, descripción, esquema, proveedor o servidor, requisitos de disponibilidad, clase de efecto, política de confirmación y clasificación de entrada y salida. Reutilizar los ejecutores existentes. Mantener una distinción verificable entre herramienta registrada, habilitada, ofrecida y autorizada para la llamada concreta.
- Ofrecer un conjunto inicial acotado de herramientas nativas y un mecanismo para descubrir herramientas habilitadas por capacidad y fuente, con resultados paginados o limitados. Descubrir servidores bajo demanda con `McpPool` y su caché. Una búsqueda puede sugerir una herramienta y ofrecerla en la ronda siguiente si es compatible. Descubrir, cargar una Skill y elegir una fuente nunca conceden un permiso.
- Usar las reglas de intención actuales como pistas para ordenar candidatos y conservar los controles explícitos del usuario. Los recursos habilitados podrán encontrarse ante distintas formulaciones. Reevaluar relevancia por ronda y conservar las exclusiones de seguridad aplicables durante todo el turno. Tras leer datos privados, impedir que esos datos o su contexto lleguen a destinos incompatibles. Las tandas vuelven a validar permisos y privacidad por llamada, incluso si la herramienta se ofreció al inicio.
- Probar alias breves y deterministas, acotados al catálogo, con detección de colisiones entre nativas y servidores. En permisos, efectos, caché, recuperación y diario usar la identidad canónica. Leer alias anteriores y migrar límites persistidos de forma conservadora. Si una identidad antigua no se puede resolver con seguridad, pedir una nueva selección en vez de ampliar el alcance o repetir un efecto.

### 2.3 Terminal y procesos gestionados

- Probar dos operaciones de cara al modelo. **Ejecutar** recibe un programa y una lista de argumentos. **Gestionar ejecución** consulta el estado, lista ejecuciones del chat o solicita cancelar por ID. Traducir ambas a `process_tools.py` y conservar las identidades históricas de lanzamiento, consulta y cancelación. Mantener el supervisor, el diario, los cursores y el aislamiento por chat, perfil y alcance.
- Aceptar una ruta absoluta o un nombre de ejecutable que se resuelva de forma determinista contra una lista explícita de ubicaciones confiables. Un nombre ambiguo o ausente devuelve un error corregible. Usar el directorio vinculado al proyecto solo si existe y está autorizado para esa operación. En los demás casos se exige un directorio explícito. Confirmar el ejecutable resuelto, los argumentos exactos y el directorio antes de lanzar. No interpretar cadenas como comandos de shell ni convertir automáticamente listas, redirecciones o tuberías en comandos. Mantener los controles de autorización y las restricciones actuales de procesos y archivos.
- Después del lanzamiento autorizado, esperar durante una ventana corta, limitada por el tiempo restante del turno. Si el supervisor confirma que el comando terminó en esa ventana, devolver directamente su salida acotada, el estado y el código de terminación en la misma llamada. El diario conserva el ID y contabiliza el cursor de la salida entregada. Si vence la espera, devolver el ID y el estado observado para consultar la ejecución larga por separado. La espera no cancela el proceso ni habilita otro lanzamiento.
- Cada resultado distingue entre inicio confirmado, ejecución activa, salida parcial o truncada, terminación con código, cancelación solicitada y estado sin confirmar. Consultar por ID también admite una espera breve y acotada. Si el proceso sigue activo al cerrar el turno, informar su ID y el estado conocido. Tras una interrupción, comprobar el ID existente antes de considerar un nuevo lanzamiento. Cancelar sigue siendo una operación con efecto y confirmación.

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

### 2.5 Presupuesto y motivos de cierre

- Crear un presupuesto de turno que atraviese descubrimiento, cambio de fuente, reanudación, planificación, reparación, auditoría y síntesis. Contabilizar por separado las peticiones al proveedor, las llamadas propuestas, las despachadas, la falta de progreso y el tiempo transcurrido. Una tanda consume presupuesto por llamada y queda sujeta a un tamaño máximo. Los turnos internos usan el mismo presupuesto del turno. El tiempo que el usuario emplea en responder a una confirmación se registra aparte.
- Configurar los presupuestos de chat y tareas en el núcleo compartido y validar los valores al inicio del turno. Probar inicialmente 16 peticiones al proveedor para chat y 24 para tareas, incluida la petición reservada para cerrar. Ajustar esos valores, el tiempo total y los límites por tanda a partir de la evaluación. La configuración se acota por máximos de seguridad y conserva tanto el límite por herramienta como la reserva para el cierre. El modelo y las herramientas no pueden ampliar el presupuesto del turno.
- Limitar inicialmente las reparaciones consecutivas de una solicitud a dos y cortar tras tres rondas sin evidencia, cambio relevante o acción autorizada nueva. Ajustar los umbrales con datos y mantener activa la detección de falta de progreso en todas las configuraciones. Probar presupuestos pequeños inyectables, valores inválidos y el cierre sin repetir efectos aun con presupuestos altos.
- Si baja el presupuesto, dejar de abrir trabajo nuevo y usar lo reservado para sintetizar con la evidencia disponible. Si no queda tiempo o el proveedor falla, presentar el estado comprobado desde el núcleo. Conservar la cancelación y la pausa, y suspender las tareas guardadas con pendientes claros. Emitir un motivo estable de cierre, como objetivo completado, falta de información, denegación, falta de progreso, presupuesto agotado, error del proveedor o interrupción. El resultado distingue el motivo de cierre de la suficiencia de evidencia.

### 2.6 Evidencia y respuesta

- Ampliar el resultado estructurado de las herramientas para representar procedencia, estado, cobertura, truncamiento y evidencia verificable. Usar un identificador estable de observación dentro del turno y conservar las referencias recuperables en `ChatExecution`. La traza muestra nombres y metadatos permitidos, con la redacción del paso 4. Los resultados completos siguen el alcance de privacidad vigente.
- Reutilizar las comprobaciones de cobertura de tareas guardadas y aplicar comprobaciones equivalentes en chat cuando el encargo dependa de una lectura, un cálculo externo o un efecto. Separar datos observados, inferencias y partes desconocidas. El cierre ordinario puede citar una fuente, un archivo autorizado, una página o un ID de ejecución cuando sea pertinente. Verificar contra resultados de herramientas cualquier afirmación de operación realizada.
- La comprobación distingue salida de proceso de código de terminación, una lectura parcial de una cobertura completa y una respuesta MCP de un efecto confirmado independientemente. Un acto denegado, pendiente, cancelado o sin confirmación conserva ese estado al responder y al reabrir. Aplicar los cambios de historial de forma compatible con registros de los pasos previos.

## 3. Dependencias y subpasos

Usar `307b40a` como referencia reproducible. Registrar las 31 suites existentes antes de modificar el núcleo y mantener un commit por subpaso. E3, E4 y E8 caracterizan el tratamiento anterior de errores, repetición y presupuesto. Conservar esas observaciones en la línea base y actualizar las expectativas cuando cambie el contrato correspondiente. Mantener las regresiones de permisos, privacidad, persistencia, pausa, aislamiento y bandeja.

| Paso | Dependencia | Entrega y comprobación |
|---|---|---|
| 5.1 Línea base y evaluación | Paso 4 | Congelar casos, datos, criterios y traza de referencia. Confirmar que ambos modelos corren desde la CLI. Registrar el resultado de las suites y las limitaciones observadas. |
| 5.2 Contexto operativo | 5.1 | Construir el contexto en la sesión y probar límites, alcance de proyecto, roles, compactación y recuperación. |
| 5.3 Catálogo y descubrimiento | 5.2 | Registrar y resolver herramientas habilitadas, alias e identidades históricas. Probar colisiones, descubrimiento bajo demanda, cambio de fuente y conservación de fronteras de privacidad. |
| 5.4 Validación y recuperación | 5.3 | Validar llamadas, devolver errores estructurados y aplicar recuperación acotada. Probar datos inválidos, denegaciones, reintentos, duplicados y reinicio con efectos inciertos. |
| 5.5 Interfaz de procesos | 5.3, 5.4 | Simplificar ejecutores visibles y preservar los registros existentes. Probar resultado directo de comandos cortos con código cero o distinto de cero, vuelta por ID al vencer la espera, cursor incremental, autorización exacta, cancelación y recuperación en Windows. |
| 5.6 Presupuesto y cierre | 5.4, 5.5 | Contar peticiones de todas las ramas, validar la configuración y reservar el cierre. Probar que ninguna transición reinicia el contador, que pausa y cancelación se respetan y que un presupuesto alto sigue terminando ante falta de progreso. |
| 5.7 Evidencia y respuesta | 5.4, 5.6 | Vincular cobertura y resultados con el cierre. Probar evidencia parcial, falta de fuentes, resultados contradictorios, estados de efectos y reanudación. |
| 5.8 Prompt y evaluación final | 5.1–5.7 | Ajustar el prompt después de medir el núcleo con el anterior. Ejecutar la matriz con ambos modelos y la verificación de paridad de Desktop. Actualizar README y registrar resultados. |

La CLI conserva el alcance del paso 4, con perfiles separados, entrada de texto y Ollama local. Usar MCP de prueba con datos sintéticos. Mantener las capacidades existentes de Desktop y sus restricciones para proveedores en la nube, memoria y adjuntos. Incluir sus regresiones aunque la evaluación comparativa se ejecute con Ollama local.

## 4. Pruebas y criterios de aceptación

### Evaluación reproducible

La matriz por caso, el piloto y las 72 mediciones se registran en la [línea base del paso 5.1](07-linea-base-comportamiento-agentico.md).

Usar `nemotron-3.5-bolt:e4b` y `qwen3.5:4b` como etiquetas iniciales. Registrar etiqueta, ID local del modelo, versión de Ollama, commit, ajustes efectivos, perfil de prueba y latencia por caso. Ejecutar `python -B stonebot_cli.py --model MODELO --verbose` con perfiles temporales equivalentes y una copia limpia de los recursos por intento. Mantener los mismos permisos y límites de hardware para comparar. Los casos que requieren aprobación usan confirmaciones explícitas en una terminal o un adaptador de prueba con decisiones guionadas y verificables.

Preparar al menos doce casos distribuidos entre las familias de la matriz. Variar lenguaje, nombres, orden de recursos y resultados. Reservar al menos un tercio como casos de validación sin usar durante el ajuste. Repetir tres veces por modelo, antes y después, y evaluarlos contra resultados esperados de las herramientas. Registrar casos completados con evidencia, recuperaciones, afirmaciones sin respaldo, preguntas innecesarias, llamadas y tiempo. Si un modelo no está disponible, registrar esa ausencia como verificación pendiente.

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
- [ ] 5.3 Catálogo y descubrimiento
- [ ] 5.4 Validación y recuperación
- [ ] 5.5 Interfaz de procesos
- [ ] 5.6 Presupuesto y cierre
- [ ] 5.7 Evidencia y respuesta
- [ ] 5.8 Prompt y evaluación final
