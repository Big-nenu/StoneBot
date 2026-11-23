# StoneBot

> Un asistente personal local que conversa, recuerda y realiza tareas con Ollama y herramientas MCP.

**Estado:** prototipo conversacional con herramientas de memoria persistente · **Inicio:** noviembre de 2026 · **Enfoque:** experimentación incremental, local-first.

## Visión

StoneBot es un asistente personal local. Mantiene continuidad entre sesiones con StoneWave y combina el chat con herramientas para ayudar al usuario a realizar tareas y verificar resultados.

## Principios

- **Primero razonamiento; después apariencia y cuerpo.**
- **Memoria personal en StoneWave.** StoneBot consulta y actualiza recuerdos mediante MCP. El servidor de StoneWave administra su SQLite y las pruebas usan una base temporal.
- **Local-first:** Ollama y modelos adecuados a una RTX 4060 de 8 GB; servicios externos opcionales, nunca obligatorios.
- **Un modelo cargado a la vez** cuando compartir GPU cause conflictos.
- **Autonomía graduada:** observar y proponer antes de actuar; pedir permiso para acciones sensibles.
- **Experimentos verificables:** registrar hipótesis, evidencias, fallos y conclusiones.
- **Pocos componentes, interfaces claras y pruebas pequeñas.**
- **Aplicación propia de Windows:** StoneBot no depende de la interfaz de Cline, Hermes ni Claude.
- **Núcleo independiente de la ventana:** cerrar la ventana lo deja en segundo plano; «Salir» detiene el proceso.

## Hoja de ruta

Las primeras etapas documentan el prototipo original. La configuración vigente está en **Memoria personal en StoneWave**.

| Etapa | Objetivo | Entregable comprobable | Estado |
|---|---|---|---|
| 0. Base segura | Definir alcance y separar la memoria | Motor local y base SQLite exclusiva | Completada. Lectura, escritura y rutas protegidas verificadas con bases de prueba. |
| 1. Núcleo conversacional | Aplicación Windows con chat, Ollama y motor local | Conversa, recuerda y permanece en la bandeja al cerrar la ventana | Chat, historial, temas, memoria y bandeja operativos. |
| 1B. Herramientas externas (MCP) | Cliente MCP reutilizable y primeras integraciones | Descubre e invoca herramientas desde el chat con controles de permiso | Implementada en prototipo. Cliente STDIO/HTTP, panel y permisos; Context7 y Exa comprobados en pruebas, Tavily pendiente de prueba en vivo según última revisión. | 
| 2. Aprendizaje de experiencias | Evaluar capacidades a partir de resultados observados | Registra una ejecución MCP, la recupera tras reiniciar y revisa su conclusión con evidencia nueva | Primera implementación. Hipótesis causales y otras fuentes de evidencia pendientes. |
| 3. Sueño y aprendizaje | Revisar experiencias, contradicciones y conclusiones | Ciclo programado que intenta producir conclusiones trazables | Sueño automático disponible con la ventana visible u oculta en la bandeja. |
| 4. Iniciativa controlada | Elegir tareas de una cola y proponer experimentos | Ejecuta tareas permitidas, con pausa y registro | Primer alcance en el chat: plan, ejecución de lecturas y revisión de evidencia. Cola y ejecución desatendida pendientes. |
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

- Primer alcance disponible: tareas reanudables de solo lectura en el chat.
- Cola de actividades, presupuesto de tiempo/recursos y botón de parada.
- Acciones clasificadas: lectura automática, propuestas sujetas a revisión y acciones prohibidas.
- Autoevaluación mediante pruebas pequeñas.
- Cambios de código solo en rama o entorno aislado, con pruebas y aprobación antes de integrarlos.
- Futuro: detectar bibliotecas Python faltantes, proponer paquete, versión y entorno, y pedir autorización antes de instalar, preferentemente en un entorno virtual aislado.

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

### Orden de implementación propuesto

1. **Context7 primero:** incorporar un cliente MCP mínimo, descubrir herramientas y consultar documentación desde el chat; comprobar con una prueba real.
2. **Permisos y observabilidad:** registrar qué herramienta se invocó, con qué autorización y qué resultado produjo. No ejecutar acciones de escritura sin aprobación.
3. **Integraciones personales:** conectar servicios como Obsidian y Gmail de forma gradual, reutilizando servidores existentes y credenciales seguras.
4. **Herramientas de escritorio y hardware:** ampliar capacidades solo después de validar límites de acceso, recuperación ante errores y parada segura.

**Regla de seguridad:** un servidor MCP externo no recibe acceso automático a toda la computadora ni a la memoria personal. Las herramientas externas pueden devolver contenido no confiable; sus instrucciones no deben prevalecer sobre las decisiones y permisos del usuario.

