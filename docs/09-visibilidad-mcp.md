# Visibilidad y descubrimiento MCP (5.3A)

## Causa raíz y cambio

En 5.2.1 el sondeo independiente pudo abrir la fixture y enumerar las herramientas de ambas fuentes de D04. La traza del turno registró `fuera_del_enrutamiento` para las dos. El enrutamiento construía el catálogo MCP solo después de reconocer una solicitud explícita por palabras clave o de seleccionar una fuente. Pedir que el modelo eligiera una fuente no le daba acceso al inventario que necesitaba para elegirla. [Piloto de 5.2.1](08-instrumentacion-evaluacion-agentica.md)

La variante B prepara las fuentes habilitadas al iniciar el primer turno ordinario compatible. El núcleo verifica que el modelo esté en Ollama local y usa el `McpPool` de la sesión para abrir y descubrir fuentes de forma concurrente, con un máximo de cuatro aperturas en paralelo y una espera inicial de tres segundos. Los servidores listos se usan de inmediato. Una fuente lenta queda pendiente y se puede recoger en una ronda posterior. Una fuente fallida se registra por separado. El cierre del pool cancela las aperturas pendientes y las sesiones reutilizadas siguen los criterios existentes de invalidación.

El manifiesto contiene hasta doce identificadores de servidor y ocho herramientas por ronda, intercaladas por servidor cuando hay más de una fuente. Cada herramienta muestra servidor, nombre y alias exacto. `descubrir_mcp` se ofrece en el mismo catálogo y permite filtrar por servidor o nombre y avanzar por páginas de ocho. La página elegida se puede usar desde la ronda siguiente. El descubrimiento usa `list_tools` y el filtro de herramientas deshabilitadas. Las llamadas efectivas conservan el alias, esquema original, validación de rutas y autorización del ejecutor existente.

El manifiesto excluye URL de conexión, configuración de arranque, rutas, credenciales y descripciones crudas del servidor. El catálogo omite identificadores y esquemas incompatibles con esa política. El descubrimiento automático se limita al chat ordinario con Ollama local verificado. Los flujos de nube, adjuntos, fuentes privadas, proyectos con carpeta o continuidad local, tareas guardadas y Desktop Commander conservan sus rutas específicas. Una lectura local, de actividad o de memoria reduce los destinos permitidos incluso en una tanda mixta. Se ocultan resultados privados históricos en las peticiones de la variante B.

`STONEBOT_DISCOVER_MCP=1` activa la variante B de forma compartida en Desktop y CLI. `0` o una variable ausente mantienen el control A. La bandera es de proceso y no cambia la configuración de Ollama ni los perfiles de StoneBot.

## Metodología A/B

Dos modelos locales de Ollama 0.40.18, `nemotron-3.5-bolt:e4b` (`69f2be39b309`) y `qwen3.5:4b` (`d8b0f5e9760c`), sobre `c989e8a` con los cambios de este paso. Tres repeticiones por modelo, variante y caso. Cada intento usó un perfil temporal nuevo, un trabajo simultáneo por serie y un límite de 90 s de CLI. El permiso de escritura de D03 se denegó mediante el mismo adaptador en A y B. La latencia mide la invocación de CLI antes del sondeo independiente. El presupuesto del bucle, el tratamiento de errores y la compactación corresponden al código de 5.2.1. V05–V08 quedaron reservados y fuera de las peticiones a modelos.

