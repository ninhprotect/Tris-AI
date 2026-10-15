# Tris AI: công cụ trong chat và giọng tham chiếu

Ngày 18/09/2026. Web vẫn ở http://127.0.0.1:7860, source dự án ở ổ D.

## Cách dùng

- **Tạo ảnh:** dấu + → Tạo ảnh trong chat → nhập mô tả → gửi. Có thể gõ trực tiếp “Tạo ảnh …” hoặc “Create an image …”. Ảnh xuất hiện trong tin nhắn với nút tải xuống; lịch sử lưu đường dẫn media vào SQLite, trình duyệt tải media có xác thực. Không mở chat hay hộp nhập tạo ảnh thứ hai.
- **GIF / video:** chọn cùng menu +; dùng bộ tạo sd-turbo hiện có. Video hiện là chuỗi ảnh ở 2 fps, không phải mô hình video chuyển động chuyên dụng.
- **Dừng tạo ảnh:** dừng chờ/nhận kết quả ở UI; tiến trình tạo ảnh đã chạy sẽ kết thúc, khóa xử lý giữ tới khi hoàn tất. Không giết tiến trình GPU giữa chừng. Có timeout và khóa chỉ cho một tác vụ tạo ảnh mỗi lượt; không tải trọng số tự động.
- **Tìm ảnh tương tự:** + → Tìm ảnh tương tự → chọn ảnh → gửi. Vision mô tả trên máy, trả liên kết Google Images/Lens. Ảnh không tự gửi Google; Google Images nhận từ khóa khi bạn bấm liên kết. Lens cần bạn tự chọn upload. Đây không phải API Google Lens tự động.
- **OCR:** trong menu Chế độ học chọn Xử lý ảnh → Đọc chữ · MinerU/OCR rồi gửi ảnh.
- **Tài liệu:** Học tập & tài liệu → Thư viện → chọn tài liệu → Hỏi AI hoặc Tạo 5 câu từ tài liệu.
- **Các chức năng khác:** sidebar Công cụ; học tập/ôn câu sai/cắm cờ/mục tiêu/backup trong Học tập & tài liệu; tài khoản/đổi mật khẩu/theme/VI-EN/trạng thái giọng trong Cài đặt.

## Người phát triển và model nền

Tris AI được tạo ra và phát triển bởi **Nguyễn Hải Hà Ninh, sinh viên ngành Công nghệ thông tin tại Đại học Thủ Dầu Một**.

Thông tin tác giả là metadata của ứng dụng. Câu hỏi tác giả phổ biến đi qua `ai/identity.py` thay vì yêu cầu LLM đoán, kể cả khi lịch sử trước đó có câu phủ nhận sai. Prompt runtime và hai Modelfile được sửa để phân biệt ứng dụng Tris AI với model nền Qwen do nhóm Qwen/Alibaba phát triển. Không tuyên bố người phát triển ứng dụng đã pretrain Qwen từ đầu. Không xóa/chỉnh các tin nhắn cũ; câu trả lời mới dùng thông tin đúng. Không tải hoặc huấn luyện lại trọng số trong đợt này.

## Giọng nói

Người dùng đã xác nhận có quyền sử dụng bản thu. Script `scripts/prepare_voice_reference.py --source "D:\Tris voice" --authorized` chạy trong venv `runtime/xtts`:

1. Đọc 41 MP3 chỉ đọc, đo độ dài/clipping, bỏ đoạn không đủ điều kiện.
2. Tạo 6 WAV tham chiếu tổng 23,27 giây (mono 22.05 kHz, cắt im lặng đầu/cuối, chuẩn hóa mức âm; không đổi pitch).
3. OpenVoice trích đặc trưng từng mẫu rồi lấy trung bình; các WAV này chỉ làm conditioning, không được ghép vào âm thanh trả cho người học.
4. Piper tạo câu mới từ văn bản → OpenVoice chuyển tone color → WAV mới. Tiếng Việt và English được thử với câu mới không có trong MP3.