## Memoria personal en StoneWave

StoneBot inicia el servidor STDIO del repositorio hermano `StoneWave/mcp_server.py` con el mismo entorno de Python. Usa la base personal existente en `%USERPROFILE%\.stonewave\memoria.db` y el namespace `default`. Si tu instalación ya usa otra base o namespace, inicia SB con los mismos valores de `STONEWAVE_DB` y `STONEWAVE_NAMESPACE`. La ruta de la base debe ser absoluta y el archivo debe existir.

En el chat puedes decir «Recuerda que…» o preguntar por un dato de otra conversación. **+ → Memoria → Ver y corregir recuerdos…** lista los recuerdos vigentes e indica el ID para corregirlos u olvidarlos. En el mismo menú puedes activar o desactivar **Guardar recuerdos automáticamente**.

### Ajustes de StoneWave

En **Configuración → Servidores MCP…**, selecciona **StoneWave · Integrado** para ver sus herramientas y para qué sirve cada una. Desde ahí, **Ajustes de StoneWave…** permite programar o ejecutar un sueño, activar las conclusiones, elegir su modelo local de Ollama, configurar la carpeta de Obsidian y usar un archivo compartido para sincronizar. **Aplicar cambios** reinicia la sesión integrada. El comando `/sueno memoria` también ejecuta un sueño manual.

### Consultar sueños y notas desde el chat

- «¿Cuándo fue el último sueño de SW?», «¿Qué recuerdos relacionó?» y «¿Qué conclusiones generó?» consultan la última ejecución registrada, tanto manual como automática.
- «¿Qué notas creó o actualizó el último sueño en Obsidian?» muestra qué archivos cambió esa ejecución. Los sueños anteriores al registro detallado solo muestran su fecha.
- «Dime las últimas 3 notas de Obsidian» consulta las notas recientes de la carpeta configurada y muestra su texto en el chat. Una pregunta de seguimiento como «¿Y qué escribiste ahí?» puede usar el modelo para identificar qué consulta hacer. SB obtiene el resultado por la conexión integrada de SW.

El asistente usa únicamente SW para sus recuerdos personales. Si SW no está disponible, un guardado explícito informa el error. El historial, los proyectos, la identidad de SB y los resultados operativos de encargos conservan su almacenamiento de aplicación.

La base experimental `%USERPROFILE%\.stonebot\memoria.db` y su CLI se conservan para revisión posterior. El motor local mantiene las validaciones que impiden abrir directamente la base de SW.

## Ejecutar y probar

Con Python 3.14, instala `PySide6`, `ollama`, `mcp`, `requests`, `numpy`, `PyYAML`, `markdown-it-py` y `Pygments`. Inicia Ollama local con `nemotron-3.5-bolt:e4b` y el modelo de embeddings que usa tu instalación de SW. Desde el repositorio de SB, inicia `python -B app.py`.

### Modelo y proveedor

En el engrane de **Configuración**, abre **Modelo y proveedor de IA**. Usa **Ollama** para conversar en el equipo local o **OpenRouter** para usar un modelo en la nube. Pulsa **Cargar modelos** y busca por nombre o identificador. En OpenRouter, **Solo gratuitos** muestra las variantes `:free` y el selector gratuito si están disponibles en el catálogo de modelos compatibles con herramientas. Selecciona un resultado para rellenar el identificador. StoneBot recuerda el último modelo de cada proveedor en este equipo. El indicador de la parte inferior izquierda también abre esta configuración.

Para OpenRouter, introduce tu clave API para guardarla en el Administrador de credenciales de Windows con `pywin32`, o configura `OPENROUTER_API_KEY`. El proveedor recibe el contexto del chat y los adjuntos que envíes. El contexto recuperado de StoneWave solo se incluye si activas esa opción. StoneWave sigue usando sus propios modelos locales de embeddings para buscar y guardar recuerdos, aunque el modelo del chat esté en la nube.

### Abrir desde Windows

Para instalar o volver a crear el acceso directo, ejecuta una vez `powershell -NoProfile -ExecutionPolicy Bypass -File .\crear_acceso_directo.ps1` desde el repositorio con el entorno Python habitual. El acceso **StoneBot** del Escritorio usa `pythonw.exe` y abre la aplicación sin consola. El icono de la bandeja y del acceso se puede reemplazar en `assets/stonebot.ico`.

La **X** oculta StoneBot. Haz clic en el icono **SB** de la bandeja o usa **Abrir StoneBot**. Para cerrarlo del todo, abre el menú de la bandeja y elige **Salir**. Usa **Salir** antes de ejecutar los comandos de memoria desde una terminal, porque el proceso oculto conserva el candado. Si la bandeja de Windows no está disponible, la X cierra la aplicación.

