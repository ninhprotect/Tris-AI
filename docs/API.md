# REST API và cấu hình

FastAPI phục vụ cả giao diện web (cổng 7860) lẫn API cho ứng dụng Kotlin (cổng 8000),
cùng một tiến trình và cùng phiên đăng nhập. Tài liệu tương tác: `http://127.0.0.1:8000/docs`.

## Endpoint chính

| Endpoint | Công dụng |
|---|---|
| `GET /health` | Kiểm tra server |
| `POST /v1/auth/register` | Tạo tài khoản PostgreSQL |
| `POST /v1/auth/login` | Nhận Bearer session token |
| `GET /v1/auth/me` | Đọc tài khoản đang đăng nhập |
| `POST /v1/auth/change-password` | Đổi mật khẩu |
| `POST /v1/auth/logout` | Thu hồi session |
| `GET /v1/auth/oauth/status` | Trạng thái cấu hình OAuth (Google trước, Facebook sau) |
| `GET /v1/auth/oauth/{provider}/start` | Bắt đầu OAuth trên trình duyệt |
| `GET /v1/auth/oauth/{provider}/callback` | Callback nhà cung cấp OAuth |
| `GET /v1/learners/{name}/settings` | Đọc cài đặt hồ sơ cho web/Kotlin |
| `PUT /v1/learners/{name}/settings` | Lưu theme, ngôn ngữ hệ thống/AI, cá nhân hóa, voice |
| `POST /v1/workspace/chat` | Chat dạng luồng NDJSON (giao diện web và Companion) |
| `POST /v1/speech` | Tạo WAV giọng linh vật local |
| `POST /v1/workspace/transcribe` | Nhận bản ghi micro và chuyển thành chữ bằng STT local |
| `POST /v1/chat` | Chat theo mode; đặt `web_search: true` để trả lời kèm nguồn web |
| `POST /v1/web-search` | Tìm kiếm DuckDuckGo, trả về tiêu đề/URL |
| `POST /v1/media-generate` | Tạo ảnh/GIF/video ngắn local bằng sd-turbo |
| `GET /v1/media/{file}` | Tải tệp media đã tạo |
| `POST /v1/exercises` | Tạo quiz thường hoặc từ tài liệu |
| `POST /v1/exercises/{id}/submit` | Nộp trọn bộ đáp án |
| `GET /v1/learners/{name}/progress` | Tiến độ, mục tiêu, kỹ năng |
| `GET /v1/learners/{name}/review/{kind}` | Câu sai/cắm cờ/điểm yếu |
| `POST /v1/documents/{name}` | Upload và lập chỉ mục tài liệu |
| `POST /v1/visual-search` | OCR local; tùy chọn Google Web Detection khi người dùng đồng ý |
| `POST /v1/rag/ask` | Hỏi đáp RAG có nguồn |
| `POST /v1/maintenance/backup` | Backup database |
| `GET /v1/learners/{name}/export` | Xuất hồ sơ JSON |

Khi đặt `TUTOR_API_TOKEN`, client gửi kèm header `X-API-Token`.

## Cấu hình

Mọi giá trị đọc từ biến môi trường; danh sách đầy đủ có chú thích nằm trong
[`.env.example`](../.env.example). Ví dụ chạy cho server nội bộ:

```powershell
$env:API_HOST = "0.0.0.0"
$env:TUTOR_API_TOKEN = "thay-bang-token-dai-ngau-nhien"
$env:TUTOR_AUTH_REQUIRED = "true"
.\.venv\Scripts\python.exe run_all.py
```

Ollama chỉ nên nghe trên `127.0.0.1`; không mở cổng của nó ra Internet. Khi đưa lên
server, chỉ public FastAPI qua HTTPS/reverse proxy. Android trong cùng mạng dùng IP LAN
của máy chạy FastAPI.

## Đăng nhập Google

Callback khai báo tại Google Cloud:

```text
http://127.0.0.1:8000/v1/auth/oauth/google/callback
```

Chạy `.\scripts\setup_google_oauth.ps1`: script hỏi Client Secret ở chế độ ẩn và lưu vào
biến môi trường người dùng Windows. Không ghi secret vào mã nguồn hay `.env` đã commit.

## Dữ liệu cục bộ

Không nằm trong git; được tạo khi chạy.

```text
data/english_tutor.db      hồ sơ, bài tập, metadata tài liệu (SQLite)
data/documents/            bản tài liệu đã nhập
data/qdrant/               vector database
data/postgres-account-db/  cụm PostgreSQL tài khoản
backups/                   bản sao SQLite
exports/                   hồ sơ JSON
```

Mật khẩu chỉ nằm trong PostgreSQL dưới dạng băm Argon2id; SQLite giữ nội dung học.
