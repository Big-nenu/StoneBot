# Plan: separar el núcleo de StoneBot de la interfaz PySide6

**Estado:** paso 0 completado. La separación del núcleo está pendiente.
**Fecha:** 26 de noviembre de 2026
**Rama base:** `codex/stonebot-tool-loop` en el commit `094c387`
**Rama de trabajo aprobada:** `refactor/stonebot-core`, creada en `ad09042`.
**Alcance:** pasos 0 a 3. La CLI (paso 4) y las correcciones del comportamiento del agente (paso 5) quedan para después.

## 1. Objetivo

Que el motor del agente (el turno, las herramientas, los permisos, el registro de ejecución) funcione **sin PySide6** y **sin ventana**, para poder:

1. Probarlo sin `QApplication`.
2. Usarlo después desde una CLI.
3. Corregir el comportamiento del agente en un solo lugar.

La interfaz actual se conserva. Escritorio y CLI deben usar **el mismo motor**. No se acepta un segundo motor ni duplicar funciones.

## 2. Por qué (resumen de la comparación con Hermes Agent)

Se comparó StoneBot con `NousResearch/hermes-agent` (commit `93dd2a4e`). Las deficiencias que se corregirán **después** de este plan, ya dentro del motor separado:

1. Una regex decide qué herramientas existen en cada turno (`request_routing.py`, `turn_worker.py` `chat_with_tools`, línea ~1093). Si no coincide, el modelo solo ve `elegir_fuente`.
2. El catálogo se estrecha sin vuelta atrás durante el turno (`limit_tools`, `before_call`, `turn_worker.py` ~1470 y ~1910). Tras cargar una Skill solo hay lecturas.
3. Solo 6 rondas por turno en chat y 12 en tareas (`turn_worker.py:1397`). Hermes permite hasta 500.
4. Un nombre de herramienta inválido o un argumento mal tipado no se repara (`tool_loop.py`). Una llamada repetida cierra el turno y quita las herramientas.
5. El prompt `SYSTEM` (en `turn_worker.py`) pide no mencionar herramientas y responder breve. Falta "termina el trabajo".
6. Los nombres MCP son largos: `mcp_{servidor}_{slug}_{sufijo}` (`mcp_client.py:183`).
7. El agente es un modo (`/tarea`), no el comportamiento por defecto.

Hermes midió Nemotron y el bloque de prompt "tool-use enforcement" movió menos de 1 punto (`agent/prompt_builder.py:358`). La palanca es el arnés (catálogo, errores, presupuesto), no solo el prompt.

Para reclonar Hermes: `git clone --depth 1 https://github.com/NousResearch/hermes-agent.git` y revisar `agent/turn_tool_validation.py`, `agent/tool_guardrails.py`, `tools/arg_coercion.py`, `agent/iteration_budget.py`.

## 3. Reglas del plan

1. **No mezclar refactor con cambios de comportamiento.** Cada commit mueve código; no cambia lo que hace.
2. **Un solo motor.** Escritorio y CLI serán adaptadores delgados.
3. **Las pruebas existentes (27 archivos en `tests/`) deben seguir en verde en cada commit.**
4. **Se conservan los nombres** `turn_worker`, `Worker`, `Client`, etc. Las pruebas los parchean con `patch.object(turn_worker, ...)`. Un parche solo funciona donde el nombre se busca.
5. **No se reorganizan carpetas.** El repo es plano y así sigue.
6. **Commits pequeños,** uno por subpaso, con la prueba que lo valida.
7. Se siguen las reglas de `AGENTS.md`: `python -B`, actualizar `README.md` ("Dónde buscar cuando quieras cambiar algo", línea ~409) cuando cambie la ubicación del código, `git status`, commit y `git push`.

## 4. Inventario del acoplamiento con Qt

Medido en `094c387`. El motor ya corre con `asyncio` dentro de un `QThread`.