Las suites usan bases temporales y modelos simulados. Comprueban las tres herramientas desde el trabajador del chat, la recuperación tras reabrir la base y el bloqueo de rutas protegidas.
En Windows, las pruebas de redirección requieren permiso para crear enlaces simbólicos.

```powershell
python -B tests/test_motor.py
python -B tests/test_aislamiento.py
python -B tests/test_servicio.py
python -B tests/test_tray.py
```

También se verificaron las tres herramientas con Nemotron y Ollama local desde la interfaz Qt. Se guardó un recuerdo sintético, se reinició la aplicación y se comprobó que el chat podía recuperarlo y encontrar su relación con dos temas.

## Servidores MCP externos

Instala el cliente con `python -m pip install "mcp>=1.28,<2"`. La memoria interna sigue usando llamadas directas al motor de StoneBot. El chat reutiliza las conexiones y los catálogos MCP entre turnos. Vuelve a descubrir un servidor cuando cambia su configuración, se cambia su clave desde el panel, se usa **Probar conexión**, se interrumpe la sesión o el servidor notifica que cambió su catálogo. Un fallo de conexión se conserva 30 segundos para evitar repetir la espera en turnos consecutivos.

Abre **MCP** en la cabecera del chat para agregar, editar o eliminar servidores y cambiar su activación con el interruptor de cada fila. **Probar conexión** abre una sesión temporal. El indicador es verde si conecta, rojo si falla y gris antes de probar.

Despliega una categoría para ver el tipo, la activación y el permiso de cada herramienta. El interruptor de la categoría cambia la activación de todo el grupo sin otorgar permisos. Selecciona una categoría o varias herramientas con **Ctrl** o **Mayús** y usa **Permisos de selección…** para pedir confirmación o autorizar explícitamente las lecturas compatibles.

Para agregar un servidor desde el chat, escribe **Instala este MCP** y pega el bloque JSON oficial `mcpServers` de un solo servidor. También puedes usar `/mcp instalar NOMBRE URL` para un endpoint Streamable HTTP o pegar una línea simple `npx -y PAQUETE` o `uvx PAQUETE` después de `/mcp instalar`. Las instrucciones de alta quedan fuera del historial. Si se necesita autenticación Bearer, indica el nombre de una variable `STONEBOT_MCP_…`, o usa un marcador `Bearer ${VARIABLE}` en el ejemplo oficial. Configura el valor fuera del chat antes de probar.

Revisa la URL, el ejecutable y los argumentos antes de pulsar **Autorizar y probar**. En STDIO se inicia el ejecutable para comprobar la conexión. `npx` y `uvx` pueden descargar y ejecutar el paquete en su caché. El alta no ejecuta bloques de comandos de shell ni instaladores independientes. Si la prueba funciona, el servidor aparece desactivado y sin permisos automáticos. Actívalo desde **+ → MCP** o desde el panel de la cabecera.

Para Desktop Commander, envía `/mcp instalar` y en la línea siguiente `npx -y @wonderwhy-er/desktop-commander@latest`. La primera prueba puede tardar unos dos minutos con una caché vacía. Cada herramienta recién descubierta queda desactivada. Habilita las que elijas en el panel **MCP**, donde también se gestionan las autorizaciones.

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

Cuando se solicita confirmación, **Permitir una vez** autoriza esa llamada y **Denegar** la cancela. **Permitir siempre** está disponible solo para herramientas declaradas de solo lectura que pasan las comprobaciones de seguridad. El permiso queda asociado al servidor y a la definición de la herramienta. Puedes revisarlo y revocarlo en **MCP → Permisos guardados…**. Las lecturas automáticas configuradas por nombre pasan por la misma comprobación. Las herramientas peligrosas o sin declaración de lectura piden confirmación en cada llamada. Los permisos automáticos requieren confiar en que el servidor describe sus herramientas con veracidad.

### Revisar archivos de una carpeta local

Con Desktop Commander habilitado, escribe en el mismo mensaje la ruta completa y qué quieres revisar. Por ejemplo, «Revisa los archivos de `C:\Proyectos\MiProyecto` y explica cómo se inicia». SB prioriza la lectura de la carpeta aunque el chat venía hablando de memoria y aplica los permisos de MCP. Si usas OpenRouter, el modelo recibe los resultados de las lecturas para redactar. Si falla el resumen después de que MCP obtuvo resultados, SB puede mostrar una revisión parcial con las rutas consultadas.

Con el ejemplo activado, pide en el chat «Usa echo del servidor ejemplo con el texto hola». Las pruebas usan configuraciones temporales.

