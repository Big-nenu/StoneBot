# Plan del paso 4 · StoneBot CLI

- **Estado** — Implementado en cuatro subpasos.
- **Fecha** — 26 de noviembre de 2026.
- **Base** — `refactor/stonebot-core` en `bd351f4`, con los pasos 0 a 3 completos.
- **Objetivo** — Conversar y continuar tareas desde PowerShell o Windows Terminal con el mismo núcleo que usa StoneBot Desktop. La primera entrega usa Ollama local, texto y un perfil independiente.

## 1. Inventario de la implementación

| Componente | Estado actual | Trabajo del paso 4 |
|---|---|---|
| [`chat_session.py`](../chat_session.py) | Guarda mensajes, prepara el turno, construye el trabajador desde `TurnPlan` y aplica el resultado al historial. | Compartir también la apertura de chats y las decisiones de entrada y recuperación de tareas que siguen en la ventana. |
| [`app.py`](../app.py) | `enviar` decide el tratamiento de `/tarea`, `/reanudar`, `/cancelar` y los seguimientos ordinarios. `open_chat` y `render_chat` cargan el proyecto y recuperan tareas interrumpidas. | Extraer esas decisiones con pruebas de paridad. Los cuadros de diálogo, la edición visual y los controles de ventana siguen en Desktop. |
| [`turn_worker.py`](../turn_worker.py) y [`turn_events.py`](../turn_events.py) | `Worker.run()` ejecuta el motor y devuelve `TurnOutcome`. El adaptador recibe actividad, texto parcial y solicitudes de confirmación. | Implementar un adaptador de terminal con el mismo contrato. `stop()` cancela el turno y `request_pause()` solicita una pausa en los puntos de control existentes. |
| [`mcp_client.py`](../mcp_client.py) y [`stonebot_engine/safety.py`](../stonebot_engine/safety.py) | `data_path()` usa una raíz fija. Ajustes INI, historial, permisos y registros dependen de ella. La base experimental comparte la función de raíz y `stonebot_service.DB_PATH` se calcula al importar. | Separar la resolución del perfil de conversación de la raíz de la base experimental. Mantener la validación de rutas y el formato de `QSettings`. |
| [`stonewave_memory.py`](../stonewave_memory.py) y [`mcp_credentials.py`](../mcp_credentials.py) | StoneWave puede abrir su memoria personal por MCP. Las credenciales de Windows identifican el proveedor o servidor con claves que no incluyen el perfil. | Definir explícitamente qué conectores se habilitan en la CLI. Una carpeta independiente por sí sola no aísla estos accesos. |

## 2. Entrada y comandos

El punto de entrada propuesto es `stonebot_cli.py`. Se ejecuta desde la raíz del repositorio con Python 3.14 en Windows.

| Entrada | Resultado |
|---|---|
| `python -B stonebot_cli.py` | Abre un chat nuevo. La primera entrada válida crea el chat en el perfil de CLI. |
| `python -B stonebot_cli.py --chat ID` | Abre un chat existente y recupera el proyecto, los mensajes y el estado de la tarea. Un ID desconocido produce un error y no crea un chat. |
| `--model MODELO` | Selecciona un identificador de Ollama durante la invocación. Precedencia sobre el ajuste del perfil CLI y sin escribir en ningún INI. |
| `--verbose` | Emite eventos de evaluación en JSON por línea a stderr. La respuesta del chat conserva su salida habitual. |
| `python -B stonebot_cli.py --help` | Muestra la sintaxis y termina antes de crear el perfil o conectar con el proveedor. |
| `/ayuda`, `/chats`, `/abrir ID`, `/nuevo`, `/salir` | Ayuda, lista de conversaciones con ID y título, apertura, chat nuevo y salida. Son comandos de la terminal y quedan fuera del historial. |
| `/tarea OBJETIVO`, `/reanudar [ACLARACIÓN]`, `/cancelar` | Usan la validación y las transiciones compartidas con Desktop. Se aplica el límite de 4 000 caracteres del objetivo. `/cancelar` cierra la tarea mediante el historial y termina sin llamar al modelo. |
| Texto ordinario | Ejecuta un turno normal. Si hay una tarea pendiente, la sesión aplica las mismas reglas de seguimiento que Desktop. Un encargo del diario ordinario se retoma con lenguaje natural y el mecanismo actual del motor. |
| `Ctrl+C` | En chat, detiene el turno y conserva el texto parcial según `ChatSession`. En una tarea, solicita pausa. En el prompt de permisos equivale a denegar y aplicar la interrupción correspondiente. |
| Fin de entrada en Windows | `Ctrl+Z` seguido de Enter en el prompt principal cierra la sesión. Durante una confirmación se trata como denegación. |

