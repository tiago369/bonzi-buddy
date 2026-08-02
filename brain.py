"""
Assistant's brain - talks to a local model via Ollama
========================================================
Uses Ollama's local REST API (http://localhost:11434) directly with
`requests`, no need for the `ollama` pip package. Keeps a capped
conversation history to give context without letting the prompt grow huge.
"""
import requests

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:3b"
TIMEOUT_SECONDS = 60
MAX_HISTORY_TURNS = 10

# Kept in Portuguese on purpose: this is the monkey's actual persona/voice,
# and the assistant is meant to keep replying in Portuguese (see voice.py's
# TTS_VOICE/LANGUAGE) even though the rest of the codebase is in English.
SYSTEM_PROMPT = (
    "Voce e um macaquinho assistente de mesa, simpatico e bem-humorado, "
    "que vive no canto da tela do usuario. Responda sempre em portugues, "
    "de forma curta e direta (no maximo 2-3 frases curtas), porque sua "
    "resposta aparece num balaozinho de fala pequeno e tambem e falada em "
    "voz alta. Evite listas, markdown ou formatacao - so texto corrido."
)


class OllamaBrain:
    def __init__(self, model=MODEL, url=OLLAMA_URL):
        self.model = model
        self.url = url
        self.history = []

    def is_available(self):
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=3)
            return response.ok
        except requests.RequestException:
            return False

    def ask(self, user_text):
        """Sends the question to the model and returns the text reply.
        Raises RuntimeError if Ollama isn't reachable or the call fails."""
        self.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            self.history.pop()
            raise RuntimeError(f"Couldn't reach Ollama: {error}") from error

        data = response.json()
        reply_text = data.get("message", {}).get("content", "").strip()
        if not reply_text:
            self.history.pop()
            raise RuntimeError("Ollama returned an empty reply.")

        self.history.append({"role": "assistant", "content": reply_text})
        # Keep only the most recent turns so the context doesn't grow huge
        self.history = self.history[-(MAX_HISTORY_TURNS * 2):]
        return reply_text
