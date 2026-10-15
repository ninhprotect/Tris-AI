# Tris AI — sửa xử lý yêu cầu và chất lượng trả lời (19/09/2026)

Đây là thay đổi mã điều phối, hướng dẫn và kiểm thử; **không huấn luyện/fine-tune trọng số**, không tải model mới. Giọng EN/VI đã được người dùng duyệt giữ nguyên.

## Lỗi có bằng chứng

- `identity_answer()` nhận `mục đích` thành lệnh `dịch` sau khi bỏ dấu. Câu “xin chào bạn là ai / người tạo ra bạn cho mục đích gì” vì vậy bỏ qua metadata giới thiệu. Đã phân biệt hai ý, trả đủ tác giả và mục đích; không gọi model/web cho câu hỏi metadata đơn giản.
- Câu “tạo ảnh mèo cam” trước đây được đưa nguyên văn vào SD-Turbo mà chưa chuyển mô tả sang English. Nay dùng model Ollama local dịch có cấu trúc trước khi giải phóng VRAM cho diffusion, giữ chủ thể/màu sắc/style/phủ định/chữ được yêu cầu. Nếu dịch lỗi, dừng và báo lỗi; không âm thầm tạo bằng prompt tiếng Việt chưa chuẩn bị.
- Hai lần lỗi chat cũ chỉ ghi `HTTPStatusError`, không còn mã/trả lời gốc để xác định chắc nguyên nhân. **Không kết luận** do thiếu RAM, do model vision, hoặc do vừa tạo ảnh. Các cuộc gọi trực tiếp 4b và vision có `think:false` đều đã trả 200 khi kiểm tra.

## Thay đổi

- Tách tác vụ dịch khỏi prompt giới thiệu: “Translate into English: Ai tạo ra bạn?” → “Who created you?”, không trả tiểu sử Tris.
- Prompt trả lời đúng yêu cầu và các ý trong câu hỏi; cho phép hỏi học tập/lập trình/toán thông thường, không ép câu nào cũng thành bài học tiếng Anh.
- Có thông tin công cụ thật: app đọc được tài liệu đã tải và xử lý ảnh, nhưng không bịa nội dung file chưa được đưa vào ngữ cảnh. Khi thiếu file, yêu cầu đính kèm lại, không phủ nhận toàn bộ khả năng đọc tài liệu.
- Giới hạn lịch sử bằng ngân sách UTF-8 ước lượng, giữ nguyên lượt gần nhất thay vì nhồi 12×8.000 ký tự vào context 2.048 token. Không xóa tin nhắn cũ hoặc cắt câu hỏi hiện tại. Đây không phải bộ đếm token chính xác; tài liệu/đầu vào rất dài vẫn có giới hạn model.
- Lỗi Ollama phân biệt mất kết nối, timeout, thiếu bộ nhớ, thiếu model, yêu cầu bị từ chối, dữ liệu rỗng/ngắt. Retry tối đa một lần với HTTP 500/502/503/504 trước khi đã phát bất kỳ chữ nào; không retry OOM, không đổi model người dùng chọn, không lưu câu dở là hoàn chỉnh.
- Log ghi mã HTTP/mã lỗi/giai đoạn, không log prompt, token đăng nhập hoặc nguyên văn lỗi upstream. Web không kết nối có thông báo riêng; không giả vờ đã tìm kiếm thành công.
- Frontend phát hiện luồng kết thúc thiếu `done`, đóng reader khi lỗi/hủy, không coi câu trả lời dở là đã xong.
- Bộ tạo ảnh chỉ giải phóng model thực sự đang resident trong `/api/ps`, không gửi lệnh cho cả danh sách model cố định. Có giới hạn thời gian. Prompt quá giới hạn CLIP bị từ chối thay vì cắt âm thầm.
- Mỗi ảnh mới có sidecar `.png.json` (tương tự GIF/video) lưu mô tả gốc, mô tả đã dùng, tên translator và model ảnh để đối chiếu local.

## Kiểm chứng thực tế

- Đã tạo thật trên máy: `data/generated/tris_image_20260919_000102_7ae5c3e5.png`. Input “tạo ảnh mèo cam” → prepared prompt “An orange cat”. Mở ảnh kiểm tra: một khuôn mặt mèo lông cam/vằn, không còn cảnh đường phố. Tổng lượt đo khoảng 20,52 giây, không cam kết mọi ảnh đều cùng tốc độ/độ chính xác.
- Bộ `tests/quality_cases.json` có 7 ca thử tổng hợp: câu trong screenshot, dịch có “mục đích”, sửa *She go*, 12×8, nhớ xe đạp đỏ từ lịch sử, PDF chưa có, dịch câu hỏi tác giả. Đã chạy bằng model thật `english-tutor-local:4b` qua route workspace với database/tài khoản test tạm, không ghi dữ liệu tài khoản thật.
- Báo cáo sau chỉnh: `data/quality-report-20260918-171021-786824Z.json` (tên theo UTC), 7/7 qua và đã đọc thủ công các câu trả lời. Kết quả trước đó cũng giữ nguyên: phát hiện lỗi dịch câu hỏi tác giả và phủ nhận khả năng đọc file, đã sửa rồi thử lại. Checker được chuẩn hóa Markdown và thêm từ “reattach/resend” để không đánh trượt cách diễn đạt hợp lệ.
- 164 unit/API/service tests qua; TypeScript/Vite build qua; 6 kiểm tra kết thúc stream, 6 kiểm tra ngôn ngữ giọng, 73 UI workspace và 11 media UI qua. Những ca mô phỏng lỗi không dùng GPU/model thật.
- 7 ca từ khóa **không phải điểm trí thông minh tổng quát** và không chứng minh mọi câu hỏi sẽ đúng. File test độc lập với dữ liệu học của người dùng.

Chạy lại khi máy không bận tác vụ model khác:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\evaluate_chat_quality.py --list
.\.venv\Scripts\python.exe -X utf8 scripts\evaluate_chat_quality.py --run --model english-tutor-local:4b
```

## Giới hạn còn lại

- Model hiện tại vẫn có thể suy luận sai; chưa có dataset fine-tune và bộ đánh giá tổng quát cho một đợt huấn luyện mới.
- SD-Turbo có giới hạn bám mô tả, chữ, số lượng và phủ định. Việc dịch đúng không bảo đảm mọi chi tiết ảnh đúng. [Model card SD-Turbo](https://huggingface.co/stabilityai/sd-turbo) nêu giới hạn và không hỗ trợ negative prompt/CFG như model thông thường.
- Tiếng Việt không dấu mơ hồ, không có lệnh tạo hoặc dấu hiệu tiếng Việt (ví dụ mô tả trần “hoa sen hong”), có thể bị coi là English. Nên dùng tiếng Việt có dấu hoặc English rõ ràng.
- Khóa workspace không bao phủ toàn bộ endpoint legacy/quiz/vision; tránh gọi nhiều tác vụ GPU nặng cùng lúc trên 6 GB. CPU vẫn xử lý web/Piper và các phần nhẹ.
- Snapshot: `backups/chat-quality-20260918-235935/` và `backups/image-prompt-20260918-235649/`. Giữ nguyên ảnh cũ, MP3 nguồn, model, lịch sử và tài khoản. Chỉ khởi động lại backend web để nạp thay đổi; dịch vụ giọng không bị khởi động lại.

Web vẫn ở http://127.0.0.1:7860. Nhấn Ctrl+F5 để nạp frontend mới; các câu trả lời lỗi trong lịch sử cũ không bị sửa/xóa.
