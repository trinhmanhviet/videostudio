# Mở VideoStudio sau khi restart máy

Để tự đăng nhập Google bằng đúng profile Chrome riêng, bấm đúp `Chrome - Clean.cmd` trong thư mục dự án. Đăng nhập xong bấm `Chrome - Debug.cmd` để dùng Flow; `Chrome - Stop.cmd` để tắt Chrome riêng. Các file này dùng được ngay cả khi server Studio chưa chạy. Trong Studio cũng có ba nút tương ứng ở cụm **Chrome riêng · Google Flow**. [Chi tiết](browser-profile-controls-2026-10-30.md).

Bấm đúp **`D:\Projects\videostudio\Start VideoStudio.cmd`**.

File này chạy bộ khởi động PowerShell để:

1. Mở server VideoStudio bằng extension bridge, hoặc dùng lại server cùng chế độ đang chạy.
2. Mở/kết nối Chrome riêng dành cho Flow qua launcher hiện có.
3. Kiểm tra ComfyUI. Nếu đã sẵn sàng thì dùng lại; nếu script trong `shell:startup` đang mở ComfyUI thì chờ tối đa 3 phút; nếu chưa có tiến trình thì chạy `start_comfy_recovery.py` hiện có. Không đóng, restart hay mở thêm bản ComfyUI khi đã thấy tiến trình.
4. Mở `http://localhost:8877/` trong Chrome thường.

Giữ tab Studio mở. Nếu nút nổi chưa kết nối, bấm **Start**, rồi **Test chữ**. Việc đăng nhập ChatGPT/Google vẫn cần người dùng khi phiên đăng nhập hết hạn. Bộ khởi động không tự tạo video, gửi prompt, tải mô hình hay thay đổi extension.

Chế độ Flow 10 ảnh/đợt đã kiểm tra trên máy này được nạp từ `data\flow-batch-acceptance.json`; mở lại hệ thống vẫn có lựa chọn 10 ảnh, không cần tự đặt biến môi trường. Các mức 20/30 vẫn khóa.

Bấm chạy lại cũng dùng lại dịch vụ hiện tại. Khi đang có một cửa sổ khởi động, lần bấm thứ hai thoát để tránh mở trùng. Nếu phát hiện server sai chế độ hoặc cổng đang bị ứng dụng khác dùng, bộ khởi động báo lỗi và không tắt tiến trình.

Khi có lỗi, cửa sổ giữ lại để đọc. Nhật ký: `D:\Projects\videostudio\data\startup.log`, `data\server.err.log`, `data\cdp.err.log`, `data\comfy-recovery\startup.log`.

Để tiện dùng, chuột phải vào `Start VideoStudio.cmd` → **Send to → Desktop (create shortcut)**. Không cần thêm vào `shell:startup`; bấm khi muốn mở hệ thống.

Kiểm tra mô phỏng an toàn, không mở dịch vụ thật: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_start_system.ps1`. Chưa kiểm chứng bằng một lần reboot thực tế.
