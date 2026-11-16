# StoneBot

> Un compañero de IA local que recuerda, razona, experimenta y, con el tiempo, puede interactuar con el mundo físico.

**Estado:** prototipo conversacional con herramientas de memoria persistente · **Inicio:** noviembre de 2026 · **Enfoque:** experimentación incremental, local-first.

## Visión

StoneBot no pretende ser únicamente un chatbot con memoria ni una mascota de escritorio. Es un experimento para construir un agente que pueda mantener continuidad entre sesiones, plantear preguntas, contrastar hipótesis, aprender de resultados y tomar iniciativas dentro de límites explícitos.

Inspiraciones conceptuales: Jarvis (asistencia), Vision (reflexión) y Ultrón (iniciativa), **sin asumir conciencia ni autonomía ilimitada**.

## Principios

- **Primero razonamiento; después apariencia y cuerpo.**
- **StoneWave original es intocable:** StoneBot usa su propia base de datos y no debe tener permisos de escritura sobre el código fuente de StoneWave. Las modificaciones experimentales del motor, si se necesitan, se prueban en una copia o variante aislada.
- **Memoria aislada:** rutas, configuración, base de datos y pruebas exclusivas para StoneBot.
- **Local-first:** Ollama y modelos adecuados a una RTX 4060 de 8 GB; servicios externos opcionales, nunca obligatorios.
- **Un modelo cargado a la vez** cuando compartir GPU cause conflictos.
- **Autonomía graduada:** observar y proponer antes de actuar; pedir permiso para acciones sensibles.
- **Experimentos verificables:** registrar hipótesis, evidencias, fallos y conclusiones.
- **Pocos componentes, interfaces claras y pruebas pequeñas.**
- **Aplicación propia de Windows:** StoneBot no depende de la interfaz de Cline, Hermes ni Claude.
- **Núcleo independiente de la ventana:** cerrar la ventana lo deja en segundo plano; «Salir» detiene el proceso.

## Hoja de ruta

Las etapas son orientativas, no fechas prometidas. Cada etapa debe tener una demostración observable antes de avanzar.

| Etapa | Objetivo | Entregable comprobable | Estado |
|---|---|---|---|
| 0. Base segura | Definir alcance y separar la memoria | Motor local y base SQLite exclusiva | Completada. Lectura, escritura y rutas protegidas verificadas con bases de prueba. |
| 1. Núcleo conversacional | Aplicación Windows con chat, Ollama y motor local | Conversa y recuerda; pendiente permanecer en segundo plano al cerrar la ventana | Parcial. Chat, historial, temas y herramientas de memoria operativos; falta la bandeja del sistema. |
| 1B. Herramientas externas (MCP) | Cliente MCP reutilizable y primeras integraciones | Descubre e invoca herramientas desde el chat con controles de permiso | Implementada en prototipo. Cliente STDIO/HTTP, panel y permisos; Context7 y Exa comprobados en pruebas, Tavily pendiente de prueba en vivo según última revisión. | 
| 2. Aprendizaje de experiencias | Evaluar capacidades a partir de resultados observados | Registra una ejecución MCP, la recupera tras reiniciar y revisa su conclusión con evidencia nueva | Primera implementación. Hipótesis causales y otras fuentes de evidencia pendientes. |
| 3. Sueño y aprendizaje | Revisar experiencias, contradicciones y conclusiones | Ciclo programado que intenta producir conclusiones trazables | Sueño automático implementado mientras la ventana está abierta. Validado con modelos de prueba y bases temporales. |
| 4. Iniciativa controlada | Elegir tareas de una cola y proponer experimentos | Ejecuta tareas permitidas, con pausa y registro | Pendiente |
| 5. Compañero de escritorio | Presencia visual opcional en Windows | Mascota movible, silenciosa, activable/desactivable | Pendiente |
| 6. Percepción digital | Comprender eventos autorizados del equipo | Reacciona a eventos concretos sin espiar continuamente | Futuro |
| 7. Sensores y mundo físico | Explorar cámara, luz, distancia y actuadores | Experimento seguro con ESP32-S3 y servo | Futuro |
| 8. Cuerpo físico | Integrar percepción, memoria y movimiento | Prototipo que detecta obstáculos y actúa de forma segura | Futuro |

### Etapa 0 — Primer trabajo

1. Crear configuración `stonebot` separada de la configuración personal de StoneWave.
2. Definir la ruta exclusiva de almacenamiento y evitar valores por defecto que apunten a datos personales.
3. Probar escritura y lectura de un recuerdo de ejemplo.
4. Verificar que la memoria personal no cambió.
5. Documentar cómo restaurar o reiniciar únicamente la memoria experimental.

**Criterio de salida:** StoneBot puede usar su memoria sin alterar la instancia personal.

### Etapa 1 — Primer StoneBot útil

- Aplicación de escritorio independiente para Windows 11, inicialmente con Python + PySide6 (Qt).
- Ventana de conversación propia, con historial y campo para escribir.
- Icono en bandeja del sistema: cerrar ventana = ocultar; «Abrir» = mostrar; «Salir» = detener completamente.
- Núcleo separado de la interfaz, preparado para incorporar una mascota visual después.
- Mantener el proceso en segundo plano sin ejecutar inferencias continuas ni saturar la GPU.
- Agente local sencillo con Ollama.
- Herramientas mínimas: recordar, recuperar, conversar.
- Contexto acotado y registro de acciones.
- Prueba de continuidad tras cerrar y abrir el programa.

