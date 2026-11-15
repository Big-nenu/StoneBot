# StoneBot

> Un compañero de IA local que recuerda, razona, experimenta y, con el tiempo, puede interactuar con el mundo físico.

**Estado:** planificación · **Inicio:** noviembre de 2026 · **Enfoque:** experimentación incremental, local-first.

## Visión

StoneBot no pretende ser únicamente un chatbot con memoria ni una mascota de escritorio. Es un experimento para construir un agente que pueda mantener continuidad entre sesiones, plantear preguntas, contrastar hipótesis, aprender de resultados y tomar iniciativas dentro de límites explícitos.

Inspiraciones conceptuales: Jarvis (asistencia), Vision (reflexión) y Ultrón (iniciativa), **sin asumir conciencia ni autonomía ilimitada**.

## Principios

- **Primero razonamiento; después apariencia y cuerpo.**
- **StoneWave es un componente independiente**, no se modifica su memoria personal.
- **Memoria aislada:** rutas, configuración, base de datos y pruebas exclusivas para StoneBot.
- **Local-first:** Ollama y modelos adecuados a una RTX 4060 de 8 GB; servicios externos opcionales, nunca obligatorios.
- **Un modelo cargado a la vez** cuando compartir GPU cause conflictos.
- **Autonomía graduada:** observar y proponer antes de actuar; pedir permiso para acciones sensibles.
- **Experimentos verificables:** registrar hipótesis, evidencias, fallos y conclusiones.
- **Pocos componentes, interfaces claras y pruebas pequeñas.**

## Hoja de ruta

Las etapas son orientativas, no fechas prometidas. Cada etapa debe tener una demostración observable antes de avanzar.

| Etapa | Objetivo | Entregable comprobable | Estado |
|---|---|---|---|
| 0. Base segura | Definir alcance y separar la memoria | Configuración propia; prueba que no toca la base personal | Pendiente |
| 1. Núcleo conversacional | Conectar un agente local con StoneWave | Conversa, guarda y recupera recuerdos en sesiones distintas | Pendiente |
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

- Agente local sencillo con Ollama.
- Herramientas mínimas: recordar, recuperar, conversar.
- Contexto acotado y registro de acciones.
- Prueba de continuidad tras cerrar y abrir el programa.

**Criterio de salida:** recuerda algo relevante de una sesión anterior y distingue un recuerdo de una inferencia.

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
Usuario / Eventos permitidos / Sensores (futuro)
                    |
              StoneBot Core
        (objetivos, decisiones, límites)
             /             \
    Ollama / modelos      Herramientas
             \             /
            StoneWave MCP
        (memoria AISLADA)
                    |
       Registro de experiencias
                    |
       Revisión / sueño / hipótesis
```

**No se necesita implementar toda la arquitectura al inicio.** La primera versión puede ser un único proceso y pocas herramientas.

## Relación con StoneWave

StoneWave ya dispone de funciones de memoria, relaciones, sueños e hipótesis. StoneBot debe **reutilizarlas**, no duplicarlas. La integración concreta se validará revisando la API/MCP actual y sus opciones de configuración.

Repositorio base: [StoneWave](https://github.com/Big-nenu/StoneWave).

## Estructura prevista (no implementada)

```text
StoneBot/
├── README.md
├── docs/
│   ├── ideas.md
│   └── decisiones.md
├── config/
│   └── example.env
├── src/
├── tests/
└── experiments/
```

Los directorios se crearán únicamente cuando hagan falta.

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
- No hay una implementación funcional de StoneBot aún: este documento es el plan inicial.

## Próxima acción

**Completar la Etapa 0:** crear una instancia experimental de StoneWave y demostrar que su base de datos es independiente de la personal.

---

Este plan está vivo: las ideas nuevas se documentan primero y se convierten en tareas solo cuando existe una prueba concreta que realizar.
