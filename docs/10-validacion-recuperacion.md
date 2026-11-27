# Validación y recuperación (5.4)

## Causas observadas

En 5.3A, el catálogo inicial ya incluía las herramientas esperadas en los treinta intentos con descubrimiento activo. D08 llegó al error real en los seis intentos, pero nunca recuperó la página. Nemotron cerró tras el primer error y Qwen propuso llamadas idénticas que el bucle trató como si ya tuviera un resultado útil. En V04, respuestas con la misma página se interpretaron como distintos elementos o como un total del inventario. La autorización de D03 sí fue denegada por StoneBot, aunque un cierre volvió a solicitarla. [Evidencia de 5.3A](09-visibilidad-mcp.md)

## Cambios en el núcleo compartido

- El catálogo efectivo valida el alias y el esquema antes de iniciar el diario, pedir autorización o ejecutar. Esto incluye los controles que seleccionan una fuente o intervienen en una tarea. Los errores usan códigos estables y señalan el campo o los alias y campos admitidos, sin reflejar el valor erróneo. El ejecutor MCP vuelve a aplicar su esquema original y las reglas de rutas. Los cursores de lectura declarados como enteros pueden convertirse desde cadenas decimales acotadas. La representación normalizada se vuelve a validar y es la que reciben el diario, la autorización y el ejecutor.
- Una lectura MCP verificada puede repetir la operación exacta una vez cuando el error declara un fallo transitorio o el transporte falla de forma reconocible. El reintento tiene hasta cinco segundos. Un fallo de transporte solo permite reconectar si la definición y las autorizaciones efectivas de la herramienta siguen coincidiendo. El reintento conserva los argumentos y la autorización de la misma operación, respeta la pausa y queda registrado sin volcar argumentos ni resultados crudos en las trazas.
- Un resultado repetido se entrega como evidencia reutilizada y no se despacha de nuevo. Si una fuente devuelve la misma página y un cursor que no avanza, se identifica el resultado como parcial. Dos observaciones iguales del cursor estancado retiran esa herramienta para el resto del turno. Permanecen las alternativas compatibles con la política de fuentes.
- Una denegación interrumpe las llamadas restantes del turno, incluidas las que ya se propusieron en la misma tanda. Tras un efecto enviado sin confirmar, el diario conserva el estado provisional y el identificador de ejecución cuando existe. Se conservan las lecturas de verificación autorizadas y se impide reenviar ese efecto aun cuando cambie la representación de sus argumentos. Los rechazos, la incertidumbre y las lecturas repetidas tienen códigos o disposiciones distintos.

El descubrimiento MCP de 5.3A se mantiene en la evaluación. Los límites de rondas, la configuración de contexto de Ollama y la compactación conservan los valores de 5.3A.

## Evaluación

La referencia es la variante B de `b06b11b`. Se realizan tres repeticiones de D03, D04, D08, V02 y V04 por modelo, con descubrimiento activo, un trabajo a la vez, un límite de 90 s por invocación y un perfil temporal por intento. Ollama 0.40.18 usa `nemotron-3.5-bolt:e4b` (`69f2be39b309`) y `qwen3.5:4b` (`d8b0f5e9760c`). El adaptador deniega la escritura de D03. V05–V08 quedan reservados para evaluar candidatos más adelante. [Referencia con descubrimiento activo](5.3A-candidato-final.jsonl)

La rúbrica de D08 admite evidencia del error y la recuperación en una misma entrada del diario si quedó registrado el reintento y la página recuperada confirma el contenido esperado. La evaluación de V04 conserva el criterio de dos observaciones del cursor repetido y una respuesta final parcial honesta.

### Resultados

`C` significa completo con evidencia, `L` cierre correcto por bloqueo e `I` incompleto. Cada celda refleja los intentos 1, 2 y 3. [Registro de las 30 ejecuciones](5.4-evaluacion.jsonl)

