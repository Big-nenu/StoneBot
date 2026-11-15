# StoneBot

> Un compañero de IA local que recuerda, razona, experimenta y, con el tiempo, puede interactuar con el mundo físico.

**Estado:** prototipo conversacional con lectura de memoria persistente comprobada · **Inicio:** noviembre de 2026 · **Enfoque:** experimentación incremental, local-first.

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
| 0. Base segura | Definir alcance y separar la memoria | Base SQLite exclusiva y prueba de lectura/escritura | Parcial: base separada y lectura/escritura manual verificadas; falta auditoría del aislamiento |
| 1. Núcleo conversacional | Aplicación Windows con chat, Ollama y StoneWave | Conversa, recuerda y permanece en segundo plano al cerrar la ventana | Parcial: ventana, chat y recuperación persistente funcionando; faltan escritura desde agente y bandeja |
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

- Ciclo de revisión de recuerdos con las capacidades existentes de StoneWave.
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

## Arquitectura conceptual

```text
Ventana PySide6  <-->  StoneBot Core  <-->  Ollama local
                           |
                    StoneWave (SQLite)
                           |
             ~/.stonebot/memoria.db

Bandeja del sistema <--> StoneBot Core
Ventana cerrada: proceso activo / «Salir»: proceso detenido
Futuro: sueños, iniciativa, mascota y sensores
```

**No se necesita implementar toda la arquitectura al inicio.** La primera versión puede ser un único proceso y pocas herramientas.

## Decisiones técnicas confirmadas

- **Aplicación independiente:** ventana Windows y bandeja del sistema, no interfaz de un agente externo.
- **Primera interfaz:** Python + PySide6 (Qt), sujeta a prueba de prototipo.
- **Persistencia:** StoneWave usa una base SQLite separada para StoneBot, ubicada en `C:\\Users\\Luis_Hdez\\.stonebot\\memoria.db` en el equipo actual.
- **Configuración:** `STONEWAVE_DB` debe apuntar explícitamente a esa ruta para evitar acceder por accidente a la memoria personal.
- **Estado de la memoria:** base experimental creada; `inject` y `query` probados desde CLI; lectura directa desde Python y recuperación tras reiniciar la GUI comprobadas. Falta verificar formalmente que la memoria personal no cambió.
- **Segundo plano:** inicialmente proceso en espera, sin razonamiento continuo; ciclos autónomos se incorporarán después.

## Relación con StoneWave

StoneWave ya dispone de funciones de memoria, relaciones, sueños, contradicciones e hipótesis. Actualmente StoneBot **solo consulta recuerdos** mediante `StoneWaveEngine.query()` con una ruta SQLite explícita y el namespace `default` dentro de su base aislada. **No guarda recuerdos desde la interfaz, no usa MCP y no ejecuta sueños ni otras herramientas avanzadas.**

La futura integración se evaluará antes de implementarse: acceso directo a la API, MCP o variante aislada del motor. **No modificar el repositorio StoneWave original para adaptar sus funciones a StoneBot.** El aislamiento de datos no sustituye al aislamiento del código: un agente con herramientas de escritura podría alterar archivos aunque su prompt lo prohíba. Se deben aplicar permisos y entornos de prueba reales.

Repositorio base: [StoneWave](https://github.com/Big-nenu/StoneWave).

## Archivos actuales

```text
StoneBot/
├── README.md
├── README-Hermes.md
├── app.py                # GUI PySide6 + Ollama + consulta a StoneWave
├── app-backup.py         # GUI anterior sin memoria persistente
├── test_memory.py        # prueba directa de lectura de memoria
└── docs/
    └── 01-primer-experimento-que-ve.md
```

El núcleo y la GUI todavía comparten un archivo. La estructura futura se decidirá conforme avance el prototipo.

## Prototipo probado (15 de noviembre de 2026)

- Windows 11, Python, PySide6 y Ollama con `nemotron-3.5-bolt:e4b`.
- `app.py` muestra una ventana de chat y envía mensajes a Nemotron mediante un trabajador en `QThread`.
- Base SQLite independiente: `~/.stonebot/memoria.db`.
- Se comprobó que el primer recuerdo quedó almacenado en el namespace `default` (no en `stonebot`); `mem_cli.py` usa `default` salvo que se pase `-n`.
- `test_memory.py` recuperó el recuerdo desde Python con `StoneWaveEngine`; después, `app.py` también lo recuperó tras cerrar y abrir de nuevo la aplicación.
- La recuperación es **solo lectura**: aún no hay guardado selectivo, edición, sueño, conclusiones ni MCP conectado a la GUI.
- Cerrar la ventana actualmente termina el proceso; la bandeja del sistema sigue pendiente.

## Autoconocimiento funcional: propuesta por investigar

La intención no es únicamente recordar información sobre el usuario. StoneBot debe poder construir y revisar **un modelo de sí mismo basado en experiencias comprobables**: qué intentó, qué resultado obtuvo, qué capacidades o límites observó, qué hipótesis formuló y cómo cambió su evaluación tras nuevas pruebas. Esto **no demuestra ni presupone conciencia subjetiva**.

Posibles registros propios de StoneBot (esquema todavía no aprobado): experiencias, autoevaluaciones de capacidades, hipótesis con evidencia y experimentos con resultados. Deben distinguirse **hechos observados**, **inferencias del modelo** y **objetivos propuestos**. También queda por estudiar si la energía/relevancia de StoneWave necesita adaptaciones para este tipo de información.

**Decisión pendiente:** reutilizar StoneWave mediante su API/MCP o mantener una variante del motor dentro de StoneBot. No duplicar ni reescribir el motor antes de inspeccionar su diseño y definir pruebas. Cualquier copia debe estar aislada del repositorio original y de la memoria personal. Ningún agente debe tener acceso de escritura al StoneWave original; la seguridad debe depender de permisos efectivos, no solo de instrucciones en prompts.

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
- Sí existe un prototipo funcional de conversación y lectura de memoria, pero **no** un agente autónomo ni un sistema de autoconocimiento funcional.

## Próxima acción

**Antes de añadir escritura o MCP:** revisar la arquitectura de StoneWave y definir cómo StoneBot representará sus experiencias, sus hipótesis y su modelo de sí mismo. Mantener el código de StoneWave sin modificaciones. Después, probar escritura desde el agente en la base experimental y verificar el aislamiento. La bandeja del sistema sigue pendiente.

---

Este plan está vivo: las ideas nuevas se documentan primero y se convierten en tareas solo cuando existe una prueba concreta que realizar.
