# Thử HTTP desktop theo kiến trúc G-Labs

Mục tiêu của nhánh này là Python tự gửi request tới Flow; Chrome chỉ cung cấp phần xác minh khi đã nối adapter phù hợp. Generation bằng nút UI không được tính là hoàn tất nhánh này.

## Đã làm

- Đọc `docs/g-labs-flow-analysis-2026-11-02.md` và đối chiếu phần mã Auth Helper.
- Viết `FlowAPI/desktop.py`: tải cookie từ file local giữ domain/path, bỏ mục hết hạn và domain ngoài Google/Flow; lấy bootstrap mới; gửi RPC trực tiếp bằng `httpx`.
- Dùng journal SQLite trước mỗi request ghi. Kết quả mất phản hồi giữ trạng thái chưa rõ, không tự tạo lại request sau restart. Journal không có cookie, CSRF hay giá trị xác minh.
- Có CLI chỉ đọc `scripts/probe_flow_desktop.py` để người dùng/agent kiểm tra đúng tài khoản và project trước khi gửi generation.
- Bảy bài kiểm tra HTTP fixture đạt. Đây chỉ là kiểm tra client, không phải nghiệm thu request tạo ảnh thật.

## Probe thật

1. Cookie ban đầu + session cũ trong HAR: đọc project bằng HTTP bị **401**.
2. Lấy bootstrap mới từ `https://flow.google.com/`: HTTP 200, có session ID/build, nhưng không có `SNlM0e` (CSRF đăng nhập).
3. Lặp lại bằng User-Agent trong HAR và URL đúng project thử: vẫn chưa có CSRF đăng nhập.
4. Người dùng đã cập nhật `FlowAPI/cookie.txt`. Bản mới có 17 mục, hai mục hết hạn; 15 cookie được nạp. Bản export thiếu `SID` và `HSID`. `__Secure-1PSID`, `__Secure-3PSID`, `SAPISID` có mặt. Giá trị các cookie không được in hoặc đưa vào tài liệu.

5. Sau khi người dùng cung cấp SID/HSID: HTTP desktop xác thực thành công và đọc được 11 project. Project test cũ không truy cập được vì cookie lấy từ **Chrome thường**, còn lượt thử cũ dùng **Chrome riêng**.
6. Đã tạo bằng HTTP một project mới `fcead1b4-c4e7-4dc1-b08c-105719b354ae`, request `2e455486-b9f8-5075-a4c3-ef70421dbd64`. Chrome thường mở được đúng project đó; tài khoản và project của hai phần đã khớp.
7. Extension 0.3.15 trên Chrome thường đã bàn giao một lần xác minh cho Python. Python gửi generation thật, không bấm Generate. Lượt ảnh không ref vẫn bị `PUBLIC_ERROR_UNUSUAL_ACTIVITY`; manifest: `data/flow-desktop-acceptance/cca23b60-4de2-48e1-bce1-377f16450b2e/run.json`.

## Nguyên nhân đã xác định trong nguồn do Google phục vụ

Một bundle ứng dụng công khai từ `www.gstatic.com` của build `boq_labs-ai-sandbox-frontend_20261030.00_p2` chứa đoạn thay thế `grecaptcha.enterprise.execute`. Khi cờ tính năng được bật, hàm thay thế luôn ghi đè tham số `action` bằng `extension_hijack_detected`. Client gốc giữ riêng lời gọi đã bind trước đó.

Điều này giải thích việc lời gọi công khai nhận một chuỗi token nhưng generation không chấp nhận nó như action `IMAGE_GENERATION`. Đã kiểm tra nguồn trực tiếp bằng HTTP, không qua extension, nên sự thay thế này không phải suy đoán từ riêng mã G-Labs. Bằng chứng metadata: `data/flow-desktop-acceptance/guard-origin-probe.json`.

Không lấy lại lời gọi riêng của client gốc, không vô hiệu hóa lớp bảo vệ. 0.3.16 phát hiện điều kiện này trước khi gọi SDK và báo `verification_guarded`, tránh tạo thêm token/request chắc chắn sai action.

Đã kiểm chứng API lab chặn trước hàng đợi khi metadata xác nhận guard: không dispatch bước xác minh và không gửi generation. Tab Studio đã được refresh sau cập nhật extension, khôi phục view Phóng xạ và xác nhận `extension_transport`/`production_acceptance` vẫn sẵn sàng. Backend video 8877 và provider ảnh production giữ nguyên.

## Còn lại

1. Cần một đường generation được Google hỗ trợ/chấp nhận. Nhánh HTTP hiện chưa tạo được ảnh.
2. Nếu chuyển sang Gemini API chính thức, cần người dùng chọn nhánh này, API key và hạn mức/chi phí riêng trước khi tích hợp.

Người dùng đã chọn **giữ Flow, chưa chuyển provider**. Không thêm provider/API tính phí khác trong lượt này.

Đã có client HTTP, adapter xác minh dùng một lần, phép thử thật và báo cáo lỗi. Chưa đạt nghiệm thu ảnh; không được gọi việc hoàn thành các thành phần này là generation thành công.

Không đổi provider video production và không coi ảnh portrait đối chứng trước đó là kết quả của nhánh HTTP này.
