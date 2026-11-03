# VideoStudio TODO

- [x] **Chrome Flow cổng CDP cố định:** dùng 19223, bỏ enable-automation, xác nhận profile bằng PID/thời điểm khởi động/listener loopback. Người dùng xác nhận ngày 2026-11-03 đã tạo thành công video 8 giây qua tool. Còn nghiệm thu video dài; kết quả này không phải nghiệm thu nhánh FlowAPI request trực tiếp.

- [ ] **Flow request qua extension VideoStudio:** đã thử cả fetch trong tab và HTTP từ Python. HTTP xác thực được, tạo project được; generation vẫn bị từ chối. Nguồn JavaScript Google xác nhận SDK công khai đổi action thành `extension_hijack_detected`. 0.3.16 báo `verification_guarded`, không gửi thêm request sai action. Chưa nghiệm thu ảnh, chưa đổi provider video. Xem `FlowAPI/desktop-status-2026-11-02.md`.

- [ ] **Ref nhất quán theo từng video job, ưu tiên chạy mượt** — đã thống nhất: áp dụng cho mọi độ dài, không giới hạn 5 phút; tạo một bộ ref nhân vật/đồ vật, cố định theo job; không bắt duyệt, không chấm điểm rồi tái tạo liên tục. Ref lỗi thì dùng mô tả cố định khi Flow đã xác nhận an toàn để tiếp tục, không gửi trùng khi chưa rõ trạng thái. Giữ đường lùi về luồng hiện tại. Xử lý kẹt Send ChatGPT trước, sau đó thử trên video ngắn rồi mới mở rộng.

- [ ] Xác nhận lại lỗi composer thật “6141/6134, first diff 1591” sau bản 0.3.4. Đã sửa lỗi đọc DOM link/paragraph và surrogate khi chia chunk; chưa có DOM của đúng lần lỗi +7. Nếu tái diễn, bằng chứng bounded tự lưu `composer-diagnostic-<request>-attempt<N>.json` trong thư mục video, không bỏ guard nội dung sai.
- [x] **Bỏ giới hạn ref 5 phút:** áp dụng cho mọi độ dài hợp lệ; kịch bản nhiều chương dùng chung manifest và ID nhân vật, chương cũ được bổ sung metadata một lần mà không viết lại lời đọc. Đã kiểm tra bằng fixture; còn nghiệm thu video dài thật.
- [x] **Phục hồi tự động:** Comfy vắng mặt trước bước được mở lại; đang boot thì chờ, không mở trùng. Flow mất daemon sẽ mở lại và dùng nguyên task/request ID. Character đã gửi nhưng mất ID chỉ được nối lại khi khớp dự án, tab và prompt; thiếu bằng chứng thì giữ receipt, không tạo thay thế.
- [ ] **Nghiệm thu restart máy thật:** chạy `scripts/check_restart.ps1 -Prepare`, restart Windows, mở `VideoStudio.exe` → Mở hệ thống. Launcher tự ghi `data/restart-acceptance.json`, chỉ báo đạt khi boot đã đổi và các dịch vụ sẵn sàng. Sau đó cần một video thật để kiểm tra extension, ref và xuất thành phẩm; chưa coi test mô phỏng là nghiệm thu reboot.
- [ ] **Để sau — cài máy khác:** tách cấu hình runtime/Comfy khỏi đường dẫn của máy hiện tại.

- [ ] **Chạy video song song thật sự** — sau bản quản lý nhiều phiên. Hiện tại cho nhận nhiều video và hiển thị hàng đợi, worker/GPU vẫn tuần tự. Cần bộ điều phối tách lượt ChatGPT/network khỏi bước GPU/render, giới hạn số lượt ChatGPT đồng thời, khóa GPU dùng chung, chống nhầm request/ảnh/audio giữa các job, phục hồi sau restart và hủy một job không ảnh hưởng job khác. Chỉ mở song song sau kiểm thử ít nhất hai video đi qua đầy đủ các bước cùng lúc. Không coi việc mở nhiều tab hoặc nhận nhiều job là đã hoàn thành TODO này.

## Đã triển khai — bàn dựng tùy chọn và Workflow (EverMind / HyperFrames)

