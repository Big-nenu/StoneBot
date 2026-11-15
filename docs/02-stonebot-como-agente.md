# Idea: StoneBot como agente, no solo chat con memoria

**Fecha:** 15 de noviembre de 2026  
**Estado:** propuesta para explorar; no implementada.

## Motivación

StoneBot no debería limitarse a responder preguntas, guardar recuerdos y recuperar información de StoneWave. La idea es que funcione como un **agente** capaz de completar tareas mediante herramientas, observar sus resultados y decidir el siguiente paso dentro de límites claros.

Esto no requiere conciencia ni autonomía sin restricciones.

## Ciclo mínimo de agente

1. Recibir una petición u objetivo concreto.
2. Identificar qué información necesita y qué herramientas tiene disponibles.
3. Elegir y ejecutar una acción permitida.
4. Leer el resultado y comprobar si funcionó.
5. Continuar, corregir o detenerse; comunicar qué hizo y qué no logró.
6. Guardar en su memoria experimental las experiencias útiles, distinguiendo hechos de inferencias.

## Componentes reutilizables

- **Ollama:** modelo que interpreta objetivos y decide los siguientes pasos.
- **StoneWave:** memoria persistente aislada de la memoria personal.
- **Herramientas/API/MCP:** operaciones concretas que el agente puede invocar.
- **Orquestador de agente (pendiente):** bucle objetivo → herramienta → observación → decisión, con límites de pasos, tiempo y permisos.
- **Interfaz StoneBot:** muestra tareas, acciones y resultados; permite cancelar.

## Primer experimento sugerido

Pedir: «Busca en tu memoria experimental qué hicimos en la sesión anterior y resume lo que falta».

Verificar que StoneBot elige la herramienta de consulta, interpreta su salida y responde sin inventar recuerdos. Después probar una tarea de dos pasos que requiera elegir herramientas y comprobar resultados.

**No confundir una llamada fija a la memoria con agencia:** la prueba debe mostrar selección de herramientas y decisiones a partir de resultados.

## Límites y precauciones

- No dar acceso de escritura al repositorio original StoneWave ni a su memoria personal.
- Empezar con herramientas de solo lectura y un máximo pequeño de pasos.
- Registrar cada acción y su resultado; permitir detener el ciclo.
- Pedir aprobación antes de modificar archivos, ejecutar comandos sensibles o actuar sobre dispositivos físicos.
- Evitar razonamiento continuo en segundo plano en la primera versión para no saturar la GPU.

## Relación con la hoja de ruta

La base del agente se puede explorar desde la **etapa 1** con una tarea sencilla; la elección de tareas propias y la iniciativa controlada corresponden a la **etapa 4**. No es necesario construir otro proyecto ni reemplazar StoneWave.

## Idea relacionada, no prioritaria

Más adelante, un ESP32-S3 por Wi-Fi podría actuar como dispositivo físico o interfaz para StoneBot; Alexa sería opcional. Esta posibilidad **no es requisito** para convertir StoneBot en agente.
