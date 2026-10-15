# Tris AI

Gia sư tiếng Anh chạy hoàn toàn trên máy của bạn: chat, luyện ngữ pháp, từ vựng, nhập vai,
hỏi đáp trên tài liệu riêng, nói chuyện bằng giọng nói, kèm linh vật Tris biết biểu cảm.
Không gọi OpenAI, Gemini hay bất kỳ API AI trả phí nào; âm thanh và tài liệu không rời máy.

> **English:** Tris AI is a fully local English tutor for Vietnamese learners. A FastAPI backend
> serves a React web app and a lightweight 2D/3D mascot companion. Ollama runs a Qwen3 4B model on a
> 6 GB consumer GPU, with retrieval over the learner's own documents, voice input and output
> (faster-whisper, Piper + OpenVoice), and no paid AI APIs.

## Tính năng

- **Gia sư 4 chế độ:** Conversation, Grammar, Vocabulary, Role Play; quiz, ôn câu sai,
  mục tiêu hằng ngày và thống kê tiến độ theo từng hồ sơ.
- **Hỏi đáp trên tài liệu (RAG):** PDF/DOCX/Markdown/TXT, trả lời có trích dẫn `[S1]`;
  tìm web DuckDuckGo có nguồn `[W1]`; Tris tự rà lại câu trả lời trước khi gửi.
- **Giọng nói:** nói qua micro (faster-whisper), Tris đọc lại ngay khi chữ đang hiện
  (Piper + OpenVoice), tự nhận tiếng Việt/English.
- **Tris Companion** (`/companion/`): linh vật 2D, Tris 3D (`.glb`) hoặc model VRM của bạn;
  mớm lời theo giọng, đổi cảm xúc theo câu trả lời, nhìn theo con trỏ.
- **Hiểu và tạo ảnh:** mô tả ảnh bằng `qwen2.5vl:3b`, OCR local; tạo ảnh/GIF/video ngắn
  bằng `sd-turbo`.
- **Tài khoản:** đăng ký/đăng nhập PostgreSQL (Argon2id) và Google OAuth; REST API cho
  ứng dụng Kotlin.

## Điểm kỹ thuật

- **Giọng đọc theo luồng:** câu trả lời truyền dạng NDJSON; câu được tách ngay khi đang sinh để
  giọng đọc bắt đầu từ câu đầu tiên, không chờ hết đoạn.
- **Kiểm soát chất lượng câu trả lời:** bản nháp được Tris tự rà lại một lượt trước khi gửi;
  nguồn tham khảo được cắt theo ngân sách token để không vượt cửa sổ ngữ cảnh 4096.
- **Chạy được trên GPU đời cũ:** chọn runtime CUDA 12 cho GTX 1060 (Pascal), dọn tiến trình
  mồ côi còn giữ VRAM, tự giải phóng tài nguyên khi đóng tab cuối.
- **Linh vật không cần build:** lipsync theo năng lượng giọng (Web Audio), cảm xúc suy ra từ
  câu trả lời, three.js cho model `.glb`/`.vrm`, giới hạn FPS và dừng khi tab ẩn.
- **Kiểm thử:** 232 unit test Python và bộ test giao diện Playwright.

## Công nghệ

| Phần | Dùng |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Giao diện | React 19, TypeScript, Vite, Tailwind CSS 4; Companion: HTML/JS thuần, three.js |
| Mô hình ngôn ngữ | Ollama (GPU CUDA), `english-tutor-local:4b` dựng từ Qwen3 4B, `qwen2.5vl:3b` |
| RAG | `nomic-embed-text`, Qdrant embedded, PyPDF/MinerU, RapidOCR |
| Giọng nói | faster-whisper `small` (int8) + Silero VAD; Piper → OpenVoice V2 |
| Dữ liệu | SQLite (nội dung học), PostgreSQL 17 (tài khoản) |

```text
Trình duyệt :7860 (React + Companion)          Ứng dụng Kotlin
                │                                     │
                └────────── FastAPI :7860 / :8000 ────┘
                                    │
       ┌──────────────┬─────────────┼──────────────┬──────────────────┐
     Ollama         Qdrant     SQLite + PostgreSQL  faster-whisper   Piper → OpenVoice
   (LLM, GPU)       (RAG)        (học / tài khoản)   (mic, CPU)      (giọng, :7861)
```

## Yêu cầu

