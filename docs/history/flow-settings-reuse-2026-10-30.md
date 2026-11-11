# Dùng lại setting Flow của dự án

Adapter đọc trạng thái hiện tại từ nút setting của Flow trước khi thao tác. Khi Tác nhân đang tắt và setting còn Nano Banana 2.1 / 9:16 / x1, không chọn lại các tùy chọn. Điều này dùng lại setting Flow đã giữ cho dự án, kể cả sau khi adapter khởi động lại, và tránh một biến cache chung bị nhầm giữa các dự án.

Nếu setting khác hoặc mất thì thiết lập lại bằng luồng cũ. Nếu người gọi yêu cầu chi phí 0 và chưa thấy dòng ước tính, có thể mở bảng để đọc giá nhưng không bấm lại các lựa chọn đã đúng. Kiểm tra draft, native Character, chi phí và Tác nhân trước Submit vẫn giữ nguyên.

42 kiểm tra qua: 4 tình huống dùng lại setting, 32 Flow cũ, 6 tải dự phòng. Sau khi người dùng xác nhận video đã xong và yêu cầu áp dụng, DB xác nhận job `70374f8d-6cef-42bd-934f-9edb7a96a178` hoàn tất tại `verify`, không còn job hoạt động. Đã nạp bản mới bằng `powershell -NoProfile -File scripts/start_browser.ps1 -RestartOwnDaemon -ServiceOnly`; PID daemon đổi 32480 → 38520, API xác nhận `service=videostudio-dedicated-cdp`, `ok=true`. Áp dụng cho các lượt tiếp theo; video vừa hoàn tất dùng bản trước tối ưu này. Chưa xác nhận tối ưu setting trên một lượt tạo ảnh thật mới.
