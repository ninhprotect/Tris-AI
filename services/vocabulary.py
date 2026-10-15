"""Vocabulary learning mode."""

from ai.llm import ChatMessage, OllamaLLM
from ai.prompts import VOCABULARY_PROMPT


def respond(
    llm: OllamaLLM,
    history: list[ChatMessage],
    message: str,
    learner_context: str = "",
) -> str:
    """Teach a word or evaluate the learner's practice sentence."""
    return llm.chat(VOCABULARY_PROMPT, history, message, learner_context)
