"""Tests for privacy-aware visual search."""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from services.visual_search import VisualSearchError, VisualSearchService


class FakeParser:
    def extract(self, path: Path) -> tuple[str, str]:
        return "English grammar lesson present simple", "fake-ocr"


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class VisualSearchTests(unittest.TestCase):
    def make_image(self, root: Path) -> Path:
        path = root / "lesson.png"
        Image.new("RGB", (32, 32), "white").save(path)
        return path

    def test_default_search_never_transmits_the_image(self) -> None:
        calls: list[object] = []

        def opener(*args, **kwargs):
            calls.append(args)
            raise AssertionError("network must not be called")

        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(Path(directory))
            service = VisualSearchService(
                api_key="configured-key", opener=opener, parser=FakeParser()
            )
            result = service.search(image, allow_external=False)
        self.assertEqual(result.mode, "local-links")
        self.assertIn("English+grammar", result.google_images_url)
        self.assertEqual(calls, [])

    def test_missing_key_falls_back_even_after_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(Path(directory))
            result = VisualSearchService(api_key="", parser=FakeParser()).search(
                image, allow_external=True
            )
        self.assertEqual(result.mode, "local-links")
        self.assertIn("Chưa cấu hình", result.notice)

    def test_google_web_detection_results_are_normalized(self) -> None:
        payload = {
            "responses": [
                {
                    "webDetection": {
                        "bestGuessLabels": [{"label": "present simple lesson"}],
                        "webEntities": [{"description": "English grammar"}],
                        "pagesWithMatchingImages": [
                            {"pageTitle": "Grammar page", "url": "https://example.com/page"}
                        ],
                        "fullMatchingImages": [{"url": "https://example.com/match.png"}],
                        "visuallySimilarImages": [{"url": "https://example.com/similar.png"}],
                    }
                }
            ]
        }
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(payload)

        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(Path(directory))
            result = VisualSearchService(
                api_key="test-key", opener=opener, parser=FakeParser()
            ).search(image, allow_external=True)
        self.assertEqual(result.mode, "google-web-detection")
        self.assertEqual(result.labels[0], "present simple lesson")
        self.assertEqual(result.pages[0]["url"], "https://example.com/page")
        self.assertEqual(result.matching_images, ["https://example.com/match.png"])
        self.assertEqual(result.similar_images, ["https://example.com/similar.png"])
        self.assertEqual(len(requests), 1)

    def test_non_image_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lesson.txt"
            path.write_text("not an image", encoding="utf-8")
            with self.assertRaises(VisualSearchError):
                VisualSearchService(api_key="", parser=FakeParser()).search(path)


if __name__ == "__main__":
    unittest.main()
