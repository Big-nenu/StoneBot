# Instrucciones de Codex para StoneBot

## Forma de trabajo

- Cuando el usuario plantee una idea, pida una propuesta o pregunte cómo implementar una funcionalidad, presenta un plan breve de implementación.
- Cuando el usuario pida directamente un cambio o apruebe un plan, implementa el cambio.
- Al resolver un error, investiga su causa raíz y corrígela.
- Actualiza el `README.md` cuando agregues, modifiques o elimines funcionalidades relevantes.

## Alcance y arquitectura

- Consulta el `README.md`, en particular «Dónde buscar cuando quieras cambiar algo», para ubicar el código y verificar el comportamiento vigente.
- Mantén StoneBot como una aplicación de escritorio local para Windows, con Python y PySide6. Ollama es el proveedor local y los servicios en la nube son opcionales.
- Mantén la lógica de conversación y ejecución de tareas separada de la ventana. Si cambias el ciclo de vida de la app, verifica que cerrar la ventana la oculte cuando la bandeja esté disponible y que «Salir» detenga el proceso.

## Memoria y herramientas

- Gestiona la memoria personal mediante el cliente MCP de StoneWave en `stonewave_memory.py`. Mantén separada la base experimental que usa `stonebot_engine/`.
- Usa bases temporales y modelos simulados en las pruebas de memoria. Conserva las validaciones que protegen los datos personales y los controles de autorización al cambiar herramientas MCP.

## Verificación y cierre

- Para iniciar la aplicación, ejecuta `python -B app.py` desde la raíz del repositorio. Los requisitos de instalación están en «Ejecutar y probar» del `README.md`.
- Ejecuta las pruebas pertinentes de `tests/` con `python -B tests/<archivo>.py`. Para cambios en la memoria personal, revisa `tests/test_stonewave_memory.py` y `tests/test_memory_integration.py`. Para cambios en la bandeja, usa `tests/test_tray.py`.
- Al finalizar los cambios, revisa `git status`, crea un commit con un mensaje descriptivo y sube los cambios con `git push`.
- Resume brevemente qué cambió y qué quedó pendiente, si corresponde.
