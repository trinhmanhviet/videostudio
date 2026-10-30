# Tự mở/tắt Chrome riêng, cùng một profile

Người dùng đã chọn: **Sạch = Chrome bình thường để đăng nhập Google; Debug = cho tool điều khiển Flow**. Cả hai dùng nguyên `D:\Projects\videostudio\data\chrome-profile`, không xóa tài khoản/cookie/dữ liệu.

Trên trang chính Studio có cụm **Chrome riêng · Google Flow**, luôn hiện kể cả khi tạo chữ bằng extension bridge:

- **Mở sạch**: đóng đúng Chrome riêng đang chạy nếu cần rồi mở Chrome bình thường vào trang thêm tài khoản Google. Không có remote debugging hoặc `--enable-automation`.
- **Mở debug**: đổi sang Chrome với cổng debug chỉ trên loopback để tool điều khiển Flow; giữ cùng profile đã đăng nhập. Chế độ này có cờ automation cần cho việc xác nhận đúng profile qua CDP.
- **Tắt Chrome riêng**: đóng đúng profile này. Không đóng Chrome thường.

Đổi chế độ sẽ đóng cửa sổ Chrome riêng hiện tại. Khi có video/tác vụ ảnh đang chạy thì không tắt/đổi chế độ. Đang mở sạch, yêu cầu tạo ảnh Flow/ChatGPT bị chặn trước khi tạo job, với hướng dẫn bấm **Mở debug**. Tạo job và đổi mode dùng cùng khóa để tránh tạo video đúng lúc đóng trình duyệt. Luồng tự mở Chrome của daemon không âm thầm dùng lại hoặc thay thế cửa sổ sạch đang đăng nhập.

Không cần mở Studio/server để dùng ba file bấm đúp ở thư mục dự án: **Chrome - Clean.cmd**, **Chrome - Debug.cmd**, **Chrome - Stop.cmd**. CLI vẫn kiểm tra job đang hoạt động và dùng cùng controller/profile. Để đăng nhập, dùng Clean; đăng nhập xong dùng Debug để làm video.

Controller xác nhận đường dẫn Chrome, đúng một cờ user-data-dir trỏ vào profile riêng, PID và thời điểm tạo tiến trình. Tắt ưu tiên đóng cửa sổ bình thường; nếu không thoát sau 8 giây thì xác nhận lại danh tính tiến trình trước khi dừng đúng PID. Không kill theo tên chrome.exe, không xóa/move profile, không copy cookie từ Chrome thường. API có kiểm tra Host loopback và Origin như điều khiển trình duyệt cũ.

Kiểm tra: 41 test Python về API/browser/backend qua; 4 kiểm tra UI giả lập qua ở chiều rộng 390px. Thử thực tế Windows trên một profile headless riêng qua cả clean → debug → stop, xác nhận không mở cổng debug ở clean, không tạo bản trùng và profile đăng nhập thật giữ nguyên PID/trạng thái. Không thử đăng nhập tài khoản Google thay người dùng và không đảm bảo Google chấp nhận mọi tài khoản.

Đã cập nhật backend và daemon lúc không có job hoạt động, giữ nguyên Chrome đang mở. Kiểm tra trang Studio thật qua một Chromium headless riêng xác nhận đủ nút **Kiểm tra Chrome / Mở sạch / Mở debug / Tắt Chrome riêng**, API profile trả 200. Tại thời điểm kiểm tra, cửa sổ thật vẫn ở `debug`; chưa tự đổi sang sạch để tránh ngắt thao tác đăng nhập đang diễn ra. Người dùng có thể bấm Clean.cmd hoặc nút Mở sạch. Không cần reload extension cho phần điều khiển này.
