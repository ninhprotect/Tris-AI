"""Local document ingestion, embedding, Qdrant retrieval, RAG, and backups."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ollama import Client, ResponseError

from ai.llm import LocalAIError, OllamaLLM
from config.settings import (
    DATABASE_PATH,
    DOCUMENT_LIBRARY_PATH,
    EMBEDDING_MODEL,
    MAX_ATTACHMENT_FILES,
    MAX_ATTACHMENT_TOTAL_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_EXTRACTED_CHARACTERS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_PDF_PAGES,
    MAX_VIDEO_BYTES,
    MINERU_BACKEND,
    MINERU_EXECUTABLE,
    MINERU_TIMEOUT_SECONDS,
    OLLAMA_HOST,
    OLLAMA_TIMEOUT_SECONDS,
    PROJECT_ROOT,
    QDRANT_COLLECTION,
    QDRANT_PATH,
    QDRANT_URL,
    RAG_TOP_K,
)
from database import DatabaseError, TutorDatabase


class StudyHubError(RuntimeError):
    """Safe error for document and RAG operations."""


DOCUMENT_SUFFIXES = {".pdf", ".txt", ".md", ".docx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
SUPPORTED_ATTACHMENT_SUFFIXES = DOCUMENT_SUFFIXES | IMAGE_SUFFIXES | VIDEO_SUFFIXES


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.0f} MB"


def attachment_limit_bytes(path: str | Path) -> int:
    """Return the per-file byte limit for one supported attachment."""
    suffix = Path(path).suffix.casefold()
    if suffix in DOCUMENT_SUFFIXES:
        return MAX_DOCUMENT_BYTES
    if suffix in IMAGE_SUFFIXES:
        return MAX_IMAGE_BYTES
    if suffix in VIDEO_SUFFIXES:
        return MAX_VIDEO_BYTES
    raise StudyHubError("Định dạng tệp này chưa được hỗ trợ.")


def validate_attachment(path: str | Path) -> int:
    """Reject missing, malformed or oversized files before expensive work."""
    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise StudyHubError("Không tìm thấy tệp đã chọn.")
    limit = attachment_limit_bytes(source_path)
    size = source_path.stat().st_size
    if size <= 0:
        raise StudyHubError("Tệp rỗng nên không thể xử lý.")
    if size > limit:
        raise StudyHubError(
            f"Tệp vượt giới hạn {_megabytes(limit)} cho định dạng này."
        )
    if source_path.suffix.casefold() in IMAGE_SUFFIXES:
        try:
            from PIL import Image, UnidentifiedImageError

            with Image.open(source_path) as image:
                pixels = int(image.width) * int(image.height)
                if pixels > MAX_IMAGE_PIXELS:
                    raise StudyHubError(
                        f"Ảnh vượt giới hạn {MAX_IMAGE_PIXELS // 1_000_000} megapixel."
                    )
                image.verify()
        except StudyHubError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise StudyHubError("Ảnh bị hỏng hoặc sai định dạng.") from exc
    return size


def validate_attachment_batch(paths: list[str]) -> tuple[list[str], list[str]]:
    """Apply count, per-file and aggregate limits without raising into Gradio."""
    accepted: list[str] = []
    errors: list[str] = []
    total = 0
    for raw_path in dict.fromkeys(paths):
        path = str(raw_path)
        name = Path(path).name or "Tệp không tên"
        if len(accepted) >= MAX_ATTACHMENT_FILES:
            errors.append(f"⚠️ {name}: tối đa {MAX_ATTACHMENT_FILES} tệp mỗi lần gửi.")
            continue
        try:
            size = validate_attachment(path)
            if total + size > MAX_ATTACHMENT_TOTAL_BYTES:
                raise StudyHubError(
                    f"Tổng tệp vượt giới hạn {_megabytes(MAX_ATTACHMENT_TOTAL_BYTES)}."
                )
            accepted.append(path)
            total += size
        except StudyHubError as exc:
            errors.append(f"⚠️ {name}: {exc}")
    return accepted, errors


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 140) -> list[dict]:
    """Split extracted text into readable overlapping chunks."""
    clean = re.sub(r"\r\n?", "\n", text)
    clean = re.sub(r"[ \t]+", " ", clean)
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    chunks: list[dict] = []
    current = ""
    heading = ""
    for paragraph in paragraphs:
        if len(paragraph) < 120 and (paragraph.startswith("#") or paragraph.isupper()):
            heading = paragraph.lstrip("# ").strip()
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > chunk_size:
            chunks.append({"heading": heading, "content": current})
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip()
        else:
            current = candidate
        while len(current) > chunk_size * 2:
            chunks.append({"heading": heading, "content": current[:chunk_size]})
            current = current[max(1, chunk_size - overlap):].strip()
    if current:
        chunks.append({"heading": heading, "content": current})
    return chunks


class DocumentParser:
    """Use MinerU when available and safe built-in fallbacks otherwise."""

    SUPPORTED_SUFFIXES = DOCUMENT_SUFFIXES | IMAGE_SUFFIXES
    _rapidocr: Any | None = None
    _ocr_lock = threading.RLock()

    def extract(self, path: Path) -> tuple[str, str]:
        validate_attachment(path)
        suffix = path.suffix.casefold()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise StudyHubError("Chỉ hỗ trợ PDF, tài liệu văn bản và ảnh phổ biến.")
        if suffix in {".txt", ".md"}:
            return self._bounded(
                path.read_text(encoding="utf-8", errors="replace"), "native-text"
            )
        if suffix == ".docx":
            return self._bounded(self._extract_docx(path), "native-docx")
        mineru_result = self._extract_with_mineru(path)
        if mineru_result:
            return self._bounded(mineru_result, "MinerU")
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            rapid_result = self._extract_with_rapidocr(path)
            if rapid_result:
                return self._bounded(rapid_result, "RapidOCR local fallback")
            raise StudyHubError("Không nhận diện được văn bản rõ ràng trong ảnh này.")
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise StudyHubError(f"PDF vượt giới hạn {MAX_PDF_PAGES} trang.")
            parts: list[str] = []
            character_count = 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                character_count += len(page_text)
                if character_count > MAX_EXTRACTED_CHARACTERS:
                    raise StudyHubError(
                        "Nội dung PDF quá dài để xử lý an toàn trong một lần."
                    )
                parts.append(page_text)
            text = "\n\n".join(parts)
        except StudyHubError:
            raise
        except Exception as exc:
            raise StudyHubError(
                "Không đọc được PDF. Hãy cài MinerU cho tài liệu scan/OCR."
            ) from exc
        return self._bounded(text, "PyPDF fallback")

    @staticmethod
    def _bounded(text: str, engine: str) -> tuple[str, str]:
        if len(text) > MAX_EXTRACTED_CHARACTERS:
            raise StudyHubError(
                "Nội dung trích xuất quá dài để xử lý an toàn trong một lần."
            )
        return text, engine

    @staticmethod
    def _extract_docx(path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            paragraphs: list[str] = []
            for node in root.iter():
                if node.tag.endswith("}p"):
                    text = "".join(
                        child.text or "" for child in node.iter() if child.tag.endswith("}t")
                    ).strip()
                    if text:
                        paragraphs.append(text)
            return "\n\n".join(paragraphs)
        except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise StudyHubError("Không đọc được file DOCX này.") from exc

    @staticmethod
    def _extract_with_mineru(path: Path) -> str:
        configured = Path(MINERU_EXECUTABLE).expanduser() if MINERU_EXECUTABLE else None
        bundled = PROJECT_ROOT / "runtime" / "mineru" / ".venv" / "Scripts" / "mineru.exe"
        executable = (
            str(configured.resolve()) if configured and configured.is_file() else None
        ) or (str(bundled) if bundled.is_file() else None) or shutil.which(
            "mineru"
        ) or shutil.which("magic-pdf")
        if not executable:
            return ""
        with tempfile.TemporaryDirectory(prefix="english-tutor-mineru-") as output_dir:
            try:
                if Path(executable).stem.casefold() == "mineru":
                    command = [
                        executable,
                        "-p",
                        str(path),
                        "-o",
                        output_dir,
                        "-b",
                        MINERU_BACKEND,
                    ]
                else:
                    command = [executable, "-p", str(path), "-o", output_dir, "-m", "auto"]
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=MINERU_TIMEOUT_SECONDS,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode != 0:
                    return ""
                markdown_files = sorted(Path(output_dir).rglob("*.md"))
                if not markdown_files:
                    return ""
                return max(markdown_files, key=lambda item: item.stat().st_size).read_text(
                    encoding="utf-8", errors="replace"
                )
            except (OSError, subprocess.TimeoutExpired):
                return ""

    @classmethod
    def _extract_with_rapidocr(cls, path: Path) -> str:
        """Read image text locally when the full MinerU runtime is unavailable."""
        try:
            with cls._ocr_lock:
                if cls._rapidocr is None:
                    from rapidocr import RapidOCR

                    cls._rapidocr = RapidOCR(params={"Global.log_level": "warning"})
                result = cls._rapidocr(path)
            lines = [
                str(value).strip()
                for value in (getattr(result, "txts", None) or [])
                if str(value).strip()
            ]
            return "\n".join(lines)
        except (ImportError, OSError, RuntimeError, ValueError):
            return ""


class LocalEmbedder:
    """Generate semantic vectors with the local Ollama embedding model."""

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SECONDS)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response: Any = self.client.embed(
                model=EMBEDDING_MODEL, input=texts, keep_alive="30m"
            )
            embeddings = getattr(response, "embeddings", None)
            if embeddings is None and isinstance(response, dict):
                embeddings = response.get("embeddings")
            vectors = [list(map(float, vector)) for vector in (embeddings or [])]
            if len(vectors) != len(texts) or not vectors:
                raise StudyHubError("Model embedding local không trả đủ vector.")
            return vectors
        except ResponseError as exc:
            raise StudyHubError(
                f"Chưa có model embedding '{EMBEDDING_MODEL}'. Chạy: "
                f"ollama pull {EMBEDDING_MODEL}"
            ) from exc
        except (OSError, ConnectionError) as exc:
            raise StudyHubError("Không kết nối được Ollama để tạo embedding.") from exc


class QdrantIndex:
    """Use Qdrant embedded mode by default or a configured company server."""

    def __init__(self, embedder: LocalEmbedder | None = None) -> None:
        self.embedder = embedder or LocalEmbedder()
        try:
            from qdrant_client import QdrantClient

            if QDRANT_URL:
                self.client = QdrantClient(url=QDRANT_URL)
            else:
                QDRANT_PATH.mkdir(parents=True, exist_ok=True)
                self.client = QdrantClient(path=str(QDRANT_PATH))
        except Exception as exc:
            raise StudyHubError("Không khởi động được Qdrant local.") from exc

    def _collection_name(self, dimension: int) -> str:
        return f"{QDRANT_COLLECTION}_{dimension}"

    def index(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0
        try:
            vectors = self.embedder.embed([str(chunk["content"]) for chunk in chunks])
            dimension = len(vectors[0])
            collection = self._collection_name(dimension)
            from qdrant_client.models import Distance, PointStruct, VectorParams

            if not self.client.collection_exists(collection):
                self.client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=dimension, distance=Distance.COSINE
                    ),
                )
            points = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                payload = {
                    "user_id": int(chunk["user_id"]),
                    "document_id": int(chunk["document_id"]),
                    "chunk_id": int(chunk["id"]),
                    "title": str(chunk["title"]),
                    "heading": str(chunk.get("heading", "")),
                    "content": str(chunk["content"]),
                }
                points.append(
                    PointStruct(
                        id=str(chunk["vector_id"]), vector=vector, payload=payload
                    )
                )
            self.client.upsert(collection_name=collection, points=points, wait=True)
            return len(points)
        except StudyHubError:
            raise
        except Exception as exc:
            raise StudyHubError(
                "Không thể lập chỉ mục Qdrant cho tài liệu này."
            ) from exc

    def search(
        self,
        user_id: int,
        query: str,
        document_ids: list[int] | None = None,
        limit: int = RAG_TOP_K,
    ) -> list[dict]:
        vector = self.embedder.embed([query])[0]
        collection = self._collection_name(len(vector))
        if not self.client.collection_exists(collection):
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        conditions: list[Any] = [
            FieldCondition(key="user_id", match=MatchValue(value=int(user_id)))
        ]
        if document_ids:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=[int(value) for value in document_ids]),
                )
            )
        result = self.client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=Filter(must=conditions),
            limit=max(1, min(int(limit), 12)),
            with_payload=True,
        )
        return [
            {**dict(point.payload or {}), "score": float(point.score)}
            for point in result.points
        ]


class StudyHub:
    """High-level local-first service shared by Gradio and FastAPI."""

    def __init__(
        self,
        database: TutorDatabase,
        llm: OllamaLLM,
        parser: DocumentParser | None = None,
        index: QdrantIndex | None = None,
    ) -> None:
        self.database = database
        self.llm = llm
        self.parser = parser or DocumentParser()
        self._index = index

    @property
    def index(self) -> QdrantIndex:
        if self._index is None:
            self._index = QdrantIndex()
        return self._index

    def ingest(self, user_id: int, source: str | Path, title: str = "") -> dict:
        source_path = Path(source).resolve()
        validate_attachment(source_path)
        text, engine = self.parser.extract(source_path)
        if len(text.strip()) < 20:
            raise StudyHubError("Tài liệu không có đủ văn bản để lập chỉ mục.")
        DOCUMENT_LIBRARY_PATH.mkdir(parents=True, exist_ok=True)
        learner_dir = DOCUMENT_LIBRARY_PATH / str(user_id)
        learner_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        stored_path = learner_dir / f"{stamp}{source_path.suffix.casefold()}"
        document_id: int | None = None
        try:
            shutil.copy2(source_path, stored_path)
            chunks = chunk_text(text)
            document_id = self.database.save_document(
                user_id=user_id,
                title=(title.strip() or source_path.stem)[:160],
                source_path=str(source_path),
                stored_path=str(stored_path),
                file_type=source_path.suffix.casefold().lstrip("."),
                extraction_engine=engine,
                text=text,
                chunks=chunks,
            )
            stored_chunks = self.database.get_document_chunks(user_id, [document_id])
            indexed = self.index.index(stored_chunks)
        except Exception as exc:
            if document_id is not None:
                try:
                    self.database.delete_document(user_id, document_id)
                except DatabaseError:
                    pass
            try:
                stored_path.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, (StudyHubError, DatabaseError)):
                raise
            raise StudyHubError(
                "Không thể hoàn tất xử lý tài liệu; dữ liệu tạm đã được dọn."
            ) from exc
        return {
            "document_id": document_id,
            "title": title.strip() or source_path.stem,
            "engine": engine,
            "characters": len(text),
            "chunks": len(chunks),
            "indexed": indexed,
        }

    def store_media_attachment(self, user_id: int, source: str | Path) -> dict:
        """Keep a local media attachment without pretending it was transcribed."""
        source_path = Path(source).resolve()
        if source_path.suffix.casefold() not in VIDEO_SUFFIXES:
            raise StudyHubError("Định dạng video này chưa được hỗ trợ.")
        validate_attachment(source_path)
        learner_dir = DOCUMENT_LIBRARY_PATH / str(user_id) / "media"
        learner_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        stored_path = learner_dir / f"{stamp}{source_path.suffix.casefold()}"
        shutil.copy2(source_path, stored_path)
        return {
            "name": source_path.name,
            "stored_path": str(stored_path),
            "size": source_path.stat().st_size,
        }

    def ensure_indexed(self, user_id: int, document_ids: list[int] | None = None) -> int:
        return self.index.index(self.database.get_document_chunks(user_id, document_ids))

    def ask(
        self,
        user_id: int,
        question: str,
        document_ids: list[int] | None = None,
    ) -> dict:
        clean_question = " ".join((question or "").split())
        if not clean_question:
            raise StudyHubError("Hãy nhập câu hỏi về tài liệu.")
        hits = self.index.search(user_id, clean_question, document_ids)
        if not hits:
            chunks = self.database.get_document_chunks(user_id, document_ids)
            if chunks:
                self.index.index(chunks)
                hits = self.index.search(user_id, clean_question, document_ids)
        if not hits:
            raise StudyHubError("Chưa có nội dung phù hợp trong thư viện tài liệu.")
        sources = []
        context_parts = []
        for index, hit in enumerate(hits, start=1):
            label = f"S{index}"
            context_parts.append(
                f"[{label}] {hit['title']} — đoạn {int(hit.get('chunk_id', 0))}\n"
                f"{hit['content']}"
            )
            sources.append(
                {
                    "label": label,
                    "document_id": int(hit["document_id"]),
                    "chunk_id": int(hit["chunk_id"]),
                    "title": str(hit["title"]),
                    "score": round(float(hit["score"]), 4),
                    "excerpt": str(hit["content"])[:240],
                }
            )
        system_prompt = (
            "Bạn là Tris (Tris AI), gia sư tiếng Anh chạy local, đang dùng RAG. "
            "Nếu được hỏi bạn là ai, chỉ nói bạn là Tris của ứng dụng Tris AI; "
            "nếu được hỏi ai tạo ra bạn, trả lời Tris AI do Nguyễn Hải Hà Ninh, "
            "sinh viên ngành Công nghệ thông tin tại Đại học Thủ Dầu Một, phát triển; "
            "không bao giờ tiết lộ model gốc hay hãng tạo ra nó. "
            "Chỉ trả lời dựa trên NGUỒN được cung cấp. "
            "Nếu nguồn không đủ, nói rõ là tài liệu chưa đủ thông tin. Trả lời bằng tiếng Việt "
            "dễ hiểu, giữ ví dụ tiếng Anh khi hữu ích, và gắn trích dẫn [S1], [S2] ngay sau ý liên quan."
        )
        answer = self.llm.chat(
            system_prompt,
            [],
            f"CÂU HỎI: {clean_question}\n\nNGUỒN:\n" + "\n\n".join(context_parts),
        )
        return {"answer": answer, "sources": sources}


def create_backup(destination_dir: Path | None = None) -> Path:
    """Create a recoverable timestamped copy of the SQLite database."""
    backup_dir = destination_dir or (PROJECT_ROOT / "backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"english_tutor_{datetime.now():%Y%m%d_%H%M%S}.db"
    if not DATABASE_PATH.exists():
        raise StudyHubError("Chưa có database để backup.")
    shutil.copy2(DATABASE_PATH, destination)
    return destination


def export_profile(database: TutorDatabase, user_id: int) -> Path:
    """Write one learner export without modifying the live database."""
    export_dir = PROJECT_ROOT / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    destination = export_dir / f"learner_{user_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
    destination.write_text(
        json.dumps(database.export_learner_data(user_id), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
