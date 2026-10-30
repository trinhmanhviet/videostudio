# Nhận lại phản hồi từ tab ChatGPT mở lại

Nguyên nhân: connector chỉ gửi inspect đến `chatTab` đã lưu. Đóng tab cũ rồi mở cùng URL tạo một tab ID khác. Ngoài ra `chrome.tabs.sendMessage` đến renderer treo trước đây không có timeout, có thể giữ hàng đợi worker và chặn cả heartbeat/reconcile.

Extension 0.3.8 giới hạn inspect 3 giây, tìm tab cuộc trò chuyện đang mở và chỉ chuyển request sang một ứng viên duy nhất có mã request đúng. Khi đã biết URL cuộc trò chuyện, URL cũng phải khớp. Không gửi lại prompt; không tạo thêm tab để thay cho một request đã gửi mà tab mất kết nối. Lưu URL qua callback gửi, inspect đã khớp marker, và navigation của tab đã khớp request. Tìm tab không thay đổi attempt/version/scope. Các tab đang do job khác giữ bị loại.

Không thêm quyền Chrome. Bản cập nhật cần reload extension và F5 tab ChatGPT mở lại / tab Studio để content scripts mới hoạt động. Có thể phải bấm Start để nối lại đúng bridge. Nếu job đã timeout, Studio có luồng nhận reply cũ rồi retry bước chữ sau khi import thành công; không tạo job mới chỉ vì tab ID đã đổi.

94 kiểm tra Node và Chromium fixture mới đều qua. Live job được chẩn đoán: `67b0c73c-4008-4083-954d-5a9e9dc8d851`, scope `fb1d3a6e-01c3-4a0c-8df4-778ee5f129cd`, pending exchange `f77e5f2f-f45a-4974-a6b3-267bcdd30080`. Chưa import reply thật: cả CUA và node computer-use đều lỗi `failed to write kernel assets ... os error 3`; không đọc Chrome profile/session files để thay thế và không tuyên bố job đã được cứu.