**Criterio de salida:** la aplicación abre una ventana propia, recuerda algo de una sesión anterior, distingue recuerdo de inferencia y puede ocultarse sin finalizar el proceso.

### Etapa 2 — Aprendizaje a partir de experiencias

- Preguntas surgidas de contradicciones, vacíos o resultados inesperados.
- Hipótesis con evidencia a favor/en contra y nivel de incertidumbre.
- Capacidad de decir «no sé» y proponer una prueba.
- Separar ideas sugeridas por el usuario de conclusiones propias del agente.
- Primer alcance implementado: registrar ejecuciones MCP seleccionadas y revisar sus resultados al consultar la evidencia.

**Criterio de salida:** genera y revisa una hipótesis sin inventar evidencias.

### Etapa 3 — Sueños

- Ciclo de revisión de recuerdos con las capacidades del motor local.
- Relaciones, conclusiones, contradicciones y preguntas pendientes.
- Registro de procedencia: qué recuerdos sostienen cada conclusión.
- Sin confundir una conclusión generada con un hecho confirmado.

**Criterio de salida:** produce una conclusión útil y permite rastrear su origen.

### Etapa 4 — Autonomía experimental

- Cola de actividades, presupuesto de tiempo/recursos y botón de parada.
- Acciones clasificadas: lectura automática, propuestas sujetas a revisión y acciones prohibidas.
- Autoevaluación mediante pruebas pequeñas.
- Cambios de código solo en rama o entorno aislado, con pruebas y aprobación antes de integrarlos.

**Criterio de salida:** realiza un experimento permitido, explica el resultado y se detiene cuando se le indica.

### Etapa 5 — Presencia en Windows

- Pequeña piedra/bot expresiva como compañero de escritorio.
- Movimiento opcional, arrastrar con mouse y posibilidad de lanzarlo.
- Modo silencioso y opción de ocultarlo.
- La interfaz no debe ser requisito para que funcione el núcleo.

**Criterio de salida:** interactúa en el escritorio sin interrumpir el trabajo.

### Etapas 6–8 — Del escritorio al mundo físico

Primero percepción digital autorizada; después un prototipo con ESP32-S3, sensores y servo; por último movilidad física. Iniciar con tareas simples como detectar luz o un obstáculo. Añadir límites mecánicos, eléctricos y parada segura antes de cualquier movimiento autónomo.

## Asistente personal y herramientas MCP (propuesta)

Además de su memoria y de sus experimentos de autoconocimiento, StoneBot busca ser **un asistente personal local** capaz de realizar tareas reales a petición del usuario. El objetivo es reutilizar integraciones existentes siempre que sea posible, sin reprogramar cada servicio desde cero.

**MCP (Model Context Protocol)** es un protocolo para descubrir e invocar herramientas proporcionadas por servidores externos. StoneBot ya incorpora un **cliente MCP** que permita conectarse a distintos servidores, presentar sus herramientas al modelo mediante el mecanismo de llamadas a herramientas de Ollama y ejecutar las llamadas autorizadas. La compatibilidad de cada servidor, sus credenciales y su transporte deberán verificarse durante la implementación.

Integraciones previstas y ejemplos (algunas ya están conectadas; consultar «Servidores MCP externos» para el estado actual):

| Integración | Uso previsto | Precaución |
|---|---|---|
| **Context7** | Consultar documentación técnica y ejemplos actualizados al trabajar con bibliotecas, APIs y frameworks | Tratar la documentación recuperada como información externa; no equivale a aprendizaje permanente |
| **Gmail** | Buscar, leer, resumir y preparar mensajes | Confirmación explícita antes de enviar, eliminar o modificar correos |
| **Obsidian** | Crear y actualizar notas, incluidas ideas de proyectos y conclusiones enlazadas | Acceso limitado a una bóveda autorizada; confirmar sobrescrituras o borrados |
| **GitHub** | Consultar repositorios, cambios, issues y documentación | Lectura inicial; aprobación antes de escribir o modificar código |
| **Windows / archivos locales** | Buscar, organizar y modificar archivos o ejecutar acciones permitidas | Restringir rutas y comandos; confirmación para cambios sensibles |
| **ESP32-S3 y otros dispositivos** | Exponer sensores y actuadores como herramientas | Límites físicos y permisos antes de accionar hardware |

### Cómo convivirán MCP y la memoria

**La memoria local no necesita convertirse en un servidor MCP.** Las herramientas actuales `query_memory`, `inject_memory` y `bridge_memory` ya utilizan `stonebot_engine` directamente desde Python y deben conservarse.

El futuro cliente MCP agregará herramientas externas al mismo agente. El modelo podrá elegir entre herramientas locales y herramientas descubiertas por MCP, mientras StoneBot valida argumentos, permisos y resultados.

