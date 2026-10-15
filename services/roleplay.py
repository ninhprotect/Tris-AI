"""Scenario-based English role play."""

from ai.llm import ChatMessage, OllamaLLM
from ai.prompts import roleplay_prompt

SCENARIOS = [
    "Coffee Shop",
    "Restaurant",
    "Airport",
    "Hotel",
    "University",
    "Job Interview",
    "Shopping",
]

OPENING_MESSAGES = {
    "Coffee Shop": "Hi! Welcome. What can I get for you today?",
    "Restaurant": "Good evening! Welcome to our restaurant. Do you have a reservation?",
    "Airport": "Good morning. May I see your passport and boarding pass, please?",
    "Hotel": "Welcome to our hotel. How may I help you today?",
    "University": "Hi! Are you looking for a particular classroom or department?",
    "Job Interview": "Good morning. Thanks for coming in. Could you introduce yourself?",
    "Shopping": "Hello! Let me know if I can help you find anything today.",
}


def opening_message(scenario: str) -> str:
    """Return a deterministic first turn so role play starts immediately."""
    return OPENING_MESSAGES.get(scenario, OPENING_MESSAGES["Coffee Shop"])


def respond(
    llm: OllamaLLM,
    history: list[ChatMessage],
    message: str,
    scenario: str,
    learner_context: str = "",
) -> str:
    """Continue the selected role-play scenario."""
    return llm.chat(roleplay_prompt(scenario), history, message, learner_context)
