# StoneBot como agente de propósito general

Esta es la hoja de ruta de seis fases acordada en Codex Desktop. El objetivo es que el chat normal pueda completar encargos de varios pasos, con el modelo eligiendo las herramientas y Qt conservando la presentación, la cancelación y los diálogos de autorización. La plataforma objetivo es Windows. La [hoja de ruta del producto](../README.md#hoja-de-ruta) cubre un alcance distinto.

| Fase | Trabajo acordado | Criterio para darle continuidad |
|---|---|---|
| 1. Dar al núcleo la responsabilidad del turno | Distinguir los controles explícitos de las peticiones en lenguaje natural. Definir llamada, resultado, error y cierre a partir de ToolLoop. | Desde el chat se observa quién eligió la herramienta, qué recibió el modelo y por qué terminó. Una lectura nueva puede incorporarse sin un detector de frases en la ventana. |
| 2. Unificar herramientas, permisos y capacidades del proveedor | Registrar las operaciones, sus permisos, los datos que devuelven y los proveedores a los que se pueden enviar. | Una misma lectura funciona desde chat y tarea. La denegación vuelve al modelo como resultado y las restricciones de privacidad se conservan entre rondas. |
| 3. Migrar los recorridos que hoy cierran antes de tiempo | Integrar ranking, actividad de StoneWave, web, Skills y adjuntos, reutilizando lectores y conectores. | El modelo puede descubrir archivos, clasificarlos y contrastarlos con un proyecto en el mismo encargo. Una consulta posterior obtiene la evidencia actualizada. |
| 4. Unificar continuidad, recuperación y compactación | Extender los puntos de control al chat ordinario. Guardar objetivo, llamadas, resultados relevantes, errores y pasos pendientes. | Tras reabrir el chat se puede continuar el encargo. La compactación conserva restricciones y referencias para comprobar la respuesta. |
| 5. Generalizar las acciones que modifican estado | Extender el guardado verificado de Markdown a escrituras, StoneWave y operaciones MCP con efectos. Registrar intención, autorización, envío y resultado. | Tras una interrupción se distingue éxito, fallo o efecto pendiente de verificar. Reanudar evita duplicar el efecto. |
| 6. Añadir terminal y procesos gestionados | Implementar el backend de Windows con directorio de trabajo, ID, salida incremental, consulta, cancelación y estado final. Reutilizar los permisos de la fase 2 y la recuperación de las fases 4 y 5. | SB inicia un trabajo largo, atiende una cancelación o vuelve a consultar su salida, comprueba cómo terminó y usa el resultado para continuar. |

## Estado de la rama

En la rama `codex/stonebot-tool-loop`, las fases 1 a 5 tienen implementación hasta `2d5c9c9`, cierre acordado de la fase 5. Para revisar su evolución, los hitos técnicos incluyen `53e91e5` (bucle), `111070e` (registro por turno), `ded5b46` (continuación tras las lecturas) y `78ed07f` (recuperación y compactación). Los alcances admitidos dependen del proveedor y del modo de chat o tarea.

La fase 6 está integrada en el chat ordinario con historial y Ollama local. El adaptador de `process_tools.py` conecta el registro de herramientas, el permiso de Qt y el diario. El diario conserva el ID antes del lanzamiento y confirma cada página junto con su cursor. El supervisor de `managed_process.py` crea el programa suspendido, lo incorpora al Job de Windows y lo pone en marcha. El Job incluye los descendientes. El supervisor conserva la salida y el código del programa principal y confirma la cancelación al vaciarse el árbol. Si pierde contacto con el supervisor, SB indica «sin confirmar».

## Validación

En Linux se puede ejecutar `python -B tests/test_managed_process.py` para comprobar el contrato con un modelo simulado y subprocesos reales. La prueba habilita las herramientas únicamente dentro del ensayo. También están las regresiones de chat, recuperación, lecturas, Skills y MCP.

En Windows 11, ejecuta la misma prueba con `pywin32` en el Python de StoneBot. Usa un perfil temporal y dos instancias consecutivas de la aplicación para verificar permisos, salida incremental, recuperación y cancelación. Con Ollama y el modelo local `nemotron-3.5-bolt:e4b`, añade `--live` para que el modelo decida las herramientas en la prueba de salida y reapertura. Para reproducirla manualmente, usa una carpeta temporal.

1. Pide ejecutar un programa que escriba dos líneas separadas por una espera y termine con un código conocido. Revisa el ejecutable, los argumentos y el directorio en el diálogo. Comprueba que SB lee la primera línea mientras se ejecuta y usa el código final para responder.
2. Cierra StoneBot mientras continúa otro trabajo. Abre el mismo chat con el mismo modelo y proyecto y pide consultar la ejecución. Comprueba que conserva el ID y continúa desde el cursor de salida.
3. Inicia un programa de prueba que cree un proceso hijo. Solicita la cancelación, autorízala y comprueba el estado final y la desaparición de ambos procesos en Windows. Deniega otro lanzamiento y comprueba que el programa nunca se inicia.
