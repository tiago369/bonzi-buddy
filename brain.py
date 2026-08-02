"""
Cerebro do assistente - fala com um modelo local via Ollama
==============================================================
Usa a API REST local do Ollama (http://localhost:11434) diretamente com
`requests`, sem precisar do pacote pip `ollama`. Mantem um historico
limitado de conversa para dar contexto sem deixar o prompt gigante.
"""
import requests

OLLAMA_URL = "http://localhost:11434"
MODELO = "llama3.2:3b"
TIMEOUT_SEGUNDOS = 60
MAX_TURNOS_HISTORICO = 10

PROMPT_SISTEMA = (
    "Voce e um macaquinho assistente de mesa, simpatico e bem-humorado, "
    "que vive no canto da tela do usuario. Responda sempre em portugues, "
    "de forma curta e direta (no maximo 2-3 frases curtas), porque sua "
    "resposta aparece num balaozinho de fala pequeno e tambem e falada em "
    "voz alta. Evite listas, markdown ou formatacao - so texto corrido."
)


class OllamaBrain:
    def __init__(self, modelo=MODELO, url=OLLAMA_URL):
        self.modelo = modelo
        self.url = url
        self.historico = []

    def is_available(self):
        try:
            resposta = requests.get(f"{self.url}/api/tags", timeout=3)
            return resposta.ok
        except requests.RequestException:
            return False

    def ask(self, texto_usuario):
        """Envia a pergunta ao modelo e devolve a resposta em texto.
        Levanta RuntimeError se o Ollama nao estiver acessivel ou a
        chamada falhar."""
        self.historico.append({"role": "user", "content": texto_usuario})
        mensagens = [{"role": "system", "content": PROMPT_SISTEMA}] + self.historico

        try:
            resposta = requests.post(
                f"{self.url}/api/chat",
                json={"model": self.modelo, "messages": mensagens, "stream": False},
                timeout=TIMEOUT_SEGUNDOS,
            )
            resposta.raise_for_status()
        except requests.RequestException as erro:
            self.historico.pop()
            raise RuntimeError(f"Nao consegui falar com o Ollama: {erro}") from erro

        dados = resposta.json()
        texto_resposta = dados.get("message", {}).get("content", "").strip()
        if not texto_resposta:
            self.historico.pop()
            raise RuntimeError("O Ollama respondeu vazio.")

        self.historico.append({"role": "assistant", "content": texto_resposta})
        # Mantem so os ultimos turnos para nao deixar o contexto gigante
        self.historico = self.historico[-(MAX_TURNOS_HISTORICO * 2):]
        return texto_resposta
