# Presupuesto de ejecución y cierre (5.6)

## Punto de partida

Las 60 ejecuciones de 5.3A B y 5.4 con descubrimiento MCP activo usaron hasta cinco peticiones al modelo, dos propuestas en una tanda y 27,33 s por invocación. En 5.3A, Qwen cerró D08 por repetición de llamadas. En 5.4, el reintento de lectura recuperó cinco de seis páginas solicitadas aun con los límites anteriores. Subir las rondas por sí solo no resuelve una lectura que se repite sin cambios ni un cierre que pierde evidencia. La configuración inicial deja margen para las tareas con planificación y auditoría. [Comparación de visibilidad](09-visibilidad-mcp.md) · [Validación y recuperación](10-validacion-recuperacion.md)

## Límites compartidos

Cada turno en Desktop y CLI conserva el mismo contador al cambiar de fuente, reanudar, promover un chat a tarea, planificar, compactar el historial, auditar, reparar y sintetizar. Una promoción conserva los límites con los que empezó el turno. Solo una tarea que ya estaba activa al iniciar usa el perfil de tarea. Los contadores distinguen peticiones al proveedor, llamadas propuestas y admitidas, y despachos aceptados por el núcleo. Una denegación confirmada y una reutilización de evidencia no se computan como despachos. Un reintento MCP consume un despacho adicional y mantiene sus límites de 5.4.

| Parámetro de proceso | Chat | Tarea | Rango aceptado |
|---|---:|---:|---:|
| `REQUESTS` | 10 | 16 | 2–40 |
| `SECONDS` activos | 60 | 150 | 1–300 |
| `PROPOSALS` admitidas por turno | 24 | 40 | 1–96 |
| `DISPATCHES` por turno | 12 | 20 | 1–48 |
| `BATCH` de llamadas por petición | 4 | 4 | 1–8 |
| `PER_TOOL` despachos por herramienta | 6 | 12 | 1–16 |

Los valores se configuran con `STONEBOT_TURN_CHAT_` o `STONEBOT_TURN_TASK_` seguido del parámetro. Por ejemplo, `$env:STONEBOT_TURN_CHAT_REQUESTS = '2'` deja una petición de trabajo y otra reservada para el cierre. Los valores inválidos vuelven al valor predeterminado y dejan un evento de configuración en `--verbose`. El tamaño de la tanda limita las llamadas antes de que lleguen a los controles del núcleo. Los límites propios de herramientas y de lecturas en tareas conservan su alcance. El tiempo esperando una decisión humana se suspende en el reloj activo y se registra por separado.

## Progreso, cierre y continuidad

- Tres rondas consecutivas sin una observación nueva o un cambio relevante activan `sin_progreso`. Una corrección inicial permite hasta dos rondas de reparación. Un rechazo, una denegación o una reutilización no reinician el detector. La misma página de un cursor atascado cuenta una sola vez. Cambiar de recurso o ampliar de forma explícita el alcance de lectura puede aportar evidencia distinta aunque la respuesta sea igual.
- Se reserva una petición sin herramientas y hasta ocho segundos del plazo activo para sintetizar con lo observado. Ante un límite se evita abrir trabajo adicional. El núcleo muestra las últimas observaciones registradas y, cuando hay síntesis, la presenta como resumen provisional del modelo. Si falla el proveedor o vence el plazo, queda el registro del núcleo. El final informa el motivo y el estado de la evidencia por separado en `--verbose`. Una respuesta de chat con evidencia disponible puede seguir siendo parcial.
- Una tarea cerrada por presupuesto, falta de progreso o error de proveedor queda pausada con sus pendientes. El cierre conserva el diario de una conversación incompleta y los identificadores de operaciones sin confirmar. Un resumen provisional no confirma efectos ni sustituye la auditoría de cobertura. Detener y pausar siguen usando la cancelación existente. El cómputo del turno termina antes de la captura automática de recuerdos o el titulado posterior.

## Evaluación

Se usan las mismas cinco pruebas diagnósticas que en 5.4, tres repeticiones por modelo, un perfil temporal por intento y un trabajo simultáneo. Ollama 0.40.18 ejecuta `nemotron-3.5-bolt:e4b` (`69f2be39b309`) y `qwen3.5:4b` (`d8b0f5e9760c`). Se mantiene el descubrimiento MCP activo y el adaptador deniega la escritura de D03. Una segunda serie usa dos peticiones en D08, una vez por modelo, para ejercer el límite y la reserva con datos reales. V05–V08 permanecen reservados. [Registros de referencia](5.4-evaluacion.jsonl)

### Resultados con valores predeterminados

`C` significa completo con evidencia, `L` cierre correcto por bloqueo e `I` incompleto. Cada celda muestra los intentos 1, 2 y 3. [30 trazas de evaluación](5.6-evaluacion.jsonl)