La ayuda identifica los comandos disponibles. Una entrada que comience con un comando de barra desconocido muestra un aviso local. `/salir`, EOF en el prompt principal y `--help` terminan con código 0. Los fallos de arranque devuelven 1 y `argparse` devuelve 2 si los argumentos son inválidos. La primera entrega difiere el modo por lotes, los adjuntos, la edición y regeneración desde terminal, la gestión de proyectos, la instalación de MCP desde chat, OpenRouter y la integración con StoneWave. Al reabrir un chat vinculado a un proyecto del perfil de CLI se conserva el contexto existente. La sesión permite elegir la política de título inicial. La CLI obtiene el título del primer mensaje con la lógica local de `History.append` y Desktop sigue usando la generación de títulos actual.

## 3. Perfil y permisos

### Perfil de conversación

- Usar `%USERPROFILE%\.stonebot-cli` por defecto y aceptar `STONEBOT_HOME` solo al iniciar la CLI. Resolver la raíz efectiva una sola vez por proceso, antes de construir `History`, leer ajustes o abrir conexiones. Un valor presente e inválido provoca un error de inicio. Desktop mantiene su raíz habitual `%USERPROFILE%\.stonebot`. La CLI experimental conserva su entrada y su propia raíz.
- Mantener un único resolvedor para `data_path()` y el mismo `check_path()` para las rutas derivadas. Exigir una ruta absoluta local. Rechazar raíces protegidas, unidades remotas, rutas redirigidas y solapamientos por igualdad, ascendencia o descendencia con el perfil Desktop o con rutas protegidas de StoneWave. Comprobar rutas declaradas y destinos resueltos, incluidos junctions, enlaces duros de archivos y auxiliares de SQLite. Crear la carpeta después de validar la ruta.
- Almacenar en esa raíz el historial y su diario, tareas, ajustes INI, identidad, experiencias, diagnósticos, Skills del perfil, configuración y permisos MCP y registros de procesos. Un perfil nuevo se inicia vacío. No importar preferencias, conversaciones ni permisos de Desktop. Proteger ambos perfiles y las rutas personales mediante las validaciones de los lectores y escritores existentes cuando la petición venga del modelo.
- Adquirir `assistant.lock` con `QLockFile` por perfil, antes de abrir el historial. Reutilizar la política actual de bloqueo de Desktop. Un segundo proceso sobre el mismo perfil sale con error y sin escribir. Perfiles distintos pueden funcionar al mismo tiempo. Liberar el bloqueo después de finalizar el turno y cerrar las conexiones. `QtCore` sigue disponible para `QSettings` y el bloqueo. La CLI se ejecuta sin `QCoreApplication`, `QApplication` ni módulos gráficos.

### Permisos y clientes

- El perfil de CLI arranca con Ollama local. Antes del primer turno del proceso, se comprueba en Ollama que el modelo seleccionado esté instalado y sea local. Si sus ajustes seleccionan un proveedor fuera del alcance inicial, informar y terminar antes de contactar con él. La construcción de la sesión omite el cliente de StoneWave y el proceso no importa `stonebot_service`. Probar incluso con variables de StoneWave y credenciales de Desktop presentes.
- Una CLI nueva no trae servidores MCP habilitados. Para las pruebas y el uso inicial, provisionar la configuración explícitamente con los validadores existentes y dentro de la raíz de CLI. Resolver referencias de autenticación únicamente desde variables declaradas para el servidor en ese proceso. Impedir que el cliente consulte credenciales persistentes de Desktop para la CLI. No almacenar valores de tokens ni añadir un instalador de servidores.
- `CliTurnEvents.confirm(request)` recibe el diccionario existente, muestra la operación y los argumentos autorizables, con datos sensibles redactados, y admite **permitir una vez** o **denegar**. Solo una respuesta afirmativa explícita concede el permiso. Entrada vacía, negativa, EOF o falta de terminal interactiva deniegan. `remember` queda en `False` en este adaptador. Se siguen aplicando las autorizaciones y validaciones del perfil y de cada herramienta que el núcleo ya hace antes de llamar al adaptador.
- La CLI no interpreta una entrada como comando de shell. Las herramientas que StoneBot ya ofrece conservan sus controles de privacidad, alcance y autorización. La separación de perfiles delimita los datos internos de StoneBot. Un servidor MCP o programa externo autorizado mantiene los permisos que Windows le da al ejecutarlo.
- Usar `is_setup_request()` para detectar las solicitudes de instalación MCP que Desktop intercepta antes de construir el turno. La terminal responde con el aviso de alcance de la CLI y se queda en el prompt.
- Mientras hay un turno activo, un único lector del terminal atiende las confirmaciones. Ejecutar `Worker.run()` en un hilo de trabajo y pasar los eventos y solicitudes al hilo principal por una cola. El principal responde al pedido de autorización con el mismo diccionario y notifica al trabajador. Al interrumpir o salir, resolver las confirmaciones pendientes por denegación, esperar a que el trabajador termine y cerrar `McpPool`. Una solicitud de pausa no se anuncia como concluida hasta recibir el resultado del motor.