Ghi nhận ngày 2026-11-02 từ `video-tool.mp4` (clip quay workflow khoảng 55,9 giây) và ba ảnh `FB_IMG_1793509205695.jpg`, `FB_IMG_1793509269896.jpg`, `FB_IMG_1793509278355.jpg`. Ngày 2026-11-03 người dùng yêu cầu triển khai cả editor kiểu CapCut và canvas kéo/nối/cấu hình được. Đã triển khai, full test đạt và nghiệm thu browser/MP4 bằng fixture riêng. Video AI dài và reboot do người dùng nghiệm thu sau. UI mới chỉ là lựa chọn thêm, UI cũ và luồng tạo video hiện tại phải giữ nguyên. Tài liệu duy nhất: [Bàn dựng mới và Workflow](docs/editor-workflow.md), gồm hướng dẫn, thiết kế/kỹ thuật, trạng thái nghiệm thu và việc còn lại.

Thứ tự đề xuất khi quay lại:

1. [x] **Thống nhất nhóm cảnh cho video ngắn và nhiều chương.** Plan mới có `visual_grouping_version: 1`; ChatGPT tự nhóm theo nội dung/bối cảnh ngay trong lượt viết hiện có, không ép số câu/ảnh. Cảnh giữ `narration_lines` riêng để lời đọc/phụ đề dùng timing đo được; metadata câu sai được dựng lại cục bộ từ toàn bộ lời đọc cảnh. Lời đọc có sẵn chỉ gộp nhóm liền nhau có cùng ID nhóm, prompt và nhân vật; thiếu/sai thì giữ cảnh riêng. Plan/chapter cache cũ và checkpoint đã có không bị nhóm lại. Đã kiểm tra pipeline bằng WAV/ảnh tổng hợp; vẫn cần nghiệm thu nhịp chia cảnh bằng video AI thật, chưa khẳng định mức giảm số ảnh cố định.
2. [x] **Kế hoạch dựng riêng, có phiên bản và scene ID ổn định.** Ví dụ `edit_plan.json` mô tả chuyển động/crop, nhãn, điểm nhấn chữ, transition, SFX và đoạn nhạc cho từng cảnh. Chỉnh phần dựng chỉ render lại phần cần thiết, tái sử dụng ảnh, lời đọc và nhạc hợp lệ. Hash kế hoạch dựng phải tham gia cache để không dùng nhầm clip cũ.
3. [x] **Preset phong cách có thể tái sử dụng.** Khởi đầu bằng lịch sử/tài liệu, giải thích khoa học và kể chuyện đời sống. Mỗi preset quy định font, màu, vùng phụ đề an toàn, chuyển động và nhịp chuyển cảnh. Nhãn/từ khóa/mốc thời gian lấy từ kịch bản; nhấn cụm từ theo cue đã đo, không giả định có timing chính xác từng từ. Một ảnh có thể kết hợp pan nhẹ và các lớp nhãn để tạo nhịp mà không xin thêm ảnh AI.
4. [x] **Nhạc theo phần/chương, SFX có chọn lọc.** Đổi mood khi nội dung chuyển phần, crossfade và giữ lời đọc rõ. Tránh bắt buộc sinh một đoạn nhạc cho từng câu/cảnh nhỏ. Thư viện SFX có metadata nguồn; gắn vào điểm nhấn/chuyển đoạn thay vì rải dày toàn video.
5. [x] **Timeline đơn giản trong editor.** Hiển thị quan hệ giữa cảnh, ảnh và nguồn Flow/Comfy, bộ ref, lời đọc/phụ đề, nhạc và hiệu ứng. Cho sửa từng phần và preview trước khi xuất; giao diện chính vẫn thuận tiện cho quy trình tự động.

6. [x] **Workflow canvas có thể dùng thật.** Có graph/API/compiler, kéo/nối/config, templates/JSON/save/run; đã nghiệm thu browser và job nhận đúng settings qua API admission hiện hành. Các node chỉ dùng provider đã tích hợp và dependency thực của pipeline, không giả có mọi model trong ảnh tham khảo.

Các mục 2–6 đã có code, full 619 Python + 139 JavaScript test đạt; hai lượt export MP4 tổng hợp hoàn tất từ UI, cùng kiểm tra workflow kéo/nối/clone/JSON/Run. Không coi fixture là nghiệm thu video AI dài/reboot hoặc mọi provider/account thật.

Ràng buộc: ưu tiên tool chạy mượt; UI cũ không tự bị opt-in, không tự nhóm lại scene ID hoặc thay checkpoint của job đang chạy/đã hoàn tất. Hiệu ứng tự động tùy chọn lỗi có thể dùng bộ dựng hiện hành và ghi cảnh báo; bản xuất manual đóng băng không được âm thầm đổi sang kiểu dựng khác. Canvas node được làm theo yêu cầu mới; chuỗi nhiều LLM tự do và video song song thật vẫn để sau.
