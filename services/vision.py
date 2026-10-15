"""Local image understanding with a multimodal Ollama model for Tris AI."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ollama import Client, ResponseError

from config.settings import (
    OLLAMA_HOST,
    OLLAMA_TIMEOUT_SECONDS,
    VISION_MODEL,
)
from services.study_hub import IMAGE_SUFFIXES, StudyHubError, validate_attachment

DESCRIPTION_PROMPT = (
    "Bạn là bộ phận nhìn ảnh của gia sư AI. Hãy mô tả những gì thực sự có trong ảnh "
    "bằng tiếng Việt: chủ thể hoặc nhân vật chính, đồ vật, cảnh vật, màu sắc nổi bật "
    "và mọi chữ xuất hiện trong ảnh. Ngắn gọn 3-5 câu. Tuyệt đối không bịa đặt những "
    "chi tiết không thấy."
)
QUESTION_PROMPT = (
    "Bạn là bộ phận nhìn ảnh của gia sư AI. Hãy nhìn kỹ ảnh và trả lời câu hỏi sau "
    "bằng tiếng Việt, chỉ dựa trên những gì thực sự thấy trong ảnh. Nếu ảnh không đủ "
    "thông tin để trả lời, hãy nói rõ ảnh cho thấy gì và còn thiếu gì. "
    "Không bịa đặt chi tiết."
)


class VisionError(RuntimeError):
    """Safe vision error suitable for the UI and API."""


class VisionService:
    """Describe attached images fully on-device with an Ollama vision model."""

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.client = client or Client(
            host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SECONDS * 2
        )
        self.model = (model or VISION_MODEL).strip()

    def available(self) -> bool:
        """Report whether the vision model is present on the local server."""
        if not self.model:
            return False
        try:
            self.client.show(self.model)
        except (ResponseError, OSError, ValueError):
            return False
        return True

    def describe(self, image_path: str | Path, question: str = "") -> str:
        """Return a grounded Vietnamese description or image-grounded answer."""
        path = Path(image_path)
        if path.suffix.casefold() not in IMAGE_SUFFIXES:
            raise VisionError("Hiểu ảnh chỉ nhận PNG, JPG, JPEG hoặc WEBP.")
        try:
            validate_attachment(path)
        except StudyHubError as exc:
            raise VisionError(str(exc)) from exc
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise VisionError("Không đọc được tệp ảnh trên máy.") from exc

        prompt = (
            f"{QUESTION_PROMPT}\n\nCÂU HỎI: {question.strip()}"
            if question.strip()
            else DESCRIPTION_PROMPT
        )
        try:
            response: Any = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [encoded],
                    }
                ],
                keep_alive="2m",
                options={"temperature": 0.2, "num_predict": 320},
            )
        except ResponseError as exc:
            error_text = str(exc).lower()
            if exc.status_code == 404 or "not found" in error_text:
                raise VisionError(
                    f"Chưa có model thị giác '{self.model}'. "
                    f"Chạy: ollama pull {self.model}"
                ) from exc
            raise VisionError("Model thị giác local gặp lỗi. Hãy thử lại.") from exc
        except (OSError, ConnectionError) as exc:
            raise VisionError(
                "Không kết nối được Ollama để hiểu ảnh. Hãy kiểm tra Ollama đang chạy."
            ) from exc

        content = self._get_content(response).strip()
        if not content:
            raise VisionError("Model thị giác không trả về mô tả. Hãy thử lại.")
        return content

    @staticmethod
    def _get_content(response: Any) -> str:
        """Support both typed Ollama responses and mapping-like test doubles."""
        if hasattr(response, "message"):
            message = response.message
            if hasattr(message, "content"):
                return message.content or ""
        if isinstance(response, dict):
            return str(response.get("message", {}).get("content", ""))
        return ""
