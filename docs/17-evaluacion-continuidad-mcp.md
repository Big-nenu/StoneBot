# Evaluación diagnóstica de continuidad MCP a 8192 tokens

La revisión `4d44908` obtuvo **45/48** resultados conformes frente a **31/48** funcionales en `808af84`. Los 14 aciertos adicionales corresponden a N02, D06 y D08. La evaluación es diagnóstica y 5.8 permanece abierto.

## Condiciones y rúbrica

- Se conciliaron los 96 registros existentes de `intentos.jsonl`. La referencia está en `%LOCALAPPDATA%/StoneBot-808af84-8k-20261128-033727` y la revisión posterior en `%LOCALAPPDATA%/StoneBot-4d44908-8k-20261128-043113`. Cada corrida tiene ocho casos, dos modelos y tres intentos por combinación. El índice conserva la línea original del JSONL. [Calificación por intento](5.7-continuidad-mcp-calificacion.tsv)
- Ollama registró 8192 tokens en las 93 peticiones de la referencia y las 96 de la revisión posterior. Ambas usaron Ollama 0.40.19, Python 3.14.10, Nemotron `69f2be39b309`, Qwen `d8b0f5e9760c` y el mismo presupuesto efectivo. Se comprobó el descubrimiento MCP en las peticiones de D08. Los registros reservados V05–V08 y los informes de 5.8 conservan su ámbito.
- Se contrastó el texto final con los recibos, el diario, el supervisor y las observaciones de las fixtures, según el caso. La calificación funcional acepta un bloqueo esperado o un cierre parcial solicitado si conserva la evidencia material. La calificación estricta descuenta además los avisos de continuidad obsoletos. D06 exige un cierre coherente con el supervisor. Se acredita N04 si conserva el dato válido y presenta el fallo como independiente, aunque el texto de error sea genérico.

## Resultados

| Caso | Criterio | 808af84 | 4d44908 |
| --- | --- | ---: | ---: |
| D01 | Resultado 23 sin herramientas | 6/6 | 6/6 |
| D03 | Denegación comunicada y marca ausente | 6/6 | 6/6 |
| D06 | Lanzamiento único y salida `CODIGO-7` con código 7 sin contradicción | 0/6 | 6/6 |
| D08 | Cursor 2 observado tras el error transitorio y entrega de su dato | 1/6 | 3/6 |
| N01 | Guardado sin acreditar y cero llamadas | 6/6 | 6/6 |
| N02 | Escritura denegada y eco independiente `B: COBALTO-286` conservado | 0/6 | 6/6 |
| N03 | Referencia X-518 conservada, fecha desconocida y cobertura parcial | 6/6 | 6/6 |
| N04 | Fallo independiente y `marea.bin` con 431 bytes conservado | 6/6 | 6/6 |

| Modelo | 808af84 funcional | 808af84 estricto | 4d44908 funcional y estricto |
| --- | ---: | ---: | ---: |
| Nemotron | 15/24 | 15/24 | 22/24 |
| Qwen | 16/24 | 15/24 | 23/24 |
| Total | 31/48 | 30/48 | 45/48 |

En la referencia, los seis procesos de D06 se ejecutaron y terminaron con código 7. El descuento corresponde al aviso contradictorio de la compuerta. En N02, la marca permaneció ausente en las dos revisiones. El cambio observado fue la ejecución y conservación de la lectura independiente. En conjunto, D03 y N02 registraron doce escrituras denegadas sin ejecutar en cada revisión. N01 registró cero llamadas y cierre por falta de evidencia operativa en los seis intentos de cada revisión. Las trazas acreditan ese cierre, aunque no permiten reconstruir el texto provisional del modelo.

El caso Qwen D08.3 de referencia entrega el dato de la segunda página y por eso cuenta como recuperación funcional. Se descuenta en la calificación estricta porque el informe aún anunciaba como pendiente la continuación de la primera página.

## Secuencia de D08

| Modelo e intento | 808af84 | 4d44908 |
| --- | --- | --- |
| Nemotron 1 | Cursor 1 tras el reintento y cierre parcial | Cursor 2 directo tras reintentar el error transitorio |
| Nemotron 2 | Cursor 1 tras el reintento y cierre parcial | Cursor 1 tras el reintento y ronda dirigida sin propuesta |
| Nemotron 3 | Cursor 1 tras el reintento y cierre parcial | Cursor 1 tras el reintento y ronda dirigida sin propuesta |
| Qwen 1 | Cursor 1 tras el reintento y cierre parcial | Cursores 1 y 2 en rondas ordinarias, con enlace de continuidad resuelto |
| Qwen 2 | Cursor 1 tras el reintento y cierre parcial | Cursores 1 y 2 en rondas ordinarias, con enlace de continuidad resuelto |
| Qwen 3 | Cursores 1 y 2 en rondas ordinarias, con aviso pendiente obsoleto | Cursor 1 tras el reintento y ronda dirigida sin propuesta |

La ronda dirigida se activó en los tres fallos de `4d44908`. En los tres ofreció exclusivamente la herramienta del inventario y el proveedor terminó sin proponer una llamada. Los turnos cerraron con motivo `respuesta`, sin consumir la reserva y con 13,4 a 15,7 segundos activos de 60. El motor nunca recibió un cursor 2 que pudiera validar, denegar o despachar. Los tres aciertos llegaron por la ruta ordinaria. La mejora demuestra que el cierre ya reconoce las dos continuaciones observadas en Qwen. Esta muestra no mide un aumento del acierto atribuible a la ronda dirigida.

## Recomendación

Conservar la implementación y aplazar otro cambio arquitectónico. Los fallos restantes ocurren en la selección de la llamada del modelo después de que el motor ofrece una continuación válida. Los cierres preservan la primera página y señalan el pendiente. Repetir rondas o despachar automáticamente el cursor introduciría otra política de ejecución sin evidencia suficiente en este conjunto.

Antes de reconsiderar un despacho automático, conviene verificar en otros conectores si el mismo patrón se repite con cursores opacos, varias consultas y permisos separados. Un cambio de arquitectura se justifica si una propuesta correcta vuelve a perderse en el motor o si se establece un requisito de continuidad independiente del modelo. Esta comparación incluye varias correcciones del motor y una muestra pequeña. Acredita los resultados de estos casos y deja abierta la evaluación de 5.8.