| Punto | Dónde | Detalle | Dificultad |
|---|---|---|---|
| `Worker(QObject)` y 12 señales | `turn_worker.py:158-170` | `activity` 46 usos, `mcp_notice` 27, `finished` 3, `reasoning` 2, `mcp_confirmation` 2, `operation_error` 2, `interrupted_reply` 2, `cancelled` 2, `error` 2, `partial` 1, `task_started` 1, `continuity_saved` 1 | Baja |
| Pausa de tareas | `turn_worker.py:514`, `722`, `739`, `809` | `QThread.currentThread().isInterruptionRequested()` | Baja |
| Confirmación de permisos | `turn_worker.py` `confirm_external` (~2185) y `app.py:1666` | Señal bloqueante `BlockingQueuedConnection`; el diálogo escribe en el `dict` de la petición | Baja |
| Armado del turno | `app.py:1577-1673` (`start_turn`) | Mezcla UI con lógica: instrucciones, contexto de proyecto, `ChatExecution`, vínculo con historial | **Media** |
| Cierre del turno | `app.py:1783-1830` (`respuesta`, `error`) y `app.py:889` (`save_message`) | Efectos sin confirmar, `finish_execution`, tarea pausada, regeneración | **Media** |
| `QSettings` | `ai_provider.py`, `chat_preferences.py`, `greetings.py`, `local_files.py`, `stonewave_memory.py` | Solo `QtCore`; no necesita pantalla | Baja, **se difiere** |
| `QtGui` / `QtPdf` | `attachments.py` | Solo adjuntos visuales; `turn_worker.py` importa 8 nombres de ahí | Baja |

Ya están libres de Qt: `history.py`, `tool_loop.py`, `chat_execution.py`, `mcp_client.py`, `mcp_pool.py`, `mcp_permissions.py`, `process_tools.py`, `managed_process.py`, `read_tools.py`, `tasks.py`, `request_routing.py`.

Estado de la ventana que usan las pruebas y que hay que conservar: `window.thread` (24 usos), `window.chat_id` (26), `window.task` (7), `window.messages` (5), `window.project` (5).

## 5. Paso 0: preparación

**0.1 Crear la rama.**

Se verificó la rama existente `refactor/stonebot-core` en `ad09042`, con el árbol de trabajo limpio al iniciar el paso 0.

