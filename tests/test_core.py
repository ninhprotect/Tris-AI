"""Fast tests that do not require a running Ollama server."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from ollama import ResponseError

from ai.llm import LocalAIConnectionError, LocalAIModelError, OllamaLLM
from database import ExerciseStats, SkillInsight
from services import conversation, exercises, grammar, roleplay, skill_analysis, vocabulary


class FakeClient:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def chat(self, **kwargs: object) -> dict:
        self.kwargs = kwargs
        return {"message": {"content": "Test response"}}


class FakeLLM:
    def __init__(self) -> None:
        self.system_prompt = ""

    def chat(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
        learner_context: str = "",
    ) -> str:
        self.system_prompt = system_prompt
        return "OK"


class OfflineClient:
    def chat(self, **kwargs: object) -> dict:
        raise httpx.ConnectError("Ollama is offline")


class MissingModelClient:
    def chat(self, **kwargs: object) -> dict:
        raise ResponseError("model not found", status_code=404)


class StructuredClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.kwargs: dict = {}

    def chat(self, **kwargs: object) -> dict:
        self.kwargs = kwargs
        return {"message": {"content": json.dumps(self.payload)}}


class OllamaLLMTests(unittest.TestCase):
    def test_builds_messages_and_disables_thinking(self) -> None:
        client = FakeClient()
        llm = OllamaLLM(client=client)  # type: ignore[arg-type]

        answer = llm.chat(
            "System prompt",
            [{"role": "assistant", "content": "Earlier answer"}],
            "Hello",
        )

        self.assertEqual(answer, "Test response")
        self.assertFalse(client.kwargs["think"])
        messages = client.kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1], {"role": "user", "content": "Hello"})

    def test_learner_memory_is_added_to_system_prompt(self) -> None:
        client = FakeClient()
        llm = OllamaLLM(client=client)  # type: ignore[arg-type]

        llm.chat("Tutor prompt", [], "Hello", "Past Simple: Yếu")

        system_message = client.kwargs["messages"][0]["content"]
        self.assertIn("Tutor prompt", system_message)
        self.assertIn("Past Simple: Yếu", system_message)

    def test_history_is_limited_to_recent_messages(self) -> None:
        history = [
            {"role": "user", "content": f"message {index}"}
            for index in range(30)
        ]
        trimmed = OllamaLLM._trim_history(history)
        self.assertLess(len(trimmed), len(history))
        self.assertEqual(trimmed[-1]["content"], "message 29")

    def test_gradio_rich_text_history_is_converted_for_ollama(self) -> None:
        client = FakeClient()
        llm = OllamaLLM(client=client)  # type: ignore[arg-type]

        llm.chat(
            "System",
            [
                {
                    "role": "assistant",
                    "content": [{"text": "Welcome!", "type": "text"}],
                }
            ],
            "Hello",
        )

        self.assertEqual(client.kwargs["messages"][1]["content"], "Welcome!")

    def test_offline_ollama_becomes_a_friendly_error(self) -> None:
        llm = OllamaLLM(client=OfflineClient())  # type: ignore[arg-type]
        with self.assertRaisesRegex(LocalAIConnectionError, "Không thể kết nối"):
            llm.chat("System", [], "Hello")

    def test_missing_model_includes_pull_command(self) -> None:
        llm = OllamaLLM(client=MissingModelClient())  # type: ignore[arg-type]
        with self.assertRaisesRegex(LocalAIModelError, "ollama pull"):
            llm.chat("System", [], "Hello")

    def test_structured_chat_passes_json_schema_to_ollama(self) -> None:
        schema = {
            "type": "object",
            "properties": {"questions": {"type": "array"}},
        }
        client = StructuredClient({"questions": []})
        llm = OllamaLLM(client=client)  # type: ignore[arg-type]

        result = llm.chat_structured("System", "Create", schema)

        self.assertEqual(result, {"questions": []})
        self.assertEqual(client.kwargs["format"], schema)
        self.assertEqual(client.kwargs["options"]["num_predict"], 2048)


class ServiceTests(unittest.TestCase):
    def test_each_mode_uses_a_different_prompt(self) -> None:
        fake = FakeLLM()
        prompts: list[str] = []

        conversation.respond(fake, [], "Hello")  # type: ignore[arg-type]
        prompts.append(fake.system_prompt)
        grammar.respond(fake, [], "I go yesterday")  # type: ignore[arg-type]
        prompts.append(fake.system_prompt)
        vocabulary.respond(fake, [], "accomplish")  # type: ignore[arg-type]
        prompts.append(fake.system_prompt)
        roleplay.respond(fake, [], "A coffee please", "Coffee Shop")  # type: ignore[arg-type]
        prompts.append(fake.system_prompt)

        self.assertEqual(len(set(prompts)), 4)
        self.assertIn("Coffee Shop", prompts[-1])

    def test_every_roleplay_scenario_has_an_opening(self) -> None:
        for scenario in roleplay.SCENARIOS:
            self.assertTrue(roleplay.opening_message(scenario))


class SkillAnalysisTests(unittest.TestCase):
    def test_classifies_common_grammar_skills(self) -> None:
        self.assertEqual(
            skill_analysis.classify_grammar_skill(
                "Yesterday I go to school.",
                "Use the past simple: went.",
            ),
            "Past Simple",
        )
        self.assertEqual(
            skill_analysis.classify_grammar_skill(
                "I bought book.",
                "Bạn cần thêm mạo từ 'a'.",
            ),
            "Articles",
        )

    def test_memory_context_uses_only_observed_evidence(self) -> None:
        context = skill_analysis.build_learner_context(
            [SkillInsight("Past Simple", correct_count=0, error_count=3)]
        )
        self.assertIn("Past Simple", context)
        self.assertIn("Yếu", context)

    def test_one_success_does_not_create_a_strong_diagnosis(self) -> None:
        insight = SkillInsight("Vocabulary", correct_count=1, error_count=0)
        self.assertEqual(insight.level, "Chưa đủ dữ liệu")


class ExerciseServiceTests(unittest.TestCase):
    def _question(self) -> dict:
        return {
            "question_type": "multiple_choice",
            "prompt": "Yesterday, I ___ to school.",
            "options": ["go", "went", "gone", "going"],
            "correct_answer": "went",
            "accepted_answers": ["went"],
            "explanation_vi": "Yesterday yêu cầu thì quá khứ đơn.",
        }

    def test_auto_selects_observed_weak_skill(self) -> None:
        insights = [SkillInsight("Past Simple", correct_count=0, error_count=3)]
        self.assertEqual(
            exercises.choose_skill(exercises.AUTO_SKILL, insights),
            "Past Simple",
        )

    def test_generates_portable_validated_questions(self) -> None:
        payload = {"questions": [self._question() for _ in range(3)]}
        client = StructuredClient(payload)
        llm = OllamaLLM(client=client)  # type: ignore[arg-type]

        questions = exercises.generate_questions(
            llm, "Past Simple", "Easy", 3
        )

        self.assertEqual(len(questions), 3)
        self.assertEqual(questions[0]["position"], 1)
        self.assertEqual(questions[0]["skill"], "Past Simple")

    def test_multiple_choice_accepts_letter_or_text(self) -> None:
        question = {
            **self._question(),
            "position": 1,
            "skill": "Past Simple",
            "difficulty": "Easy",
        }
        self.assertTrue(exercises.check_answer(question, "B"))
        self.assertTrue(exercises.check_answer(question, "went."))
        self.assertFalse(exercises.check_answer(question, "A"))

    def test_sanitizes_inline_choices_and_duplicate_labels(self) -> None:
        raw = self._question()
        raw["prompt"] = (
            "Choose the correct sentence:\n"
            "A) I go. B) I went. C) I gone. D) I going."
        )
        raw["options"] = ["A) I go.", "B) I went.", "C) I gone.", "D) I going."]
        raw["correct_answer"] = "B) I went."
        raw["accepted_answers"] = ["B"]
        payload = {"questions": [raw, raw, raw]}
        llm = OllamaLLM(client=StructuredClient(payload))  # type: ignore[arg-type]

        question = exercises.generate_questions(
            llm, "Past Simple", "Easy", 3
        )[0]

        self.assertEqual(question["prompt"], "Choose the correct sentence")
        self.assertEqual(question["options"][0], "I go.")
        self.assertEqual(question["correct_answer"], "I went.")


class AppHandlerTests(unittest.TestCase):
    def test_attachment_menu_stages_unique_files(self) -> None:
        import app

        with tempfile.TemporaryDirectory() as directory:
            lesson = Path(directory) / "lesson.pdf"
            photo = Path(directory) / "photo.png"
            lesson.write_bytes(b"%PDF-test")
            # Minimal valid PNG used only for safe image header validation.
            from PIL import Image

            Image.new("RGB", (2, 2)).save(photo)
            staged, preview = app.stage_attachments(
                [str(lesson)], [str(lesson), str(photo)]
            )
        self.assertEqual(staged, [str(lesson), str(photo)])
        self.assertIn("lesson.pdf", preview)
        self.assertIn("photo.png", preview)

    def test_attachment_menu_rejects_oversized_document(self) -> None:
        import app

        with tempfile.TemporaryDirectory() as directory:
            oversized = Path(directory) / "oversized.pdf"
            with oversized.open("wb") as stream:
                stream.seek(20 * 1024 * 1024)
                stream.write(b"x")
            staged, preview = app.stage_attachments([], [str(oversized)])
        self.assertEqual(staged, [])
        self.assertIn("vượt giới hạn 20 MB", preview)

    @staticmethod
    def _exercise_state() -> dict:
        questions = []
        for position in (1, 2):
            questions.append(
                {
                    "question_id": position,
                    "position": position,
                    "skill": "Past Simple",
                    "difficulty": "Easy",
                    "question_type": "multiple_choice",
                    "prompt": "Yesterday, I ___ home.",
                    "options": ["go", "went", "gone", "going"],
                    "correct_answer": "went",
                    "accepted_answers": ["went"],
                    "explanation_vi": "Yesterday yêu cầu quá khứ đơn.",
                }
            )
        return {
            "session_id": 1,
            "questions": questions,
            "current_index": 0,
            "draft_answers": {},
            "graded": {},
            "results": {},
            "feedbacks": {},
            "flags": [],
            "completed": False,
        }

    def test_exercise_view_exposes_clickable_abcd_choices(self) -> None:
        import app

        view = app.exercise_view(self._exercise_state())
        options_update = view[1]

        self.assertTrue(options_update["visible"])
        self.assertTrue(options_update["interactive"])
        self.assertEqual(options_update["choices"][0], ("A. go", "A"))
        self.assertEqual(options_update["choices"][1], ("B. went", "B"))

    def test_navigation_preserves_unsubmitted_selection(self) -> None:
        import app

        result = app.next_exercise_question(
            self._exercise_state(), "B", ""
        )
        state = result[0]

        self.assertEqual(state["current_index"], 1)
        self.assertEqual(state["draft_answers"]["0"], "B")

    def test_numbered_button_jumps_directly_and_marks_answered(self) -> None:
        import app

        result = app.jump_to_exercise_question(
            self._exercise_state(), "B", "", 1
        )

        self.assertEqual(result[0]["current_index"], 1)
        self.assertEqual(result[0]["draft_answers"]["0"], "B")
        self.assertEqual(result[11]["value"], "1")
        self.assertEqual(result[11]["variant"], "primary")
        self.assertEqual(result[12]["value"], "▶ 2")
        self.assertEqual(result[12]["variant"], "secondary")

    def test_question_grid_never_reveals_correct_or_wrong(self) -> None:
        import app

        state = self._exercise_state()
        state["completed"] = True
        state["draft_answers"] = {"0": "A", "1": "B"}
        state["results"] = {"0": False, "1": True}

        view = app.exercise_view(state)

        self.assertEqual(view[10]["variant"], "primary")
        self.assertEqual(view[11]["variant"], "primary")
        self.assertNotIn("✅", view[10]["value"])
        self.assertNotIn("❌", view[10]["value"])
        self.assertNotIn("✅", view[11]["value"])
        self.assertNotIn("❌", view[11]["value"])

    def test_post_submission_report_lists_wrong_answers(self) -> None:
        import app

        state = self._exercise_state()
        state["completed"] = True
        state["draft_answers"] = {"0": "A", "1": "B"}
        state["results"] = {"0": False, "1": True}

        report = app._exercise_report(state, state["questions"])

        self.assertIn("Báo cáo kết quả", report)
        self.assertIn("❌ Câu 1", report)
        self.assertIn("A. go", report)
        self.assertNotIn("❌ Câu 2", report)

    def test_written_answer_is_never_sent_to_next_radio(self) -> None:
        import app

        state = self._exercise_state()
        state["questions"][0]["question_type"] = "guided_sentence"
        state["questions"][0]["options"] = []

        result = app.next_exercise_question(
            state, None, "She goes to school. Make a sentence."
        )

        self.assertEqual(result[0]["draft_answers"]["0"], "She goes to school. Make a sentence.")
        self.assertIsNone(result[2]["value"])

    def test_submit_all_stops_at_first_unanswered_question(self) -> None:
        import app
        from database import LearningStats

        state = self._exercise_state()
        with patch.object(app, "database") as fake_database:
            fake_database.get_or_create_user.return_value = 1
            fake_database.get_stats.return_value = LearningStats("Nam", 0, 0, 0)
            fake_database.get_exercise_stats.return_value = ExerciseStats(0, 0, 0)
            fake_database.get_recent_vocabulary.return_value = []
            fake_database.get_skill_insights.return_value = []

            result = app.submit_exercise_answer(state, "B", "", "Nam")

        self.assertFalse(result[0]["completed"])
        self.assertEqual(result[0]["current_index"], 1)
        self.assertIn("chưa trả lời câu", result[0]["notice"])
        fake_database.submit_exercise_session.assert_not_called()

    def test_submit_reveals_explanation_and_completes_all_answered(self) -> None:
        import app
        from database import LearningStats

        state = self._exercise_state()
        state["draft_answers"] = {"1": "B"}
        with patch.object(app, "database") as fake_database:
            fake_database.get_or_create_user.return_value = 1
            fake_database.get_stats.return_value = LearningStats("Nam", 0, 0, 0)
            fake_database.get_exercise_stats.return_value = ExerciseStats(1, 1, 1)
            fake_database.get_recent_vocabulary.return_value = []
            fake_database.get_skill_insights.return_value = []

            result = app.submit_exercise_answer(state, "B", "", "Nam")

        updated_state = result[0]
        self.assertTrue(updated_state["graded"]["0"])
        self.assertTrue(updated_state["graded"]["1"])
        self.assertTrue(updated_state["completed"])
        self.assertIn("Giải thích", result[4])
        fake_database.submit_exercise_session.assert_called_once()

    def test_clear_roleplay_restarts_scene(self) -> None:
        import app
        from database import LearningStats

        with patch.object(app, "database") as fake_database:
            fake_database.get_or_create_user.return_value = 1
            fake_database.get_stats.return_value = LearningStats("Nam", 0, 0, 0)
            fake_database.get_exercise_stats.return_value = ExerciseStats(0, 0, 0)
            fake_database.get_recent_vocabulary.return_value = []
            fake_database.get_skill_insights.return_value = []
            history, message, progress, exercise_state, audio = app.clear_conversation(
                "Nam", app.MODE_ROLEPLAY, "Airport"
            )
        self.assertEqual(message, "")
        self.assertEqual(history[0]["role"], "assistant")
        self.assertIn("passport", history[0]["content"].lower())
        self.assertIn("Nam", progress)
        self.assertEqual(exercise_state, {})
        self.assertIsNone(audio["value"])
        self.assertNotIn("visible", audio)

    def test_processing_time_is_formatted_for_the_chat(self) -> None:
        import app

        self.assertEqual(app.format_processing_time(0.2), "Đã xử lý trong 0 phút 0 giây")
        self.assertEqual(app.format_processing_time(65.4), "Đã xử lý trong 1 phút 5 giây")

    def test_generate_reply_appends_both_turns(self) -> None:
        import app
        from database import LearningStats

        with (
            patch.object(app.conversation, "respond", return_value="Hello there!"),
            patch.object(app, "database") as fake_database,
        ):
            fake_database.get_or_create_user.return_value = 1
            fake_database.get_stats.return_value = LearningStats("Nam", 1, 0, 0)
            fake_database.get_exercise_stats.return_value = ExerciseStats(0, 0, 0)
            fake_database.get_recent_vocabulary.return_value = []
            fake_database.get_skill_insights.return_value = []
            textbox, history, progress = app.generate_reply(
                "Hello", [], app.MODE_CONVERSATION, "Coffee Shop", "Nam"
            )

        self.assertEqual(textbox, "")
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertIn("Lượt luyện tập", progress)
        fake_database.save_exchange.assert_called_once()

    def test_vocabulary_lookup_detection(self) -> None:
        from app import is_vocabulary_lookup

        self.assertTrue(is_vocabulary_lookup("accomplish"))
        self.assertTrue(is_vocabulary_lookup("look forward"))
        self.assertFalse(is_vocabulary_lookup("I accomplished my goal."))


if __name__ == "__main__":
    unittest.main()