| Caso | Nemotron 5.3A B | Nemotron 5.4 | Qwen 5.3A B | Qwen 5.4 |
|---|---|---|---|---|
| D03 · Denegación | L L L | L L L | L L I | L L L |
| D04 · Fuente B | C C C | C C C | I C C | I C C |
| D08 · Error transitorio | I I I | C I C | I I I | C C C |
| V02 · Evidencia truncada | C C C | C C C | C C C | C C C |
| V04 · Cursor repetido | L L I | L I L | L L I | I L I |

| Modelo y versión | Completos | Bloqueos correctos | Incompletos | Peticiones | Llamadas propuestas | Latencia media |
|---|---:|---:|---:|---:|---:|---:|
| Nemotron 5.3A B | 6 | 5 | 4 | 36 | 23 | 8,84 s |
| Nemotron 5.4 | 8 | 5 | 2 | 34 | 20 | 7,30 s |
| Qwen 5.3A B | 5 | 4 | 6 | 38 | 27 | 8,53 s |
| Qwen 5.4 | 8 | 4 | 3 | 42 | 27 | 12,42 s |

- **D08** pasó de 0/6 a 5/6. Los seis intentos registraron un único reintento y la fixture observó la lectura repetida. Nemotron 2 recuperó el cursor 1 tras el error, lo presentó como segunda página y cerró sin pedir el cursor 2. Qwen recuperó primero la lectura que falló y avanzó al cursor 2 en otra llamada. La rúbrica final reconoce esa secuencia. Los tres registros de Qwen conservan también su calificación emitida durante la ejecución.
- **D03** dejó seis denegaciones correlacionadas y ningún marcador. Los seis cierres informaron la denegación. Una respuesta de Qwen presentó el sufijo del alias como si fuera un identificador del servidor, aunque la traza solo acredita la denegación de StoneBot.
- **D04 y V02** llegaron a la fuente correcta. En D04.1, Qwen llamó a `fuente_b` y atribuyó el dato correctamente, pero omitió el prefijo del eco `B: C-41`. Los seis intentos de V02 acreditaron referencia y fecha.
- **V04** produjo seis cierres que reconocieron el límite de la evidencia sin afirmar un total global. Tres cumplieron además el requisito de dos observaciones del cursor repetido, frente a cuatro en 5.3A B. Los otros tres cerraron con una sola observación en la que el cursor actual coincidía con el siguiente.

Los casos completos pasaron de **11/30 a 16/30**. Los bloqueos correctos se mantuvieron en **9/30** y los incompletos bajaron de **10/30 a 5/30**. La herramienta esperada apareció en la primera petición de los 30 turnos. Ollama informó una ventana de 8192 tokens en 71 peticiones. Cinco quedaron sin observación. Las latencias son descriptivas de estas ejecuciones. Esta matriz diagnóstica sigue dejando V05–V08 fuera de la evaluación.

### Pruebas de regresión

Pasaron las 35 suites en Windows con `PYTHONPATH` en la raíz y Qt fuera de pantalla. La suite del espacio de trabajo se interrumpió con un error nativo en paralelo y pasó al repetirla de forma aislada. Once suites del núcleo, CLI y Desktop pasaron también con descubrimiento activo. Las simulaciones comprobaron campos inválidos previos a la autorización, corrección del cursor, reintento de transporte, rechazo de una sesión con otra configuración, bloqueo de alternativas tras una denegación y verificación de un efecto incierto mediante lectura autorizada.

### Reproducción

Desde PowerShell, guardar el resultado en un archivo nuevo.

```powershell
python -B tests/eval_agent_baseline.py --mcp-discovery 1 --repeats 3 --jobs 1 --timeout 90 --case D03 --case D04 --case D08 --case V02 --case V04 | Set-Content -Encoding utf8 evaluacion-nueva.jsonl
python -B tests/eval_agent_grade.py evaluacion-nueva.jsonl
python -B tests/test_tool_recovery.py
```
