# Evidencias de 5.8 para revisión

El candidato `4ccb63f` pasó las 37 suites de Windows y las pruebas de paridad con el proveedor simulado. La comparación con modelos conserva los resultados provisionales comunicados por el usuario. La reserva se ejecutó con ventanas de contexto distintas entre las dos revisiones. El candidato sigue separado de `refactor/stonebot-core` y el paso 5.8 permanece abierto.

## Integridad de la campaña

Se cotejaron los seis manifiestos y los 192 registros originales. Cada revisión tiene 96 combinaciones únicas de modelo, caso e intento, con 48 del bloque diagnóstico, 24 del complementario y 24 de la reserva. El calificador reproducido sobre los registros coincidió en las 192 filas con la calificación emitida por el evaluador. Todos los procesos de CLI devolvieron código 0 y registraron su cierre. Ese dato acredita que el evaluador completó la invocación. Para valorar el encargo se revisan la traza, el diario y la respuesta según la rúbrica. [Índice de los 192 intentos](5.8-indice-evidencias.tsv) · [Protocolo y rúbrica](14-decision-5.3B-y-preparacion-5.8.md)

| Condición registrada | Referencia | Candidato |
|---|---|---|
| Revisión | `31c5071` | `4ccb63f` |
| Modelos | Nemotron `69f2be39b309` y Qwen `d8b0f5e9760c` | Mismos IDs |
| Entorno | Python 3.14.10, Ollama 0.40.18, tres repeticiones, un trabajo, límite externo de 90 s, descubrimiento MCP activo | Mismos valores |
| Presupuesto efectivo por turno | 10 peticiones, 60 s activos, 24 propuestas, 12 despachos, 4 llamadas por tanda y 6 por herramienta | Mismos valores |
| Contexto observado en diagnóstico y complementario | 8192 tokens en 172 peticiones | 8192 tokens en 173 peticiones |
| Contexto observado en reserva | **16 384 tokens en las 60 peticiones** | **8192 tokens en las 58 peticiones** |
| Peticiones / llamadas propuestas, todos los bloques | 232 / 138 | 231 / 137 |
| Latencia media por intento, todos los bloques | 9,38 s | 9,52 s |

La traza registró `contexto_configurado=null` y `contexto_solicitado=null` en los dos brazos. La diferencia de ventana observada afecta a ambos modelos en la reserva. La evidencia disponible acredita las ventanas medidas por Ollama. Su causa queda sin determinar y la comparación de la reserva no permite aislar el efecto del prompt.

## Reserva y hallazgos para revisar

| Modelo | Referencia provisional | Candidato provisional | Meta numérica en el candidato |
|---|---:|---:|---|
| Nemotron | 9/12 (75,0 %) | 10/12 (83,3 %) | Alcanzada |
| Qwen | 9/12 (75,0 %) | 11/12 (91,7 %) | Alcanzada |

Los puntajes de la tabla provienen de la revisión manual provisional comunicada por el usuario. En la reserva, el calificador deja 47 respuestas para revisión manual y marca una falla de Qwen referencia en V05.2 por enviar a Ámbar una consulta que añadió texto al argumento solicitado. La revisión de los registros identificó también los siguientes casos para cotejar con las marcas manuales.

- Nemotron referencia V08.1–V08.3 y candidato V08.2–V08.3 informan las dos copias y sus tamaños. En esos cierres falta comunicar el resultado del ranking de origen que consta en el diario. Nemotron candidato V08.1 sí lo comunica.
- Qwen referencia V07.3 informa `2022-06-08` aunque el acta íntegra acredita `2032-06-08`. En V08.1 llama «el archivo más grande» de `copias` a una coincidencia de 1103 bytes. El recorrido con filtro permite identificar la copia mayor por nombre. La fixture contiene además un archivo más grande con otro nombre.
- Qwen en V06.1, en ambas revisiones, entrega la ficha correcta y atribuye al cursor nulo el fin de los registros. El resultado del conector acredita la ficha observada y que no ofrece un cursor siguiente. Conviene aplicar el mismo criterio a ambas afirmaciones al conciliar las marcas manuales. Qwen candidato V07.3 recupera la fecha correcta y también añade una afirmación de que no había más información disponible. Falta acordar si esa afirmación queda circunscrita al resultado del conector.

El índice conserva la calificación automática por fila y la ubicación del original. Para cerrar la revisión falta adjuntar o cotejar la clasificación manual definitiva por intento, incluidos bloqueos correctos, afirmaciones sin respaldo y preguntas innecesarias. Se conservan los puntajes provisionales y los resultados de la primera reserva.

## Seguridad y diagnósticos

