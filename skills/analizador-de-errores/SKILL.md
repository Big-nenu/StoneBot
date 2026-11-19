---
name: analizador-de-errores
description: Diagnostica un fallo técnico concreto cuando el usuario pide entenderlo o corregirlo. Identifica el error y propone una comprobación sencilla. Para solicitudes de guardar, copiar o confirmar información, elige el flujo del encargo.
---

# Analizador de errores

## Cuándo usar esta skill

Úsala cuando el usuario muestre una captura, un mensaje de error, un registro o describa un fallo técnico y pida ayuda para diagnosticarlo o corregirlo.

Una captura que aporta datos a un encargo de escritura o guardado se usa como fuente en ese encargo. Reserva el formato de diagnóstico para cuando el usuario quiera investigar un fallo técnico.

## Procedimiento

1. **Identifica lo observable.** Extrae el mensaje de error exacto, la aplicación involucrada y lo que el usuario intentaba hacer. Si hay imagen o archivo, usa solamente el contenido que realmente puedas leer; no inventes texto oculto.
2. **Separa certeza de hipótesis.** Indica brevemente qué sabemos y cuál es la causa más probable. Si hay varias causas plausibles, no presentes ninguna como confirmada.
3. **Prioriza una comprobación.** Propón el siguiente paso más sencillo, seguro y reversible que permita confirmar o descartar la causa principal. Evita listas largas de soluciones.
4. **Espera el resultado.** Cuando el usuario devuelva la captura, el mensaje o el resultado de la prueba, actualiza el diagnóstico y ofrece el siguiente paso. No repitas pruebas ya realizadas.
5. **Verifica la solución.** Considera resuelto el problema únicamente cuando haya evidencia de que funciona.

## Formato de respuesta preferido

- **Error detectado:** una frase clara.
- **Causa probable:** explicación breve en lenguaje sencillo; marca la incertidumbre.
- **Haz esto ahora:** una única acción concreta, con comando copiable solo si hace falta.
- **Qué esperamos observar:** resultado que confirmaría o descartaría la hipótesis.

Si el usuario solo quiere saber qué significa el error, explícalo sin obligarlo a hacer pruebas.

## Precauciones

- No afirmes que ejecutaste comandos, leíste archivos o reparaste sistemas sin una herramienta y evidencia reales.
- No inventes rutas, configuraciones, números de error ni resultados.
- Antes de recomendar borrados, cambios de permisos, modificaciones del registro, restauraciones o comandos destructivos, explica el riesgo y pide confirmación.
- Evita solicitar contraseñas, tokens, claves o información privada innecesaria; indica cómo ocultar datos sensibles en capturas.
- Si el archivo o la imagen no es legible, dilo claramente y pide únicamente el dato indispensable.
- No guardes automáticamente errores, capturas ni datos personales en memoria persistente.

## Estilo

Responde en español natural, de forma concisa. Trata un problema por turno. Evita tecnicismos cuando una explicación sencilla sea suficiente.
