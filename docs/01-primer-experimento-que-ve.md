# Primer experimento: el ojo que ve y registra

> **VERSIÓN 1 — pruebas con cámara web en la PC**
> (El ESP32-S3 con cámara mini será la fase siguiente; el flujo de abajo se vuelve
> igual, solo cambia la *fuente* de la imagen.)

## 1. Objetivo

Probar que StoneBot puede **captar lo que ve un entorno, extraer una descripción
con IA local y guardarla como experiencia en la memoria aislada de StoneWave**.

No se busca un bot que tome decisiones complejas todavía. Se busca la base:
- captar lo que ve el entorno (cámara web),
- la PC lo procesa con un modelo de visión de Ollama,
- la descripción se queda en **StoneWave (instancia aparte de la personal)**,
- después se puede consultar.

## 2. Componentes

### Hardware (verificado, funciona)
- **Cámara web** conectada a la PC (índice 0, abre y captura sin configuración extra).
- PC con **Python 3.14** y **OpenCV 5.0** (instalado y probado).

### Software / IA
- **Ollama** corriendo en la PC (`localhost:11434`), con modelos que soportan visión:
  - `lfm3-vl:latest` (1.5 GB, 1.7B param) → *recomendado para empezar* (ligero, tipo "vista rápida").
  - `gemma4:e2b-it-qat` (4.3 GB, 4.6B param) → *otro buen candidato*.
  - `qwen3.5:4b` (3.3 GB, 4.2B param) → también con visión.
- **StoneWave** (instancia de trabajo de StoneBot, base/DB propia, sin modificar la memoria personal).

## 3. Flujo de datos

```
[Cámara web] -- imagen --> [Python (OpenCV)] --> [PC] --> [Ollama (modelo de visión)]
      |                                   |
      |                                   +--> descripción de texto
      |                                   |
      +-----------------------------------+--> [StoneWave] --> experiencia registrada
                                                 (timestamp, observación, contexto)
```

Pasos del ciclo:

1. Python lee un fotograma de la cámara con OpenCV (tamaño 320×240 o 640×480).
2. Lo manda a Ollama con un modelo de visión usando la API de Ollama.
3. Ollama devuelve un texto breve: "había una ventana, una mesa y una silla..." y,
   si se lo pedís, clasificaciones simples (luz, movimiento, personas, etc.).
4. La PC envía esa descripción (con timestamp y contexto) a StoneWave MCP y se queda
   como "experiencia".
5. El usuario consulta StoneWave y ve cómo van apareciendo observaciones de lo que
   ve el dispositivo.

## 4. Qué guarda StoneWave (como experiencia)

Una experiencia no es un simple log. Por ahora, al menos:

- `timestamp` (fecha/hora local del evento)
- `observación` (texto que devolvió Ollama)
- `fuente` (ej. "webcam index0")
- `contexto` (p.ej. etiqueta del momento, estado de otros sensores)
- `metadatos` (ID, flag de calidad, retry, etc.)

Esto queda **en la instancia de StoneBot**, nunca en la memoria personal.

## 5. Cómo verificarlo

1. El script captura el webcam y manda un fotograma a Ollama al menos 3 veces.
2. Cada imagen llega a Ollama y devuelve una descripción.
3. La descripción llega a StoneWave y aparece como experiencia.
4. Se puede consultar desde el cliente de StoneWave (CLI o MCP) y leer el registro.
5. Se mide:
   - ¿llega la imagen? (timeout, tamaño, pérdida)
   - ¿la IA responde en un tiempo razonable?
   - ¿la experiencia queda guardada y consultable?

## 6. Mikado de paso (si las hay)

- ¿Qué modelo elegir para la visión? `lfm3-vl:latest` por ser el más ligero con
  visión; `gemma4:e2b-it-qat` o `qwen3.5:4b` si se necesita mayor calidad.
- ¿Qué configuración de StoneWave usamos para la instancia de StoneBot (DB, ruta,
  nombre del espacio de memoria)?
- ¿Qué formato mandar a Ollama: imagen base64 JPEG, o diagonal/ruta local?
- ¿Qué tipo de descripción querés: libre, o clasificación cerrada (p.e.j.
  "persona / mueve / luz / vacío / otro")?

## 7. Futuro: ESP32-S3 + cámara mini

Cuando te sientas cómodo con el hardware y un mini-cámara, el mismo flujo se repite
con el ESP32-S3 capturando y mandando imágenes a la PC, que ya pasa a Ollama y
StoneWave. El código de Python/OpenCV se usa igual; solo cambia la fuente de la
imagen.

## 8. Límites generados para este primer experimento

- Solo *ve* y *registra*. No decide aún.
- Sin servo, sin botones de control, sin IMU.
- La descripción es textual (no mapa ni posición 2D aún).
- Si el modelo de visión es lento, se sujetan fotogramas o se redimensiona la imagen.
