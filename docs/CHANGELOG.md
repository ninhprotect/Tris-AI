# Lịch sử phiên bản Tris AI

Theo thứ tự thời gian, bản mới nhất ở cuối.

- **v0.1–v0.6:** Conversation, Grammar, Vocabulary, Role Play, hồ sơ kỹ năng,
  quiz 3/5/10 câu, điều hướng theo số, cắm cờ và nộp toàn bộ một lần.
- **v0.7:** lịch sử bài, mục tiêu câu/ngày, thống kê 7 ngày, ôn lại câu sai,
  câu cắm cờ và điểm yếu.
- **v0.8:** thư viện PDF/TXT/Markdown/DOCX; ưu tiên MinerU khi đã cài, tự dùng
  PyPDF cho PDF văn bản; chia đoạn và lưu metadata vào SQLite.
- **v0.9:** embedding local bằng `nomic-embed-text`, Qdrant embedded trên máy,
  RAG giới hạn theo tài liệu đã chọn, phản hồi có trích dẫn `[S1]`, `[S2]`.
- **v1.0:** FastAPI dùng chung cho web/Kotlin, API token tùy chọn, backup SQLite,
  xuất hồ sơ JSON, cấu hình local hoặc server công ty.
- **v1.1:** đăng ký, đăng nhập, đăng xuất và đổi mật khẩu bằng PostgreSQL;
  Argon2id, session token ngẫu nhiên và chế độ bắt buộc xác thực cho mobile API.
- **v1.2:** đăng ký/đăng nhập Google OpenID Connect; backend Facebook OAuth đã
  chuẩn bị nhưng tạm ẩn; danh tính liên kết trong PostgreSQL, mã chuyển tiếp một
  lần và không lưu token truy cập; trang đăng nhập/đăng ký độc lập, composer hỗ trợ
  kéo-thả tệp/ảnh/video và bảng Cài đặt chung riêng.
- **v1.3:** giọng linh vật Tris nguyên bản chạy local bằng Piper, tiếng Việt và
  English, nút phát theo yêu cầu, cache WAV có giới hạn và REST API cho Kotlin;
  OCR ảnh ưu tiên MinerU rồi tự fallback sang RapidOCR local.
- **v1.4:** hiểu nội dung ảnh như Google Lens bằng model thị giác local
  `qwen2.5vl:3b` (mô tả đối tượng, nhân vật, cảnh vật hoàn toàn trên máy);
  tìm kiếm web DuckDuckGo không cần API key với trích dẫn `[W1]`, `[W2]` kèm
  liên kết nguồn; nút 🔎 Tìm ảnh tương tự dùng chính mô tả ảnh làm từ khóa; REST
  API mở rộng với `/v1/web-search` và cờ `web_search` cho `/v1/chat`.
- **v1.5:** bản sắc linh vật Tris được khóa chặt trong Modelfile và mọi system
  prompt (không còn nhận nhầm Qwen/Alibaba); khi được hỏi ai tạo ra, Tris giới
  thiệu Tris AI do **Nguyễn Hải Hà Ninh** phát triển; tạo ảnh, GIF và video
  ngắn hoàn toàn local bằng `sd-turbo` trong `runtime/imagegen` (nút 🎨 trong
  khung chat và REST API `/v1/media-generate`); tối ưu tốc độ với
  `OLLAMA_KEEP_ALIVE=30m` để model không phải nạp lại giữa các lượt chat.
- **v1.6:** không chạy ngầm nữa. Đóng tab trình duyệt cuối cùng (hoặc F5 rồi
  không mở lại) là toàn bộ app web + API tự tắt sau 120 giây
  (`TUTOR_SHUTDOWN_GRACE_SECONDS`) và xả VRAM của Ollama, phù hợp máy cũ.
- **v1.7:** nhập giọng nói không còn phụ thuộc Web Speech của Brave. Trình duyệt
  chỉ ghi âm bằng `MediaRecorder`, hiển thị mức tín hiệu/thời lượng rồi gửi bản
  ghi giới hạn về faster-whisper local; tự nhận tiếng Việt/English, giữ model
  `small` trong RAM và không gửi audio ra Internet.
- **v1.8:** trò chuyện được ngay trong lúc Tris đang tạo nội dung. Mọi tác vụ
  (ảnh/GIF/video, hội thoại) đều mở đầu bằng một câu xác nhận có ngữ cảnh
  ("Mình sẽ tạo ảnh từ mô tả của bạn bằng bộ sinh ảnh local sd-turbo…"), kèm
  tiến trình thật do chính subprocess sinh ảnh báo về: mô tả đã chuẩn bị,
  đang nạp model vào GPU, từng bước khử nhiễu 1/4, từng khung 2/6 — không có
  phần trăm bịa. Ô chat không khóa khi bận: tin nhắn mới được xếp hàng
  (`follow_up`), Tris xác nhận ngay "Đã nhận yêu cầu mới — tác vụ hiện tại
  không bị ảnh hưởng" và tự trả lời ngay sau khi lượt hiện tại xong. Gợi ý
  nhanh theo ngữ cảnh (Sáng màu hơn · Tông điện ảnh · Thêm chi tiết nền khi
  tạo ảnh; Ngắn gọn hơn · Cho ví dụ · Dễ hiểu hơn khi chat) và hành động sau
  hoàn thành (Tạo biến thể · Sáng màu hơn · Chỉnh mô tả) đều là hành vi thật.
  Nút dừng hủy lượt hiện tại và xóa hàng đợi; lỗi giữ lại yêu cầu để thử lại.
  Animation tiết chế, tôn trọng `prefers-reduced-motion`; trạng thái có
  `role="status"`/`aria-live` cho trình đọc màn hình. Giới hạn đúng khả năng
  backend: không sửa nội dung tác vụ đang chạy giữa chừng (diffusion đã nhận
  prompt cố định — yêu cầu chỉnh sửa sẽ tạo phiên bản mới sau khi xong);
  follow-up chờ lượt GPU vì bộ sinh ảnh và Ollama dùng chung VRAM 6 GB.