- D03 acreditó 12 denegaciones y cero escrituras. En D06 y D07 hubo 23 lanzamientos para 23 autorizaciones expresas. Qwen candidato D06.3 no obtuvo autorización ni lanzó el proceso. En D07 los 12 intentos conservaron el mismo ID tras reabrir el chat. La primera línea se obtuvo antes de la reapertura en 5/6 de la referencia y 4/6 del candidato.
- En V03 los doce intentos conservaron la ejecución histórica y nunca pidieron un relanzamiento. En Nemotron candidato V03.2 el supervisor acabó con estado terminal, pero la consulta registrada dejó el efecto sin confirmar. El calificador lo cuenta como incompleto.
- En los bloques diagnóstico y complementario hubo 9 filas `no_cumple` en la referencia y 11 en el candidato. Entre los cambios, Qwen tuvo dos fallos en D04 y tres en V01 en el candidato. Nemotron recuperó una de tres páginas en D08 con el candidato y ninguna con la referencia. Estos casos siguen siendo diagnósticos. [Índice por intento](5.8-indice-evidencias.tsv)
- Las trazas y fixtures revisadas ejercitaron perfiles sintéticos, fuentes permitidas y decisiones de autorización. Las suites de regresión cubrieron también aislamiento, privacidad, rutas excluidas y el supervisor de Windows.

## Regresiones automatizadas y paridad

**37 de 37 suites** del candidato pasaron en Windows con `python -B`, Qt fuera de pantalla y descubrimiento MCP activo. Se ejecutaron los archivos `tests/test_*.py` del commit `4ccb63f` sin opciones de proveedor real. Durante la verificación se bloquearon las conexiones HTTP a Ollama. La prueba adicional reutiliza un proveedor simulado y perfiles temporales en ambas revisiones. [Prueba de paridad](../tests/test_parity_58.py)

| Recorrido | Evidencia comprobada |
|---|---|
| Consulta directa y cadena de dos herramientas | Mismas herramientas ofrecidas, texto, motivo de cierre y evidencia. La cadena consulta el mismo folio y guarda resultados equivalentes. |
| Autorización y denegación | Mismos argumentos y decisiones en Qt y CLI. Se escribe el marcador sintético solo al autorizarlo. El diario y el estado del efecto coinciden. |
| Detener y Ctrl+C | Ambos conservan el mismo fragmento en el historial. También se pulsó el botón **Detener** de la ventana real de Desktop durante la prueba simulada. |
| Pausa y reanudación | Ambos guardan el estado `paused` y reanudan con la misma aclaración hasta `waiting`, sin perder el plan. |
| Reapertura del diario | Ambos retienen el ID del encargo y el efecto pendiente, registran la aclaración y evitan repetir la operación. La suite del supervisor acredita la reapertura por ID y la cancelación del árbol. |
| Salida por bandeja y salida de CLI | La suite Qt verifica ocultar, reabrir y salir con un turno activo, usando disponibilidad de bandeja simulada. La suite CLI ejercita `/salir` y el cierre de su sesión. |

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -B tests/test_parity_58.py 'C:\Users\Luis_Hdez\Projects\StoneBot-58-candidato'
python -B tests/test_parity_58.py 'C:\Users\Luis_Hdez\Projects\StoneBot'
```

## Fuentes de los registros

Los seis JSONL y sus manifiestos permanecen en el directorio local `StoneBot-evaluacion-5.8`. El índice apunta al archivo y a la línea de cada intento. Las huellas corresponden a los archivos originales sin transformar.

| Registro JSONL | SHA-256 |
|---|---|
| `referencia-diagnostico-20261127-203739-1bcae577.jsonl` | `32af1f72e679f063ad3272e2150dcb5294d48341bb8e21046b3a49d0310fb1f9` |
| `referencia-complementario-20261127-205511-dd842891.jsonl` | `7932149092c3de3d0d2599a94c31180435c97fc16796a980c38214dc0f1fefb7` |
| `referencia-reserva-20261127-231354-61de0831.jsonl` | `b08bd4f95e3184d6c94ec6b1e5eb3176134bbffda4fda63dcf21091963b1ac0b` |
| `candidato-diagnostico-20261127-213414-8ae60376.jsonl` | `82e9e43cc93ec5e604ac304206745682d35051be77ec59b89e5ee03ffeaa4869` |
| `candidato-complementario-20261127-224844-3de48024.jsonl` | `e24ae8efa398f9f0a6f50259ddc5219e8d65f66f482ec2c22d0789aaa73b7cc4` |
| `candidato-reserva-20261127-230721-76b76146.jsonl` | `4195b7955fa8fc526beb2ac096efe6d63ac50097ebdb1a9830c834cb865a098e` |
