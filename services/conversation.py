"""Conversation learning mode."""

from ai.llm import ChatMessage, OllamaLLM
from ai.prompts import CONVERSATION_PROMPT


def respond(
    llm: OllamaLLM,
    history: list[ChatMessage],
    message: str,
    learner_context: str = "",
) -> str:
    """Continue a natural English conversation."""
    return llm.chat(CONVERSATION_PROMPT, history, message, learner_context)