- **v1.9:** đối chiếu hai model chống bịa. Trong menu model có nút
  "Đối chiếu hai model": cùng một câu hỏi được gửi tuần tự cho model chính và
  một model thứ hai (Tris 4b ↔ Tris 8b ↔ qwen3 nền), rồi model chính đóng vai
  trọng tài nêu điểm đồng thuận, mâu thuẫn trực tiếp và nội dung chỉ một bên
  nêu — trọng tài bị cấm thêm kiến thức ngoài hai câu trả lời và phải ghi
  "cần kiểm chứng thêm" thay vì phán xử khi không chắc. Chạy tuần tự dưới cùng
  một khóa GPU (máy 6 GB không giữ được hai model cùng lúc; trạng thái đổi
  model nói thật về việc giải phóng VRAM). Kết quả hiển thị hai cột song song
  kèm phần "Kết luận đối chiếu", lưu thành markdown nên còn nguyên sau khi
  tải lại trang. Chế độ này chưa dùng tài liệu/web; hai model nền qwen3 được
  ghi chú rõ vai trò: dựng lại bản Tris khi cần và làm chuẩn so sánh.
- **v2.0:** Tris Companion — trình đồng hành kiểu Project AIRI (moeru-ai/airi,
  MIT) thu gọn cho máy yếu, mở bằng nút ✦ ở đầu trang ứng dụng hoặc trực tiếp
  tại `/companion/`. Nhân vật "star spirit" là SVG thuần (không WebGL, không
  Live2D, không bundle): thở, chớp mắt, vẫy tay, và **mớm lời theo biên độ
  giọng thật** qua WebAudio AnalyserNode. Chat dùng đúng hợp đồng NDJSON của
  `/v1/workspace/chat`, giọng đọc dùng `/v1/speech` (Piper + OpenVoice local),
  mic dùng `/v1/workspace/transcribe` (faster-whisper local) — không thêm dịch
  vụ nào mới. Tối ưu máy yếu: giới hạn FPS 30/15/8 cho nhân vật (khi nói tự
  nâng 30), dừng toàn bộ hoạt hình khi tab ẩn, tôn trọng
  `prefers-reduced-motion`, lưu lựa chọn theo máy.
- **v2.1:** Companion thêm chế độ mèo Live2D (Tororo & Hijiki, model mẫu của
  Live2D Inc.) trên một canvas WebGL, mớm lời theo biên độ giọng TTS.
- **v2.2:** Companion nhận **model 3D của bạn (.vrm)**: kéo thả tệp `.vrm` (xuất
  từ VRoid Studio) vào sân khấu hoặc chọn qua ⚙ Tối ưu; model được lưu vào OPFS
  của trình duyệt. Nạp bằng three.js + @pixiv/three-vrm (tải sẵn trong
  `companion/lib`): thở, chớp mắt, nhìn theo con trỏ và mớm lời qua expression
  `aa`. Kèm `scripts/optimize_vrm.py` nén texture nhúng về WebP ≤1024 px.
- **v2.3:** port hệ thuật toán "sống" của airi: **lipsync** theo công thức gốc
  (volume^0.7, cap 0.7, cập nhật 40 ms + lerp 120 ms) kèm noise-gate dải giọng
  nói ~85-4000 Hz; **emotion engine** nhận cảm xúc từ câu trả lời (VN/EN +
  emoji) và tự về trạng thái thường sau 4.5 s; **nhìn theo con trỏ** kèm liếc
  ngẫu nhiên khi rảnh; idle scheduler. Cài STT đơn giản hóa bằng
  `scripts\setup_stt.ps1`.
- **v2.4:** Companion bỏ chế độ mèo Live2D (không đi lại được, nặng hơn); linh
  vật 2D SVG thành mặc định: sửa lỗi mắt khi chớp, thêm nhiều cảm xúc, tự dạo
  quanh sân khấu, kéo thả và bấm để chọc. Giọng đọc chạy song song khi chữ đang
  hiện (tách câu theo luồng), không đọc emoji/icon. Mic dùng Silero VAD lọc
  khoảng lặng và số luồng CPU theo số nhân thật.
- **v2.5:** Ollama chạy trên GPU (bản CUDA 12 cho GTX 1060), cửa sổ ngữ cảnh
  4096 token và cắt nguồn tham khảo theo ngân sách token. Tris 4b tự rà lại câu
  trả lời một lượt trước khi gửi (`TRIS_SELF_REVIEW`); bảng chọn model chỉ hiện
  Tris 4b (`TRIS_VISIBLE_MODELS`); phần giải thích luôn bằng tiếng Việt.
  Companion thêm chế độ **Tris 3D** (`tris_mascot.glb`: biểu cảm, mớm lời, LED
  đổi màu theo cảm xúc), ảnh nền sân khấu, và header `Cache-Control` để trình
  duyệt không giữ trang cũ sau khi cập nhật.
