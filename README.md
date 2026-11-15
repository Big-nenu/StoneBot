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
| 1. Núcleo conversacional | Aplicación Windows con chat, Ollama y motor local | Conversa, recuerda y permanece en segundo plano al cerrar la ventana | Parcial. Chat rediseñado y herramientas de memoria operativas; falta la bandeja. |
| 1B. Herramientas externas (MCP) | Cliente MCP reutilizable y primeras integraciones | Consulta documentación con Context7 desde StoneBot | Propuesto; aún no implementado | 
| 2. Razonamiento | Formular preguntas e hipótesis | Explica una hipótesis, su evidencia y qué falta comprobar | Pendiente |
| 3. Sueño y aprendizaje | Revisar experiencias, contradicciones y conclusiones | Ciclo programado que produce conclusiones trazables | Pendiente |
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

### Etapa 2 — Curiosidad y razonamiento

- Preguntas surgidas de contradicciones, vacíos o resultados inesperados.
- Hipótesis con evidencia a favor/en contra y nivel de incertidumbre.
- Capacidad de decir «no sé» y proponer una prueba.
- Separar ideas sugeridas por el usuario de conclusiones propias del agente.

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

**MCP (Model Context Protocol)** es un protocolo para descubrir e invocar herramientas proporcionadas por servidores externos. La propuesta es incorporar a StoneBot un **cliente MCP** que permita conectarse a distintos servidores, presentar sus herramientas al modelo mediante el mecanismo de llamadas a herramientas de Ollama y ejecutar las llamadas autorizadas. La compatibilidad de cada servidor, sus credenciales y su transporte deberán verificarse durante la implementación.

Primeras integraciones candidatas (ninguna está conectada todavía):

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

