# Tự khôi phục khi ChatGPT bị treo hoặc Studio không nhận câu trả lời

Trên nút nổi VideoStudio, mở đúng video rồi bấm **Khôi phục ChatGPT**.

- Tool tìm lại tab có câu trả lời. Nếu tab cũ không đọc được và đã lưu URL, tool mở lại cuộc trò chuyện đó trong nền.
- Nếu hiện **Dán URL**, sao chép địa chỉ cuộc trò chuyện ChatGPT đang có phản hồi, dán vào ô trong float rồi bấm **Thử khôi phục**. Nếu đã đóng tab, có thể mở lại từ Lịch sử Chrome.
- Nếu cần đăng nhập, bấm **Mở ChatGPT**, đăng nhập hoặc xử lý thông báo trên trang, rồi quay lại bấm **Thử khôi phục**.
- Khi nhận được phản hồi, Studio tiếp tục video. Nếu bước chữ đã timeout do mất kết nối, Studio thử tiếp tục đúng bước đó một lần. Nếu còn lỗi khác, float hướng dẫn xem thông báo và nút tiếp tục ở lịch sử tác vụ.

Không cần tạo job mới. Khôi phục chỉ đọc cuộc trò chuyện cũ; không gửi lại prompt. Những tab cũ do tool mở được dọn sau khi xác nhận đúng cuộc trò chuyện. Nếu có nhiều tab cùng yêu cầu, giữ một tab rồi thử lại.

Lần đầu cập nhật lên **extension 0.3.9**: Reload extension trong `chrome://extensions`, F5 Studio, bấm Start nếu chưa kết nối. Không cần restart server hay dừng video đang tạo giọng/ảnh. Nếu float báo tiện ích vừa tải lại thì F5 Studio.