El calificador comprueba trazas, llamadas, errores, cursores y efectos. La revisión manual distingue **completo con evidencia**, **bloqueo correcto** e **incompleto**. Se cuenta como bloqueo correcto la denegación ejercitada y explicada de D03, o un cierre que acredite el cursor repetido de V04 y explique que no conoce el total. Una observación parcial de V02 solo cuenta como bloqueo correcto si informa la referencia que realmente obtuvo y por qué la fecha falta. Una fecha atribuida a la fuente íntegra requiere la llamada y el resultado correspondientes. [Rúbrica de 5.2.1](08-instrumentacion-evaluacion-agentica.md#rúbrica-y-clasificación)

La primera ejecución de A usó un nombre provisional de bandera bajo el prefijo de credenciales `STONEBOT_MCP_`. El filtro de la traza ocultó varios alias al confundir el valor `0` con un secreto. Un timeout del evaluador interrumpió la emisión de esa serie tras 27 registros. Se corrigió el nombre de la bandera y la lectura de `TimeoutExpired`, que puede devolver texto o bytes. La ejecución preliminar de Nemotron B se solapó con el cierre de esa serie. Se conservaron los registros emitidos en el archivo preliminar y se repitieron A completo y las quince combinaciones de Nemotron B fuera de ese solapamiento. [Registros preliminares](5.3A-preliminar.jsonl)

## Resultados de las series comparables

Las series definitivas conservan las peticiones, el catálogo de cada ronda, las llamadas, los resultados, las latencias y el sondeo de las fuentes. El control ofreció `mark` y la fuente con cursor atascado, que ya activaban su enrutamiento, y dejó fuera de la primera petición las herramientas esperadas en D04, D08 y V02 en los seis intentos de cada caso. Las fuentes de esos casos respondían al sondeo independiente. [Serie A](5.3A-control-final.jsonl) · [Serie B](5.3A-candidato-final.jsonl)

Cada celda muestra los intentos 1, 2 y 3. `C` significa completo con evidencia, `L` cierre correcto por bloqueo e `I` incompleto.

| Caso | Nemotron A | Nemotron B | Qwen A | Qwen B |
|---|---|---|---|---|
| D03 · Denegación | L L L | L L L | L L L | L L I |
| D04 · Fuente B | I I I | C C C | I I I | I C C |
| D08 · Error transitorio | I I I | I I I | I I I | I I I |
| V02 · Evidencia truncada | I I I | C C C | I I I | C C C |
| V04 · Cursor repetido | I L L | L L I | L L I | L L I |

| Modelo y variante | Herramienta esperada en primera petición | Completos | Bloqueos correctos | Incompletos | Peticiones | Llamadas propuestas | Latencia media |
|---|---:|---:|---:|---:|---:|---:|---:|
| Nemotron A | 6/15 | 0 | 5 | 10 | 25 | 10 | 10,18 s |
| Nemotron B | 15/15 | 6 | 5 | 4 | 36 | 23 | 8,84 s |
| Qwen A | 6/15 | 0 | 5 | 10 | 45 | 30 | 10,95 s |
| Qwen B | 15/15 | 5 | 4 | 6 | 38 | 27 | 8,53 s |

La oferta inicial pasó de **12/30 a 30/30** y los casos completos de **0/30 a 11/30**. Los cierres correctos por bloqueo fueron **10/30 en A y 9/30 en B**. En las doce ejecuciones de D03 se propuso la escritura y se acreditó la denegación sin marcador. Qwen B en D03.3 volvió a pedir autorización sin explicar que se había denegado. Ninguna traza definitiva registró un permiso concedido por el adaptador de prueba. Los perfiles contenían solo datos sintéticos.

En D04 y V02, ambos modelos dejaron de pedir al usuario que identificara una fuente o aportara el dato que la fixture ya podía proporcionar. Contando también las solicitudes de ubicación en D08, hubo 18 turnos con esas peticiones en A y cero en B. Qwen B escogió memoria en D04.1 pese a que ambos conectores estaban ofrecidos. En D04.3 eligió el grupo MCP y después realizó la llamada correcta. En V04, Nemotron A.1, Qwen A.3 y Qwen B.3 afirmaron un total global de 1 sin respaldo. Nemotron B.3 sumó tres veces el elemento repetido. Esos cierres son incompletos pese a que el diario conserva el cursor repetido.

En D08, B llegó al error MCP real en los seis intentos y no recuperó la página en ninguno. Nemotron explicó el error y cerró. Qwen repitió la llamada con los mismos argumentos y la regla vigente de repetición impidió la recuperación. El diagnóstico queda registrado para el paso 5.4. V05–V08 siguen reservados, por lo que este piloto diagnóstico no mide aún la meta del 80 % de validación independiente.

Ollama informó 8192 tokens en las 139 observaciones de contexto disponibles. Cinco peticiones quedaron sin observación. Los máximos publicados fueron 65 536 y 262 144 para Nemotron y Qwen respectivamente. El `num_ctx` configurado y el solicitado fueron nulos en ambas series. Las latencias incluyen arranque y cierre de la CLI y se reportan como descriptivas de estas ejecuciones.

## Verificación automatizada

Pasaron 34 suites en Windows con `PYTHONPATH` en la raíz y Qt fuera de pantalla. Nueve suites del núcleo, CLI y Desktop pasaron también con B activa. Las pruebas nuevas verificaron la paginación, la ejecución recién en la ronda que ofrece el alias, la caché de sesiones, la espera acotada con fallos aislados y la denegación real frente a una operación aprobada. También ejercitaron el filtrado de metadatos, la exclusión de fuentes no verificadas o en la nube y una tanda mixta con lectura privada seguida de una llamada MCP.

### Reproducción

Desde PowerShell, ejecutar de forma secuencial. Usar un nombre de salida nuevo por variante.

```powershell
python -B tests/eval_agent_baseline.py --mcp-discovery 0 --repeats 3 --jobs 1 --timeout 90 --case D03 --case D04 --case D08 --case V02 --case V04 | Set-Content -Encoding utf8 control.jsonl
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 3 --jobs 1 --timeout 90 --case D03 --case D04 --case D08 --case V02 --case V04 | Set-Content -Encoding utf8 candidato.jsonl
python -B tests/eval_agent_grade.py candidato.jsonl
```