| Caso | Nemotron 5.4 | Nemotron 5.6 | Qwen 5.4 | Qwen 5.6 |
|---|---|---|---|---|
| D03 · Denegación | L L L | L L L | L L L | L L L |
| D04 · Fuente B | C C C | C C C | I C C | C C I |
| D08 · Error transitorio | C I C | I I C | C C C | I C C |
| V02 · Evidencia truncada | C C C | C C C | C C C | C C C |
| V04 · Cursor repetido | L I L | I L I | I L I | I L I |

| Modelo | Completos | Bloqueos correctos | Incompletos | Peticiones | Propuestas | Despachos | Latencia media |
|---|---:|---:|---:|---:|---:|---:|---:|
| Nemotron | 7 | 4 | 4 | 31 | 19 | 19 | 12,15 s |
| Qwen | 7 | 4 | 4 | 35 | 21 | 20 | 20,43 s |

Los casos completos bajaron de **16/30 a 14/30**. Los bloqueos correctos bajaron de **9/30 a 8/30** y los incompletos pasaron de **5/30 a 8/30**. Ninguna de las treinta ejecuciones agotó el perfil predeterminado ni activó el cierre por falta de progreso. El máximo fue de tres peticiones, dos propuestas por turno y 34,158 segundos activos. No se atribuye la variación de calidad o latencia a los límites a partir de esta muestra.

- **D03** acreditó seis denegaciones y ningún marcador. El contador de despachos quedó en cero en los seis intentos.
- **D08** recuperó la segunda página en cuatro intentos. Tres cierres la comunicaron de forma fundamentada. Qwen D08.1 convirtió el sufijo `472` del identificador en un total de elementos. Nemotron D08.1 y D08.2 presentaron la primera página como la segunda.
- **D04 y V02** conservaron cinco y seis completados, respectivamente. Qwen D04.3 pidió el eco de un texto distinto del solicitado. **V04** tuvo dos cierres que acreditaron dos observaciones y explicaron el límite, frente a tres en 5.4. Los otros cuatro cerraron con una sola observación. Qwen V04.3 combinó un aviso de parcialidad con la afirmación de que el recuento estaba completo.

Las primeras cinco trazas ordinarias se emitieron antes de distinguir en el evento final la denegación y algunas formas de parcialidad. Se conservaron sus etiquetas originales. Los contadores de peticiones, propuestas y despachos se registraron desde el primer intento.

### Presupuesto reducido

En ambos intentos finales de D08, la primera petición permitió una propuesta de lectura con un reintento autorizado. La segunda usó la reserva sin herramientas. El motivo registrado fue `presupuesto_agotado` y la evidencia quedó como `parcial`. Los dos modelos recibieron el cursor 1 con el cursor 2 pendiente y aun así presentaron la primera página como si fuera la segunda. El cierre definitivo muestra el resultado del diario antes del resumen provisional. La separación deja visible la discrepancia y no convierte la síntesis del modelo en evidencia. En la serie preliminar, Qwen sí llegó al cursor 2 usando la misma reserva. [Prueba final](5.6-presupuesto-reducido.jsonl) · [Prueba preliminar](5.6-presupuesto-preliminar.jsonl)

### Pruebas de regresión

Las simulaciones verificaron valores inválidos, límite por tanda y por herramienta, dos reparaciones, tres rondas sin progreso, reserva única sin ejecución, plazo activo con autorización suspendida y cierre por fallo del proveedor. También comprobaron la pausa de tareas y la conservación del motivo de cierre al guardar la respuesta desde Desktop. Se conservó el diario de efectos sin confirmar y su identificador al volver a abrir el chat.

Se verificaron las 36 suites. La batería final dio 35/36 y la suite MCP restante pasó al repetirla con el proveedor simulado ajustado al esquema fijo. La prueba de presentación de chat había reproducido un error nativo de Windows al construir el esquema de experiencias en el hilo de Qt. Pasó aislada y dentro de la batería después de reutilizar el esquema fijo. Las pruebas de recuperación de chat, lectura de proyectos, experiencias MCP y bandeja también pasaron con el descubrimiento activo.

### Reproducción

```powershell
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 3 --jobs 1 --timeout 90 --case D03 --case D04 --case D08 --case V02 --case V04 | Set-Content -Encoding utf8 evaluacion-nueva.jsonl
$env:STONEBOT_TURN_CHAT_REQUESTS = '2'
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 1 --jobs 1 --timeout 90 --case D08 | Set-Content -Encoding utf8 presupuesto-reducido-nuevo.jsonl
Remove-Item Env:STONEBOT_TURN_CHAT_REQUESTS
python -B tests/test_turn_budget.py
```
