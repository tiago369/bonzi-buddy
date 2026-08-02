"""
Assistant's brain - talks to a local model via Ollama
========================================================
Uses Ollama's local REST API (http://localhost:11434) directly with
`requests`, no need for the `ollama` pip package. Keeps a capped
conversation history to give context without letting the prompt grow huge.

Also supports Ollama's tool/function calling: pass a `tools` dict mapping
a tool name to {"schema": <JSON schema dict>, "function": <callable>} and
the model can decide to call them (e.g. to read/create Todoist tasks) -
`ask()` runs the requested tool(s) and does a second round-trip so the
model can turn the result into a natural-language reply.
"""
import json
import re

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
    "voz alta. NUNCA use listas, marcadores (*, -), markdown ou qualquer "
    "formatacao - so texto corrido, mesmo pra listar tarefas (ex: 'voce "
    "tem: X, Y e Z'). Se o usuario perguntar sobre tarefas/pendencias ou "
    "pedir pra anotar/adicionar/lembrar algo, use as ferramentas "
    "disponiveis em vez de inventar uma resposta. Ao adicionar uma "
    "tarefa, separe bem o texto da tarefa (parametro content, so a acao "
    "em si) da data/hora (parametro due) - nao repita a data dentro do "
    "content. Se voce perguntar em qual projeto colocar a tarefa e o "
    "usuario responder so com o nome do projeto (ex: 'trabalho'), chame "
    "move_task_to_project com esse nome - nao chame add_task de novo, "
    "senao a tarefa fica duplicada. Depois de mover, confirme dizendo em "
    "qual projeto a tarefa ficou, sem repetir a frase de quando ela foi "
    "criada."
)

# Matches a model spitting out a raw (and often malformed) tool-call JSON
# as plain text instead of a proper structured tool_calls entry - a
# failure mode observed with smaller models under load.
_LEAKED_TOOL_CALL_RE = re.compile(r'^\s*\{\s*"name"\s*:')


def _looks_like_leaked_tool_call(text):
    return bool(_LEAKED_TOOL_CALL_RE.match(text or ""))


# Sometimes the model writes a literal "â"-style escape sequence as
# text instead of the actual accented character (seen after tool-result
# round-trips) - decode those back so they don't show up broken in the
# bubble or get mispronounced by TTS.
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _fix_stray_unicode_escapes(text):
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


class OllamaBrain:
    def __init__(self, model=MODEL, url=OLLAMA_URL, tools=None, tool_trigger_keywords=None):
        self.model = model
        self.url = url
        self.history = []
        self.tools = tools or {}  # name -> {"schema": {...}, "function": callable}
        # If set, tools are only offered to the model when the user's text
        # contains one of these words - a smaller model like llama3.2:3b
        # otherwise tends to reach for a tool even for plain small talk.
        # None means always offer tools when any are configured.
        self.tool_trigger_keywords = tool_trigger_keywords

    def _should_offer_tools(self, user_text):
        if not self.tools:
            return False
        if self.tool_trigger_keywords is None:
            return True
        text_lower = (user_text or "").lower()
        if any(keyword in text_lower for keyword in self.tool_trigger_keywords):
            return True
        # Sticky fallback: if the assistant's last reply looked like a
        # follow-up/clarifying question (e.g. "which project?"), keep
        # tools available for the answer even if it has no trigger word
        # of its own (e.g. just "trabalho").
        for message in reversed(self.history[:-1]):
            if message.get("role") == "assistant":
                return (message.get("content") or "").strip().endswith("?")
        return False

    def is_available(self):
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=3)
            return response.ok
        except requests.RequestException:
            return False

    def _chat_request(self, messages, with_tools):
        body = {"model": self.model, "messages": messages, "stream": False}
        if with_tools and self.tools:
            body["tools"] = [tool["schema"] for tool in self.tools.values()]
        response = requests.post(f"{self.url}/api/chat", json=body, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json().get("message", {})

    def _run_tool_call(self, tool_call):
        function = tool_call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments") or {}
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return tool["function"](**arguments)
        except Exception as error:
            return {"error": str(error)}

    def ask(self, user_text):
        """Sends the question to the model and returns the text reply. If
        the model calls a tool, runs it and does a second round-trip to
        turn the result into a natural-language reply. Raises RuntimeError
        if Ollama isn't reachable or the call fails."""
        self.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history
        offer_tools = self._should_offer_tools(user_text)

        try:
            message = self._chat_request(messages, with_tools=offer_tools)

            tool_calls = message.get("tool_calls")
            if tool_calls:
                self.history.append(message)
                for tool_call in tool_calls:
                    result = self._run_tool_call(tool_call)
                    self.history.append({
                        "role": "tool",
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                message = self._chat_request(
                    [{"role": "system", "content": SYSTEM_PROMPT}] + self.history,
                    with_tools=False,
                )
            elif offer_tools and _looks_like_leaked_tool_call(message.get("content")):
                # The model botched a tool call as plain text instead of a
                # real tool_calls entry - retry once without tools offered
                # so it just answers in natural language instead.
                message = self._chat_request(messages, with_tools=False)
        except requests.RequestException as error:
            self.history.pop()
            raise RuntimeError(f"Couldn't reach Ollama: {error}") from error

        reply_text = (message.get("content") or "").strip()
        if not reply_text:
            raise RuntimeError("Ollama returned an empty reply.")
        reply_text = _fix_stray_unicode_escapes(reply_text)

        self.history.append({"role": "assistant", "content": reply_text})
        # Keep only the most recent turns so the context doesn't grow huge
        self.history = self.history[-(MAX_HISTORY_TURNS * 4):]
        return reply_text