```powershell
python -B tests/test_mcp.py
python -B tests/test_mcp_ui.py
python -B tests/test_workspace_features.py
python -B tests/test_chat_presentation.py
```

El panel se probó con servidores de ejemplo mediante STDIO y Streamable HTTP en loopback. En el mismo chat, Nemotron y Ollama ejecutaron una herramienta MCP y recuperaron un recuerdo de una base temporal.

## Historial de conversaciones

Usa **☰** para mostrar u ocultar el panel izquierdo. Arrastra su borde derecho para ajustar el ancho hasta 480 píxeles. StoneBot lo guarda al cerrar la ventana. Los títulos largos se muestran con puntos suspensivos. Pasa el cursor sobre uno para leerlo completo. **Nuevo chat** inicia una conversación vacía y genera un título a partir del primer mensaje. **Recientes** muestra diez conversaciones al principio. Pulsa **Ver más conversaciones…** para ver otras diez. El buscador filtra por título o contenido.

Las conversaciones se guardan en `%USERPROFILE%\.stonebot\conversations.sqlite3`. El historial almacena los mensajes del usuario y las respuestas visibles. Los permisos MCP se guardan en `mcp_permissions.sqlite3` y el diagnóstico en `diagnostics.log`. Los recuerdos personales de StoneBot se consultan mediante el MCP de StoneWave.

La columna izquierda mantiene los iconos visibles con la barra expandida o recogida. Al expandirla aparecen los nombres de las acciones, los proyectos desplegables con sus conversaciones y los chats recientes. El icono **Proyectos** abre la lista de proyectos locales. Puedes crear uno con nombre, descripción, instrucciones y una carpeta opcional, fijarlo arriba y abrir su ficha desde el menú de su fila. Para asociar un chat existente, usa **Mover a proyecto…** en su menú.

El menú **⋯** de la ficha permite editar, fijar o eliminar el proyecto. También puedes eliminarlo desde el menú de su fila en la barra izquierda. Al confirmar, los chats pasan a **Recientes** y los archivos originales siguen en su carpeta.

Cada ficha incluye un **Punto de continuidad** editable para recordar dónde te quedaste y qué sigue. Puedes escribirlo a mano o decir «Guarda el resumen» tras completar una tarea en ese proyecto. Los chats del proyecto reciben la nota como contexto anterior, además de las instrucciones y la carpeta vinculada. Los permisos MCP se aplican según su configuración.

En **Documentos → Vincular archivo…** puedes añadir un PDF, un README u otro archivo compatible. En cualquier chat de ese proyecto, abre **+ → Usar documento del proyecto…**, elige el archivo y envía tu pregunta. StoneBot lee la versión que esté guardada en ese momento y muestra el nombre del documento consultado. Ese turno se procesa en Ollama local como una consulta de adjuntos. Si mueves el archivo, vuelve a vincularlo desde su nueva ubicación. **Desvincular** quita el acceso desde el proyecto y conserva el archivo original.

Queda pendiente la prueba manual con un documento del usuario y Ollama.

Los mensajes con hora registrada la muestran en formato local. Las respuestas muestran Markdown con títulos, listas, enlaces HTTP(S) y expresiones matemáticas sencillas en línea. Cada bloque de código tiene su lenguaje, resaltado cuando el lenguaje es compatible y un botón **Copiar** que copia solo ese bloque.

En el cuadro de mensaje, **Ampliar editor** y **Reducir editor** ajustan la altura. El texto largo se desplaza dentro del editor y deja **+** y **Enviar** en la fila inferior. Al enviar, el editor vuelve al tamaño compacto.

El corrector local de Windows subraya posibles faltas en el borrador cuando hay un diccionario de español disponible. Haz clic derecho sobre una palabra marcada para ver sus sugerencias y elegir una. Los enlaces web se resaltan al escribir. Ábrelos con **Ctrl + clic** en el borrador o con un clic en el mensaje enviado.

El selector junto a **Enviar** muestra el modo de razonamiento. **Automático** usa el ajuste habitual, **Rápido** pide una respuesta directa y **Activado** pide al modelo razonar antes de responder.

Escribe `/` al inicio para ver comandos como `/buscar`, `/resumir` y `/tarea`. Usa `@` para adjuntar archivos, elegir un documento del proyecto o empezar un chat en otro proyecto con el borrador actual. Con `#` puedes mencionar un adjunto o el encargo actual. Usa `>` para abrir acciones del chat y `!` para abrir PowerShell por separado. Elige con clic o con flechas y Enter.

Al pasar el cursor sobre una conversación, **⋯** abre las acciones **Renombrar** y **Eliminar**. También puedes abrir ese menú con clic derecho o con **Mayús + F10** sobre la fila seleccionada.

