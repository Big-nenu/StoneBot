# StoneBot

Proyecto independiente que une tres partes:

1. **StoneWave** — la memoria local de experiencias (instancia de trabajo de StoneWave, **separada** de la memoria personal).
2. **IA local** — Ollama y/o PC, con modelo de visión para que el dispositivo "vea" lo que hay alrededor.
3. **Componentes electrónicos** — sobre todo el **ESP32-S3 N16R8** con mini cámara, que es el "ojo y cuerpo" del sistema.

La idea es que un dispositivo físico **aprenda por experiencias reales**: ve, registra, prueba, falla, corrige y va acumulando conocimiento, usando eso para ajustar sus decisiones.

## Estado

Idea y planificación. Aún no se ha construido ni probado el experimento.

## Principios

- **Primero pruebas reales, después complejidad.** No montar una arquitectura grande sin comprobar qué falta.
- **Memoria aislada.** StoneBot usa su propia base de datos / ruta de almacenamiento en StoneWave; **no** se toca la memoria personal.
- **Medir resultados.** ¿Mejora con los intentos? ¿qué recuerda? ¿qué hipótesis cambian?
- **No confundir respuesta memorizada con aprendizaje generalizable.**
- **Seguridad del hardware.** Acciones críticas (p.ej. un servo) deben tener límites definidos por código, no depender de la IA.
- **Primero lo físico, luego lo complejo.** El experimento inicial es modesto; se compone conforme llega la información.

## Estructura del proyecto

```
StoneBot/
├── docs/
│   ├── 00-visión-del-proyecto.md
│   └── 01-primer-experimento-que-ve.md
├── experiments/
│   └── primer-experimento-que-ve/
│       ├── esp32/            # firmware para el ESP32-S3
│       ├── pc/               # servidor Python + cliente de Ollama + cliente de StoneWave
│       └── config/           # configuración y logs de prueba
├── firmware/                 # futuro
├── pc/                       # futuro
└── memory/                   # configuración de la instancia aparte de StoneWave
```

## Próximo paso

El primer experimento es **"el ojo que ve y registra"**: la cámara web de la PC captura lo que ve el entorno, la PC lo procesa con un modelo de visión de Ollama (una descripción sencilla), y esa descripción se registra como experiencia en StoneWave (instancia aparte). Después se añaden el ESP32-S3 + cámara mini y, luego, servo, botones, etc.

## Notas importantes

- El **ESP32-S3** es el "ojo y cuerpo" de StoneBot; se conecta a la PC (y/o a Ollama) por WiFi.
- La conexión con Ollama y StoneWave se hace por **configuración**, no modificando código de StoneWave.
- Los archivos de configuración y logs de pruebas se dejan en `config/` y `docs/`, separados de la memoria personal.
