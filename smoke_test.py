"""Live end-to-end check for all four modes; requires the project Ollama model."""

import sys

from ai.llm import LocalAIError, OllamaLLM
from services import conversation, grammar, roleplay, vocabulary


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    llm = OllamaLLM()
    checks = [
        (
            "Conversation",
            lambda: conversation.respond(llm, [], "Yesterday I go to university."),
        ),
        (
            "Grammar",
            lambda: grammar.respond(llm, [], "Yesterday I go to school."),
        ),
        (
            "Vocabulary",
            lambda: vocabulary.respond(llm, [], "accomplish"),
        ),
        (
            "Role Play",
            lambda: roleplay.respond(
                llm,
                [{"role": "assistant", "content": roleplay.opening_message("Coffee Shop")}],
                "I want two coffee please.",
                "Coffee Shop",
            ),
        ),
    ]

    for mode, run_check in checks:
        print(f"\n--- {mode} ---")
        try:
            print(run_check())
        except LocalAIError as exc:
            print(f"FAILED: {exc}")
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
