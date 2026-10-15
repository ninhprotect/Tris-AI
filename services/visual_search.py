"""Privacy-aware local and Google visual-search adapter for Tris AI."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from config.settings import (
    GOOGLE_VISION_API_KEY,
    VISUAL_SEARCH_MAX_RESULTS,
    VISUAL_SEARCH_TIMEOUT_SECONDS,
)
from services.study_hub import (
    IMAGE_SUFFIXES,
    DocumentParser,
    StudyHubError,
    validate_attachment,
)


class VisualSearchError(RuntimeError):
    """Safe visual-search error suitable for the UI and API."""


_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FILEISH_RE = re.compile(r"\S*(https?://|\.(jpg|jpeg|png|webp|gif|md))\S*", re.IGNORECASE)


def clean_search_keywords(value: str) -> str:
    """Strip markdown artifacts, URLs and file references from raw text."""
    text = _MARKDOWN_IMAGE_RE.sub(" ", value or "")
    text = _FILEISH_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(slots=True)
class VisualSearchResult:
    mode: str
    query: str
    google_images_url: str
    lens_url: str = "https://lens.google.com/"
    labels: list[str] = field(default_factory=list)
    pages: list[dict[str, str]] = field(default_factory=list)
    matching_images: list[str] = field(default_factory=list)
    similar_images: list[str] = field(default_factory=list)
    notice: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "google_images_url": self.google_images_url,
            "lens_url": self.lens_url,
            "labels": self.labels,
            "pages": self.pages,
            "matching_images": self.matching_images,
            "similar_images": self.similar_images,
            "notice": self.notice,
        }


class VisualSearchService:
    """Build local search hints and optionally call Google Web Detection."""

    endpoint = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(
        self,
        api_key: str | None = None,
        opener: Callable[..., Any] = urlopen,
        parser: DocumentParser | None = None,
    ) -> None:
        self.api_key = GOOGLE_VISION_API_KEY if api_key is None else api_key.strip()
        self.opener = opener
        self.parser = parser or DocumentParser()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        image_path: str | Path,
        allow_external: bool = False,
        query_override: str = "",
    ) -> VisualSearchResult:
        """Analyze locally first; transmit the image only with explicit consent."""
        path = Path(image_path).resolve()
        if path.suffix.casefold() not in IMAGE_SUFFIXES:
            raise VisualSearchError("Tìm kiếm hình ảnh chỉ nhận PNG, JPG, JPEG hoặc WEBP.")
        try:
            validate_attachment(path)
        except StudyHubError as exc:
            raise VisualSearchError(str(exc)) from exc

        query = clean_search_keywords(query_override) or self._local_query(path)
        fallback = VisualSearchResult(
            mode="local-links",
            query=query,
            google_images_url=self._google_images_url(query),
            notice=(
                "Ảnh chưa rời khỏi máy. Hãy bật cho phép gửi ảnh nếu muốn tìm "
                "ảnh khớp và ảnh tương tự trực tiếp."
            ),
        )
        if not allow_external:
            return fallback
        if not self.configured:
            fallback.notice = (
                "Chưa cấu hình Google Cloud Vision nên ảnh vẫn ở trên máy. "
                "Bạn vẫn có thể tìm bằng từ khóa hoặc mở Google Lens để tự tải ảnh."
            )
            return fallback

        try:
            return self._google_web_detection(path, query)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            fallback.notice = (
                "Google Web Detection chưa phản hồi; Tris AI đã chuyển sang liên kết "
                f"tìm kiếm an toàn. Chi tiết: {type(exc).__name__}."
            )
            return fallback

    def _local_query(self, path: Path) -> str:
        try:
            text, _ = self.parser.extract(path)
        except StudyHubError:
            text = ""
        clean = clean_search_keywords(text)
        if clean:
            words = clean.split()
            return " ".join(words[:24])[:180]
        stem = clean_search_keywords(re.sub(r"[-_]+", " ", path.stem)).strip()
        return stem[:180] or "similar image"

    @staticmethod
    def _google_images_url(query: str) -> str:
        return f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}"

    def _google_web_detection(self, path: Path, query: str) -> VisualSearchResult:
        payload = {
            "requests": [
                {
                    "image": {
                        "content": base64.b64encode(path.read_bytes()).decode("ascii")
                    },
                    "features": [
                        {
                            "type": "WEB_DETECTION",
                            "maxResults": VISUAL_SEARCH_MAX_RESULTS,
                        }
                    ],
                }
            ]
        }
        request = Request(
            f"{self.endpoint}?key={quote_plus(self.api_key)}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener(request, timeout=VISUAL_SEARCH_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
        first = body.get("responses", [{}])[0]
        if first.get("error"):
            raise ValueError(str(first["error"].get("message") or "Google Vision error"))
        web = first.get("webDetection") or {}

        labels = [
            str(item.get("label") or "").strip()
            for item in web.get("bestGuessLabels", [])
            if str(item.get("label") or "").strip()
        ]
        labels.extend(
            str(item.get("description") or "").strip()
            for item in web.get("webEntities", [])
            if str(item.get("description") or "").strip()
        )
        labels = list(dict.fromkeys(labels))[:VISUAL_SEARCH_MAX_RESULTS]
        if labels:
            query = " ".join(labels[:4])[:180]

        pages = []
        for item in web.get("pagesWithMatchingImages", [])[:VISUAL_SEARCH_MAX_RESULTS]:
            url = str(item.get("url") or "").strip()
            if url.startswith(("http://", "https://")):
                pages.append({"title": str(item.get("pageTitle") or url), "url": url})

        def image_urls(*groups: str) -> list[str]:
            values: list[str] = []
            for group in groups:
                for item in web.get(group, []):
                    url = str(item.get("url") or "").strip()
                    if url.startswith(("http://", "https://")) and url not in values:
                        values.append(url)
            return values[:VISUAL_SEARCH_MAX_RESULTS]

        return VisualSearchResult(
            mode="google-web-detection",
            query=query,
            google_images_url=self._google_images_url(query),
            labels=labels,
            pages=pages,
            matching_images=image_urls("fullMatchingImages", "partialMatchingImages"),
            similar_images=image_urls("visuallySimilarImages"),
            notice="Ảnh đã được gửi tới Google Web Detection theo lựa chọn của bạn.",
        )
