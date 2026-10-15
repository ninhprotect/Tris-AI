"""Small terminal checkpoint for testing Ollama and conversation history."""

import sys

from ai.llm import ChatMessage, LocalAIError, OllamaLLM
from services import conversation


def main() -> None:
    # Local model responses can contain Vietnamese characters on Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    llm = OllamaLLM()
    history: list[ChatMessage] = []

    print("Tris AI CLI — type /clear to reset or /exit to stop.")
    while True:
        user_message = input("You: ").strip()
        if not user_message:
            continue
        if user_message.lower() == "/exit":
            break
        if user_message.lower() == "/clear":
            history.clear()
            print("Conversation cleared.")
            continue

        try:
            answer = conversation.respond(llm, history, user_message)
        except LocalAIError as exc:
            print(f"AI: {exc}")
            continue

        history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": answer},
            ]
        )
        print(f"AI: {answer}")


if __name__ == "__main__":
    main()
