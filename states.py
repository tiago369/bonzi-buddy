"""
Assistant states <-> animation pools
=======================================
Each assistant state (idle, listening, thinking, talking, etc.) maps to a
list of animation names (defined in imgs/animations.json). When a pool has
more than one option, one is picked at random - this keeps the monkey from
feeling repetitive/mechanical.
"""

# Neutral resting pose - plays in a continuous loop the whole time (slow
# breathing makes sense to keep going). The gestures below are "one-shot":
# they play once on top of the base pose and return to it, instead of
# repeating forever (blinking nonstop for 15s looks like a nervous tic).
IDLE_BASE = "breathing"

IDLE_GESTURES = [
    "blinking",
    "yawn",
    "shrug",
    "shuffling_papers",
    "hands_behind_back",
]

GREETING_POOL = ["waving_hello", "waving"]

LISTENING_POOL = ["listening"]

THINKING_POOL = ["clipboard", "spin_globe_on_finger", "suggestion"]

TALKING_POOL = ["talking_pout"]

SUCCESS_POOL = ["applause", "tooth_sparkle", "thanks_flip"]

ERROR_POOL = ["dont_know", "cant_help", "cant_help_2", "head_shake_no"]

NO_HEAR_POOL = ["cant_hear_you"]

# Words that, if they appear in the AI's reply, suggest the "error/doubt"
# reaction fits better than the generic talking pose. Kept in Portuguese
# on purpose - the assistant's persona still replies in Portuguese
# (see brain.py's PROMPT_SISTEMA), so these need to match its own output.
ERROR_KEYWORDS = (
    "não sei", "nao sei", "não tenho certeza", "nao tenho certeza",
    "desculp", "não consigo", "nao consigo", "não posso", "nao posso",
    "infelizmente", "erro",
)

SUCCESS_KEYWORDS = (
    "claro!", "com certeza", "consegui", "perfeito", "ótimo", "otimo",
    "boa ideia", "parabéns", "parabens",
)


def choose_pool_for_reply(text):
    """Given the AI's text reply, decides whether the reaction should be
    the success one, the error/doubt one, or the default talking pose."""
    text_lower = (text or "").lower()
    if any(word in text_lower for word in ERROR_KEYWORDS):
        return ERROR_POOL
    if any(word in text_lower for word in SUCCESS_KEYWORDS):
        return SUCCESS_POOL
    return TALKING_POOL