- Windows 10/11, Python 3.12, [Ollama](https://ollama.com)
- Node.js 22.12+ và pnpm 11 (chỉ để build giao diện)
- Khuyến nghị GPU NVIDIA 6 GB VRAM và 16 GB RAM (đã chạy trên GTX 1060 6 GB)

## Cài đặt

```powershell
# 1. Môi trường Python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Mô hình
ollama pull qwen3:4b-instruct
ollama create english-tutor-local:4b -f Modelfile.4b
ollama pull nomic-embed-text
ollama pull qwen2.5vl:3b

# 3. Giọng đọc và micro
.\.venv\Scripts\python.exe scripts\setup_tts.py
.\scripts\setup_stt.ps1

# 4. Giao diện web
.\scripts\build_workspace.ps1 -Install
```

Tùy chọn:

- **Tài khoản:** giải nén PostgreSQL 17.11 portable vào `runtime/postgresql-17.11`, rồi chạy
  `.\scripts\setup_postgres.ps1` (sinh mật khẩu ngẫu nhiên, lưu DSN vào biến môi trường).
- **Đăng nhập Google:** `.\scripts\setup_google_oauth.ps1`, xem [docs/API.md](docs/API.md).
- **Giọng Tris (OpenVoice):** cần runtime trong `runtime/xtts`, xem
  [docs/CHAT_MEDIA_VOICE.md](docs/CHAT_MEDIA_VOICE.md). Chưa cài thì đặt `TTS_ENGINE=piper`.
- **Tạo ảnh:** `.\scripts\setup_imagegen.ps1` (cần GPU NVIDIA, ~15 GB trống).
- **PDF scan / công thức:** `.\scripts\setup_mineru.ps1 -InstallRoot "D:\TrisAI\MinerU"`.

Cấu hình qua biến môi trường; mẫu có chú thích trong [.env.example](.env.example).

## Chạy

```powershell
.\start_tris_ai.bat
```

- Ứng dụng: http://127.0.0.1:7860 · Companion: http://127.0.0.1:7860/companion/
- API: http://127.0.0.1:8000 · Swagger: http://127.0.0.1:8000/docs

Đóng tab trình duyệt cuối cùng thì Tris tự tắt sau 120 giây và giải phóng VRAM.

## Cấu trúc thư mục

```text
ai/          prompt, bản sắc Tris, client LLM
auth/        tài khoản PostgreSQL, Google OAuth
config/      cấu hình từ biến môi trường
database/    SQLite: hồ sơ, bài tập, tài liệu
services/    chat, RAG, giọng nói, micro, tạo ảnh, tìm web
frontend/    giao diện React (src/) và Tris Companion (public/companion/)
runtime/     máy chủ giọng nói, bộ tạo ảnh; model và runtime được cài vào đây
scripts/     cài đặt, khởi động, build
tests/       kiểm thử unittest
docs/        tài liệu
```

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Test không đụng vào dữ liệu học viên thật.

## Tài liệu

- [docs/API.md](docs/API.md): REST API, cấu hình, Google OAuth, dữ liệu cục bộ
- [docs/WORKSPACE_WEB.md](docs/WORKSPACE_WEB.md): giao diện web, build và kiểm thử
- [docs/CHAT_MEDIA_VOICE.md](docs/CHAT_MEDIA_VOICE.md): công cụ trong chat và giọng Tris
- [docs/CHANGELOG.md](docs/CHANGELOG.md): lịch sử phiên bản
- [docs/mascot/](docs/mascot/), [docs/TRIS_3D_FX_PROMPT.md](docs/TRIS_3D_FX_PROMPT.md),
  [docs/TRIS_STAGE_BG_PROMPT.md](docs/TRIS_STAGE_BG_PROMPT.md): dựng linh vật và sân khấu

## Ghi công

- Thuật toán lipsync và hành vi linh vật port từ [Project AIRI](https://github.com/moeru-ai/airi) (MIT).
- [three.js](https://threejs.org) và [@pixiv/three-vrm](https://github.com/pixiv/three-vrm) (MIT),
  đóng gói sẵn trong `frontend/public/companion/lib`.
- [Piper](https://github.com/rhasspy/piper), [OpenVoice](https://github.com/myshell-ai/OpenVoice),
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Qwen](https://github.com/QwenLM),
  [Ollama](https://github.com/ollama/ollama).

Tris AI do **Nguyễn Hải Hà Ninh** phát triển.