**0.2 Línea base de pruebas.** Antes de tocar nada, ejecutar cada prueba y anotar el resultado en el apéndice A.

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:QT_QPA_PLATFORM = 'offscreen'
Get-ChildItem tests\test_*.py | ForEach-Object { python -B $_.FullName; "$($_.Name): exit $LASTEXITCODE" }
```

Las pruebas usan un perfil temporal (`patch.object(mcp_client, "default_root", ...)`), no `~/.stonebot`. Si alguna ya falla en la base, se documenta y se deja fuera de la regla "en verde".

**0.3 Higiene de `__pycache__`.** Se aprobó agregar `.gitignore` y retirar del índice los 59 archivos `.pyc` con `git rm --cached`, conservando las copias locales. La limpieza se registra en un commit separado.

**Criterio de salida:** rama creada, apéndice A completo, decisión sobre `.pyc` anotada.

## 6. Paso 1: pruebas del motor sin Qt (red de seguridad)

**Qué se hace:** escribir pruebas que ejecuten `Worker` sin ventana, **antes** de cambiarlo. Describen el comportamiento actual; no lo mejoran.

**Archivos nuevos** (solo pruebas):

- `tests/engine_harness.py`: utilidades compartidas.
- `tests/test_engine_headless.py`: los escenarios.

**Reglas de las pruebas:**

- No importan `app`. No crean `QApplication` ni importan `QtWidgets`.
- Parchean lo mismo que `tests/test_chat_execution.py`: `mcp_client.default_root` (perfil temporal), `turn_worker.Client` (modelo simulado con `SimpleNamespace(chat=model)`), `turn_worker.ollama_model_is_local`, `turn_worker.automatic_memory_enabled` y `Worker.enabled_skills`.
- No importar `stonebot_service` en el arnés: calcula `DB_PATH` al importarse (`stonebot_service.py:28`).
- El modelo simulado usa el ayudante `call(name, **args)` de `tests/test_chat_execution.py:25`.

**Arnés:**

- `FakeModel`: lista de respuestas guiadas (texto o llamada a herramienta).
- `EventRecorder`: guarda `(canal, texto)` en orden. En este paso se conecta a las señales del `Worker`; en el paso 2 se conecta a `TurnEvents`.
- Se ejecuta `worker.run()` directo en el hilo de la prueba. Las señales con conexión directa funcionan sin bucle de eventos. `mcp_confirmation` se conecta a una función que pone `request["approved"] = True` o `False`.
- **Verificar al empezar:** que `Worker` se pueda instanciar sin `QCoreApplication`. Si no, crear solo `QCoreApplication([])` (no `QApplication`).

**Escenarios:**

| Id | Escenario | Se afirma |
|---|---|---|
| E1 | El modelo responde sin herramientas | `finished` con el texto; sin `error` |
| E2 | Una lectura de proyecto (`read_project_file`) y luego respuesta | La herramienta se ejecuta una vez; el resultado vuelve al modelo; `finished` |
| E3 | El modelo pide una herramienta inexistente | El resultado "Herramienta desconocida o no disponible…" vuelve al modelo; el turno sigue |
| E4 | El modelo repite la misma llamada | Se emite el aviso de repetición y el turno cierra sin herramientas |
| E5 | Permiso denegado (`approved = False`) en una herramienta de proceso | La herramienta no se ejecuta; el modelo recibe el resultado |
| E6 | `worker.stop()` durante la espera del modelo | `cancelled` e `interrupted_reply` con el texto parcial |
| E7 | El proveedor lanza `ResponseError` | `error` con mensaje; sin `finished` |
| E8 | El modelo pide herramientas más de 6 rondas | `TurnError` del límite de llamadas |

La pausa de tareas (E9) ya está cubierta por `tests/test_tasks.py`. Se agrega al arnés en el paso 2, cuando la pausa deje de depender de `QThread`.

**Qué se compara:** el orden de los eventos y los nombres de herramientas, no el texto exacto de la interfaz. El texto está en español y cambia.

**Comprobación de utilidad:** romper a propósito algo pequeño (por ejemplo, quitar la comprobación de herramienta repetida) y confirmar que la prueba correspondiente falla. Revertir.

**Commit:** `Add headless engine characterization tests`

**Criterio de salida:**

- Las pruebas nuevas pasan en la rama actual, sin `QApplication` y sin importar `app`.
- El resto de `tests/` sigue igual que en el apéndice A.

## 7. Paso 2: eventos y confirmación fuera de Qt

**Qué se hace:** `Worker` deja de ser `QObject`. Sigue llamándose `Worker` y sigue en `turn_worker.py`, pero habla con la interfaz a través de un objeto de eventos. Un adaptador de Qt lo conecta a la ventana.

**Diseño:**

- `turn_events.py` (sin Qt):
  - `TurnEvents`: `activity(text)`, `notice(text)`, `reasoning(text)`, `partial(text)`, `operation_error(text)`, `task_started(task)`, `continuity_saved(project_id, text)` y `async confirm(request)`.
  - `NullEvents` (no hace nada) y `RecordingEvents` (para pruebas).
  - `TurnOutcome`: `kind` (`finished`, `cancelled`, `error`), `text` y `partial_text`.
- `confirm(request)` conserva el contrato actual: el `dict` se modifica con `approved` y `remember`. Así no cambia la lógica de permisos.
- `finished`, `cancelled`, `error` e `interrupted_reply` dejan de ser eventos: `Worker.run()` devuelve un `TurnOutcome`.
- La pausa de tareas usa `self.pause_requested = threading.Event()` y un método `request_pause()`. Desaparece el parámetro `thread` de `check_pause`.
- `qt_turn_runner.py` (con Qt): `QtTurnRunner(QObject)` crea y gestiona el `QThread`, implementa `TurnEvents` con señales y emite `finished`, `error`, `cancelled` e `interrupted_reply` a partir del `TurnOutcome`. Usa **los mismos nombres de señal** que hoy tiene `Worker`, para que las líneas `connect` de `app.py:1658-1671` casi no cambien. Para la confirmación conserva `BlockingQueuedConnection`.

**Subpasos (un commit cada uno, pruebas en verde en todos):**

| Subpaso | Cambio | Commit |
|---|---|---|
| 2.1 | Crear `turn_events.py` sin uso todavía | `Add turn events and outcome types` |
| 2.2 | Cambiar los ~91 `self.<señal>.emit(...)` por `self.events.<método>(...)`. `Worker` sigue siendo `QObject`; un adaptador temporal reenvía a las señales actuales | `Route Worker output through TurnEvents` |
| 2.3 | Reemplazar `QThread.isInterruptionRequested` por `pause_requested`. En `app.py`, `enable_pause(self.thread.requestInterruption)` pasa a `request_pause` (líneas 1604, 1696 y `on_saved_task_started`) | `Replace thread interruption with a pause event` |
| 2.4 | Crear `qt_turn_runner.py`. `Worker` deja de heredar de `QObject` y se elimina el adaptador temporal. `start_turn` usa el ejecutor. `Worker.run()` devuelve `TurnOutcome` | `Run Worker through a Qt adapter` |
| 2.5 | Importación diferida de `attachments` (QtGui/QtPdf) en la rama de adjuntos visuales (`chat_with_attachments`, `turn_worker.py` ~2029). **Verificar** primero cuáles de los 8 nombres importados dependen de Qt; si solo algunos, separarlos | `Load visual attachment code lazily` |

**Restricciones de compatibilidad (no negociables en este paso):**

- `app.Worker` y `turn_worker.Worker` siguen existiendo: las pruebas hacen `patch.object(app.Worker, "enabled_skills", ...)`.
- `window.thread` debe seguir existiendo (24 usos en pruebas). `app.py` guarda `self.thread = runner.thread`.
- `self.worker` en `app.py` sigue apuntando al motor (`.task`, `.execution`, `.stop()`, `.task_reply`). El ejecutor expone `.worker`.

**Cambio en las pruebas del paso 1:** el `EventRecorder` pasa a `RecordingEvents`; los escenarios E1 a E8 no cambian y deben dar las mismas secuencias. Se agrega E9 (pausa de tarea con `request_pause`).

**Criterios de salida:**

1. `grep -n "PySide6" turn_worker.py` no devuelve nada.
2. `python -B -c "import sys, turn_worker; print('PySide6.QtWidgets' in sys.modules)"` imprime `False`. (`QtCore` sigue entrando por `QSettings`; es la deuda D1.)
3. E1 a E9 pasan sin Qt. Todo el resto de `tests/` queda igual que en el apéndice A.
4. Prueba manual en el escritorio: chat sin herramientas; una herramienta con diálogo de permiso (aprobar y denegar); botón de detener; tarea con pausa y `/reanudar`; cerrar la ventana a mitad de un turno.

## 8. Paso 3: sesión de chat sin Qt

**Qué se hace:** crear `chat_session.py` con la lógica de la conversación que hoy vive en `app.py`. La ventana solo pinta.

**Estado que pasa a la sesión:** `messages`, `chat_id`, `project`, `history`, `history_write_ok`, `pending_edit`, `task`, `ai`, `memory`, `pool`, y la bandera de "detener" (`stopping_turn`) y `turn_failed`.

**API de la sesión:**

| Método | Origen en `app.py` | Responsabilidad |
|---|---|---|
| `save_message(role, text, created, attachments, task, finish_execution)` | `app.py:889` | Agregar a `messages` y escribir en el historial; si falla, `history_write_ok = False` |
| `begin_turn(task=None) -> TurnPlan` | `app.py:1577-1650` | Copiar mensajes sin `created`; agregar instrucciones generales (`load_instructions`) y contexto de proyecto (continuidad recortada a 6000); crear `ChatExecution` con su alcance; devolver los argumentos para `Worker` |
| `complete_turn(outcome, worker)` | `app.py:1783-1822` | Aviso de efectos sin confirmar, `finish_execution`, guardar el mensaje, marcar tarea `interrupted` si el historial no se puede escribir, ruta de regeneración con `history.replace_from` |
| `fail_turn(detail, worker)` | `app.py:1823-1832` | Tarea en pausa con `task_reply("paused", ...)`, `turn_failed`, restaurar la edición pendiente |

`complete_turn` y `fail_turn` devuelven un resultado simple (texto, `created`, índice guardado, si hay que pintar mensajes siguientes, si hay que programar título). La ventana decide cómo mostrarlo.

**Se queda en `app.py`:** paneles, mascota, botones habilitados/deshabilitados, desplazamiento, diálogos, lista del historial, programación del título (`schedule_chat_title`) y la pintura de la regeneración.

**Estrategia para no tocar 200 usos a la vez:** en `app.py` se definen propiedades que delegan a la sesión (`messages`, `chat_id`, `project`, `history_write_ok`, `pending_edit`, `task`, `ai`). Usos actuales en `app.py`: `messages` 18, `chat_id` 20, `project` 36, `history_write_ok` 11, `pending_edit` 11, `task` 28, `history` 52, `ai` 16, `memory` 5, `pool` 4, `stopping_turn` 14, `turn_failed` 4. Las pruebas que leen `window.chat_id` o `window.messages` siguen funcionando.

**Subpasos:**

| Subpaso | Cambio | Commit |
|---|---|---|
| 3.1 | Crear `ChatSession` con el estado y `save_message`; `app.py` delega con propiedades | `Move chat state and message saving to ChatSession` |
| 3.2 | Mover el armado del turno a `begin_turn` | `Move turn preparation to ChatSession` |
| 3.3 | Mover el cierre a `complete_turn` y `fail_turn` | `Move turn completion to ChatSession` |
| 3.4 | Pruebas de sesión sin Qt (abajo) | `Add headless ChatSession tests` |

**Pruebas de sesión (con `History` en un perfil temporal):**

| Id | Escenario |
|---|---|
| S1 | `begin_turn` agrega instrucciones y contexto de proyecto al mensaje de sistema |
| S2 | `begin_turn` crea `ChatExecution` con el alcance esperado (proveedor, modelo, memoria en la nube, proyecto) |
| S3 | `complete_turn` con efectos sin confirmar agrega el aviso y **no** marca el cierre |
| S4 | `complete_turn` guarda el mensaje y devuelve `finish_execution` cuando todo quedó confirmado |
| S5 | Fallo del historial: `history_write_ok` pasa a `False` y la tarea queda `interrupted` |
| S6 | `fail_turn` en una tarea la deja en pausa |
| S7 | Regeneración: `replace_from` y restauración si falla |
| S8 | Detener antes de la respuesta: no se guarda la respuesta vacía |

**Criterios de salida:**

1. `chat_session.py` no importa `PySide6` ni `app`.
2. `app.py` ya no contiene la construcción de `Worker`, de `ChatExecution` ni la lógica de efectos sin confirmar.
3. S1 a S8 y E1 a E9 pasan sin Qt. El resto de `tests/` queda igual que en el apéndice A.
4. La misma prueba manual del paso 2, más: regenerar una respuesta, editar un mensaje, reabrir un chat con una ejecución interrumpida.
5. `README.md` actualizado ("Dónde buscar cuando quieras cambiar algo") con `turn_events.py`, `qt_turn_runner.py` y `chat_session.py`.

## 9. Resultado esperado al terminar el paso 3

Una CLI futura necesitaría solo esto (ilustrativo; no se implementa aquí):

```python
session = ChatSession(history=History(), ai=load_ai(), memory=StoneWaveMemory(), pool=McpPool())
session.save_message("user", text, time.time_ns())
plan = session.begin_turn()
worker = Worker(**plan.worker_kwargs, events=CliEvents())   # CliEvents imprime y pregunta permisos con input()
outcome = worker.run()
session.complete_turn(outcome, worker)
```

## 10. Decisiones abiertas y riesgos

| Id | Tema | Detalle | Decisión sugerida |
|---|---|---|---|
| D1 | `QSettings` | 5 módulos de lógica dependen de `QtCore` | Aprobado conservarlo temporalmente |
| D2 | `.pyc` versionados | 59 archivos en `ad09042` | Aprobado retirarlos del índice e ignorarlos en el paso 0.3 |
| D3 | Perfil de datos para la CLI | `default_root()` es `~/.stonebot` fijo (`stonebot_engine/safety.py`) y `stonebot_service.DB_PATH` se calcula al importar | En el paso 4 agregar una variable `STONEBOT_HOME`; no entra aquí |
| D4 | Escritorio y CLI a la vez | `QLockFile` (`app.py:1887`) solo evita dos escritorios; `History` abre SQLite en cada operación | Usar un perfil aparte para la CLI mientras se prueba |
| D5 | Nombre del módulo | `turn_worker.py` es un nombre de Qt | Renombrarlo a `turn_engine.py` solo cuando las pruebas parcheen el nuevo nombre; no ahora |
| D6 | Adjuntos visuales en CLI | Requieren `QtGui`/`QtPdf` | Fuera de la CLI inicial |
| D7 | Pausa fuera de tareas | Solo las tareas se pausan; el resto usa detener | Mantener |

## 11. Fuera de este plan

- Quitar el enrutamiento por regex, el catálogo fijo, más rondas, reparación de errores y cambios de prompt (paso 5).
- La CLI (paso 4).
- Cambios de interfaz o de estilo.
- Funciones nuevas.

## 12. Para quien continúe (otro agente)

**Leer primero:** este archivo, `AGENTS.md`, `docs/03-hoja-de-ruta-arquitectura.md` y `README.md` (sección "Dónde buscar cuando quieras cambiar algo").

**Archivos clave (en `094c387`):**

- `turn_worker.py` (~2195 líneas): `Worker` (158), `chat_with_tools` (1093), `request_round` (1487), `execute_external` (1692), `confirm_external` (~2185).
- `tool_loop.py`: `ToolLoop` y `TurnTools`.
- `chat_execution.py`: `ChatContext` y `ChatExecution`.
- `app.py`: `start_turn` (1577), `respuesta` (1783), `error` (1823), `save_message` (889).
- `history.py`: SQLite sin Qt.

**Comandos:** `python -B tests/<archivo>.py`; arrancar con `python -B app.py`. Windows, Python 3.14, PySide6.

**Reglas:** un subpaso por commit; no cambiar comportamiento; no renombrar módulos; pruebas en verde.

## 13. Lista de avance

- [x] 0.1 Rama creada
- [x] 0.2 Línea base registrada (apéndice A)
- [x] 0.3 Limpieza de archivos `.pyc` y decisión registrada
- [ ] 1 Pruebas del motor sin Qt (E1-E8)
- [ ] 2.1 `turn_events.py`
- [ ] 2.2 Salida por `TurnEvents`
- [ ] 2.3 Pausa con `Event`
- [ ] 2.4 `qt_turn_runner.py` y `Worker` sin `QObject`
- [ ] 2.5 Adjuntos con importación diferida
- [ ] 3.1 `ChatSession` con estado
- [ ] 3.2 `begin_turn`
- [ ] 3.3 `complete_turn` y `fail_turn`
- [ ] 3.4 Pruebas de sesión (S1-S8)
- [ ] README actualizado
- [ ] Prueba manual del escritorio

## Apéndice A: línea base de pruebas

El 26 de noviembre de 2026 se ejecutaron las 27 suites en `ad09042`, con Python 3.14.10 en Windows y la configuración del paso 0.2. Todas terminaron con código 0.

| Archivo | Resultado en `ad09042` |
|---|---|
| `test_ai_provider.py` | Aprobada (0) |
| `test_aislamiento.py` | Aprobada (0) |
| `test_attachments.py` | Aprobada (0) |
| `test_automatic_memory.py` | Aprobada (0) |
| `test_chat_continuity.py` | Aprobada (0) |
| `test_chat_execution.py` | Aprobada (0) |
| `test_chat_presentation.py` | Aprobada (0) |
| `test_experiences.py` | Aprobada (0) |
| `test_local_files.py` | Aprobada (0) |
| `test_managed_process.py` | Aprobada (0) |
| `test_mcp.py` | Aprobada (0) |
| `test_mcp_setup.py` | Aprobada (0) |
| `test_mcp_tool_groups.py` | Aprobada (0) |
| `test_mcp_ui.py` | Aprobada (0) |
| `test_memory_integration.py` | Aprobada (0) |
| `test_motor.py` | Aprobada (0) |
| `test_office_attachments.py` | Aprobada (0) |
| `test_project_reads.py` | Aprobada (0) |
| `test_project_tasks.py` | Aprobada (0) |
| `test_servicio.py` | Aprobada (0) |
| `test_skills.py` | Aprobada (0) |
| `test_stonewave_memory.py` | Aprobada (0) |
| `test_task_coverage.py` | Aprobada (0) |
| `test_tasks.py` | Aprobada (0) |
| `test_tray.py` | Aprobada (0) |
| `test_user_corrections.py` | Aprobada (0) |
| `test_workspace_features.py` | Aprobada (0) |
