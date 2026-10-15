"""Guard the Tris mascot identity in every system prompt."""

import unittest

from ai.prompts import (
    CONVERSATION_PROMPT,
    GRAMMAR_PROMPT,
    ROLEPLAY_BASE_PROMPT,
    VOCABULARY_PROMPT,
    roleplay_prompt,
)


class IdentityPromptTests(unittest.TestCase):
    def test_every_mode_prompt_carries_identity(self) -> None:
        for prompt in (
            CONVERSATION_PROMPT,
            GRAMMAR_PROMPT,
            VOCABULARY_PROMPT,
            ROLEPLAY_BASE_PROMPT,
            roleplay_prompt("Coffee Shop"),
        ):
            self.assertIn("Tris", prompt)
            self.assertIn("NEVER", prompt)

    def test_identity_names_the_creator(self) -> None:
        self.assertIn("Nguyễn Hải Hà Ninh", CONVERSATION_PROMPT)

    def test_technical_provenance_is_only_for_explicit_questions(self) -> None:
        self.assertIn("Qwen", CONVERSATION_PROMPT)
        self.assertIn("Only discuss technical provenance", CONVERSATION_PROMPT)
        self.assertNotIn("Alibaba", CONVERSATION_PROMPT)


if __name__ == "__main__":
    unittest.main()