### Evaluación del agente

La traza usa un observador opcional en el motor. Registra rondas y peticiones al proveedor con los nombres de herramientas ofrecidas, las llamadas propuestas con sus argumentos, los resultados del ejecutor y el motivo de cierre. Incluye los reintentos al proveedor y distingue las llamadas propuestas de las ejecutadas, reutilizadas, denegadas u omitidas. El adaptador no reconstruye decisiones del motor.

Serializar únicamente datos de la traza, sin prompt, razonamiento, conversación, credenciales o contenido privado. Mostrar nombres, forma de argumentos y resultados, campos operativos seguros y longitudes. Ocultar por defecto texto libre de argumentos y resultados, incluidos rutas y salida de procesos. La traza es optativa y no se persiste.

## 4. Subpasos y commits

Línea base verificada en `42e28a3` con **29 suites** aprobadas antes del primer cambio de código. Mantener un commit por subpaso y validar todas las suites en cada uno.

| Subpaso | Alcance | Prueba que debe pasar | Commit |
|---|---|---|---|
| 4.1 | Añadir la selección de perfil a nivel de conversación. Hacer que `data_path()` use esa raíz y compartir la apertura del bloqueo. Mantener la base experimental y el perfil habitual en sus rutas vigentes. | Raíz por defecto, personalizada e inválida. Dos procesos en perfiles distintos. Rechazo del segundo escritor y de rutas protegidas o redirigidas. | `Isolate CLI conversation profiles` |
| 4.2 | Extraer a `ChatSession` la carga y recuperación de chats y las decisiones compartidas de entrada para tareas. Mantener las acciones visuales y el tratamiento de adjuntos en Desktop. Conservar la señalización de errores y el orden entre guardar y ejecutar. | Crear, reabrir, reanudar, cancelar y seguir una tarea con casos de paridad. Si falla el guardado del estado de la tarea, no lanzar el turno. | `Share chat opening and task input handling` |
| 4.3 | Implementar `CliTurnEvents`, el ciclo de ejecución en terminal y el arranque con Ollama, memoria personal desactivada y política de credenciales por perfil. Conectar el observador opcional a las rutas reales del motor. | Aprueba una vez y deniega contra un servidor de prueba. Cancelación con texto parcial, pausa, EOF durante permiso, cierre de conexiones y ausencia de accesos al perfil personal. | `Run shared StoneBot turns in the terminal` |
| 4.4 | Completar el punto de entrada, los comandos de navegación, `--model`, `--verbose` y la ayuda. Pasar los mensajes por `save_message`, `begin_turn`, el mismo `Worker` y `complete_turn`. Documentar el uso en README. | Abrir otra vez un chat desde un segundo proceso, continuar una tarea y recuperar un encargo interrumpido. Prueba manual de terminal y regresión de Desktop. | `Add StoneBot CLI chat commands and documentation` |

## 5. Matriz de verificación y salida