Đây là chuyển đặc trưng giọng zero-shot, **không phải một đợt train model mới, không cam kết giống 100%**. Chưa có đánh giá nghe từ người dùng; test định dạng/đầu ra không chứng minh độ giống giọng. Công nghệ và giới hạn tham khảo [OpenVoice](https://github.com/myshell-ai/OpenVoice), [OpenVoice Q&A](https://github.com/myshell-ai/OpenVoice/blob/main/docs/QA.md). Runtime tạo ảnh chỉ dùng model đã cache theo cơ chế [Diffusers local loading](https://huggingface.co/docs/diffusers/using-diffusers/loading).

Manifest có tên file/hash nguồn ở `runtime/xtts/references/manifest.json`. Cache TTS có hash của phiên bản tham chiếu: đổi mẫu không dùng nhầm cache giọng cũ. Nếu chuyển giọng lỗi, báo lỗi chứ không âm thầm phát giọng Piper khác. Loa chỉ phát sau click. Cài đặt → Giọng Tris hiển thị trạng thái/số mẫu.

Mẫu kiểm tra tổng hợp mới:

- `data/voice-previews/tris-authorized-reference-en.wav`: “Hello Ninh. This is a newly synthesized sentence for Tris AI.”
- `data/voice-previews/tris-authorized-reference-vi.wav`: “Xin chào Ninh. Tris sẽ cùng bạn học tiếng Anh hôm nay.”

Đã đối chiếu SHA-256: **0/41 MP3 nguồn bị thay đổi**. Snapshot mã nguồn và speaker_ref cũ: `backups/chat-media-voice-20260918-230407/`. Không xóa file gốc/model/dữ liệu tài khoản.

## Kiểm thử

- 119 unit/API/service tests qua, gồm định tuyến tác giả, tạo ảnh và không tự thay giọng.
- 73 assertions shell, 23 study và 11 media UI: cùng composer, ảnh có auth, tải xuống, không autoplay, lưu sau reload, mobile không tràn. Browser fixtures độc lập, không tạo account giả trên production.
- sd-turbo thật tạo PNG 512×512 trong 52 giây trên máy; đây là một lần đo, không phải cam kết tốc độ.
- Bộ chuyển giọng thực tế tạo WAV mới EN 3,94 giây và VI 2,55 giây, `/health` báo OpenVoice V2 với 6 references, không lỗi.
- Smoke test Ollama thật vẫn trả lời, lưu vào SQLite tạm; không sửa lịch sử học thật.
- Chưa kiểm lại Google login với tài khoản thật hoặc mọi nội dung OCR/video. Tệp GIF/video dùng engine cũ; đợt này chỉ chạy tạo PNG thật.

Sau chỉnh frontend: `scripts/build_workspace.ps1`, Ctrl+F5. Sau chỉnh backend: khởi động lại `start_tris_ai.bat`. Cả web 7860 và API 8000 dùng cùng một backend.

## Bản chỉnh giới thiệu, tiếng Anh và GTX 1060 — 18/09/2026

- Giới thiệu / hỏi tác giả: trả lời trực tiếp **Nguyễn Hải Hà Ninh là người tạo ra và phát triển Tris AI**, sinh viên CNTT Đại học Thủ Dầu Một. Không tự thêm tên công ty/đội ngũ khác hoặc đoạn giải thích model nền. Chỉ câu hỏi kỹ thuật trực tiếp về model nền mới giải thích Qwen/Ollama; không thay lịch sử cũ, trọng số hoặc thông tin giấy phép.
- English có preset riêng: Piper `length_scale=1.40`, pitch `1.0`, tempo `0.95`. Bỏ nâng cao độ trước chuyển giọng; cache tiếng Anh mới theo preset và hash tham chiếu. Câu mẫu cũ 3,94 giây → bản mới 5,00 giây. Chọn 6 clip hội thoại tham chiếu riêng, tổng 16,09 giây, trong `runtime/xtts/references_en/`. Không sử dụng 2 đoạn dài có tên giống lời hát trong bộ tham chiếu tiếng Anh mới. Chưa có đánh giá nghe chủ quan của người dùng; đây vẫn là tone conversion, không thể xác nhận giống 100% chỉ bằng kiểm thử phần mềm.
- Tiếng Việt giữ nguyên model, pitch 1.06 / tempo 0.94 / length 1.05, bộ 6 mẫu và cache v3. Hash WAV mẫu tiếng Việt và 41 MP3 nguồn được xác nhận không đổi. Chuyển thiết bị tính toán có thể tạo sai khác số học rất nhỏ ở câu tổng hợp mới.
- Sửa chọn ngôn ngữ trên nút loa: tên Việt trong câu tiếng Anh không tự làm cả câu chuyển sang bộ đọc tiếng Việt. Văn bản trộn nhiều ngôn ngữ vẫn chọn một ngôn ngữ chính, chưa đọc luân phiên từng câu.
- `scripts/start_voice.ps1` chạy `runtime/xtts/start_clone.py`: dùng Python CUDA của imagegen, bổ sung các dependency còn thiếu từ XTTS. Hai môi trường hiện đều Python 3.12.10; không sửa package của môi trường nào, không tải lại model. Đã kiểm tra torch **2.5.1+cu121**, kiến trúc **sm_61**, GTX 1060. Tham khảo bản CUDA tương ứng tại [PyTorch previous versions](https://pytorch.org/get-started/previous-versions/). Không nâng torch mới nhất tùy tiện trên Pascal.
- Chuyển giọng chạy GPU; Piper nhẹ vẫn CPU. Sau mỗi lượt, trọng số về RAM và bộ nhớ đệm CUDA được giải phóng, chỉ còn CUDA context của tiến trình. Khi VRAM khả dụng dưới 1 GB hoặc CUDA lỗi, dùng CPU **với chính cùng model và tham chiếu**, không đổi sang giọng stock. `/health` và Cài đặt → Giọng Tris báo thiết bị xử lý; đó là thiết bị của lượt gần nhất, không phải cam kết toàn bộ ứng dụng chỉ dùng GPU.
- Đo cùng một WAV tiếng Việt 2,55 giây: CPU cũ 1,89–2,02 giây, GPU đã nạp 0,47–0,50 giây cho bước chuyển giọng. Lượt GPU nguội đầu tiên 7,10 giây; sau restart, một câu tiếng Anh mới mất 9,71 giây tổng gồm nạp Piper/OpenVoice, trong đó converter 6,00 giây. Câu preview English 8,84 giây âm thanh được tạo trong 1,28 giây khi đã nạp. Đây là mẫu đo trên máy hiện tại, không phải bảo đảm tốc độ mọi độ dài/tải máy.
- Preview nghe thử: `data/voice-previews/tris-english-v4-preview.wav`. Bản so sánh cùng câu: `tris-english-v4-comparison.wav`. Script A/B chỉ dùng khi có riêng server CPU trên 7861 và GPU thử trên 7862; hiện production 7861 đã là GPU, không cần chạy lại A/B.
- 127 unit/API/service tests và 6 kiểm tra chọn ngôn ngữ đã qua; build TypeScript/Vite, 73 kiểm tra UI và 11 media UI qua. Test mô phỏng GPU thiếu VRAM, không hỗ trợ sm_61 và lỗi CUDA để kiểm đường CPU cùng giọng.
- Snapshot trước chỉnh: `backups/identity-voice-gpu-20260918-233605/`. Không xóa file gốc hoặc dữ liệu tài khoản.
