"""SQLite tests use a temporary file and never touch real learner data."""

import tempfile
import unittest
from pathlib import Path

from database import TutorDatabase


class TutorDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "test_tutor.db"
        self.database = TutorDatabase(database_path)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_workspace_history_is_scoped_ordered_and_limited(self) -> None:
        user_id = self.database.get_or_create_user("Workspace learner")
        other_id = self.database.get_or_create_user("Other learner")
        self.database.save_exchange(user_id, "Grammar", "", "first", "first reply")
        self.database.save_exchange(other_id, "Grammar", "", "private", "private reply")
        self.database.save_exchange(user_id, "Role Play", "Coffee Shop", "second", "second reply")
        rows = self.database.workspace_history(user_id, 3)
        self.assertEqual([row["content"] for row in rows], ["first reply", "second", "second reply"])
        self.assertEqual(rows[-1]["scenario"], "Coffee Shop")
        self.assertEqual(len(self.database.workspace_history(user_id)), 4)

    def test_history_survives_a_new_database_instance(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        self.database.save_exchange(
            user_id,
            "Conversation",
            "",
            "My name is Nam.",
            "Nice to meet you, Nam.",
        )

        reopened = TutorDatabase(self.database.database_path)
        reopened.initialize()
        history = reopened.load_history(user_id, "Conversation", "", 20)

        self.assertEqual(
            history,
            [
                {"role": "user", "content": "My name is Nam."},
                {"role": "assistant", "content": "Nice to meet you, Nam."},
            ],
        )

    def test_profiles_and_modes_are_separated(self) -> None:
        nam_id = self.database.get_or_create_user("Nam")
        lan_id = self.database.get_or_create_user("Lan")
        self.database.save_exchange(
            nam_id, "Grammar", "", "I go yesterday.", "Correction: I went yesterday."
        )

        self.assertEqual(
            self.database.load_history(lan_id, "Grammar", "", 20), []
        )
        self.assertEqual(
            self.database.load_history(nam_id, "Vocabulary", "", 20), []
        )

    def test_vocabulary_and_grammar_stats_are_persistent(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        self.database.save_vocabulary(user_id, "accomplish", "To finish successfully.")
        self.database.save_vocabulary(user_id, "accomplish", "To achieve a goal.")
        self.database.save_grammar_mistake(
            user_id,
            "Grammar",
            "Yesterday I go.",
            "Correction: Yesterday I went.",
        )

        stats = self.database.get_stats(user_id)
        self.assertEqual(stats.vocabulary_count, 1)
        self.assertEqual(stats.grammar_mistake_count, 1)
        self.assertEqual(
            self.database.get_recent_vocabulary(user_id), ["accomplish"]
        )

    def test_clear_only_removes_selected_conversation(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        self.database.save_exchange(
            user_id, "Conversation", "", "Hello", "Hi there!"
        )
        self.database.save_exchange(
            user_id, "Grammar", "", "I go", "Correction: I went"
        )

        self.database.clear_history(user_id, "Conversation", "")

        self.assertEqual(
            self.database.load_history(user_id, "Conversation", "", 20), []
        )
        self.assertEqual(
            len(self.database.load_history(user_id, "Grammar", "", 20)), 2
        )

    def test_skill_profile_aggregates_attempts(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        self.database.record_skill_attempt(user_id, "Past Simple", is_error=True)
        self.database.record_skill_attempt(user_id, "Past Simple", is_error=True)
        self.database.record_skill_attempt(user_id, "Past Simple", is_error=True)
        self.database.record_skill_attempt(user_id, "Articles", is_error=False)

        insights = self.database.get_skill_insights(user_id)

        self.assertEqual(insights[0].skill_name, "Past Simple")
        self.assertEqual(insights[0].level, "Yếu")
        self.assertEqual(insights[0].error_count, 3)

    def test_initialize_upgrades_schema_idempotently(self) -> None:
        self.database.initialize()
        self.database.initialize()

        import sqlite3

        connection = sqlite3.connect(self.database.database_path)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        connection.close()

        self.assertEqual(version, 12)
        self.assertIn("learning_skills", tables)
        self.assertIn("exercise_sessions", tables)
        self.assertIn("exercise_questions", tables)
        self.assertIn("exercise_attempts", tables)
        self.assertIn("learning_goals", tables)
        self.assertIn("documents", tables)
        self.assertIn("document_chunks", tables)
        self.assertIn("user_preferences", tables)

    def test_user_preferences_are_persistent_and_exported(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        defaults = self.database.get_user_preferences(user_id)
        self.assertEqual(defaults.theme, "system")
        self.assertEqual(defaults.interface_language, "vi")
        self.assertEqual(defaults.language, "vi")
        self.assertTrue(defaults.adaptive_intelligence)
        self.assertFalse(defaults.voice_input)
        self.assertFalse(defaults.voice_output)

        saved = self.database.save_user_preferences(
            user_id, "dark", "en", "en", False, True, True
        )
        reopened = TutorDatabase(self.database.database_path)
        loaded = reopened.get_user_preferences(user_id)
        exported = reopened.export_learner_data(user_id)

        self.assertEqual(loaded, saved)
        self.assertEqual(loaded.theme, "dark")
        self.assertEqual(loaded.interface_language, "en")
        self.assertEqual(loaded.language, "en")
        self.assertFalse(loaded.adaptive_intelligence)
        self.assertTrue(loaded.voice_input)
        self.assertTrue(loaded.voice_output)
        self.assertEqual(exported["schema_version"], 12)
        self.assertEqual(exported["preferences"][0]["theme"], "dark")
        self.assertEqual(exported["preferences"][0]["interface_language"], "en")

    def test_daily_goal_history_and_review_queue(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        self.assertEqual(self.database.get_daily_goal(user_id), 10)
        self.assertEqual(self.database.set_daily_goal(user_id, 25), 25)
        question = {
            "position": 1,
            "skill": "Articles",
            "difficulty": "Easy",
            "question_type": "multiple_choice",
            "prompt": "Choose an article: ___ apple",
            "options": ["a", "an", "the", "none"],
            "correct_answer": "an",
            "accepted_answers": ["an"],
            "explanation_vi": "Dùng an trước nguyên âm.",
        }
        session_id, stored = self.database.create_exercise_session(
            user_id, "Articles", "Easy", [question]
        )
        self.database.set_exercise_question_flag(
            user_id, session_id, stored[0]["question_id"], True
        )
        self.database.submit_exercise_session(
            user_id,
            session_id,
            [{
                "question_id": stored[0]["question_id"],
                "user_answer": "a",
                "is_correct": False,
                "skill": "Articles",
            }],
        )

        self.assertEqual(self.database.get_daily_goal(user_id), 25)
        self.assertEqual(len(self.database.get_daily_progress(user_id)), 1)
        self.assertEqual(len(self.database.list_exercise_history(user_id)), 1)
        self.assertEqual(len(self.database.get_review_questions(user_id, "wrong")), 1)
        self.assertEqual(len(self.database.get_review_questions(user_id, "flagged")), 1)

    def test_document_chunks_and_profile_export_are_scoped(self) -> None:
        nam_id = self.database.get_or_create_user("Nam")
        lan_id = self.database.get_or_create_user("Lan")
        document_id = self.database.save_document(
            nam_id,
            "Grammar notes",
            "notes.txt",
            "stored.txt",
            "txt",
            "native-text",
            "Present simple is used for routines.",
            [{"heading": "Present Simple", "content": "Use it for routines."}],
        )

        self.assertEqual(self.database.list_documents(lan_id), [])
        self.assertEqual(self.database.list_documents(nam_id)[0]["id"], document_id)
        chunks = self.database.get_document_chunks(nam_id, [document_id])
        self.assertEqual(chunks[0]["user_id"], nam_id)
        self.assertEqual(chunks[0]["title"], "Grammar notes")
        self.assertIn("skills", self.database.export_learner_data(nam_id))

    def test_exercise_review_flag_is_persistent(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        question = {
            "position": 1,
            "skill": "Past Simple",
            "difficulty": "Easy",
            "question_type": "multiple_choice",
            "prompt": "I ___ yesterday.",
            "options": ["go", "went", "gone", "going"],
            "correct_answer": "went",
            "accepted_answers": ["went"],
            "explanation_vi": "Dùng quá khứ đơn.",
        }
        session_id, stored = self.database.create_exercise_session(
            user_id, "Past Simple", "Easy", [question]
        )

        self.database.set_exercise_question_flag(
            user_id, session_id, stored[0]["question_id"], True
        )

        import sqlite3

        connection = sqlite3.connect(self.database.database_path)
        is_flagged = connection.execute(
            "SELECT is_flagged FROM exercise_questions WHERE id = ?",
            (stored[0]["question_id"],),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(is_flagged, 1)

    def test_exercise_session_attempts_and_score_are_persistent(self) -> None:
        user_id = self.database.get_or_create_user("Nam")
        questions = [
            {
                "position": 1,
                "skill": "Past Simple",
                "difficulty": "Easy",
                "question_type": "multiple_choice",
                "prompt": "Yesterday, I ___ home.",
                "options": ["go", "went", "gone", "going"],
                "correct_answer": "went",
                "accepted_answers": ["went"],
                "explanation_vi": "Dùng quá khứ đơn.",
            },
            {
                "position": 2,
                "skill": "Past Simple",
                "difficulty": "Easy",
                "question_type": "fill_blank",
                "prompt": "She ___ dinner last night. (cook)",
                "options": [],
                "correct_answer": "cooked",
                "accepted_answers": ["cooked"],
                "explanation_vi": "Động từ có quy tắc thêm -ed.",
            },
        ]
        session_id, stored = self.database.create_exercise_session(
            user_id, "Past Simple", "Easy", questions
        )
        self.database.record_exercise_attempt(
            user_id, session_id, stored[0]["question_id"], "B", True
        )
        self.database.record_exercise_attempt(
            user_id, session_id, stored[1]["question_id"], "cook", False
        )
        self.database.complete_exercise_session(user_id, session_id)

        reopened = TutorDatabase(self.database.database_path)
        reopened.initialize()
        stats = reopened.get_exercise_stats(user_id)

        self.assertEqual(stats.completed_sessions, 1)
        self.assertEqual(stats.total_attempts, 2)
        self.assertEqual(stats.correct_attempts, 1)
        self.assertEqual(stats.accuracy_percent, 50)

    def test_full_exercise_submission_is_atomic_and_updates_skills(self) -> None:
        user_id = self.database.get_or_create_user("Lan")
        questions = [
            {
                "position": position,
                "skill": "Past Simple",
                "difficulty": "Easy",
                "question_type": "multiple_choice",
                "prompt": f"Question {position}",
                "options": ["go", "went", "gone", "going"],
                "correct_answer": "went",
                "accepted_answers": ["went"],
                "explanation_vi": "Dùng quá khứ đơn.",
            }
            for position in (1, 2)
        ]
        session_id, stored = self.database.create_exercise_session(
            user_id, "Past Simple", "Easy", questions
        )

        self.database.submit_exercise_session(
            user_id,
            session_id,
            [
                {
                    "question_id": stored[0]["question_id"],
                    "user_answer": "B",
                    "is_correct": True,
                    "skill": "Past Simple",
                },
                {
                    "question_id": stored[1]["question_id"],
                    "user_answer": "A",
                    "is_correct": False,
                    "skill": "Past Simple",
                },
            ],
        )

        stats = self.database.get_exercise_stats(user_id)
        insight = self.database.get_skill_insights(user_id)[0]
        self.assertEqual(stats.completed_sessions, 1)
        self.assertEqual(stats.total_attempts, 2)
        self.assertEqual(insight.correct_count, 1)
        self.assertEqual(insight.error_count, 1)


if __name__ == "__main__":
    unittest.main()
