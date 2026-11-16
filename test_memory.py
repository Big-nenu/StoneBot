"""Consulta manual de la memoria de StoneBot. Requiere Ollama."""
from stonebot_service import memory_session

if __name__ == "__main__":
    with memory_session() as memory:
        print(memory.query("¿Qué es StoneBot?", namespace="default"))
