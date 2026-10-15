"""Tests for local document parsing and the v1.0 API shell."""

import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import app
from database import TutorDatabase
from services.study_hub import DocumentParser, StudyHub, StudyHubError, chunk_text


class StudyHubTests(unittest.TestCase):
    def test_image_ocr_fallback_returns_detected_lines(self) -> None:
        parser = DocumentParser()
        with patch.object(
            DocumentParser,
            "_rapidocr",
            return_value=SimpleNamespace(
                txts=("Dòng một", "Dòng hai")
            ),
        ):
            text = parser._extract_with_rapidocr(Path("sample.png"))
        self.assertEqual(text, "Dòng một\nDòng hai")
    def test_chunk_text_keeps_all_content_and_creates_multiple_chunks(self) -> None:
        text = "\n\n".join(f"Paragraph {index} " + ("word " * 80) for index in range(8))
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        self.assertGreater(len(chunks), 2)
        self.assertIn("Paragraph 0", chunks[0]["content"])
        self.assertIn("Paragraph 7", chunks[-1]["content"])

    def test_native_text_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lesson.txt"
            path.write_text("A useful English lesson.", encoding="utf-8")
            text, engine = DocumentParser().extract(path)
        self.assertEqual(engine, "native-text")
        self.assertIn("English lesson", text)

    def test_failed_index_is_safe_and_removes_partial_document(self) -> None:
        class FailingIndex:
            def index(self, chunks: list[dict]) -> int:
                raise KeyError("simulated index payload error")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = TutorDatabase(root / "test.db")
            database.initialize()
            user_id = database.get_or_create_user("Nam")
            source = root / "lesson.txt"
            source.write_text(
                "This document contains enough English lesson text.",
                encoding="utf-8",
            )
            hub = StudyHub(database, object(), index=FailingIndex())  # type: ignore[arg-type]
            with patch("services.study_hub.DOCUMENT_LIBRARY_PATH", root / "documents"):
                with self.assertRaises(StudyHubError):
                    hub.ingest(user_id, source)
            self.assertEqual(database.list_documents(user_id), [])
            self.assertEqual(list((root / "documents").rglob("*.txt")), [])

    def test_fastapi_health_endpoint(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")
            favicon = client.get("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "1.3.0")
        self.assertTrue(response.json()["local_tts"]["vi"])
        self.assertTrue(response.json()["local_tts"]["en"])
        self.assertIn("social_login", response.json())
        self.assertEqual(favicon.status_code, 200)
        self.assertEqual(favicon.headers["content-type"], "image/x-icon")
        self.assertGreater(len(favicon.content), 100)

    def test_login_and_registration_are_separate_pages(self) -> None:
        with TestClient(app) as client:
            login = client.get("/auth/login")
            register = client.get("/auth/register")
        self.assertEqual(login.status_code, 200)
        self.assertIn("Tris AI", login.text)
        self.assertIn("Đăng nhập", login.text)
        self.assertNotIn("Facebook", login.text)
        self.assertNotIn("Nhập lại mật khẩu", login.text)
        self.assertEqual(register.status_code, 200)
        self.assertIn("Tạo tài khoản", register.text)
        self.assertIn("Nhập lại mật khẩu", register.text)


if __name__ == "__main__":
    unittest.main()