| Caso | Criterio observable |
|---|---|
| C1 · Núcleo compartido | El chat normal y las tareas usan `ChatSession`, `TurnPlan` y `Worker` desde ambos adaptadores. S1–S8 y E1–E9 siguen en verde. Verificar el importado y ejecutar la CLI sin módulos gráficos de Qt ni `app`. |
| C2 · Persistencia | Dos procesos consecutivos abren el mismo ID de CLI y recuperan mensajes, proyecto, tarea y diario. Un efecto pendiente se conserva tras reabrir y se aplican las reglas actuales de reanudación. Un ID inexistente y los comandos locales no alteran el historial. |
| C3 · Perfil | Usar raíces temporales distintas para Desktop y CLI. Colocar marcadores en la raíz de Desktop y la memoria experimental. Verificar que la CLI no lee ni modifica esos marcadores, todos sus archivos internos quedan en la raíz elegida y un segundo escritor termina sin tocar el historial. Probar una junction en Windows y los auxiliares de SQLite. |
| C4 · Permisos | Un servidor MCP local simulado registra cero ejecuciones ante denegación, EOF o confirmación no interactiva y una ante aprobación. La siguiente solicitud vuelve a preguntar. Los dobles fallan si la CLI intenta leer credenciales de Windows o abrir StoneWave. Los datos sensibles no aparecen en salida ni diagnósticos. |
| C5 · Interrupción | Verificar chat con y sin texto parcial, interrupción en confirmación y pausa de tarea. La aplicación vuelve al prompt tras cerrar el turno. Una tarea pausada puede reanudarse desde otra invocación. El cierre libera el bloqueo y termina las conexiones. |
| C7 · Evaluación | Un proveedor simulado verifica modelo explícito, precedencia y ausencia de escritura de ajustes. Comparar turnos con y sin traza y comprobar catálogo, llamadas, argumentos redactados, resultados, rondas y motivos. Un secreto sintético nunca llega a la traza. |
| C6 · Windows | Probar una conversación con Ollama local en un perfil desechable. Recorrer `/chats`, `/abrir`, `/nuevo` y `/salir`. Confirmar el comportamiento real de Ctrl+C y fin de entrada en terminal. Repetir en Desktop la prueba de bandeja y salida y comprobar que sigue funcionando junto a la CLI con su perfil propio. |

Añadir `tests/test_cli_profile.py` para C3 y `tests/test_stonebot_cli.py` para C1, C2, C4 y C5. Extender `tests/test_chat_session.py` con la paridad de apertura, recuperación y enrutamiento de tareas. Ejecutar cada archivo con `python -B tests/<archivo>.py`. Usar bases temporales, respuestas simuladas, subprocesos para el arranque y un servidor local de prueba para los permisos. La comprobación con Ollama real se hace aparte de la suite automatizada. Registrar por subpaso comandos, resultados y cualquier caso pendiente en este documento. Revisar el estado de Git y publicar los commits de la implementación tras la validación.

### Resultados de verificación

- Línea base de 29 suites. Pasaron 30 suites en 4.1, 4.2 y 4.3, y 31 al incorporar las pruebas del punto de entrada en 4.4.
- El proveedor simulado verificó la precedencia de `--model` y la conservación del INI. El servidor MCP de prueba verificó aprobación, denegación, EOF y entrada no interactiva. La traza registró el cierre por repetición y ocultó el texto sintético de argumentos y resultados.
- En Windows se ejecutó Ollama con `nemotron-3.5-bolt:e4b` en un perfil temporal. Se recorrieron `/chats`, `/abrir`, `/nuevo` y `/salir`, y una segunda invocación recuperó la respuesta. Ctrl+C devolvió el prompt de una consola nativa durante un turno simulado. Ctrl+Z seguido de Enter cerró la terminal de StoneBot con código 0. La prueba nativa de bandeja verificó ocultar la ventana, reabrirla y salir durante un turno.
- La recuperación simulada desde la CLI conservó el identificador del diario original y el efecto sin confirmar. Se verificó la bandeja nativa de Desktop mientras la CLI mantenía abierto otro perfil, además del rechazo de un segundo escritor en el mismo perfil.

## 6. Alcance del siguiente paso

El paso 5 conserva las decisiones sobre enrutamiento, selección de herramientas, reintentos, presupuesto, instrucciones y comportamiento del agente. Este paso solo incorpora una entrada al motor compartido.

## 7. Lista de avance

- [x] 4.1 Perfil de conversación y bloqueo
- [x] 4.2 Apertura y entrada de tareas compartidas
- [x] 4.3 Adaptador de terminal y permisos
- [x] 4.4 Comandos, documentación y verificación de aceptación
