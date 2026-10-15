"""Grammar correction learning mode."""

from ai.llm import ChatMessage, OllamaLLM
from ai.prompts import GRAMMAR_PROMPT


def respond(
    llm: OllamaLLM,
    history: list[ChatMessage],
    message: str,
    learner_context: str = "",
) -> str:
    """Correct important grammar errors and continue the conversation."""
    return llm.chat(GRAMMAR_PROMPT, history, message, learner_context)
