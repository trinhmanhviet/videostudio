# VideoStudio TODO

- [ ] **Ref nhất quán theo từng video job, ưu tiên chạy mượt** — đã thống nhất: áp dụng cho mọi độ dài, không giới hạn 5 phút; tạo một bộ ref nhân vật/đồ vật, cố định theo job; không bắt duyệt, không chấm điểm rồi tái tạo liên tục. Ref lỗi thì dùng mô tả cố định khi Flow đã xác nhận an toàn để tiếp tục, không gửi trùng khi chưa rõ trạng thái. Giữ đường lùi về luồng hiện tại. Xử lý kẹt Send ChatGPT trước, sau đó thử trên video ngắn rồi mới mở rộng.

- [ ] Xác nhận lại lỗi composer thật “6141/6134, first diff 1591” sau bản 0.3.4. Đã sửa lỗi đọc DOM link/paragraph và surrogate khi chia chunk; chưa có DOM của đúng lần lỗi +7. Nếu tái diễn, bằng chứng bounded tự lưu `composer-diagnostic-<request>-attempt<N>.json` trong thư mục video, không bỏ guard nội dung sai.
- [ ] Mở rộng phục hồi Comfy khi dịch vụ đã tắt trước lúc bắt đầu bước; bản hiện tại tự phục hồi khi `/free` hoặc kiểm tra ngay sau đó làm mất kết nối. Launcher thủ công đã có và kiểm tra tránh mở trùng.

- [ ] **Chạy video song song thật sự** — sau bản quản lý nhiều phiên. Hiện tại cho nhận nhiều video và hiển thị hàng đợi, worker/GPU vẫn tuần tự. Cần bộ điều phối tách lượt ChatGPT/network khỏi bước GPU/render, giới hạn số lượt ChatGPT đồng thời, khóa GPU dùng chung, chống nhầm request/ảnh/audio giữa các job, phục hồi sau restart và hủy một job không ảnh hưởng job khác. Chỉ mở song song sau kiểm thử ít nhất hai video đi qua đầy đủ các bước cùng lúc. Không coi việc mở nhiều tab hoặc nhận nhiều job là đã hoàn thành TODO này.