En un mensaje del usuario, **Editar → Regenerar** vuelve a usar el historial anterior a ese punto. Si Ollama entrega una respuesta nueva y se guarda correctamente, se reemplaza el tramo posterior solo en esa conversación. Si la regeneración falla, se restaura el historial guardado.

### Tareas reanudables

En un chat sin adjuntos, pide un encargo de lectura con varios pasos en lenguaje natural. StoneBot puede abrir una tarea y guardarla antes de empezar a leer. Usa `/tarea` seguido del objetivo para abrirla explícitamente. Los permisos MCP se aplican a cada lectura nueva.

- StoneBot divide el objetivo en un plan, lo guarda y ejecuta sus pasos en el mismo turno. Puedes verlo en **Actividad**. Para ejecutar sin confirmaciones por lectura, usa **Permitir siempre** en las herramientas de lectura que quieras autorizar. StoneBot pregunta si le falta un dato indispensable que no puede obtener.
- Si la revisión final detecta evidencia faltante y queda presupuesto, StoneBot hace hasta dos intentos de resolverla en el mismo turno antes de entregar el resultado o explicar qué falta.
- Al planificar una tarea, StoneBot consulta recuerdos pertinentes de su memoria y resultados del mismo encargo. También recupera métodos y resultados generales de revisiones de proyectos parecidas. Cada revisión comprueba por separado los archivos y el estado del proyecto actual. StoneBot conserva las aclaraciones, las lecturas y lo que falta al pausar. Si quieres conservar la respuesta de una tarea completada, di «Guarda el resumen» en el mismo chat.
- Para clasificar una carpeta por tamaño en un chat sin adjuntos, escribe «Revisa Descargas y dime cuáles son los cinco archivos más pesados». StoneBot guarda el encargo, usa la carpeta Descargas configurada en Windows y calcula la clasificación con tamaños reales. Puedes volver al mismo chat y responder «incluye las subcarpetas» o «sin subcarpetas». También puedes indicar otra carpeta con una ruta absoluta entre comillas o enviarla como respuesta. StoneBot devuelve los recuentos y avisa si omitió rutas inaccesibles o redirigidas.
- StoneBot guarda automáticamente el resultado de estas clasificaciones en su base de experiencias y busca ejecuciones de la misma carpeta, alcance y cantidad de resultados antes de elegir el método. **Actividad** muestra las experiencias recuperadas y el método elegido. Si la última ejecución verificada usó Desktop Commander, StoneBot puede repetir ese método cuando estén autorizadas sus lecturas. Ante resultados parciales, errores o falta de evidencia, usa el recorrido local. La experiencia guarda una huella del alcance y el número de entradas omitidas cuando se conoce.
- Si la tarea espera un dato, reabre el mismo chat y responde con el dato, por ejemplo la ruta absoluta. La tarea recupera su objetivo y los resultados guardados.
- **Actividad** muestra el estado y los pasos registrados. **Pausar** deja terminar la operación actual y detiene el siguiente paso. Usa `/reanudar` para retomar una tarea pausada o interrumpida, o `/cancelar` para cerrarla. Tras un cierre inesperado, un paso sin resultado queda marcado como incierto.
- Junto a **Actividad**, usa **Guardar corrección…** después de recibir el resultado de una tarea. Anota qué salió mal, qué prefieres y cómo corregirlo. StoneBot consulta la corrección al preparar otro encargo con el mismo objetivo o una revisión parecida dentro del mismo proyecto.
- En una clasificación por tamaño, también puedes decir «Ese conteo incluía carpetas ocultas» para abrir el formulario con una propuesta. Si confirmas **Omitir los ocultos**, las próximas clasificaciones locales de esa carpeta en el mismo proyecto los dejarán fuera. Puedes pedir «incluye carpetas ocultas» para una consulta concreta. **Actividad** muestra cuando se aplicó la corrección guardada.
- El historial local conserva el objetivo, el estado y los resultados acotados de las lecturas de la tarea más reciente de cada chat. Se reutiliza una lectura idéntica durante la tarea. Para volver a consultar datos que hayan cambiado, inicia otra. Los mensajes anteriores siguen en la conversación. Usa conversaciones sin tarea para editar y regenerar.

**Qué significa Completada.** StoneBot revisa si las lecturas respaldan el objetivo y las aclaraciones. Un recorte, páginas pendientes, una lectura sin resultado o un presupuesto agotado pueden dejar el encargo pendiente. `/reanudar` conserva las lecturas y abre otro turno. Si la evidencia acumulada cubre el objetivo, la tarea puede completarse. Para una clasificación grande, usa una fuente que pueda demostrar que calculó sobre todo el conjunto, o comprueba lotes con alcance explícito.

