"""
Estados do assistente <-> pools de animacoes
=============================================
Cada estado do assistente (ocioso, ouvindo, pensando, falando, etc.) mapeia
para uma lista de nomes de animacoes (definidas em imgs/animations.json).
Quando ha mais de uma opcao no pool, uma e escolhida aleatoriamente - isso
evita que o macaco pareca repetitivo/mecanico.
"""

# Pose neutra de descanso - toca em loop continuo o tempo todo (respirar
# devagar faz sentido continuar). Os gestos abaixo sao "pontuais": tocam
# uma unica vez por cima da base e voltam pra ela, em vez de ficar
# repetindo pra sempre (piscar sem parar por 15s parece um tique nervoso).
IDLE_BASE = "respirando"

IDLE_GESTOS = [
    "piscando",
    "bocejo",
    "dar_de_ombros",
    "passando_papeis",
    "maos_atras",
]

GREETING_POOL = ["dando_ola", "acenando"]

LISTENING_POOL = ["ouvindo"]

THINKING_POOL = ["prancheta", "girando_terra_dedos", "sugestao"]

TALKING_POOL = ["boca_fazendo_bico"]

SUCCESS_POOL = ["parabens", "dente_brilhando", "obrigada_pirueta"]

ERROR_POOL = ["nao_sei_dois", "posso_fazer_nada", "posso_fazer_nada_2", "negacao"]

NO_HEAR_POOL = ["nao_te_escuto"]

# Palavras que, se aparecerem no comeco da resposta da IA, sugerem que a
# reacao "de erro/duvida" combina mais do que a pose generica de fala.
ERROR_KEYWORDS = (
    "não sei", "nao sei", "não tenho certeza", "nao tenho certeza",
    "desculp", "não consigo", "nao consigo", "não posso", "nao posso",
    "infelizmente", "erro",
)

SUCCESS_KEYWORDS = (
    "claro!", "com certeza", "consegui", "perfeito", "ótimo", "otimo",
    "boa ideia", "parabéns", "parabens",
)


def escolher_pool_para_resposta(texto):
    """Dada a resposta em texto da IA, decide se a reacao deve ser a de
    sucesso, a de erro/duvida, ou a pose padrao de fala."""
    texto_lower = (texto or "").lower()
    if any(p in texto_lower for p in ERROR_KEYWORDS):
        return ERROR_POOL
    if any(p in texto_lower for p in SUCCESS_KEYWORDS):
        return SUCCESS_POOL
    return TALKING_POOL