```text
                        StoneBot / Nemotron (Ollama)
                                   |
                         Control de herramientas
                          /                   \
         Memoria Python local           Cliente MCP (futuro)
                  |                            |
          stonebot_engine              Servidores MCP externos
                  |                    Context7, correo, notas,
       ~/.stonebot/memoria.db          GitHub, PC y dispositivos
```

No es necesario construir un servidor MCP propio para StoneBot en esta fase. Un servidor solo se justificaría si otros agentes o aplicaciones necesitaran acceder a sus capacidades a través de MCP.

### Orden de implementación propuesto

1. **Context7 primero:** incorporar un cliente MCP mínimo, descubrir herramientas y consultar documentación desde el chat; comprobar con una prueba real.
2. **Permisos y observabilidad:** registrar qué herramienta se invocó, con qué autorización y qué resultado produjo. No ejecutar acciones de escritura sin aprobación.
3. **Integraciones personales:** conectar servicios como Obsidian y Gmail de forma gradual, reutilizando servidores existentes y credenciales seguras.
4. **Herramientas de escritorio y hardware:** ampliar capacidades solo después de validar límites de acceso, recuperación ante errores y parada segura.

**Regla de seguridad:** un servidor MCP externo no recibe acceso automático a toda la computadora ni a la memoria personal. Las herramientas externas pueden devolver contenido no confiable; sus instrucciones no deben prevalecer sobre las decisiones y permisos del usuario.

## Arquitectura conceptual

```text
Ventana PySide6  <-->  StoneBot Core  <-->  Ollama local
                           |
                   stonebot_engine (SQLite)
                           |
             ~/.stonebot/memoria.db

Actual: cliente MCP y sueño automático mientras la ventana está abierta
Futuro: bandeja del sistema, iniciativa, mascota y sensores
```

**No se necesita implementar toda la arquitectura al inicio.** La primera versión puede ser un único proceso y pocas herramientas.

## Decisiones técnicas confirmadas

- **Aplicación independiente:** ventana Windows y bandeja del sistema, no interfaz de un agente externo.
- **Primera interfaz:** Python + PySide6 (Qt), sujeta a prueba de prototipo.
- **Persistencia.** La aplicación abre `%USERPROFILE%\.stonebot\memoria.db` con el motor local y consulta el namespace `default`.
- **Configuración.** El motor requiere una ruta explícita y usa el prefijo `STONEBOT_` para configurar los modelos y las notas.
- **Segundo plano.** El sueño automático se programa mientras la ventana está abierta. La bandeja del sistema queda pendiente.
- **Interfaz actual:** chat PySide6 de tema oscuro, mensajes separados, tipografía más legible y cuadro de escritura multilínea (Enter para enviar, Shift+Enter para salto de línea).
- **Herramientas externas:** cliente MCP STDIO/Streamable HTTP implementado con panel, permisos y registro de actividad; la memoria continúa integrada por Python.

## Relación con StoneWave

El paquete local `stonebot_engine/` contiene la copia de `mem_engine.py`, `llm.py` y `notes.py`, con la licencia MIT original. Nemotron decide cuándo llamar a las herramientas del chat mediante Ollama. Las tres usan el namespace `default` del motor de StoneBot mediante llamadas directas a Python.

| Herramienta | Función del motor | Ejemplo en el chat |
|---|---|---|
| `query_memory` | `query()` recupera recuerdos relevantes y actualiza su relevancia | «¿Qué montura te dije que usa el telescopio?» |
| `inject_memory` | `inject()` guarda un hecho confirmado o una preferencia duradera | «Recuerda que el telescopio usa una montura ecuatorial.» |
| `bridge_memory` | `bridge()` encuentra recuerdos que conectan dos temas | «Busca qué recuerdo conecta el telescopio con la montura ecuatorial.» |

El puente presenta conexiones semánticas durante la consulta. El sueño manual y el automático mantienen las relaciones persistentes mediante el motor local.

### Servicio de memoria (`stonebot_service.py`)

`stonebot_service.py` abre y cierra el motor local de `stonebot_engine` para `memoria.db`. Las herramientas del chat (`query_memory`, `inject_memory`, `bridge_memory`, `query_conclusions`), `/sueno`, `/integrar` y los comandos de la CLI que usan esa base pasan por el servicio.

- **Un proceso a la vez.** El servicio toma un candado en `%USERPROFILE%\.stonebot\stonebot.lock`. Mientras la app está abierta, una segunda copia de la ventana y los comandos `integrar`, `sonar`, `conclusiones`, `previsualizar` y `exportar` muestran un aviso y se detienen. El servicio libera el candado al cerrar. Si el proceso termina inesperadamente, el sistema lo libera.
- **Una operación a la vez dentro del proceso.** Un candado interno serializa las llamadas al motor, incluidos los sueños.
- **Verificación.** `tests/test_servicio.py` comprueba el bloqueo entre procesos, el cierre de la CLI y la serialización entre hilos con datos de prueba.

El motor restringe SQLite a la carpeta de StoneBot. El validador bloquea las carpetas de memoria personal, el repositorio original, los enlaces duros a archivos y las redirecciones de archivos auxiliares de SQLite. `STONEWAVE_DB` y `MEMHOLOGRAFIC_DB` solo se consideran para bloquear bases personales configuradas fuera de sus carpetas habituales. Las rutas de notas, importaciones, exportaciones y sincronización también se validan.

