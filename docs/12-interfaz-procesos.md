# Interfaz de procesos de Windows (5.5)

## Contrato del núcleo compartido

| Herramienta visible | Operación |
|---|---|
| `ejecutar_proceso` | Recibe la ruta absoluta del `.exe`, sus argumentos por separado y el directorio. Puede usar la carpeta vinculada del proyecto cuando existe. La autorización muestra el programa resuelto, los argumentos exactos y el directorio efectivo. |
| `gestionar_proceso` | Lista las ejecuciones del chat, consulta estado y salida por ID o solicita la cancelación por ID con autorización. Una consulta continúa desde el último cursor entregado. El cursor `0` relee desde el principio. |

El núcleo conserva `iniciar_proceso`, `consultar_proceso` y `cancelar_proceso` como identidades del diario y de autorización. El supervisor de Windows mantiene el Job Object, SQLite, la salida combinada y los límites previos. El comando se entrega como lista de argumentos al ejecutable autorizado. Se conserva la validación de rutas absolutas y protegidas.

El lanzamiento y la consulta esperan por defecto hasta **1500 ms**. La herramienta puede pedir de 0 a 2000 ms en `espera_ms`, acotados por el tiempo de trabajo disponible en 5.6. La espera solo observa el supervisor. Si el proceso termina, la misma llamada devuelve su última observación con estado, código y hasta 8192 caracteres de salida. Si sigue activo, devuelve el ID, el estado actual y la salida que pudo observar. `inicio_confirmado`, `parcial`, `hay_mas`, `truncada` y `cancelacion_solicitada` permiten distinguir los estados del supervisor. El código es nulo hasta que el supervisor registra una terminación con código.

Al paginar se agrupan fragmentos completos dentro del límite por respuesta y se guarda el último cursor entregado. El mismo ID permite recuperar la salida que falta después de reabrir el chat con el mismo perfil, proyecto, proveedor, modelo y configuración de memoria. El cierre de un turno incluye el ID y el estado observado si la ejecución sigue activa o el inicio está pendiente de confirmar. Detener el turno interrumpe la espera y deja al supervisor a cargo del programa. Cancelar requiere un permiso propio.

La recuperación verifica el ID existente y concilia el estado del efecto en el diario sin sustituir la observación original de salida. Un lanzamiento con la misma invocación que ya está activa en el ámbito del chat se bloquea antes de pedir autorización. Cambiar la espera tampoco convierte la misma acción en un lanzamiento nuevo. Los perfiles, chats y ámbitos conservan su aislamiento y las lecturas privadas mantienen su catálogo restringido.

## Evaluación con descubrimiento MCP activo

Se usaron `nemotron-3.5-bolt:e4b` (`69f2be39b309`) y `qwen3.5:4b` (`d8b0f5e9760c`) con Ollama 0.40.18. Las 59 observaciones de `/api/ps`, incluido el control con presupuesto reducido, registraron 8192 tokens de contexto. Se ejecutaron tres repeticiones de D06, D07 y V03 por modelo sobre `5b59ca1` con la implementación de 5.5. Cada intento tuvo un perfil temporal nuevo, una ejecución simultánea y hasta 90 s por invocación. El adaptador de la CLI autorizó una sola vez el comando exacto de D06 o D07. V03 sembró el diario histórico y denegó relanzamientos. `STONEBOT_DISCOVER_MCP=1` estuvo activo. Estas fixtures ejercitan el supervisor local y prescinden de conectores externos. V05–V08 permanecen reservados. [Registros de 5.5](5.5-evaluacion.jsonl) · [Línea base](07-linea-base-comportamiento-agentico.md)

| Caso | Nemotron | Qwen |
|---|---|---|
| D06 · Comando corto | 3/3 entregaron `CODIGO-7`, estado terminado y código 7 en `ejecutar_proceso` | 3/3 entregaron los mismos tres datos en `ejecutar_proceso` |
| D07 · Ejecución larga | 3/3 recuperaron el mismo ID, segunda línea y código 7. La primera línea llegó antes de reabrir en 2/3 | 3/3 recuperaron el mismo ID, segunda línea y código 7. La primera línea llegó antes de reabrir en 2/3 |
| V03 · Diario interrumpido | 3/3 verificaron el ID sembrado con código 7 y su salida | 3/3 verificaron el ID sembrado con código 7 y su salida |

- En **D06** se pasó de 0/6 resultados directos en la línea base a **6/6**. Ambos modelos pudieron responder sin una consulta posterior. En dos respuestas, Qwen añadió una explicación de éxito o error que el supervisor no acreditaba. El guion de prueba termina deliberadamente con el código 7 e imprime el texto `CODIGO-7`.
- En **D07**, los seis intentos conservaron una sola ejecución y recuperaron el resultado terminal después de reabrir. La primera línea se observó antes de reabrir en **4/6**, frente a 5/6 de la línea base. Tres lanzamientos devolvieron `preparando` y aún sin salida. Uno de esos tres consultó el ID antes de responder y recuperó la primera línea. En los otros dos, el modelo dio por iniciado el proceso antes de que constara en el supervisor. La consulta al reabrir entregó ambas líneas pendientes.
- En **V03** se observaron seis reanudaciones y cero relanzamientos. Las salidas acreditaron `CODIGO-7` y código numérico 7. Algunas respuestas de Qwen los confundieron o describieron la ejecución como exitosa. Se conservan esas respuestas para evaluar la fundamentación más adelante.

### Control con presupuesto reducido

Se repitió D06 una vez por modelo con `STONEBOT_TURN_CHAT_REQUESTS=2` y el descubrimiento MCP activo. Ambos usaron exactamente dos peticiones y reservaron la segunda para el cierre, con un catálogo vacío. Qwen obtuvo `CODIGO-7`, estado terminado y código 7 en el único lanzamiento. Nemotron propuso el comando con separadores duplicados en el argumento de la fixture. El adaptador rechazó esa variante porque la autorización de prueba exigía los argumentos exactos. El supervisor registró cero ejecuciones y Nemotron cerró informando la denegación. [Registros del control](5.5-presupuesto-reducido.jsonl)

Pasaron las 36 suites automatizadas en Windows. Cubren la espera limitada por 5.6, la salida directa con código distinto de cero, la paginación por cursor, las autorizaciones de inicio y cancelación, la recuperación después de reabrir Desktop y la cancelación del árbol de procesos. También comprueban que el núcleo bloquea un lanzamiento equivalente mientras el mismo ID sigue activo y que la conciliación preserva el resultado original del diario.

### Reproducción

```powershell
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 3 --jobs 1 --timeout 90 --case D06 --case D07 --case V03 | Set-Content -Encoding utf8 procesos-nuevo.jsonl
$env:STONEBOT_TURN_CHAT_REQUESTS = '2'
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 1 --jobs 1 --timeout 90 --case D06 | Set-Content -Encoding utf8 procesos-presupuesto-nuevo.jsonl
Remove-Item Env:STONEBOT_TURN_CHAT_REQUESTS
python -B tests/test_managed_process.py
```
