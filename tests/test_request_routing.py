"""Pruebas aisladas de clasificación de solicitudes, sin iniciar la interfaz Qt."""
import sys
import unittest
from pathlib import Path

# Permite ejecutar este archivo directamente desde la carpeta raíz del repositorio.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from request_routing import requests_external_tools, requests_local_read, requested_web_link


def user(content):
    return {"role": "user", "content": content}


def assistant(content):
    return {"role": "assistant", "content": content}


class RequestRoutingTests(unittest.TestCase):
    def test_external_lookup(self):
        self.assertTrue(requests_external_tools([user("Busca documentación en internet")]))

    def test_memory_request_not_external(self):
        self.assertFalse(requests_external_tools([user("Busca en tu memoria lo que recuerdas")]))

    def test_local_directory_read(self):
        self.assertTrue(requests_local_read([user(r"Revisa C:\\Proyectos\\StoneBot")]))

    def test_web_link_from_previous_message(self):
        messages = [user("https://example.com/readme"), assistant("Puedo revisarlo."),
                    user("Abre el enlace")]
        self.assertEqual(requested_web_link(messages), "https://example.com/readme")

    def test_new_topic_does_not_reuse_tool_request(self):
        messages = [user("Busca documentación web"), assistant("¿Qué versión necesitas?"),
                    user("Mejor hablemos de otra cosa")]
        self.assertFalse(requests_external_tools(messages))


if __name__ == "__main__":
    unittest.main()