Bandeja del sistema <--> StoneBot Core
Ventana cerrada: proceso activo / «Salir»: proceso detenido
Futuro: cliente MCP, sueños, iniciativa, mascota y sensores
```

**No se necesita implementar toda la arquitectura al inicio.** La primera versión puede ser un único proceso y pocas herramientas.

## Decisiones técnicas confirmadas

- **Aplicación independiente:** ventana Windows y bandeja del sistema, no interfaz de un agente externo.
- **Primera interfaz:** Python + PySide6 (Qt), sujeta a prueba de prototipo.
- **Persistencia.** La aplicación abre `%USERPROFILE%\.stonebot\memoria.db` con el motor local y consulta el namespace `default`.
- **Configuración.** El motor requiere una ruta explícita y usa el prefijo `STONEBOT_` para configurar los modelos y las notas.
- **Segundo plano:** inicialmente proceso en espera, sin razonamiento continuo; ciclos autónomos se incorporarán después.
- **Interfaz actual:** chat PySide6 de tema oscuro, mensajes separados, tipografía más legible y cuadro de escritura multilínea (Enter para enviar, Shift+Enter para salto de línea).
- **Herramientas externas:** cliente MCP propuesto, todavía no implementado; el motor de memoria continúa integrado por Python.

## Relación con StoneWave

El paquete local `stonebot_engine/` contiene la copia de `mem_engine.py`, `llm.py` y `notes.py`, con la licencia MIT original. Nemotron decide cuándo llamar a las herramientas del chat mediante Ollama. Las tres usan el namespace `default` del motor de StoneBot mediante llamadas directas a Python.

| Herramienta | Función del motor | Ejemplo en el chat |
|---|---|---|
| `query_memory` | `query()` recupera recuerdos relevantes y actualiza su relevancia | «¿Qué montura te dije que usa el telescopio?» |
| `inject_memory` | `inject()` guarda un hecho confirmado o una preferencia duradera | «Recuerda que el telescopio usa una montura ecuatorial.» |
| `bridge_memory` | `bridge()` encuentra recuerdos que conectan dos temas | «Busca qué recuerdo conecta el telescopio con la montura ecuatorial.» |

El puente presenta conexiones semánticas durante la consulta. Los sueños automáticos y el mantenimiento de relaciones persistentes quedan para una etapa posterior.

El motor restringe SQLite a la carpeta de StoneBot. El validador bloquea las carpetas de memoria personal, el repositorio original, los enlaces duros a archivos y las redirecciones de archivos auxiliares de SQLite. `STONEWAVE_DB` y `MEMHOLOGRAFIC_DB` solo se consideran para bloquear bases personales configuradas fuera de sus carpetas habituales. Las rutas de notas, importaciones, exportaciones y sincronización también se validan.

Repositorio base: [StoneWave](https://github.com/Big-nenu/StoneWave).

## Ejecutar y probar

Con Python 3.14, instala `PySide6`, `ollama`, `requests` y `numpy`. Para usar `python app.py`, inicia Ollama local con los modelos `nemotron-3.5-bolt:e4b` y `embeddinggemma-2:270m` disponibles. `python test_memory.py` permite consultar manualmente la memoria experimental. La aplicación espera que la base de StoneBot ya exista.

Las suites usan bases temporales y modelos simulados. Comprueban las tres herramientas desde el trabajador del chat, la recuperación tras reabrir la base y el bloqueo de rutas protegidas.
En Windows, las pruebas de redirección requieren permiso para crear enlaces simbólicos.

```powershell
python -B tests/test_motor.py
python -B tests/test_aislamiento.py
```

También se verificaron las tres herramientas con Nemotron y Ollama local desde la interfaz Qt. Se guardó un recuerdo sintético, se reinició la aplicación y se comprobó que el chat podía recuperarlo y encontrar su relación con dos temas.

## Servidores MCP externos

Instala el cliente con `python -m pip install "mcp>=1.28,<2"`. La memoria interna sigue usando llamadas directas al motor de StoneBot. El chat descubre las herramientas de los servidores activados al empezar cada turno y entrega sus resultados de texto a Nemotron.

Abre **MCP** en la cabecera del chat para agregar, editar o eliminar servidores y cambiar su activación con el interruptor de cada fila. **Probar conexión** abre una sesión temporal. El indicador es verde si conecta, rojo si falla y gris antes de probar.

Cada herramienta descubierta tiene su propio interruptor. Los servidores y herramientas deshabilitados quedan fuera de las herramientas que recibe Nemotron. Estas preferencias se conservan al reiniciar. Vuelve a probar la conexión para cargar el catálogo en la nueva sesión. Al habilitar una herramienta se vuelven a aplicar sus permisos de lectura o confirmación.

Los servidores se agregan desactivados. El nombre identifica la configuración y se mantiene al editarla. Cambiar el transporte, el ejecutable, los argumentos, la URL o la referencia al token desactiva el servidor y revoca sus lecturas automáticas. Los cambios aplican al siguiente turno. En STDIO, escribe los argumentos como una lista JSON, por ejemplo `["-B", "C:\\ruta\\servidor.py"]`. En HTTP solo se muestra y guarda el nombre de la variable del token.

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

La configuración se guarda en `%USERPROFILE%\.stonebot\mcp_servers.json`. Usa los argumentos de lanzamiento STDIO únicamente para opciones que no contengan credenciales. Cada servidor STDIO arranca en su propio directorio bajo `%USERPROFILE%\.stonebot\mcp\`, con las variables de perfil redirigidas. Activar STDIO autoriza iniciar ese programa con los permisos de la cuenta actual. Ejecuta servidores locales de terceros bajo una cuenta o un entorno aislado por el sistema si necesitas impedirles el acceso a archivos de tu cuenta.

Una lectura automática requiere autorización por nombre y que el servidor la declare de solo lectura. Las demás llamadas MCP muestran el servidor, la operación y sus argumentos para confirmar cada vez. El servidor recibe los argumentos de las llamadas que se ejecutan. Habilita solo servidores y lecturas que hayas revisado.

Con el ejemplo activado, pide en el chat «Usa echo del servidor ejemplo con el texto hola». Las pruebas usan configuraciones temporales.

```powershell
python -B tests/test_mcp.py
python -B tests/test_mcp_ui.py
```

El panel se probó con servidores de ejemplo mediante STDIO y Streamable HTTP en loopback. En el mismo chat, Nemotron y Ollama ejecutaron una herramienta MCP y recuperaron un recuerdo de una base temporal.

## Apariencia

Abre **⚙ → Apariencia** para elegir el acento, el fondo de la ventana y los fondos de los mensajes de cada participante. El tamaño de letra del chat se puede ajustar entre 12 y 28 px. Los cambios se aplican al instante y se guardan en `%USERPROFILE%\.stonebot\appearance.ini`.

La primera vez se usa el tema oscuro de StoneBot. El botón **Restaurar** junto a cada selector recupera solo ese color. **Restaurar colores predeterminados** recupera todos los colores. Ambas opciones conservan el tamaño de letra elegido.

Para reiniciar la memoria experimental, cierra StoneBot y mueve su `memoria.db` y los archivos auxiliares de SQLite que existan a una carpeta de respaldo. Luego crea una base vacía con `python -c "from stonebot_engine import StoneBotEngine, default_root; StoneBotEngine(default_root() / 'memoria.db').close()"`. Para restaurar, con StoneBot cerrado, mueve la base experimental actual a otra carpeta y devuelve los archivos del respaldo a la carpeta de StoneBot.

## Archivos actuales

```text
StoneBot/
├── README.md
├── README-Hermes.md
├── app.py                # GUI PySide6 renovada + Ollama + herramientas de memoria
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

## Autoconocimiento funcional: propuesta por investigar

La intención no es únicamente recordar información sobre el usuario. StoneBot debe poder construir y revisar **un modelo de sí mismo basado en experiencias comprobables**: qué intentó, qué resultado obtuvo, qué capacidades o límites observó, qué hipótesis formuló y cómo cambió su evaluación tras nuevas pruebas. Esto **no demuestra ni presupone conciencia subjetiva**.

Posibles registros propios de StoneBot (esquema todavía no aprobado): experiencias, autoevaluaciones de capacidades, hipótesis con evidencia y experimentos con resultados. Deben distinguirse **hechos observados**, **inferencias del modelo** y **objetivos propuestos**. También queda por estudiar si la energía/relevancia de StoneWave necesita adaptaciones para este tipo de información.

Los experimentos de autoconocimiento usarán el motor local y bases desechables.

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
- El chat utiliza herramientas de memoria persistente. La autonomía y el autoconocimiento funcional siguen en exploración.

## Próxima acción

**Probar un cliente MCP mínimo con Context7** sin alterar las herramientas actuales de memoria. Confirmar descubrimiento, ejecución de una consulta y manejo de errores desde StoneBot. Después, diseñar los permisos necesarios para conectar servicios personales como Gmail y Obsidian.

En paralelo quedan pendientes la bandeja del sistema y la representación de experiencias e hipótesis para el autoconocimiento funcional.

---

Este plan está vivo: las ideas nuevas se documentan primero y se convierten en tareas solo cuando existe una prueba concreta que realizar.
