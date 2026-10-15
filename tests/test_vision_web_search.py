"""Tests for local image understanding and keyless web search."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from services.vision import VisionError, VisionService
from services.web_search import WebSearchError, WebSearchService


def make_image(root: Path, name: str = "photo.png") -> Path:
    path = root / name
    Image.new("RGB", (48, 32), "steelblue").save(path)
    return path


class FakeVisionClient:
    def __init__(self, reply: str = "Một ngôi nhà màu đỏ dưới nắng.") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def chat(self, model: str, messages: list, options: dict | None = None, **kwargs) -> dict:
        self.calls.append({"model": model, "messages": messages})
        return {"message": {"content": self.reply}}


class VisionServiceTests(unittest.TestCase):
    def test_describe_returns_local_model_content(self) -> None:
        client = FakeVisionClient("Bức ảnh vẽ ngôi nhà đỏ và mặt trời vàng.")
        with tempfile.TemporaryDirectory() as directory:
            image = make_image(Path(directory))
            service = VisionService(client=client)
            description = service.describe(image)
        self.assertIn("ngôi nhà", description)
        self.assertEqual(len(client.calls), 1)
        sent = client.calls[0]["messages"][0]
        self.assertTrue(sent["content"])  # prompt present
        self.assertTrue(sent["images"])  # image bytes attached

    def test_describe_rejects_non_image_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.txt"
            path.write_text("hello", encoding="utf-8")
            with self.assertRaises(VisionError):
                VisionService(client=FakeVisionClient()).describe(path)

    def test_describe_maps_missing_model_to_hint(self) -> None:
        from ollama import ResponseError

        class MissingModelClient:
            def chat(self, *args, **kwargs):
                raise ResponseError("model not found", status_code=404)

        with tempfile.TemporaryDirectory() as directory:
            image = make_image(Path(directory))
            service = VisionService(client=MissingModelClient())
            with self.assertRaises(VisionError) as ctx:
                service.describe(image)
        self.assertIn("ollama pull", str(ctx.exception))


def fake_results(query: str, limit: int) -> list[dict]:
    return [
        {
            "title": "Present simple rules",
            "href": "https://example.com/grammar",
            "body": "Use the present simple for habits.",
        },
        {"title": "Broken", "href": "javascript:alert(1)", "body": "ignored"},
    ]


class WebSearchServiceTests(unittest.TestCase):
    def test_search_normalizes_and_filters_hits(self) -> None:
        service = WebSearchService(search_fn=fake_results)
        hits = service.search("present simple")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["url"], "https://example.com/grammar")
        self.assertIn("habits", hits[0]["snippet"])

    def test_search_empty_query_is_rejected(self) -> None:
        with self.assertRaises(WebSearchError):
            WebSearchService(search_fn=fake_results).search("   ")

    def test_search_network_failure_raises_safe_error(self) -> None:
        def broken(query: str, limit: int) -> list[dict]:
            raise RuntimeError("dns failure")

        with self.assertRaises(WebSearchError):
            WebSearchService(search_fn=broken).search("english grammar")

    def test_gather_builds_citation_block(self) -> None:
        service = WebSearchService(
            search_fn=fake_results,
            page_reader=lambda url: "Full page text about present simple.",
        )
        result = service.gather("present simple")
        self.assertEqual(result.sources[0]["label"], "W1")
        self.assertIn("[W1]", result.context_block)
        self.assertIn("Full page text", result.context_block)
        self.assertEqual(result.sources[0]["url"], "https://example.com/grammar")

    def test_gather_continues_when_page_reading_fails(self) -> None:
        def failing_reader(url: str) -> str:
            raise WebSearchError("blocked")

        service = WebSearchService(search_fn=fake_results, page_reader=failing_reader)
        result = service.gather("present simple")
        self.assertTrue(result.sources)
        self.assertIn("không đọc được", result.notice)

    def test_read_page_truncates_long_text(self) -> None:
        long_text = "word " * 100000
        service = WebSearchService(page_reader=lambda url: long_text)
        clipped = service.read_page("https://example.com/big")
        self.assertLessEqual(len(clipped), 6000)


if __name__ == "__main__":
    unittest.main()