Esta etapa admite herramientas MCP de solo lectura y se inicia desde el chat. Adjuntos, Skills, acciones de escritura y ejecución desatendida quedan pendientes en el modo de tareas. Las tareas se guardan en `conversations.sqlite3`, separadas de la memoria de StoneBot y StoneWave.

`python -B tests/test_tasks.py` comprueba el reinicio, la pausa y la cancelación con un MCP STDIO de prueba. Con Ollama activo, `python -B tests/test_tasks.py --desktop RUTA_NODE RUTA_DIST_INDEX_JS` usa el Desktop Commander ya instalado. La prueba crea seis archivos en una carpeta temporal y verifica los cinco resultados y sus tamaños.

### Adjuntos del chat

Pulsa **+ → Adjuntar archivos** junto al cuadro de mensaje y selecciona los archivos juntos. Se muestran como tarjetas en una fila desplazable. Usa la **×** de cada tarjeta para quitarla antes de enviar. El submenú **+ → MCP** permite activar o desactivar servidores configurados usando la misma configuración que el panel **MCP** de la cabecera. El menú también contiene Memoria y Skills. Se admiten imágenes PNG, JPG/JPEG y WebP, PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) y archivos TXT, MD, CSV, TSV, LOG y JSON en UTF-8 o UTF-16 con BOM.

Los archivos de Office se leen localmente. Word aporta el texto de párrafos y tablas del cuerpo, Excel indica hojas y celdas y PowerPoint identifica las diapositivas con texto. Excel usa los resultados que están guardados junto a las fórmulas y avisa cuando un resultado falta. Los adjuntos de Office se abren para lectura. Si necesitas que StoneBot analice un gráfico, una imagen o el diseño de una página, exporta esa parte a PDF. El lector admite hasta 64 MB por archivo y 4 millones de caracteres de texto y referencias extraídos.

Las imágenes de hasta 16 megapíxeles se redimensionan para Ollama y se envían al modelo local `nemotron-3.5-bolt:e4b`. StoneBot comprueba que Ollama anuncie capacidad visual y avisa si el modelo carece de ella. En un PDF mixto extrae el texto disponible por página y renderiza las páginas sin texto como imágenes para ese mismo modelo.

StoneBot prepara todas las páginas del PDF y agrupa los adjuntos en lotes de hasta cuatro imágenes o páginas visuales y 12 000 caracteres de texto por llamada a Ollama. Analiza los lotes y combina sus hallazgos en una respuesta. El tiempo, la memoria y el almacenamiento crecen con el volumen. Si un PDF antiguo se guardó por tramos, adjunta el original para recuperar las páginas faltantes.

Con un solo adjunto en el chat, puedes acotar una consulta larga. Para Excel escribe «Revisa la hoja "Totales"». Para PDF escribe «Resume las páginas 5 a 8». El archivo completo queda disponible para otras preguntas.

El historial local conserva el nombre, una copia de la imagen redimensionada o el texto extraído. Al reabrir o regenerar el chat, los adjuntos siguen disponibles aunque se mueva el original. Las rutas de origen quedan fuera del historial. StoneBot consulta los adjuntos en Ollama local. Si pides explícitamente guardar algo en la memoria o crear un Markdown en una ruta de Windows, ofrece las herramientas necesarias para ese encargo. Para el Markdown busca una herramienta de escritura entre tus servidores MCP habilitados y, si falta, puede crear el archivo localmente. Pide confirmación y comprueba el contenido antes de reportarlo como guardado. Si el archivo ya existe, se conserva.

Puedes enviar primero la petición y después la captura que contiene el material. Si StoneBot ya enumeró ese material, puedes responder «Sí, esos comandos» para continuar con el guardado pendiente. Si el recuerdo se guardó y solo falta el archivo, «Intenta guardar el archivo de nuevo» retoma esa parte.

Pega una captura o un archivo copiado desde el Explorador con **Ctrl+V**. Las tarjetas de imagen muestran una miniatura y las de documentos muestran el tipo de archivo.

Al elegir una consulta de **Memoria** desde una conversación con adjuntos ya enviados, StoneBot la prepara en un chat nuevo. Si hay adjuntos pendientes de enviar, primero puedes enviarlos o quitarlos.

### Agent Skills locales

