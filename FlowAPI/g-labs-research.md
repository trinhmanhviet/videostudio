# Đối chiếu G-Labs Studio — 2026-11-02

Tài liệu tổng hợp mới nhất, gồm kiến trúc, schema request, profile, journal, lỗi và toàn bộ nghiệm thu: [G-Labs / Flow analysis](../docs/g-labs-flow-analysis-2026-11-02.md). Các mục dưới là ghi chép theo từng giai đoạn nghiên cứu.

## Bổ sung sau khi đọc tài liệu G-Labs mới

Đã đối chiếu `docs/g-labs-flow-analysis-2026-11-02.md` với `page_script.js` và `_resolveWidget()` của Auth Helper 9.0.19 đang cài. Mã thực tế ưu tiên `window.__real_execute` nếu có, rồi mới dùng `grecaptcha.enterprise.execute`. Đoạn giữ `__real_execute` nằm trong interceptor từ `document_start` và loại hàm chứa `extension_hijack_detected`.

Đo chỉ đọc trên tab Flow thật bằng VideoStudio 0.3.14 cho kết quả:

```json
{"verification_sdk":true,"verification_key_available":true,"verification_guard_detected":true}
```

`verification_guard_detected` chỉ đọc biểu diễn hàm SDK hiện hành để tìm dấu hiệu đã thấy trong mã G-Labs; không sửa hay thực thi hàm, không xuất mã hàm/token/cookie. Nó xác nhận **sự hiện diện của lớp kiểm tra**, không tự chứng minh toàn bộ nguyên nhân Google từ chối.

Lượt thử 0.3.13 đã dùng API SDK sẵn có trên trang, lấy giá trị token cho từng request, gắn vào cả `payload[1][0][7][10]` và `payload[3][10]`, thêm header cùng origin `X-Same-Domain: 1`. Một request ảnh không ref trên project test vẫn nhận `PUBLIC_ERROR_UNUSUAL_ACTIVITY`. Request ID mới: `b59e6491-993f-5ce2-b60b-031963ed9b1e`. Lịch sử lần đầu được giữ trong `receipt_history`.

Vì vậy, kết luận trong tài liệu mới rằng chỉ cần token mới là đủ đang mạnh hơn bằng chứng. Phần app desktop gửi request chưa có source hoặc ghi nhận thành công trên máy này; cũng chưa xác định được endpoint, header và ngữ cảnh mà app thực sự dùng. Không được gán việc có thư viện `curl_cffi` với việc chính nó là transport đã tạo ảnh thành công.

Hướng có thể triển khai tiếp là API app giao bước generation cho client gốc của Flow, rồi thu response có định danh; metadata, project và Character vẫn có thể đi qua RPC. Hướng này phải được mô tả đúng là có bước gửi qua giao diện, không gọi nó là generation bằng HTTP trực tiếp.

### Kết quả sau đó: HTTP desktop và nguồn guard

Đã triển khai `desktop.py`, bộ bàn giao xác minh một lần và chạy thử ở cùng tài khoản Chrome thường. Python xác thực được, tạo project và gửi request generation thật. Generation vẫn bị `PUBLIC_ERROR_UNUSUAL_ACTIVITY`.

Đọc trực tiếp bundle JavaScript ứng dụng do `www.gstatic.com` phục vụ xác nhận guard ghi đè **mọi action** của lời gọi `execute` công khai thành `extension_hijack_detected` khi cờ tính năng bật. Vì vậy lớp này có nguồn từ Google, không phải chỉ suy luận từ G-Labs hoặc do G-Labs tự thêm. Bản thử 0.3.16 báo rõ `verification_guarded` trước khi gọi SDK thêm lần nữa. Chi tiết và project test: [desktop-status-2026-11-02.md](desktop-status-2026-11-02.md).

Phạm vi: chỉ đọc extension được người dùng chỉ định trong profile Chrome riêng và cấu trúc app tại `D:\Tools-AI\G-Labs Studio`. Không đọc storage/cookie đăng nhập, không chạy app, không can thiệp job/video.

## Những điều đã xác nhận từ mã cài đặt

- Extension **G-Labs Studio - Auth Helper 9.0.19**, ID `clhcjdjbcldkogahjfmcgfipmlilmkpg`.
- Service worker trao đổi với app local tại `http://127.0.0.1:18923`, qua các route `/sync/config`, `/sync/status`, `/sync/render`, `/sync/theme` và route dành cho Grok.
- Manifest có quyền `cookies`, `tabs`, `scripting`, `webRequest`, `storage`, `alarms`; chèn mã MAIN world vào Flow từ `document_start`.
- Worker đọc cấu hình app, có mã truy cập cookie và xử lý token reCAPTCHA. `content_interceptor.js` còn can thiệp `Object.defineProperty` để lưu hàm `execute`. Đây là cơ chế cụ thể của extension này, không phải bằng chứng rằng quyền extension tự làm mọi request được chấp nhận.
- Không tìm thấy `ogiZ0b` hay `batchexecute` trong `background.js`. Vì vậy **chưa xác nhận** phần tạo ảnh của app dùng chính endpoint/schema có trong `FlowAPI/network.har`; không suy diễn hai hệ thống là một.
- App có executable `G-LabsStudio.exe`, runtime Python 3.12, PySide6, `curl_cffi`, Playwright và tài nguyên UI. Thư mục `src` đang có tài nguyên/mẫu UI, chưa thấy source Python đọc được cho phía gửi request. Chưa phân tích logic bên trong executable.

## Điều áp dụng cho VideoStudio

Kiến trúc **app local ↔ extension ↔ phiên website đã đăng nhập** phù hợp. Tuy nhiên chưa có bằng chứng để hứa sao chép được toàn bộ khả năng tạo ảnh trực tiếp của G-Labs từ extension riêng lẻ.

VideoStudio triển khai bridge riêng bên trong extension hiện có, bật bằng quyền tùy chọn; giữ cookie trong Chrome, gửi RPC cùng origin, lưu biên nhận trước khi gửi và đối chiếu sau gián đoạn. Không sao chép mã/token/cookie của G-Labs, không nối VideoStudio vào cổng 18923 của app kia.

Phần cần kiểm chứng tiếp là **Flow có chấp nhận request tạo ảnh bình thường từ bridge này không**. Nếu từ chối, báo mã lỗi thật và giữ đường Flow cũ; không đánh dấu nghiệm thu chỉ dựa trên HTTP 200 hoặc “request đã phát”.

Tài liệu Chrome chính thức dùng để đối chiếu:

- [Cross-origin network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests): phân biệt request từ extension và từ content script.
- [chrome.scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting): thực thi mã trong ngữ cảnh trang theo quyền được cấp.
- [Service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle): worker có thể bị dừng; trạng thái lần gửi không được chỉ nằm trong RAM.