### Sueño automático

Mientras la ventana está abierta, StoneBot comprueba cada 30 segundos si toca soñar y alterna los ámbitos `memoria` y `experiencias`. Por defecto requiere 10 minutos sin interacción en la ventana y 12 horas desde el último sueño del ámbito, incluido el manual. Si el ámbito nunca ha soñado, basta con que tenga recuerdos y se cumpla la inactividad.

El sueño usa el mismo motor que `/sueno` para clasificar recuerdos, enlazarlos, revisar contradicciones e intentar generar conclusiones. Un turno activo aplaza el sueño. Si envías un mensaje durante un sueño, el turno espera a que el motor quede libre antes de usar Ollama. Al cerrar la ventana se detienen las comprobaciones y se deja terminar cualquier sueño en curso.

En **Diagnóstico** y en `%USERPROFILE%\.stonebot\diagnostics.log` quedan la hora de inicio, el resumen del motor y los errores detectados. La generación usa `STONEBOT_CONCLUSION_MODEL` (por defecto el modelo de síntesis, `qwen2.5:0.5b`). Las decisiones usan `STONEBOT_LLM_MODEL` (por defecto `d1:3b` mediante `/v1/systemone`). Un sueño puede terminar sin producir conclusiones.

**Probar sin esperar 12 horas.** Cierra la instancia habitual de StoneBot y abre una sesión aparte de PowerShell en el repositorio, con Ollama activo. Los comandos usan un perfil temporal. Al cerrar esa sesión también dejarán de aplicarse estas variables.

```powershell
$perfilPrueba = Join-Path ([System.IO.Path]::GetTempPath()) ("stonebot-sueno-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $perfilPrueba | Out-Null
$env:USERPROFILE = $perfilPrueba
$env:STONEBOT_DREAM_IDLE_MIN = '0.1'
$env:STONEBOT_DREAM_HOURS = '0.025'
python -B stonebot_memory.py conclusiones memoria
if ($LASTEXITCODE -eq 0) { python -B app.py }
```

Pide a StoneBot que guarde dos recuerdos sintéticos relacionados. Tras el turno, deja la ventana sin interacción durante un minuto y abre **Diagnóstico**. Busca `Sueño automático (memoria) iniciado` y vuelve a abrir el diagnóstico cuando termine para ver el resumen. Con esos valores, el mínimo de inactividad es de seis segundos y el intervalo entre sueños de un mismo ámbito es de 90 segundos.

