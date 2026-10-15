# Tris AI — giao diện chính tại cổng 7860

Cập nhật 18/09/2026: giao diện React/TypeScript đã thay giao diện Gradio tại **http://127.0.0.1:7860**. Đây là giao diện của hệ thống AI đang có, không phải một bản demo riêng và chưa phải ứng dụng Kotlin.

## Chạy ứng dụng

Cập nhật tiếp theo: tạo ảnh/GIF/video đã chuyển vào **cùng luồng chat**, không
mở hộp tạo ảnh riêng. Mục Công cụ gom lại các lối vào. Xem
`CHAT_MEDIA_VOICE.md` cho nhận diện người phát triển, giọng mẫu và kiểm thử mới.

Thư mục dự án: `D:\Ai building\2026-08-30\sau-x20\outputs\english-ai-tutor`.

Nhấp đúp **start_tris_ai.bat** như trước. Launcher mở các dịch vụ bằng cửa sổ ẩn, giữ cấu hình model ở ổ D, rồi mở trình duyệt tại 7860. Nó không tự tải model, không tự giết tiến trình chiếm cổng. Nếu còn backend cũ ở 7860 hoặc 8000, dừng đúng backend đó trước.

Các entrypoint `run_all.py`, `run_workspace.py`, `start_tris_workspace.bat` và cấu hình Run Tris AI Web trong VS Code đều dùng giao diện chính này. `python app.py` cũng chuyển đến host mới; chỉ đặt `TRIS_LEGACY_UI=1` khi thực sự muốn chạy mã Gradio lưu lại.

- Web: **http://127.0.0.1:7860**
- API và Google callback vẫn tại **http://127.0.0.1:8000**
- Hai cổng dùng **một app, một tiến trình backend, một event loop và cùng phiên đăng nhập**.
- OAuth callback giữ nguyên `http://127.0.0.1:8000/v1/auth/oauth/google/callback`, sau đăng nhập trả về web 7860. Khởi động lại backend cần đăng nhập lại.
- Chỉ nghe loopback; không tự mở LAN hoặc Internet.
- Khi đóng tab cuối, web/API tự dừng sau thời gian chờ 120 giây và yêu cầu Ollama nhả model. Ollama daemon, PostgreSQL và dịch vụ voice là dịch vụ riêng, không bị xóa hoặc tắt cưỡng bức. Tab mất kết nối được phát hiện qua heartbeat.

## Tích hợp dữ liệu và chức năng cũ

Danh tính lấy từ phiên đăng nhập hợp lệ và ánh xạ tới **learner_name hiện có**, không tạo namespace hồ sơ mới. Không nhận tên người học từ client để đọc dữ liệu qua route workspace.

- Chat streaming dùng các prompt Conversation, Grammar, Vocabulary, Role Play và ngữ cảnh cá nhân hóa hiện có. Lượt hoàn tất ghi vào SQLite và tiếp tục cập nhật sổ lỗi/từ vựng/kỹ năng.
- Lịch sử cũ nạp vào sidebar, tối đa 500 tin gần nhất, nhóm theo mode/tình huống vì dữ liệu cũ không có ID hội thoại. Nhóm này không khôi phục ranh giới các cuộc trò chuyện mà bản cũ chưa lưu.
- **Học tập & tài liệu**: tạo bài bằng model, câu hỏi ở giữa, bảng số bên phải, cờ, câu trước/sau, tô ô đã trả lời (chưa chấm), nộp tất cả một lần rồi xem giải thích. Bài đang làm giữ trong sessionStorage khi đóng/mở bảng.
- Ôn câu sai/cắm cờ/điểm yếu, mục tiêu ngày, lịch sử điểm và thống kê đọc từ dữ liệu cũ.
- Thư viện dùng tài liệu cũ; chọn tài liệu rồi đưa vào chat RAG. Tệp mới kéo vào chat hoặc chọn dấu +.
- Ảnh có lựa chọn Vision local hoặc MinerU/OCR trong menu chế độ học. Video chỉ lưu local, không tuyên bố đã hiểu/phiên âm.
- Dấu + có mục mở tạo ảnh/GIF/video qua dịch vụ local hiện có. Không tải trọng số tự động.
- Trong bảng học tập có ngôn ngữ phản hồi AI, tùy chọn cá nhân hóa, backup SQLite và xuất hồ sơ JSON.
- Loa chỉ phát sau khi click; giữ thời gian xử lý trên phản hồi. Micro dùng nhận dạng trình duyệt và có thể gửi âm thanh qua mạng.
- Cài đặt giao diện có VI/EN, sáng/tối/hệ thống, lịch học chỉ nhắc khi trang đang mở. Các bản nháp và thiết lập layout nằm trong localStorage, tách khóa chat theo tài khoản; token chỉ ở sessionStorage.
- Xuất JSON ở Cài đặt → Dữ liệu là backup workspace trình duyệt. **Xuất hồ sơ JSON** trong Học tập & tài liệu là dữ liệu học từ SQLite. Backup SQLite không phải backup tài khoản PostgreSQL.

