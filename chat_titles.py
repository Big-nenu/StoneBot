"""Títulos breves para conversaciones nuevas."""
import re

from ollama import Client

from ai_provider import OLLAMA_URL, OpenRouter


PATH_START = r"(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|\.{1,2}[\\/]|/(?=[\w.]))"
QUOTED_PATH = re.compile(rf'''["'`«]{PATH_START}[^\r\n"'`»]*["'`»]''')
LOCAL_PATH = re.compile(rf"(?<![\w/]){PATH_START}[^\r\n]*")
URL = re.compile(r"https?://[^\s<>]+", re.I)
RELATIVE_PATH = re.compile(r"(?<![\w/])(?:[\w.-]+[\\/]){2,}[\w.-]+|(?<![\w/])(?:[\w.-]+[\\/])+[\w-]+\.[\w-]+")
QUOTES = str.maketrans("", "", '\"\'«»“”‘’`')


def title_text(text):
    text = QUOTED_PATH.sub("", URL.sub("", text))
    pathless, removed = LOCAL_PATH.subn("", text)
    if removed:
        pathless = re.sub(r"\s+\b(?:en|desde|hacia|de|del)[ \t]*$", "", pathless, flags=re.I | re.M)
    return " ".join(RELATIVE_PATH.sub("", pathless).translate(QUOTES).split()).strip(" #*:-–—.")


def generate_title(ai, question):
    question = title_text(question)
    fallback = question[:40].rstrip() or "Nuevo chat"
    try:
        client = OpenRouter() if ai.cloud else Client(host=OLLAMA_URL, timeout=12)
        response = client.chat(
            model=ai.model,
            messages=[
                {"role": "system", "content": "Escribe un título en español de una a cinco palabras para esta "
                 "conversación. Devuelve solo el título, sin rutas, comillas ni etiquetas."},
                {"role": "user", "content": question[:600]},
            ],
            think=False,
            options={"temperature": 0, "num_predict": 80},
        )
        line = (response.message.content or "").strip().partition("\n")[0]
        line = re.sub(r"^\s*t[ií]tulo\s*:\s*", "", line, flags=re.I)
        return " ".join(title_text(line).split()[:5]) or fallback
    except Exception:
        return fallback