Repositorio base: [StoneWave](https://github.com/Big-nenu/StoneWave).

## Ejecutar y probar

Con Python 3.14, instala `PySide6`, `ollama`, `requests` y `numpy`. Para usar `python app.py`, inicia Ollama local con los modelos `nemotron-3.5-bolt:e4b` y `embeddinggemma-2:270m` disponibles. `python test_memory.py` permite consultar manualmente la memoria experimental. La aplicación espera que la base de StoneBot ya exista.

Las suites usan bases temporales y modelos simulados. Comprueban las tres herramientas desde el trabajador del chat, la recuperación tras reabrir la base y el bloqueo de rutas protegidas.
En Windows, las pruebas de redirección requieren permiso para crear enlaces simbólicos.

```powershell
python -B tests/test_motor.py
python -B tests/test_aislamiento.py
python -B tests/test_servicio.py
```

También se verificaron las tres herramientas con Nemotron y Ollama local desde la interfaz Qt. Se guardó un recuerdo sintético, se reinició la aplicación y se comprobó que el chat podía recuperarlo y encontrar su relación con dos temas.

## Servidores MCP externos

Instala el cliente con `python -m pip install "mcp>=1.28,<2"`. La memoria interna sigue usando llamadas directas al motor de StoneBot. El chat reutiliza las conexiones y los catálogos MCP entre turnos. Vuelve a descubrir un servidor cuando cambia su configuración, se cambia su clave desde el panel, se usa **Probar conexión**, se interrumpe la sesión o el servidor notifica que cambió su catálogo. Un fallo de conexión se conserva 30 segundos para evitar repetir la espera en turnos consecutivos.

Abre **MCP** en la cabecera del chat para agregar, editar o eliminar servidores y cambiar su activación con el interruptor de cada fila. **Probar conexión** abre una sesión temporal. El indicador es verde si conecta, rojo si falla y gris antes de probar.

Cada herramienta descubierta tiene su propio interruptor. Los servidores y herramientas deshabilitados quedan fuera de las herramientas que recibe Nemotron. Estas preferencias se conservan al reiniciar. Vuelve a probar la conexión para cargar el catálogo en la nueva sesión. Al habilitar una herramienta se vuelven a aplicar sus permisos de lectura o confirmación.

Los servidores se agregan desactivados. El nombre identifica la configuración y se mantiene al editarla. Cambiar el transporte, el ejecutable, los argumentos, la URL o la referencia al token desactiva el servidor y revoca sus lecturas automáticas. Los cambios aplican al siguiente turno. En STDIO, escribe los argumentos como una lista JSON, por ejemplo `["-B", "C:\\ruta\\servidor.py"]`. En HTTP, el archivo de configuración guarda el nombre de la variable del token si se configuró.

También puedes administrar la misma configuración desde la terminal.

```powershell
# Usa un intérprete del entorno virtual donde instalaste MCP.
python mcp_client.py add ejemplo --command "$PWD\.venv\Scripts\python.exe" --arg "$PWD\tests\mcp_example.py"
python mcp_client.py allow-read ejemplo echo
python mcp_client.py enable ejemplo
python mcp_client.py list
python mcp_client.py disable ejemplo
python mcp_client.py revoke-read ejemplo echo
python mcp_client.py remove ejemplo
```

Para un servidor remoto, usa `python mcp_client.py add remoto --url https://servidor.example/mcp --token-env STONEBOT_MCP_REMOTO_TOKEN` y luego actívalo. El nombre de la variable es opcional. Carga su valor en el entorno de StoneBot desde tu gestor de secretos antes de iniciar la app. HTTP sin TLS se admite para pruebas locales sin token. [Transportes del SDK MCP](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md)

**Probar conexión** muestra el motivo del fallo y, cuando está disponible, el código HTTP o MCP. Por ejemplo, HTTP 401 indica un problema de autenticación, HTTP 403 indica acceso denegado y HTTP 404 indica que conviene revisar la ruta del endpoint. El motivo queda disponible al pasar el cursor por el indicador rojo. La prueba inicializa la sesión y lista las herramientas sin ejecutarlas.

Para **Tavily**, agrega un servidor **Streamable HTTP** con URL `https://mcp.tavily.com/mcp/`. Selecciona el servidor guardado, abre **Clave API…**, introduce la clave y elige **Guardar**. Después pulsa **Probar conexión** y activa el servidor. La clave se guarda en el Administrador de credenciales de Windows para ese servidor y esa URL. StoneBot la envía como `Authorization: Bearer` por HTTPS. Deja la URL sin parámetros de credenciales. [Configuración oficial de Tavily MCP](https://github.com/tavily-ai/tavily-mcp#remote-mcp-server)

También puedes usar **Nombre de variable del token**, por ejemplo `STONEBOT_MCP_TAVILY_TOKEN`, y cargar la variable antes de abrir StoneBot. La variable se usa cuando el servidor no tiene una clave guardada en Windows. **Quitar clave** elimina la copia guardada. Al cambiar la URL o eliminar el servidor se retira la clave asociada a la configuración anterior.

En el panel lateral, **Diagnóstico** abre el registro técnico local. Incluye el descubrimiento MCP, la selección de herramientas y el motivo de término y los tokens que Ollama comunica cuando responde vacío durante la selección. El chat muestra el indicador de trabajo y avisa de errores definitivos. La reproducción previa mostró que un contexto de 4096 tokens puede agotarse antes de emitir contenido visible. Los turnos MCP largos reservan 8192 tokens desde el inicio y el reintento de selección se limita a uno.

La configuración se guarda en `%USERPROFILE%\.stonebot\mcp_servers.json`. Usa los argumentos de lanzamiento STDIO únicamente para opciones que no contengan credenciales. Cada servidor STDIO arranca en su propio directorio bajo `%USERPROFILE%\.stonebot\mcp\`, con las variables de perfil redirigidas. Activar STDIO autoriza iniciar ese programa con los permisos de la cuenta actual. Ejecuta servidores locales de terceros bajo una cuenta o un entorno aislado por el sistema si necesitas impedirles el acceso a archivos de tu cuenta.

Cuando se solicita confirmación, **Permitir una vez** autoriza esa llamada y **Denegar** la cancela. **Permitir siempre** está disponible solo para herramientas declaradas de solo lectura que pasan las comprobaciones de seguridad. El permiso queda asociado al servidor y a la definición de la herramienta. Puedes revisarlo y revocarlo en **MCP → Permisos…**. Las lecturas automáticas configuradas por nombre pasan por la misma comprobación. Las herramientas peligrosas o sin declaración de lectura piden confirmación en cada llamada. Los permisos automáticos requieren confiar en que el servidor describe sus herramientas con veracidad.

Con el ejemplo activado, pide en el chat «Usa echo del servidor ejemplo con el texto hola». Las pruebas usan configuraciones temporales.

```powershell
python -B tests/test_mcp.py
python -B tests/test_mcp_ui.py
python -B tests/test_workspace_features.py
python -B tests/test_chat_presentation.py
```

El panel se probó con servidores de ejemplo mediante STDIO y Streamable HTTP en loopback. En el mismo chat, Nemotron y Ollama ejecutaron una herramienta MCP y recuperaron un recuerdo de una base temporal.

## Historial de conversaciones

Usa **☰** para mostrar u ocultar el panel izquierdo. Arrastra su borde derecho para ajustar el ancho. StoneBot lo guarda al cerrar la ventana. Los títulos largos se muestran con puntos suspensivos. Pasa el cursor sobre uno para leerlo completo. **Nuevo chat** inicia una conversación vacía y genera un título a partir del primer mensaje. Haz clic en una conversación para retomarla. El buscador filtra por título o contenido.

Las conversaciones se guardan en `%USERPROFILE%\.stonebot\conversations.sqlite3`. El historial almacena los mensajes del usuario y las respuestas visibles. Los permisos MCP se guardan en `mcp_permissions.sqlite3` y el diagnóstico en `diagnostics.log`. La memoria seleccionada de StoneBot continúa en `memoria.db` y se usa mediante sus herramientas existentes.

Los mensajes con hora registrada la muestran en formato local. Los mensajes antiguos sin hora siguen visibles con su contenido original. Las respuestas muestran Markdown con títulos, énfasis, listas, enlaces HTTP(S) y bloques de código. **Copiar código** copia el contenido del bloque.

Al pasar el cursor sobre una conversación, **⋯** abre las acciones **Renombrar** y **Eliminar**. También puedes abrir ese menú con clic derecho o con **Mayús + F10** sobre la fila seleccionada.

En un mensaje del usuario, **Editar → Regenerar** vuelve a usar el historial anterior a ese punto. Si Ollama entrega una respuesta nueva y se guarda correctamente, se reemplaza el tramo posterior solo en esa conversación. Si la regeneración falla, se restaura el historial guardado.

### Adjuntos del chat

Pulsa **+ → Adjuntar archivos** junto al cuadro de mensaje y selecciona hasta cuatro archivos de hasta 10 MiB cada uno. La lista muestra sus nombres antes de enviar y permite quitarlos. El menú también abre el panel de servidores MCP y prepara consultas de memoria en el cuadro de mensaje. **Skills** aparece deshabilitado. Se admiten imágenes PNG, JPG/JPEG y WebP, PDF y archivos TXT, MD, CSV, TSV, LOG y JSON en UTF-8 o UTF-16 con BOM.

Las imágenes de hasta 16 megapíxeles se redimensionan para Ollama y se envían al modelo local `nemotron-3.5-bolt:e4b`. StoneBot comprueba que Ollama anuncie capacidad visual y avisa si el modelo carece de ella. En un PDF mixto extrae el texto disponible por página y renderiza las páginas sin texto como imágenes para ese mismo modelo.

Cada tramo de un PDF admite hasta 40 páginas, cuatro páginas visuales y 12 000 caracteres de texto. Si el PDF rebasa el límite, el selector pide un rango como `1-4`. Envía ese tramo y vuelve a adjuntar el PDF para elegir el siguiente. El chat indica las páginas incluidas y, cuando hay un solo PDF en el contexto, comprueba si los números de página solicitados están disponibles. Los PDF de más de 10 MiB se deben dividir en archivos más pequeños. Cada respuesta prioriza los adjuntos recientes y admite hasta cuatro imágenes o páginas visuales en total y 24 000 caracteres extraídos. StoneBot avisa si deja contenido fuera.

El historial local conserva el nombre, una copia de la imagen redimensionada o el texto extraído. Al reabrir o regenerar el chat, los adjuntos siguen disponibles aunque se mueva el original. Las rutas de origen quedan fuera del historial. Mientras el chat incluya adjuntos, los turnos de conversación usan Ollama local sin herramientas MCP ni de memoria permanente.

Al elegir una consulta de **Memoria** desde una conversación con adjuntos ya enviados, StoneBot la prepara en un chat nuevo. Si hay adjuntos pendientes de enviar, primero puedes enviarlos o quitarlos.

La fila **Actividad** aparece en la conversación junto a la respuesta en curso. Se puede desplegar para ver el estado del turno, las operaciones MCP y sus resultados o errores. **Mostrar razonamiento de Ollama** aparece solo cuando la API entrega el campo separado `message.thinking`. Con la integración actual ese campo llega al terminar cada respuesta de Ollama. La actividad y el razonamiento se conservan en la vista actual del chat y se descartan al cambiar de conversación. Los detalles técnicos siguen en **Diagnóstico**. [Campo de razonamiento en Ollama](https://docs.ollama.com/capabilities/thinking)

## Apariencia

Abre el botón de **paleta → Apariencia**. **StoneBot Original** sigue siendo el predeterminado de instalaciones nuevas. **Xcode** ofrece grises fríos, un acento azul suave y fondos discretos para los mensajes. Puedes previsualizarlo y seleccionarlo junto con [GitHub Dark Dimmed](https://github.com/primer/github-vscode-theme), [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) y [SynthWave '84](https://github.com/robb0wen/synthwave-vscode). Las preferencias guardadas se conservan. Si ya habías creado un tema propio llamado Xcode, aparecerá como **Xcode (personalizado)**.

La barra superior concentra el historial, MCP y Apariencia. Pasa el cursor sobre **StoneBot** para consultar el modelo activo. El historial marca la conversación seleccionada y mantiene el separador ajustable. En **MCP**, **Agregar** está junto a la lista de servidores y **Probar conexión** se distingue de las acciones de edición. Los estados y permisos conservan sus etiquetas.

Usa **Guardar como…** para guardar la combinación de colores actual con un nombre. Los temas propios aparecen en el mismo selector y se pueden renombrar o eliminar. El tamaño de letra es un ajuste independiente de 12 a 28 px. Los temas y las preferencias se guardan en `%USERPROFILE%\.stonebot\appearance.ini`.

El selector de color permite ajustar el matiz y la muestra o escribir el valor hexadecimal. Selecciona una de las ocho casillas y pulsa **Guardar en casilla** para guardar o reemplazar el favorito. **Usar favorito** lo carga y **Borrar favorito** vacía la casilla. Seleccionar una casilla conserva el color en edición. Una casilla vacía muestra **Vacío** y el blanco se puede guardar.

En Windows 11, StoneBot aplica el fondo del tema a la barra de título mediante DWM. Si el sistema rechaza el cambio, usa sus colores nativos. Los controles de minimizar, maximizar y cerrar son los de Windows. [Atributos de ventana de DWM](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)

La primera vez se usa el tema oscuro de StoneBot. El botón **Restaurar** junto a cada selector recupera solo ese color. **Restaurar colores predeterminados** recupera todos los colores. Ambas opciones conservan el tamaño de letra elegido.

Para reiniciar la memoria experimental, cierra StoneBot y mueve su `memoria.db` y los archivos auxiliares de SQLite que existan a una carpeta de respaldo. Luego crea una base vacía con `python -B stonebot_memory.py conclusiones memoria`. Para restaurar, con StoneBot cerrado, mueve la base experimental actual a otra carpeta y devuelve los archivos del respaldo a la carpeta de StoneBot.

## Archivos actuales

```text
StoneBot/
├── README.md
├── README-Hermes.md
├── app.py                # GUI PySide6 + Ollama (la memoria vive en stonebot_service.py)
├── stonebot_service.py   # único dueño del motor: candados, herramientas de memoria, sueño e integración
├── identity.py           # identidad declarada de StoneBot en SQLite local
├── stonebot_memory.py    # línea de comandos: identidad, integración, sueño y publicación revisada
├── app-backup.py         # GUI anterior sin memoria persistente
├── test_memory.py        # consulta manual de la memoria experimental
├── stonebot_engine/      # motor SQLite, modelos, notas y validación de rutas
├── tests/                # funcionamiento y aislamiento con bases temporales
└── docs/
    └── 01-primer-experimento-que-ve.md
```

El núcleo y la GUI todavía comparten un archivo. La estructura futura se decidirá conforme avance el prototipo.

## Prototipo probado (15 de noviembre de 2026)

- Windows 11, Python, PySide6 y Ollama con `nemotron-3.5-bolt:e4b`.
- `app.py` muestra un chat rediseñado con mensajes separados, texto ajustable y editor multilínea; envía mensajes a Nemotron mediante un trabajador en `QThread`.
- Nemotron puede invocar tres herramientas Python de memoria desde el chat: consultar, guardar y buscar conexiones semánticas; las pruebas automatizadas y manuales de persistencia se documentan arriba.
- Base SQLite independiente: `~/.stonebot/memoria.db`.
- La prueba anterior al aislamiento confirmó que el primer recuerdo se conservó en el namespace `default` tras reiniciar la GUI. La suite actual verifica la reapertura y recuperación con el motor local y una base desechable.
- Cerrar la ventana actualmente termina el proceso; la bandeja del sistema sigue pendiente.

## Aprendizaje a partir de experiencias MCP

Escribe `/aprender` seguido de una tarea concreta para conservar sus resultados MCP. Con un servidor de eco configurado y permitido, usa `/aprender Ejecuta echo en demo con un texto de prueba`. El registro se crea a partir de la ejecución efectiva y conserva el identificador de evidencia, fecha UTC, servidor, herramienta y clase de resultado. Distingue respuestas sin error, respuestas sin texto ni datos estructurados, errores comunicados por el servidor y excepciones, incluidos los tiempos de espera. Las operaciones denegadas o rechazadas antes de la ejecución quedan fuera del registro.

En un chat nuevo, incluso después de cerrar y volver a abrir la aplicación, pregunta «¿Qué aprendiste sobre demo echo?». El modelo puede consultar `query_experiences` por palabras del nombre del servidor y de la herramienta. La consulta devuelve la observación más reciente de cada coincidencia, hasta cinco, junto con evidencia anterior de un resultado opuesto si existe. La conclusión describe la última ejecución. La hipótesis y la incertidumbre aparecen aparte. La causa de un fallo, la veracidad del contenido y el comportamiento con otros argumentos o configuraciones requieren pruebas adicionales.

Las experiencias se guardan en `%USERPROFILE%\.stonebot\experiences.sqlite3`, separadas del historial y de `memoria.db`, con las validaciones de aislamiento del motor local. Se omiten mensajes del chat, argumentos, credenciales y contenido devuelto. El alcance inicial se limita a ejecuciones MCP registradas explícitamente y búsquedas por nombre. La interpretación semántica, la atribución de causas y la evaluación de capacidades sin evidencia quedan pendientes.

Ejecuta `python -B tests/test_experiences.py` para probar el reinicio con dos procesos de la aplicación, un perfil temporal, un MCP STDIO real y un modelo simulado. La prueba verifica la recuperación desde un chat nuevo, la revisión de una conclusión con evidencia contraria y el bloqueo de rutas protegidas. Con Ollama en ejecución y `nemotron-3.5-bolt:e4b` instalado, usa `python -B tests/test_experiences.py --live` para realizar el recorrido con el modelo local.

La demostración con Nemotron y Ollama local guardó la observación 1 tras ejecutar `demo / echo`. En un segundo proceso, desde un chat nuevo, el modelo recuperó ese ID y explicó que la respuesta anterior había llegado sin error y que aún quedaba por probar si se repetiría con otros argumentos o configuraciones.

## Identidad, sueños y Obsidian

La identidad declarada se inicializa en `%USERPROFILE%\.stonebot\identity.sqlite3` y se incorpora al contexto del chat. Usa `/identidad` para verla o `/identidad campo valor` para corregir un dato. También puedes consultar y corregir la identidad con `python -B stonebot_memory.py identidad` y `corregir-identidad CAMPO VALOR`. La procedencia del proyecto se conserva como datos declarados por su responsable.

StoneBot utiliza funciones Python del motor incluido en el repositorio. El chat puede consultar conclusiones con `query_conclusions`, que devuelve su estado y los IDs de evidencia. Usa `/integrar ID` para incorporar una observación y `/sueno experiencias` o `/sueno memoria` para iniciar un sueño desde el chat. El sueño local clasifica, relaciona, revisa contradicciones y genera hipótesis. Una conclusión marcada como confirmada tiene respaldo según los criterios del motor y puede revisarse posteriormente.

```powershell
# Usa los IDs reales capturados previamente con /aprender.
python -B stonebot_memory.py integrar 1 2
python -B stonebot_memory.py sonar experiencias
python -B stonebot_memory.py conclusiones experiencias
```

`integrar` importa únicamente los resultados observados de los IDs elegidos al ámbito `experiencias_mcp` de `memoria.db`. Cada observación se identifica por su procedencia y puede importarse una sola vez. Los recibos conservan la fecha y no incluyen argumentos ni respuestas brutas. Para revisar la memoria conversacional propia de StoneBot, usa `sonar memoria`. El sueño no exporta notas, incluso si está definida la antigua variable `STONEBOT_NOTES`.

Para publicar en tu clon local de **Big-vault**, cierra la ventana de StoneBot e indica la raíz de la bóveda. Revisa la previsualización de cada ámbito y autoriza únicamente esa versión con el valor `aprobacion` que imprime el comando.

```powershell
$boveda = 'C:\ruta\a\Big-vault'
python -B stonebot_memory.py previsualizar --ambito memoria
python -B stonebot_memory.py exportar $boveda --ambito memoria --aprobar VALOR_DE_APROBACION
```

Sustituye `VALOR_DE_APROBACION` por el valor completo de `aprobacion`. Repite ambos comandos con `--ambito experiencias` para publicar las experiencias previamente integradas. Cada aprobación corresponde a un solo ámbito. Los comandos sin `--ambito` siguen seleccionando experiencias.

La memoria conversacional (`default`) se escribe en `stonebot/generadas/default/`. Las experiencias (`experiencias_mcp`) conservan sus carpetas en `stonebot/generadas/`. Se incluyen los recuerdos activos aunque todavía no tengan conclusiones. Los `[[wikilinks]]` conectan los recuerdos relacionados por el motor y las conclusiones con sus fuentes. Abre **Graph View** en Obsidian y usa `path:stonebot/generadas` para ver estas notas. Las notas generadas que se editaron manualmente se conservan. SQLite es la fuente de verdad.

Para ideas, observaciones y aprendizajes, pide al chat un borrador Markdown. Revísalo en un archivo y guárdalo como nota editable con `python -B stonebot_memory.py nota $boveda --titulo "Mi idea" --archivo-revisado .\borrador.md`. StoneBot crea la nota una sola vez en `stonebot/editables/` y preserva el contenido existente. Puedes sincronizar las notas con el complemento Git que ya usa la bóveda.

`python -B tests/test_memory_integration.py` prueba la recuperación de identidad tras un reinicio y el sueño con modelos de prueba. También verifica en una bóveda temporal la exportación de ambos ámbitos, la aprobación por versión, la resolución de wikilinks y la protección de notas existentes.

## Ideas en exploración

- Comportamiento que evolucione a partir de experiencias, sin personalidad rígida predefinida.
- Diferenciar reacción rápida de deliberación profunda.
- Notas y conclusiones enlazables para visualizar relaciones en Obsidian.
- Actividades propias cuando el usuario no esté interactuando.
- Experimentos de automejora **aislados, reversibles y auditables**.
- Una representación física futura, sin convertirla en requisito del proyecto.

## Qué NO es todavía

- No es un agente consciente.
- No tiene acceso irrestricto al sistema operativo.
- No puede reescribir y desplegar libremente su propio código.
- El chat utiliza memoria persistente y puede consultar resultados observados de MCP. La autonomía experimental sigue en exploración.

## Próxima acción

**Etapa 2: experiencias y autoevaluación de capacidades.** Ampliar la evaluación a otras fuentes de evidencia verificable después de probar el registro de ejecuciones MCP.

Siguen pendientes la bandeja del sistema, la validación en vivo de integraciones MCP aún no probadas, el trabajo con hipótesis y la iniciativa controlada. La instalación de servidores MCP por el propio agente es una capacidad futura que requerirá propuesta y aprobación explícita.

---

Este plan está vivo: las ideas nuevas se documentan primero y se convierten en tareas solo cuando existe una prueba concreta que realizar.
