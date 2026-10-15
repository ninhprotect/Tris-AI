from __future__ import annotations

import unittest

from services.local_tts import speech_text, tris_voice
from unittest.mock import patch


class LocalTTSTests(unittest.TestCase):
    def test_markdown_is_cleaned_and_bounded(self) -> None:
        value = speech_text("## Xin chào **bạn** [nhé](https://example.com) `code`", 24)
        self.assertNotIn("**", value)
        self.assertNotIn("https://", value)
        self.assertLessEqual(len(value), 25)

    @staticmethod
    def _has_icon(value: str) -> bool:
        icon_ranges = (
            (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF),
            (0x25A0, 0x25FF), (0x2190, 0x21FF), (0xE0020, 0xE007F),
        )
        return any(
            start <= ord(char) <= end or char in "︎️‍⃣©®™"
            for char in value
            for start, end in icon_ranges
        )

    def test_emoji_are_not_read_aloud(self) -> None:
        answer = (
            "Hello! Yes, I can speak English — and I'm Tris, your friendly local English tutor 😊\n\n"
            "How are you today? 🌞\n\n"
            "*(I'm not a real person, but I love helping learners like you practice English "
            "in a natural way!)*\n\n"
            "Would you like to chat about something fun or learn a little bit of English together? 💬 ✨"
        )
        value = speech_text(answer)
        self.assertFalse(self._has_icon(value), value)
        # The emoji was the only sentence boundary; the line break keeps the pause.
        self.assertIn("tutor. How are you today?", value)
        self.assertIn("(I'm not a real person", value)
        self.assertIn("way!) Would", value)  # no doubled terminator after "!)"
        self.assertTrue(value.endswith("English together?"), value)

    def test_line_breaks_without_punctuation_become_pauses(self) -> None:
        self.assertEqual(speech_text("- ✅ Done\n- ❌ Not done"), "- Done. - Not done")
        self.assertEqual(speech_text("## Tip\r\nSay it slowly.\n\nThen repeat!"),
                         "Tip. Say it slowly. Then repeat!")

    def test_arrows_become_pauses_not_words(self) -> None:
        self.assertEqual(speech_text("go → went → gone"), "go, went, gone")
        self.assertEqual(speech_text("**I am** ➡️ **I'm**"), "I am, I'm")
        self.assertEqual(speech_text("Past tense? → went"), "Past tense? went")
        self.assertEqual(speech_text("↔ ↩ ⤴️ ⬅️"), "")
        self.assertEqual(speech_text("word ↔ ↩ ↔ next"), "word, next")
        self.assertNotIn("→", speech_text("Remember: go → went"))

    def test_symbol_icons_are_not_read_aloud(self) -> None:
        self.assertEqual(speech_text("▶️ ▪️ ℹ️ ©️ ™️"), "")
        self.assertEqual(
            speech_text("#️⃣ Tip ⁉️ 〰️ 〽️ ㊗️ Ⓜ️ ◼️ ◀️ ®"),
            "Tip",
        )

    def test_vietnamese_letters_survive_icon_removal(self) -> None:
        value = speech_text("Chào bạn ✦ mình là Tris 😄 — học tiếng Việt nhé!")
        self.assertEqual(value, "Chào bạn mình là Tris — học tiếng Việt nhé!")

    def test_emoji_only_text_has_nothing_to_read(self) -> None:
        self.assertEqual(speech_text("😊 🌞 ✨ 👍🏽 ❤️"), "")

    def test_zwj_sequences_flags_and_empty_brackets_vanish(self) -> None:
        self.assertEqual(speech_text("Mình 👩‍💻 ở 🇻🇳 nè"), "Mình ở nè")
        self.assertEqual(speech_text("Great job (😊) [⭐] ( ) **🎉**"), "Great job")
        self.assertEqual(speech_text("Số 1️⃣ ⏰ 7h → 9h, giá 50.000₫ ©"), "Số 1 7h, 9h, giá 50.000₫")

    def test_icon_removal_happens_before_length_limit(self) -> None:
        value = speech_text("😊" * 40 + " Xin chào bạn nhé", 20)
        self.assertEqual(value, "Xin chào bạn nhé")

    def test_installed_local_voices_are_available(self) -> None:
        self.assertTrue(tris_voice.available("vi"))
        self.assertTrue(tris_voice.available("en"))

    def test_english_has_independent_natural_pace_preset(self):
        vi_profile = tris_voice.speech_profile('vi')
        self.assertEqual(vi_profile, (1.0, 1.06, 1.0))
        self.assertEqual(tris_voice.speech_profile('en'), (1.0, 1.0, 1.0))
        old_english = tris_voice.cache_profile('en')
        with patch('services.local_tts.TTS_EN_LENGTH_SCALE', 1.5):
            self.assertNotEqual(tris_voice.cache_profile('en'), old_english)
            self.assertEqual(tris_voice.cache_profile('vi'), 'tris-clone-v3')
            self.assertEqual(tris_voice.speech_profile('vi'), vi_profile)


if __name__ == "__main__":
    unittest.main()
