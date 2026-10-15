"""Tests for mood-based mascot voice line selection."""

import unittest

from services.voice_lines import pick_category


class PickCategoryTests(unittest.TestCase):
    def test_battle_keywords_pick_combat(self) -> None:
        self.assertEqual(pick_category("Chúng ta sẽ chiến thắng kẻ địch!"), "chien_dau")
        self.assertEqual(pick_category("Time to fight the enemy!"), "chien_dau")

    def test_praise_keywords_pick_excited(self) -> None:
        self.assertEqual(pick_category("Xuất sắc! Bạn làm tốt lắm."), "hung_phan")
        self.assertEqual(pick_category("Perfect answer, well done!"), "hung_phan")

    def test_sad_keywords_pick_calm(self) -> None:
        self.assertEqual(pick_category("Đừng lo, ai cũng sai. Cố lên nhé."), "buon")
        self.assertEqual(
            pick_category("Unfortunately that was a mistake, but take a break."),
            "buon",
        )

    def test_greeting_picks_happy(self) -> None:
        self.assertEqual(pick_category("Xin chào! Cùng học thôi nào."), "vui")
        self.assertEqual(pick_category("Hello! Ready to practice today?"), "vui")

    def test_long_neutral_answers_skip_the_intro(self) -> None:
        long_text = "Giải thích ngữ pháp chi tiết. " * 80
        self.assertIsNone(pick_category(long_text))

    def test_exercise_mode_defaults_to_excited(self) -> None:
        self.assertEqual(pick_category("Câu hỏi số 1 của bài tập.", "Exercises"), "hung_phan")

    def test_short_neutral_defaults_to_happy(self) -> None:
        self.assertEqual(pick_category("Mình giúp bạn được gì?"), "vui")

    def test_empty_text_returns_none(self) -> None:
        self.assertIsNone(pick_category(""))


if __name__ == "__main__":
    unittest.main()
