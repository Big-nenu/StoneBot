"""Consulta manual de la memoria de StoneBot. Requiere Ollama."""
from app import get_memory

if __name__ == "__main__":
    memory = get_memory()
    try:
        print(memory.query("¿Qué es StoneBot?", namespace="default"))
    finally:
        memory.close()