Mặc định chat dùng AI thật. **Tris AI → Trải nghiệm mẫu** là chế độ tùy chọn, có nhãn Mẫu; không dùng kết quả mẫu để giả làm suy luận thật.

Giới hạn lượt đính kèm: tối đa 5 tệp / 180 MB; tài liệu 20 MB, ảnh 10 MB, video 150 MB. Backend kiểm tra kiểu, kích thước và giới hạn request trước multipart cho route workspace; ingestion xử lý tuần tự.

Mã nguồn Gradio, trọng số Ollama, PostgreSQL, SQLite và Qdrant cũ vẫn giữ tại chỗ. Snapshot các tệp thay đổi trước tích hợp:
`backups/ui-migration-20260918-220641/`.
Đây là bản sao mã nguồn/UI trước sửa, không phải bản sao đầy đủ database/model. Không có thao tác xóa dữ liệu người dùng trong đợt này.

## Build và kiểm thử

```powershell
Set-Location -LiteralPath 'D:\Ai building\2026-08-30\sau-x20\outputs\english-ai-tutor'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_workspace.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_workspace*.py' -v
.\.venv\Scripts\python.exe tests\smoke_workspace_local.py
```

Máy hiện tại sử dụng Node/pnpm có sẵn trong runtime. Máy khác cần Node 22.12+ hoặc 24 và pnpm; `build_workspace.ps1 -Install` dùng lockfile đã lưu. Sau khi sửa frontend, build rồi Ctrl+F5; khi sửa backend, khởi động lại ứng dụng.

Tại thư mục frontend, chạy `pnpm test:e2e` và `node tests/study.spec.mjs`. Các bài kiểm tra trình duyệt dùng Chrome đã cài (biến `TRIS_BROWSER` để đổi), context riêng, không chạm profile trình duyệt người dùng. `TRIS_TEST_URL` mặc định là 7860.

Ngày 18/09/2026 đã xác nhận:
- TypeScript/Vite build thành công; 19 API regression tests qua.
- 73 browser assertions cho giao diện/scroll/menu ở 320/375/390/768/1024/1440 px.
- 23 assertions cho bài tập/thư viện dùng browser fixtures, không ghi vào hồ sơ thật.
- 53 tests cho SQLite, tutor core, Study Hub và cơ chế đóng tab đều qua; test mới kiểm tra lịch sử đúng hồ sơ, thứ tự và giới hạn.
- Smoke test **model Ollama thật english-tutor-local:4b** trả lời và lưu hai tin vào database tạm; không sửa lịch sử người dùng.
- Cổng 7860 và 8000 trả cùng runtime_id; Google được cấu hình, callback vẫn ở 8000.
- Chưa đăng nhập Google bằng tài khoản thật trong đợt này; chưa chạy lại đầy đủ OCR/RAG/TTS/tạo ảnh với tệp thật. Các dịch vụ đó được nối lại, không coi kiểm tra giao diện là kiểm chứng inference của từng pipeline.

## Mã nguồn

| Tệp | Chức năng |
| --- | --- |
| workspace_host.py | Một backend dùng chung 7860 và 8000 |
| workspace_api.py | Chat NDJSON, upload, model, OAuth bridge |
| workspace_features.py | Nối dữ liệu học/bài tập/thư viện/presence |
| services/learning_records.py | Ghi hội thoại, sổ lỗi và kỹ năng |
| frontend/src/App.tsx | State, tích hợp tài khoản/hồ sơ, gửi và dừng chat |
| frontend/src/components/TutorTools.tsx | Bài tập, ôn tập, tài liệu, backup, tạo media |
| frontend/src/components/Composer.tsx | Nhập liệu, đính kèm, chọn mode/model |
| frontend/src/components/Sidebar.tsx | Sidebar và menu tài khoản |
| frontend/src/components/Panels.tsx | Cài đặt, auth, tìm kiếm, lịch học |
| scripts/start_tris_ai.ps1 | Launcher giữ model local, không diệt tiến trình tùy tiện |

Dev frontend: `pnpm dev` ở frontend (5173, proxy API 8000). Kiểm tra OAuth ở bản build 7860; URL quay lại đăng nhập không chuyển theo dev server.
