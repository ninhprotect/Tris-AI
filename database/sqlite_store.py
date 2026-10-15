"""SQLite storage for learner memory, skills, and personalized exercises."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ai.llm import ChatMessage


class DatabaseError(RuntimeError):
    """A storage error with a safe message for the local UI."""


@dataclass(frozen=True)
class LearningStats:
    """Small progress summary shown in the Gradio interface."""

    learner_name: str
    message_count: int
    vocabulary_count: int
    grammar_mistake_count: int


@dataclass(frozen=True)
class SkillInsight:
    """Aggregated evidence for one learner skill."""

    skill_name: str
    correct_count: int
    error_count: int

    @property
    def attempt_count(self) -> int:
        return self.correct_count + self.error_count

    @property
    def accuracy_percent(self) -> int:
        if self.attempt_count == 0:
            return 0
        return round(self.correct_count / self.attempt_count * 100)

    @property
    def level(self) -> str:
        """Use cautious labels so one event does not over-diagnose a learner."""
        if self.attempt_count < 3:
            return "Chưa đủ dữ liệu"
        if self.accuracy_percent < 50:
            return "Yếu"
        if self.accuracy_percent < 80:
            return "Đang cải thiện"
        return "Tốt"


@dataclass(frozen=True)
class ExerciseStats:
    """Persistent exercise totals for one learner."""

    completed_sessions: int
    total_attempts: int
    correct_attempts: int

    @property
    def accuracy_percent(self) -> int:
        if self.total_attempts == 0:
            return 0
        return round(self.correct_attempts / self.total_attempts * 100)


@dataclass(frozen=True)
class DailyProgress:
    """Exercise activity for one calendar day."""

    day: str
    completed_sessions: int
    answered_questions: int
    correct_answers: int

    @property
    def accuracy_percent(self) -> int:
        if self.answered_questions == 0:
            return 0
        return round(self.correct_answers / self.answered_questions * 100)


@dataclass(frozen=True)
class UserPreferences:
    """Persistent per-learner behavior and interface preferences."""

    theme: str = "system"
    interface_language: str = "vi"
    language: str = "vi"
    adaptive_intelligence: bool = True
    voice_input: bool = False
    voice_output: bool = False


class TutorDatabase:
    """Store all tutor data in one local SQLite file."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Create the database directory, tables and indexes when missing."""
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        mode TEXT NOT NULL,
                        scenario TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS vocabulary_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        word TEXT NOT NULL COLLATE NOCASE,
                        tutor_response TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'learning',
                        review_count INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        UNIQUE (user_id, word)
                    );

                    CREATE TABLE IF NOT EXISTS grammar_mistakes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        mode TEXT NOT NULL,
                        original_sentence TEXT NOT NULL,
                        tutor_feedback TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS learning_skills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        skill_name TEXT NOT NULL COLLATE NOCASE,
                        correct_count INTEGER NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        UNIQUE (user_id, skill_name)
                    );

                    CREATE TABLE IF NOT EXISTS exercise_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        skill TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        total_questions INTEGER NOT NULL CHECK (total_questions > 0),
                        correct_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'completed', 'abandoned')),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at TEXT,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS exercise_questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        position INTEGER NOT NULL,
                        question_type TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        options_json TEXT NOT NULL DEFAULT '[]',
                        correct_answer TEXT NOT NULL,
                        accepted_answers_json TEXT NOT NULL DEFAULT '[]',
                        explanation_vi TEXT NOT NULL,
                        is_flagged INTEGER NOT NULL DEFAULT 0
                            CHECK (is_flagged IN (0, 1)),
                        FOREIGN KEY (session_id) REFERENCES exercise_sessions(id)
                            ON DELETE CASCADE,
                        UNIQUE (session_id, position)
                    );

                    CREATE TABLE IF NOT EXISTS exercise_attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        question_id INTEGER NOT NULL UNIQUE,
                        user_id INTEGER NOT NULL,
                        user_answer TEXT NOT NULL,
                        is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (session_id) REFERENCES exercise_sessions(id)
                            ON DELETE CASCADE,
                        FOREIGN KEY (question_id) REFERENCES exercise_questions(id)
                            ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS learning_goals (
                        user_id INTEGER PRIMARY KEY,
                        daily_question_goal INTEGER NOT NULL DEFAULT 10
                            CHECK (daily_question_goal BETWEEN 1 AND 200),
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        stored_path TEXT NOT NULL,
                        file_type TEXT NOT NULL,
                        extraction_engine TEXT NOT NULL,
                        character_count INTEGER NOT NULL DEFAULT 0,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'ready',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        heading TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL,
                        vector_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (document_id) REFERENCES documents(id)
                            ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        UNIQUE (document_id, chunk_index)
                    );

                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id INTEGER PRIMARY KEY,
                        theme TEXT NOT NULL DEFAULT 'system'
                            CHECK (theme IN ('system', 'light', 'dark')),
                        interface_language TEXT NOT NULL DEFAULT 'vi'
                            CHECK (interface_language IN ('vi', 'en')),
                        language TEXT NOT NULL DEFAULT 'vi'
                            CHECK (language IN ('vi', 'en')),
                        adaptive_intelligence INTEGER NOT NULL DEFAULT 1
                            CHECK (adaptive_intelligence IN (0, 1)),
                        voice_input INTEGER NOT NULL DEFAULT 0
                            CHECK (voice_input IN (0, 1)),
                        voice_output INTEGER NOT NULL DEFAULT 0
                            CHECK (voice_output IN (0, 1)),
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_conversation_context
                        ON conversation_messages(user_id, mode, scenario, id);
                    CREATE INDEX IF NOT EXISTS idx_vocabulary_user
                        ON vocabulary_items(user_id, updated_at);
                    CREATE INDEX IF NOT EXISTS idx_grammar_user
                        ON grammar_mistakes(user_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_skills_user
                        ON learning_skills(user_id, error_count, updated_at);
                    CREATE INDEX IF NOT EXISTS idx_exercise_sessions_user
                        ON exercise_sessions(user_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_exercise_questions_session
                        ON exercise_questions(session_id, position);
                    CREATE INDEX IF NOT EXISTS idx_exercise_attempts_user
                        ON exercise_attempts(user_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_documents_user
                        ON documents(user_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_document_chunks_document
                        ON document_chunks(document_id, chunk_index);

                    """
                )
                exercise_columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(exercise_questions)"
                    ).fetchall()
                }
                if "is_flagged" not in exercise_columns:
                    connection.execute(
                        """
                        ALTER TABLE exercise_questions
                        ADD COLUMN is_flagged INTEGER NOT NULL DEFAULT 0
                            CHECK (is_flagged IN (0, 1))
                        """
                    )
                preference_columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(user_preferences)"
                    ).fetchall()
                }
                if "interface_language" not in preference_columns:
                    connection.execute(
                        """
                        ALTER TABLE user_preferences
                        ADD COLUMN interface_language TEXT NOT NULL DEFAULT 'vi'
                            CHECK (interface_language IN ('vi', 'en'))
                        """
                    )
                if "voice_output" not in preference_columns:
                    connection.execute(
                        """
                        ALTER TABLE user_preferences
                        ADD COLUMN voice_output INTEGER NOT NULL DEFAULT 0
                            CHECK (voice_output IN (0, 1))
                        """
                    )
                connection.execute("PRAGMA user_version = 12")
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError(
                "Không thể khởi tạo bộ nhớ SQLite local. Hãy kiểm tra quyền ghi thư mục data."
            ) from exc

    def get_or_create_user(self, learner_name: str) -> int:
        """Return one stable local user id for a display name."""
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO users(name)
                    VALUES (?)
                    ON CONFLICT(name) DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP
                    """,
                    (learner_name,),
                )
                row = connection.execute(
                    "SELECT id FROM users WHERE name = ? COLLATE NOCASE",
                    (learner_name,),
                ).fetchone()
                if row is None:
                    raise DatabaseError("Không thể tạo hồ sơ người học local.")
                return int(row["id"])
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể mở hồ sơ người học local.") from exc

    def get_user_preferences(self, user_id: int) -> UserPreferences:
        """Return saved settings or safe local defaults."""
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT theme, interface_language, language,
                           adaptive_intelligence, voice_input, voice_output
                    FROM user_preferences WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
            if row is None:
                return UserPreferences()
            return UserPreferences(
                theme=str(row["theme"]),
                interface_language=str(row["interface_language"]),
                language=str(row["language"]),
                adaptive_intelligence=bool(row["adaptive_intelligence"]),
                voice_input=bool(row["voice_input"]),
                voice_output=bool(row["voice_output"]),
            )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc cài đặt người học.") from exc

    def save_user_preferences(
        self,
        user_id: int,
        theme: str,
        interface_language: str,
        language: str,
        adaptive_intelligence: bool,
        voice_input: bool,
        voice_output: bool = False,
    ) -> UserPreferences:
        """Validate and persist settings in one upsert."""
        clean_theme = (theme or "system").casefold()
        clean_interface_language = (interface_language or "vi").casefold()
        clean_language = (language or "vi").casefold()
        if clean_theme not in {"system", "light", "dark"}:
            raise DatabaseError("Chủ đề không hợp lệ.")
        if clean_language not in {"vi", "en"}:
            raise DatabaseError("Ngôn ngữ không hợp lệ.")
        if clean_interface_language not in {"vi", "en"}:
            raise DatabaseError("Ngôn ngữ hệ thống không hợp lệ.")
        preferences = UserPreferences(
            clean_theme,
            clean_interface_language,
            clean_language,
            bool(adaptive_intelligence),
            bool(voice_input),
            bool(voice_output),
        )
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO user_preferences(
                        user_id, theme, interface_language, language,
                        adaptive_intelligence, voice_input, voice_output
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        theme = excluded.theme,
                        interface_language = excluded.interface_language,
                        language = excluded.language,
                        adaptive_intelligence = excluded.adaptive_intelligence,
                        voice_input = excluded.voice_input,
                        voice_output = excluded.voice_output,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        user_id,
                        preferences.theme,
                        preferences.interface_language,
                        preferences.language,
                        int(preferences.adaptive_intelligence),
                        int(preferences.voice_input),
                        int(preferences.voice_output),
                    ),
                )
            return preferences
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu cài đặt người học.") from exc

    def save_exchange(
        self,
        user_id: int,
        mode: str,
        scenario: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Save one user/assistant pair in a single transaction."""
        try:
            with self._connection() as connection:
                connection.executemany(
                    """
                    INSERT INTO conversation_messages(
                        user_id, mode, scenario, role, content
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (user_id, mode, scenario, "user", user_message),
                        (user_id, mode, scenario, "assistant", assistant_message),
                    ],
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu lịch sử hội thoại local.") from exc

    def load_history(
        self,
        user_id: int,
        mode: str,
        scenario: str,
        limit: int,
    ) -> list[ChatMessage]:
        """Load the newest messages, returned in chronological order."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT role, content
                    FROM (
                        SELECT id, role, content
                        FROM conversation_messages
                        WHERE user_id = ? AND mode = ? AND scenario = ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    ORDER BY id ASC
                    """,
                    (user_id, mode, scenario, limit),
                ).fetchall()
                return [
                    {"role": str(row["role"]), "content": str(row["content"])}
                    for row in rows
                ]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể tải lịch sử hội thoại local.") from exc

    def workspace_history(self, user_id: int, limit: int = 500) -> list[dict]:
        """Read existing conversations for the replacement UI without changing rows."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM (SELECT id, mode, scenario, role, content, created_at "
                    "FROM conversation_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
                    (int(user_id), max(1, min(int(limit), 1000))),
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc lịch sử học hiện tại.") from exc

    def clear_history(self, user_id: int, mode: str, scenario: str) -> None:
        """Delete only the selected conversation context."""
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    DELETE FROM conversation_messages
                    WHERE user_id = ? AND mode = ? AND scenario = ?
                    """,
                    (user_id, mode, scenario),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể xóa lịch sử hội thoại local.") from exc

    def save_vocabulary(self, user_id: int, word: str, tutor_response: str) -> None:
        """Insert a new word or count another review of an existing word."""
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO vocabulary_items(user_id, word, tutor_response)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, word) DO UPDATE SET
                        tutor_response = excluded.tutor_response,
                        review_count = vocabulary_items.review_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, word, tutor_response),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu từ vựng local.") from exc

    def save_grammar_mistake(
        self,
        user_id: int,
        mode: str,
        original_sentence: str,
        tutor_feedback: str,
    ) -> None:
        """Store a learner sentence when the tutor returned a correction."""
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO grammar_mistakes(
                        user_id, mode, original_sentence, tutor_feedback
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (user_id, mode, original_sentence, tutor_feedback),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu lỗi ngữ pháp local.") from exc

    def get_stats(self, user_id: int) -> LearningStats:
        """Count saved learning activity for one learner."""
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                        users.name AS learner_name,
                        (
                            SELECT COUNT(*) FROM conversation_messages
                            WHERE conversation_messages.user_id = users.id
                              AND role = 'user'
                        ) AS message_count,
                        (
                            SELECT COUNT(*) FROM vocabulary_items
                            WHERE vocabulary_items.user_id = users.id
                        ) AS vocabulary_count,
                        (
                            SELECT COUNT(*) FROM grammar_mistakes
                            WHERE grammar_mistakes.user_id = users.id
                        ) AS grammar_mistake_count
                    FROM users
                    WHERE users.id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if row is None:
                    raise DatabaseError("Không tìm thấy hồ sơ người học local.")
                return LearningStats(
                    learner_name=str(row["learner_name"]),
                    message_count=int(row["message_count"]),
                    vocabulary_count=int(row["vocabulary_count"]),
                    grammar_mistake_count=int(row["grammar_mistake_count"]),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc thống kê học tập local.") from exc

    def get_recent_vocabulary(self, user_id: int, limit: int = 5) -> list[str]:
        """Return a few recently studied words for the dashboard."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT word FROM vocabulary_items
                    WHERE user_id = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [str(row["word"]) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc danh sách từ vựng local.") from exc

    def record_skill_attempt(
        self,
        user_id: int,
        skill_name: str,
        is_error: bool,
    ) -> None:
        """Update one transparent correct/error counter for a learner skill."""
        correct_increment = 0 if is_error else 1
        error_increment = 1 if is_error else 0
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO learning_skills(
                        user_id, skill_name, correct_count, error_count
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, skill_name) DO UPDATE SET
                        correct_count = learning_skills.correct_count + excluded.correct_count,
                        error_count = learning_skills.error_count + excluded.error_count,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, skill_name, correct_increment, error_increment),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể cập nhật hồ sơ kỹ năng local.") from exc

    def get_skill_insights(self, user_id: int, limit: int = 8) -> list[SkillInsight]:
        """Return weak skills first, followed by the most practiced skills."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT skill_name, correct_count, error_count
                    FROM learning_skills
                    WHERE user_id = ?
                    ORDER BY
                        CASE
                            WHEN correct_count + error_count < 3 THEN 3
                            WHEN correct_count * 100 / (correct_count + error_count) < 50 THEN 0
                            WHEN correct_count * 100 / (correct_count + error_count) < 80 THEN 1
                            ELSE 2
                        END,
                        error_count DESC,
                        updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [
                    SkillInsight(
                        skill_name=str(row["skill_name"]),
                        correct_count=int(row["correct_count"]),
                        error_count=int(row["error_count"]),
                    )
                    for row in rows
                ]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc hồ sơ kỹ năng local.") from exc

    def create_exercise_session(
        self,
        user_id: int,
        skill: str,
        difficulty: str,
        questions: list[dict],
    ) -> tuple[int, list[dict]]:
        """Persist generated questions and return their stable database ids."""
        if not questions:
            raise DatabaseError("Không thể lưu một bài tập trống.")
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO exercise_sessions(
                        user_id, skill, difficulty, total_questions
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (user_id, skill, difficulty, len(questions)),
                )
                session_id = int(cursor.lastrowid)
                stored_questions: list[dict] = []
                for question in questions:
                    question_cursor = connection.execute(
                        """
                        INSERT INTO exercise_questions(
                            session_id, position, question_type, prompt,
                            options_json, correct_answer, accepted_answers_json,
                            explanation_vi
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            int(question["position"]),
                            str(question["question_type"]),
                            str(question["prompt"]),
                            json.dumps(question.get("options", []), ensure_ascii=False),
                            str(question["correct_answer"]),
                            json.dumps(
                                question.get("accepted_answers", []),
                                ensure_ascii=False,
                            ),
                            str(question["explanation_vi"]),
                        ),
                    )
                    stored_questions.append(
                        {**question, "question_id": int(question_cursor.lastrowid)}
                    )
                return session_id, stored_questions
        except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            raise DatabaseError("Không thể lưu phiên bài tập local.") from exc

    def record_exercise_attempt(
        self,
        user_id: int,
        session_id: int,
        question_id: int,
        user_answer: str,
        is_correct: bool,
    ) -> None:
        """Save one immutable answer and update the owning session score."""
        try:
            with self._connection() as connection:
                ownership = connection.execute(
                    """
                    SELECT 1
                    FROM exercise_questions AS question
                    JOIN exercise_sessions AS session
                      ON session.id = question.session_id
                    WHERE question.id = ? AND session.id = ? AND session.user_id = ?
                    """,
                    (question_id, session_id, user_id),
                ).fetchone()
                if ownership is None:
                    raise DatabaseError("Câu hỏi không thuộc phiên bài tập hiện tại.")
                connection.execute(
                    """
                    INSERT INTO exercise_attempts(
                        session_id, question_id, user_id, user_answer, is_correct
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, question_id, user_id, user_answer, int(is_correct)),
                )
                if is_correct:
                    connection.execute(
                        """
                        UPDATE exercise_sessions
                        SET correct_count = correct_count + 1
                        WHERE id = ? AND user_id = ?
                        """,
                        (session_id, user_id),
                    )
        except DatabaseError:
            raise
        except sqlite3.IntegrityError as exc:
            raise DatabaseError("Câu hỏi này đã được trả lời rồi.") from exc
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu đáp án bài tập local.") from exc

    def submit_exercise_session(
        self,
        user_id: int,
        session_id: int,
        attempts: list[dict],
    ) -> None:
        """Atomically submit every answer, update skills, and complete the set."""
        try:
            with self._connection() as connection:
                session = connection.execute(
                    """
                    SELECT total_questions, status
                    FROM exercise_sessions
                    WHERE id = ? AND user_id = ?
                    """,
                    (session_id, user_id),
                ).fetchone()
                if session is None or str(session["status"]) != "active":
                    raise DatabaseError("Phiên bài tập không còn hoạt động.")
                if len(attempts) != int(session["total_questions"]):
                    raise DatabaseError("Bạn cần trả lời đủ tất cả câu trước khi nộp.")

                expected_ids = {
                    int(row["id"])
                    for row in connection.execute(
                        "SELECT id FROM exercise_questions WHERE session_id = ?",
                        (session_id,),
                    ).fetchall()
                }
                submitted_ids = {int(item["question_id"]) for item in attempts}
                if submitted_ids != expected_ids or len(submitted_ids) != len(attempts):
                    raise DatabaseError("Danh sách câu trả lời không hợp lệ.")

                existing_attempts = connection.execute(
                    "SELECT COUNT(*) FROM exercise_attempts WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                if int(existing_attempts) != 0:
                    raise DatabaseError("Bài tập này đã có câu trả lời được lưu.")

                correct_count = 0
                skill_totals: dict[str, list[int]] = {}
                for item in attempts:
                    is_correct = bool(item["is_correct"])
                    correct_count += int(is_correct)
                    connection.execute(
                        """
                        INSERT INTO exercise_attempts(
                            session_id, question_id, user_id, user_answer, is_correct
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            int(item["question_id"]),
                            user_id,
                            str(item["user_answer"]),
                            int(is_correct),
                        ),
                    )
                    skill_name = str(item["skill"])
                    counters = skill_totals.setdefault(skill_name, [0, 0])
                    counters[0 if is_correct else 1] += 1

                for skill_name, (correct, errors) in skill_totals.items():
                    connection.execute(
                        """
                        INSERT INTO learning_skills(
                            user_id, skill_name, correct_count, error_count
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(user_id, skill_name) DO UPDATE SET
                            correct_count = learning_skills.correct_count
                                + excluded.correct_count,
                            error_count = learning_skills.error_count
                                + excluded.error_count,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (user_id, skill_name, correct, errors),
                    )

                connection.execute(
                    """
                    UPDATE exercise_sessions
                    SET correct_count = ?, status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ? AND status = 'active'
                    """,
                    (correct_count, session_id, user_id),
                )
        except DatabaseError:
            raise
        except (sqlite3.IntegrityError, KeyError, TypeError, ValueError) as exc:
            raise DatabaseError("Không thể nộp toàn bộ bài tập local.") from exc
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu toàn bộ bài tập local.") from exc

    def complete_exercise_session(self, user_id: int, session_id: int) -> None:
        """Mark an active exercise set complete for its owning learner."""
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE exercise_sessions
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ? AND status = 'active'
                    """,
                    (session_id, user_id),
                )
                if cursor.rowcount == 0:
                    raise DatabaseError("Không tìm thấy phiên bài tập đang hoạt động.")
        except DatabaseError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể hoàn tất phiên bài tập local.") from exc

    def set_exercise_question_flag(
        self,
        user_id: int,
        session_id: int,
        question_id: int,
        is_flagged: bool,
    ) -> None:
        """Persist a review flag only when the question belongs to the learner."""
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE exercise_questions
                    SET is_flagged = ?
                    WHERE id = ? AND session_id = ?
                      AND EXISTS (
                          SELECT 1 FROM exercise_sessions
                          WHERE exercise_sessions.id = exercise_questions.session_id
                            AND exercise_sessions.user_id = ?
                      )
                    """,
                    (int(is_flagged), question_id, session_id, user_id),
                )
                if cursor.rowcount == 0:
                    raise DatabaseError("Không thể cắm cờ câu hỏi này.")
        except DatabaseError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu trạng thái cắm cờ local.") from exc

    def get_exercise_stats(self, user_id: int) -> ExerciseStats:
        """Aggregate completed sets and submitted answers for a learner."""
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM exercise_sessions
                         WHERE user_id = ? AND status = 'completed') AS sessions,
                        (SELECT COUNT(*) FROM exercise_attempts
                         WHERE user_id = ?) AS attempts,
                        (SELECT COUNT(*) FROM exercise_attempts
                         WHERE user_id = ? AND is_correct = 1) AS correct
                    """,
                    (user_id, user_id, user_id),
                ).fetchone()
                return ExerciseStats(
                    completed_sessions=int(row["sessions"]),
                    total_attempts=int(row["attempts"]),
                    correct_attempts=int(row["correct"]),
                )
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc thống kê bài tập local.") from exc

    def set_daily_goal(self, user_id: int, question_goal: int) -> int:
        """Create or update the learner's daily answered-question target."""
        goal = max(1, min(int(question_goal), 200))
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO learning_goals(user_id, daily_question_goal)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        daily_question_goal = excluded.daily_question_goal,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, goal),
                )
            return goal
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể lưu mục tiêu học tập.") from exc

    def get_daily_goal(self, user_id: int) -> int:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT daily_question_goal FROM learning_goals WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                return int(row["daily_question_goal"]) if row else 10
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc mục tiêu học tập.") from exc

    def get_daily_progress(self, user_id: int, days: int = 7) -> list[DailyProgress]:
        """Return recent exercise activity grouped by local SQLite date."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT date(session.completed_at, 'localtime') AS day,
                           COUNT(DISTINCT session.id) AS sessions,
                           COUNT(attempt.id) AS answered,
                           COALESCE(SUM(attempt.is_correct), 0) AS correct
                    FROM exercise_sessions AS session
                    LEFT JOIN exercise_attempts AS attempt
                      ON attempt.session_id = session.id
                    WHERE session.user_id = ? AND session.status = 'completed'
                    GROUP BY date(session.completed_at, 'localtime')
                    ORDER BY day DESC
                    LIMIT ?
                    """,
                    (user_id, max(1, min(int(days), 90))),
                ).fetchall()
            return [
                DailyProgress(
                    day=str(row["day"]),
                    completed_sessions=int(row["sessions"]),
                    answered_questions=int(row["answered"]),
                    correct_answers=int(row["correct"]),
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc lịch sử học tập.") from exc

    def list_exercise_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """List completed quiz summaries newest first."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, skill, difficulty, total_questions, correct_count,
                           created_at, completed_at
                    FROM exercise_sessions
                    WHERE user_id = ? AND status = 'completed'
                    ORDER BY completed_at DESC, id DESC
                    LIMIT ?
                    """,
                    (user_id, max(1, min(int(limit), 100))),
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc lịch sử bài tập.") from exc

    def get_review_questions(
        self,
        user_id: int,
        review_kind: str = "wrong",
        limit: int = 10,
    ) -> list[dict]:
        """Load reusable wrong, flagged, or weak-skill questions."""
        where = "attempt.is_correct = 0"
        if review_kind == "flagged":
            where = "question.is_flagged = 1"
        elif review_kind == "weak":
            where = "attempt.is_correct = 0"
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT question.id AS source_question_id, session.skill,
                           session.difficulty, question.question_type,
                           question.prompt, question.options_json,
                           question.correct_answer, question.accepted_answers_json,
                           question.explanation_vi, question.is_flagged,
                           attempt.user_answer, attempt.is_correct
                    FROM exercise_questions AS question
                    JOIN exercise_sessions AS session ON session.id = question.session_id
                    LEFT JOIN exercise_attempts AS attempt ON attempt.question_id = question.id
                    WHERE session.user_id = ? AND session.status = 'completed' AND {where}
                    ORDER BY COALESCE(attempt.created_at, session.completed_at) DESC
                    LIMIT ?
                    """,
                    (user_id, max(1, min(int(limit), 50))),
                ).fetchall()
            questions: list[dict] = []
            for position, row in enumerate(rows, start=1):
                questions.append(
                    {
                        "position": position,
                        "source_question_id": int(row["source_question_id"]),
                        "skill": str(row["skill"]),
                        "difficulty": str(row["difficulty"]),
                        "question_type": str(row["question_type"]),
                        "prompt": str(row["prompt"]),
                        "options": json.loads(str(row["options_json"])),
                        "correct_answer": str(row["correct_answer"]),
                        "accepted_answers": json.loads(str(row["accepted_answers_json"])),
                        "explanation_vi": str(row["explanation_vi"]),
                        "is_flagged": bool(row["is_flagged"]),
                    }
                )
            return questions
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseError("Không thể tải câu hỏi ôn tập.") from exc

    def get_exercise_session(self, user_id: int, session_id: int) -> dict:
        """Load one owned exercise session with questions and saved attempts."""
        try:
            with self._connection() as connection:
                session = connection.execute(
                    "SELECT * FROM exercise_sessions WHERE id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
                if session is None:
                    raise DatabaseError("Không tìm thấy phiên bài tập.")
                rows = connection.execute(
                    """
                    SELECT question.*, attempt.user_answer, attempt.is_correct
                    FROM exercise_questions AS question
                    LEFT JOIN exercise_attempts AS attempt
                      ON attempt.question_id = question.id
                    WHERE question.session_id = ? ORDER BY question.position
                    """,
                    (session_id,),
                ).fetchall()
                questions = []
                for row in rows:
                    questions.append(
                        {
                            "question_id": int(row["id"]),
                            "position": int(row["position"]),
                            "skill": str(session["skill"]),
                            "difficulty": str(session["difficulty"]),
                            "question_type": str(row["question_type"]),
                            "prompt": str(row["prompt"]),
                            "options": json.loads(str(row["options_json"])),
                            "correct_answer": str(row["correct_answer"]),
                            "accepted_answers": json.loads(str(row["accepted_answers_json"])),
                            "explanation_vi": str(row["explanation_vi"]),
                            "is_flagged": bool(row["is_flagged"]),
                            "user_answer": row["user_answer"],
                            "is_correct": (
                                None if row["is_correct"] is None else bool(row["is_correct"])
                            ),
                        }
                    )
                return {**dict(session), "questions": questions}
        except DatabaseError:
            raise
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseError("Không thể tải phiên bài tập.") from exc

    def save_document(
        self,
        user_id: int,
        title: str,
        source_path: str,
        stored_path: str,
        file_type: str,
        extraction_engine: str,
        text: str,
        chunks: list[dict],
    ) -> int:
        """Atomically store a parsed document and its searchable chunks."""
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO documents(user_id, title, source_path, stored_path,
                                          file_type, extraction_engine,
                                          character_count, chunk_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, title, source_path, stored_path, file_type,
                        extraction_engine, len(text), len(chunks),
                    ),
                )
                document_id = int(cursor.lastrowid)
                for index, chunk in enumerate(chunks):
                    connection.execute(
                        """
                        INSERT INTO document_chunks(document_id, user_id, chunk_index,
                                                    heading, content, vector_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id, user_id, index,
                            str(chunk.get("heading", "")), str(chunk["content"]),
                            str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"english-tutor:{self.database_path}:{document_id}:{index}",
                                )
                            ),
                        ),
                    )
                return document_id
        except (sqlite3.Error, KeyError, TypeError) as exc:
            raise DatabaseError("Không thể lưu tài liệu local.") from exc

    def list_documents(self, user_id: int) -> list[dict]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, title, file_type, extraction_engine, character_count,
                           chunk_count, status, created_at
                    FROM documents WHERE user_id = ? ORDER BY created_at DESC, id DESC
                    """,
                    (user_id,),
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc thư viện tài liệu.") from exc

    def delete_document(self, user_id: int, document_id: int) -> bool:
        """Delete one learner-owned document and its cascaded chunk rows."""
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM documents WHERE id = ? AND user_id = ?",
                    (int(document_id), int(user_id)),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể dọn tài liệu lỗi.") from exc

    def get_document_chunks(
        self, user_id: int, document_ids: list[int] | None = None
    ) -> list[dict]:
        """Return chunks owned by a learner, optionally restricted to documents."""
        try:
            with self._connection() as connection:
                parameters: list[object] = [user_id]
                clause = ""
                if document_ids:
                    placeholders = ",".join("?" for _ in document_ids)
                    clause = f" AND chunk.document_id IN ({placeholders})"
                    parameters.extend(int(value) for value in document_ids)
                rows = connection.execute(
                    f"""
                    SELECT chunk.id, chunk.document_id, chunk.user_id,
                           chunk.chunk_index,
                           chunk.heading, chunk.content, chunk.vector_id,
                           document.title
                    FROM document_chunks AS chunk
                    JOIN documents AS document ON document.id = chunk.document_id
                    WHERE chunk.user_id = ?{clause}
                    ORDER BY chunk.document_id, chunk.chunk_index
                    """,
                    parameters,
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể đọc nội dung tài liệu.") from exc

    def export_learner_data(self, user_id: int) -> dict:
        """Return a JSON-serializable local profile export."""
        try:
            with self._connection() as connection:
                user = connection.execute(
                    "SELECT id, name, created_at, last_seen_at FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
                if user is None:
                    raise DatabaseError("Không tìm thấy hồ sơ người học.")
                table_queries = {
                    "skills": "SELECT skill_name, correct_count, error_count, updated_at FROM learning_skills WHERE user_id = ?",
                    "exercise_sessions": "SELECT id, skill, difficulty, total_questions, correct_count, status, created_at, completed_at FROM exercise_sessions WHERE user_id = ?",
                    "documents": "SELECT id, title, file_type, extraction_engine, character_count, chunk_count, created_at FROM documents WHERE user_id = ?",
                    "preferences": "SELECT theme, interface_language, language, adaptive_intelligence, voice_input, voice_output, updated_at FROM user_preferences WHERE user_id = ?",
                }
                payload = {"schema_version": 12, "learner": dict(user)}
                for key, query in table_queries.items():
                    payload[key] = [dict(row) for row in connection.execute(query, (user_id,))]
                return payload
        except DatabaseError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseError("Không thể xuất dữ liệu người học.") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open, commit or roll back, and always close one SQLite connection."""
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
