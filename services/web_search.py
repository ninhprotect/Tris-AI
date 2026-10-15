"""Keyless DuckDuckGo web search with local page reading for Tris AI."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from ddgs import DDGS

from config.settings import (
    WEB_FETCH_MAX_CHARACTERS,
    WEB_SEARCH_MAX_PAGES,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_TIMEOUT_SECONDS,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class WebSearchError(RuntimeError):
    """Safe web-search error suitable for the UI and API."""


@dataclass(slots=True)
class WebSearchResult:
    """Bounded search context plus citations for one question."""

    query: str
    sources: list[dict[str, str]] = field(default_factory=list)
    notice: str = ""

    @property
    def context_block(self) -> str:
        """Render sources as a compact numbered block for the local LLM."""
        parts = []
        for source in self.sources:
            parts.append(
                f"[{source['label']}] {source['title']}\n"
                f"URL: {source['url']}\n"
                f"{source['content']}"
            )
        return "\n\n".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {"query": self.query, "sources": self.sources, "notice": self.notice}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class WebSearchService:
    """Search the web without an API key and read pages locally.

    Only the caller-provided query text leaves the machine. Attached
    documents, images and conversation history never do.
    """

    def __init__(
        self,
        search_fn: Callable[..., list[dict[str, Any]]] | None = None,
        page_reader: Callable[[str], str] | None = None,
    ) -> None:
        self._search_fn = search_fn
        self._page_reader = page_reader

    def search(self, query: str, max_results: int | None = None) -> list[dict[str, str]]:
        """Return title/url/snippet hits from DuckDuckGo."""
        clean = _clean_text(query)
        if not clean:
            raise WebSearchError("Hãy nhập từ khóa tìm kiếm.")
        limit = max_results or WEB_SEARCH_MAX_RESULTS
        try:
            if self._search_fn is not None:
                raw = self._search_fn(clean, limit)
            else:
                raw = DDGS(timeout=WEB_SEARCH_TIMEOUT_SECONDS).text(clean, max_results=limit)
        except Exception as exc:  # ddgs raises many network exception types.
            raise WebSearchError(
                "Không tìm được kết quả web. Hãy kiểm tra kết nối mạng và thử lại."
            ) from exc
        hits: list[dict[str, str]] = []
        for item in raw or []:
            url = _clean_text(item.get("href") or item.get("url") or item.get("link"))
            if not url.startswith(("http://", "https://")):
                continue
            hits.append(
                {
                    "title": _clean_text(item.get("title")) or url,
                    "url": url,
                    "snippet": _clean_text(item.get("body") or item.get("snippet")),
                }
            )
            if len(hits) >= limit:
                break
        if not hits:
            raise WebSearchError("Không có kết quả web phù hợp cho từ khóa này.")
        return hits

    def read_page(self, url: str) -> str:
        """Download one page and extract readable article text."""
        if self._page_reader is not None:
            text = self._page_reader(url)
        else:
            try:
                response = httpx.get(
                    url,
                    timeout=WEB_SEARCH_TIMEOUT_SECONDS,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
            except (httpx.HTTPError, OSError) as exc:
                raise WebSearchError(f"Không đọc được trang: {url}") from exc
            text = self._extract_html(response.text)
        clean = _clean_text(text)
        if len(clean) > WEB_FETCH_MAX_CHARACTERS:
            clean = clean[:WEB_FETCH_MAX_CHARACTERS]
        return clean

    @staticmethod
    def _extract_html(html: str) -> str:
        try:
            import trafilatura

            return trafilatura.extract(html, include_comments=False) or ""
        except Exception:  # Extraction must never break the chat flow.
            return ""

    def gather(self, query: str) -> WebSearchResult:
        """Search, read the strongest pages and build one citation block."""
        hits = self.search(query)
        sources: list[dict[str, str]] = []
        notice = ""
        for index, hit in enumerate(hits, start=1):
            label = f"W{index}"
            content = hit["snippet"]
            if index <= WEB_SEARCH_MAX_PAGES:
                try:
                    page_text = self.read_page(hit["url"])
                except WebSearchError:
                    notice = "Một số trang không đọc được nội dung đầy đủ."
                    page_text = ""
                if page_text:
                    content = f"{hit['snippet']}\nNỘI DUNG TRANG: {page_text}".strip()
            sources.append(
                {
                    "label": label,
                    "title": hit["title"],
                    "url": hit["url"],
                    "content": content,
                    "excerpt": content[:240],
                }
            )
        return WebSearchResult(query=_clean_text(query), sources=sources, notice=notice)