Abre **+ → Skills** para ver las Skills y marcar las que quieres habilitar. **Agregar desde carpeta** importa el `SKILL.md` a `%USERPROFILE%\.stonebot\skills\<nombre>\SKILL.md`. La carpeta de origen debe llamarse igual que el campo `name`. El archivo lleva `name` y `description` en el encabezado YAML, seguidos por las instrucciones en Markdown. Las Skills importadas quedan desactivadas hasta que las marques. [Formato Agent Skills](https://agentskills.io/specification)

Ollama recibe solo los nombres y descripciones de las Skills habilitadas. Cuando Nemotron elige una, StoneBot lee su cuerpo para ese turno y muestra **Skill cargada** en **Actividad**. Esta versión importa únicamente `SKILL.md`. Las carpetas auxiliares y los scripts quedan fuera del flujo, y la respuesta guiada por la Skill se genera sin herramientas MCP ni de memoria.

Para probarlo, habilita **faro-de-prueba** y escribe «Genera una ficha Faro SB sobre astronomía». La primera línea debe incluir `FARO SB · LINTERNA-742`. Una pregunta general, como «¿Cuánto es 7 por 8?», no debería mostrar la carga. La prueba automatizada con Nemotron local se ejecuta con `python -B tests/test_skills.py --live`.

La fila **Actividad** aparece en la conversación junto a la respuesta en curso. Se puede desplegar para ver el estado del turno, las operaciones MCP y sus resultados o errores. **Mostrar razonamiento de Ollama** aparece solo cuando la API entrega el campo separado `message.thinking`. Con la integración actual ese campo llega al terminar cada respuesta de Ollama. La actividad y el razonamiento se conservan en la vista actual del chat y se descartan al cambiar de conversación. Los detalles técnicos siguen en **Diagnóstico**. [Campo de razonamiento en Ollama](https://docs.ollama.com/capabilities/thinking)

### Instrucciones generales

En **+ → Instrucciones generales…** puedes guardar preferencias para todas las conversaciones. StoneBot responde en español por defecto. Las preferencias se aplican en el siguiente turno y se conservan al reiniciar.

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
├── app.py                # arranque y ventana principal
├── turn_worker.py        # ejecución del turno de chat
├── request_routing.py    # elección de fuente para el turno
├── attachment_actions.py # guardado solicitado desde el chat
├── stonewave_memory.py   # cliente MCP de la memoria personal
├── stonebot_service.py   # acceso de la CLI a la base experimental
├── identity.py           # identidad declarada de StoneBot en SQLite local
├── stonebot_memory.py    # línea de comandos: identidad, integración, sueño y publicación revisada
├── app-backup.py         # GUI anterior sin memoria persistente
├── test_memory.py        # consulta manual de la memoria experimental
├── stonebot_engine/      # motor SQLite, modelos, notas y validación de rutas
├── tests/                # funcionamiento y aislamiento con bases temporales
└── docs/
    └── 01-primer-experimento-que-ve.md
```

### Dónde buscar cuando quieras cambiar algo

| Si quieres cambiar… | Empieza aquí |
| --- | --- |
| El menú, la bandeja o cómo se conectan las partes de la ventana | [`app.py`](app.py) |
| El cuadro de mensaje, las burbujas o el panel de actividad | [`chat_ui.py`](chat_ui.py). Para colores y temas, [`appearance.py`](appearance.py). |
| La lista de conversaciones o cómo se guardan | [`history_ui.py`](history_ui.py) para la lista y [`history.py`](history.py) para el almacenamiento. |
| Cuándo SB interpreta que quieres abrir un enlace, leer una carpeta o usar herramientas externas | [`request_routing.py`](request_routing.py) |
| Cómo SB procesa un mensaje, ejecuta herramientas o termina un turno | [`turn_worker.py`](turn_worker.py) |
| Cómo se reciben adjuntos o se pide guardar su contenido | [`attachments.py`](attachments.py) para la lectura y [`attachment_actions.py`](attachment_actions.py) para el guardado. |
| Ollama, OpenRouter o el selector de modelos | [`ai_provider.py`](ai_provider.py) para la conexión y [`ai_settings_ui.py`](ai_settings_ui.py) para el selector. |
| Qué muestra SB sobre los sueños y las notas de SW | [`stonewave_activity.py`](stonewave_activity.py). La conexión MCP está en [`stonewave_memory.py`](stonewave_memory.py) y los ajustes en [`stonewave_settings_ui.py`](stonewave_settings_ui.py). |
| Servidores MCP, permisos o skills | [`mcp_client.py`](mcp_client.py) para servidores, [`mcp_permissions.py`](mcp_permissions.py) para permisos y [`local_skills.py`](local_skills.py) para skills. |
| Pausar, reanudar o registrar el avance de un encargo | [`tasks.py`](tasks.py) para su estado y [`turn_worker.py`](turn_worker.py) para su ejecución. |

## Prototipo anterior con memoria local (15 de noviembre de 2026)

- Windows 11, Python, PySide6 y Ollama con `nemotron-3.5-bolt:e4b`.
- `app.py` muestra un chat rediseñado con mensajes separados, texto ajustable y editor multilínea; envía mensajes a Nemotron mediante un trabajador en `QThread`.
- Nemotron puede invocar tres herramientas Python de memoria desde el chat: consultar, guardar y buscar conexiones semánticas; las pruebas automatizadas y manuales de persistencia se documentan arriba.
- Base SQLite independiente: `~/.stonebot/memoria.db`.
- La prueba anterior al aislamiento confirmó que el primer recuerdo se conservó en el namespace `default` tras reiniciar la GUI. La suite actual verifica la reapertura y recuperación con el motor local y una base desechable.

## Aprendizaje a partir de experiencias MCP

Escribe `/aprender` seguido de una tarea concreta para conservar sus resultados MCP. Con un servidor de eco configurado y permitido, usa `/aprender Ejecuta echo en demo con un texto de prueba`. El registro se crea a partir de la ejecución efectiva y conserva el identificador de evidencia, fecha UTC, servidor, herramienta y clase de resultado. Distingue respuestas sin error, respuestas sin texto ni datos estructurados, errores comunicados por el servidor y excepciones, incluidos los tiempos de espera. Las operaciones denegadas o rechazadas antes de la ejecución quedan fuera del registro.

En un chat nuevo, incluso después de cerrar y volver a abrir la aplicación, pregunta «¿Qué aprendiste sobre demo echo?». El modelo puede consultar `query_experiences` por palabras del nombre del servidor y de la herramienta. La consulta devuelve la observación más reciente de cada coincidencia, hasta cinco, junto con evidencia anterior de un resultado opuesto si existe. La conclusión describe la última ejecución. La hipótesis y la incertidumbre aparecen aparte. La causa de un fallo, la veracidad del contenido y el comportamiento con otros argumentos o configuraciones requieren pruebas adicionales.

Las experiencias se guardan en `%USERPROFILE%\.stonebot\experiences.sqlite3`, separadas del historial y de `memoria.db`, con las validaciones de aislamiento del motor local. Se omiten mensajes del chat, argumentos, credenciales y contenido devuelto. El alcance inicial se limita a ejecuciones MCP registradas explícitamente y búsquedas por nombre. La interpretación semántica, la atribución de causas y la evaluación de capacidades sin evidencia quedan pendientes.

Ejecuta `python -B tests/test_experiences.py` para probar el reinicio con dos procesos de la aplicación, un perfil temporal, un MCP STDIO real y un modelo simulado. La prueba verifica la recuperación desde un chat nuevo, la revisión de una conclusión con evidencia contraria y el bloqueo de rutas protegidas. Con Ollama en ejecución y `nemotron-3.5-bolt:e4b` instalado, usa `python -B tests/test_experiences.py --live` para realizar el recorrido con el modelo local.

La demostración con Nemotron y Ollama local guardó la observación 1 tras ejecutar `demo / echo`. En un segundo proceso, desde un chat nuevo, el modelo recuperó ese ID y explicó que la respuesta anterior había llegado sin error y que aún quedaba por probar si se repetiría con otros argumentos o configuraciones.

## Identidad y herramientas de la memoria experimental

La identidad declarada se inicializa en `%USERPROFILE%\.stonebot\identity.sqlite3` y se incorpora al contexto del chat. Usa `/identidad` para verla o `/identidad campo valor` para corregir un dato. También puedes consultar y corregir la identidad con `python -B stonebot_memory.py identidad` y `corregir-identidad CAMPO VALOR`. La procedencia del proyecto se conserva como datos declarados por su responsable.

La CLI permite revisar la base experimental de SB. Su sueño clasifica, relaciona, revisa contradicciones y genera hipótesis con sus evidencias.

```powershell
# Usa los IDs reales capturados previamente con /aprender.
python -B stonebot_memory.py integrar 1 2
python -B stonebot_memory.py sonar experiencias
python -B stonebot_memory.py conclusiones experiencias
```

`integrar` importa únicamente los resultados observados de los IDs elegidos al ámbito `experiencias_mcp` de `memoria.db`. Cada observación se identifica por su procedencia y puede importarse una sola vez. Los recibos conservan la fecha y no incluyen argumentos ni respuestas brutas. Para revisar la memoria conversacional propia de StoneBot, usa `sonar memoria`. El comando manual deja la publicación para una revisión posterior.

Para publicar en tu clon local de **Big-vault**, selecciona **Salir** en la bandeja de StoneBot e indica la raíz de la bóveda. Revisa la previsualización de cada ámbito y autoriza únicamente esa versión con el valor `aprobacion` que imprime el comando.

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

Siguen pendientes la validación en vivo de integraciones MCP aún no probadas, el trabajo con hipótesis y la iniciativa controlada.

---

Este plan está vivo: las ideas nuevas se documentan primero y se convierten en tareas solo cuando existe una prueba concreta que realizar.
