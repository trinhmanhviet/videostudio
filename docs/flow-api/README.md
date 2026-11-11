# Flow request bridge cho VideoStudio

Đây là đường thử nghiệm **gửi request qua phiên Flow trong Chrome**, tích hợp vào extension VideoStudio hiện có. Không cần cài extension thứ hai, không dùng `cookie.txt`, không mở profile riêng và không cần bật cổng debug cho đường request.

Luồng tạo video hiện tại vẫn dùng provider Flow cũ. Bridge mới chưa được tự động chọn cho job thật: tạo ảnh bằng request còn cần nghiệm thu trên tài khoản đang đăng nhập.

## Mở và kết nối

1. Chạy `Start Flow Request.cmd` trong `app\launch`. Mở **http://localhost:8878/flow-request**. Dịch vụ thử dùng cổng 8878, không restart Studio/Flow daemon hay job đang chạy.
2. Trong `chrome://extensions`, **Reload extension VideoStudio đang dùng**, nguồn `extensions/videostudio-chatgpt`. Bản thử hiện tại là 0.3.16. Nếu profile Chrome đang mở Flow chưa có VideoStudio thì Load unpacked cùng thư mục đó trong profile này; không cài thêm một extension Flow khác. ChatGPT giữ nguyên quyền và giao thức cũ.
3. Mở Flow, đăng nhập và bấm icon **VideoStudio** trên thanh công cụ Chrome. Chọn “Flow request lab · 8878”.
4. Trên trang thử bấm **Lấy mã kết nối**; nhập mã vào popup rồi bấm **Kết nối / Tiếp tục**. Chrome hỏi quyền Flow/scripting một lần khi bật tính năng này. Quyền này là tùy chọn, không bắt buộc với người chỉ dùng ChatGPT.
5. Nếu chưa đọc được phiên, chờ Flow phát request. Sau khi các tác vụ cũ đã dừng, có thể F5 Flow một lần. Không reload tab Flow đang tạo ảnh cho video.
6. Chọn **Liệt kê dự án** rồi **Gửi request** trước. Với thao tác trong dự án, giữ tab Flow đã chọn ở đúng Project ID. Bấm tên dự án trong kết quả để điền ID, sau đó mở dự án đó trong Flow.
7. Muốn thử tạo ảnh: chọn **Tạo x1 ảnh bằng request**, nhập prompt, đánh dấu xác nhận và gửi. Tham chiếu có dạng `[{"character_id":"UUID", "name":"Tên"}]`. Để tạo portrait, điền thêm Character ID đích. Mỗi lệnh luôn tạo x1; không có lệnh tạo hàng loạt tự động trong trang thử.

Sau khi backend Studio được cập nhật bằng lần restart bình thường, cũng có thể dùng **http://localhost:8877/flow-request** và chọn “VideoStudio · 8877” trong popup. Hai cổng dùng cùng kho biên nhận trong `data/flow-request.sqlite3` nếu chạy từ cùng bản source mặc định.

Các lần sau không cần lấy mã mới: popup giữ kết nối. Sau khi ngừng nhận lệnh, để trống mã và bấm **Kết nối / Tiếp tục**. Nút **Kiểm tra** chỉ đồng bộ/đọc biên nhận, không tạo lại ảnh.

## Đã làm

- Codec cho liệt kê/tạo project, đọc/tạo/đổi tên Character, tạo ảnh cảnh hoặc portrait, có hoặc không có Character reference.
- Probe chỉ đọc trên phiên Flow thật ngày 02/11/2026: RPC liệt kê dự án trả HTTP 200, đúng RPC, đọc được 21 dự án. Probe dùng kết nối debug đang có để chạy `fetch` cùng origin; chưa phải nghiệm thu extension mới từ đầu đến cuối, không tạo ảnh hoặc điều khiển UI.
- Sửa cách đọc response lồng nhau. Đã đọc được 16 response thuộc sáu thao tác trong HAR bàn giao, gồm 5/5 kết quả ảnh với ID, URL và kích thước. HAR này là bằng chứng về định dạng response đã ghi; không chứng minh request thủ công hiện được Flow chấp nhận.
- Cookie và CSRF/session giữ trong Chrome. Quan sát `at`, `f.sid`, build và ngôn ngữ của request cùng origin. Generation thử gọi SDK Google đã có trên trang; giá trị xác minh chỉ dùng trong lần gửi đó và không lưu vào journal hay xuất về Python. Không tự tính `at` từ SAPISID.
- Seed và các UUID generation ổn định theo request ID. SQLite ghi trạng thái trước khi giao lệnh; extension ghi journal trước `fetch`. Restart/mất callback không đưa lệnh đã giao trở lại hàng đợi.
- Phân biệt HTTP lỗi, lỗi RPC trong HTTP 200, sai schema, thiếu callback và kết quả thành công. Callback đến muộn vẫn có thể hoàn tất cùng request; không tự gửi prompt thay thế.
- Request tạo ảnh có timeout 90 giây, request đọc 20 giây. Năm request tạo ảnh trong HAR mất khoảng 20,7–25,5 giây; không dùng timeout 20 giây cho bước tạo ảnh.
- Chỉ gọi sáu RPC cố định, trên đúng origin Flow và đúng project đang chọn. Ghép nối bằng mã dùng một lần, khóa riêng của extension và kiểm tra origin/Host loopback.

## Giới hạn còn phải nghiệm thu

**Extension không tự bảo đảm request tạo ảnh được Flow chấp nhận.** Bản bàn giao và thử nghiệm thật đều ghi nhận `PUBLIC_ERROR_UNUSUAL_ACTIVITY` khi gọi RPC thủ công. Lượt thử sau khi bổ sung SDK có sẵn và hai trường xác minh vẫn bị từ chối. 0.3.14 có cờ chỉ đọc `verification_guard_detected` để báo SDK hiện hành mang dấu hiệu lớp kiểm tra extension. Việc này chưa giải quyết generation trực tiếp; xem [phân tích G-Labs bổ sung](g-labs-research.md).

Bridge chưa có bước tải ảnh 1K/2K qua extension; hiện trả URL ảnh đã gắn đúng request để mở/kiểm tra. Chưa tích hợp reference lifecycle, batch và Comfy fallback vào provider request. Chưa thay provider của các video hiện có.

**Nghiệm thu thật 02/11/2026:** tạo project và Character qua extension thành công; request portrait, ảnh có ref và ảnh không ref đều trả `PUBLIC_ERROR_UNUSUAL_ACTIVITY`. Nút gốc Flow trên cùng Character đã tạo và tải được portrait đối chứng. Xem [báo cáo và biên nhận](acceptance-2026-11-02.md). Vì vậy bridge mới chưa đạt yêu cầu thay đường tạo ảnh hiện hành.

Tiêu chí trước khi chuyển production: request liệt kê dự án thật thành công; tạo một ảnh không ref và một ảnh có ref được Flow chấp nhận; tải đúng ảnh; thử mất kết nối rồi đối chiếu cùng ID; sau đó mới nối vào provider sau một cờ lựa chọn, giữ đường cũ để quay lại.

## Dùng từ Python

### Nhánh thử HTTP desktop

`desktop.py` là client **Python tự gửi HTTP**, dùng cookie do người dùng export vào file local, lấy build/session/CSRF mới từ Flow thay vì dùng lại các giá trị trong HAR. Có journal riêng `data/flow-desktop.sqlite3`; một request ghi đã gửi sẽ không tự gửi lại khi mất phản hồi. Cookie và giá trị xác minh không được lưu trong journal.

Kiểm tra xác thực chỉ đọc, trước khi thử generation:

```powershell
C:\Python312\python.exe app/scripts/dev/probe_flow_desktop.py --project-id bf624dbc-42a2-4aa6-94a8-4765058c9734
```

Kết quả phải có `ready:true` và `test_project_found:true` cho project thuộc đúng tài khoản. Sau khi cập nhật đủ cookie, HTTP desktop đã đọc được 11 project và tạo project test riêng trong tài khoản Chrome thường. Project test cũ thuộc phiên Chrome riêng không dùng cho lượt HTTP này.

`DesktopFlowClient.submit(..., verification_provider=...)` đã nối với bộ xác minh qua extension. Dữ liệu bàn giao chỉ giữ trong RAM 90 giây, cần khóa riêng và chỉ đọc một lần; không lưu nó trong SQLite/chrome.storage/sessionStorage. Lượt HTTP generation thật vẫn bị từ chối. Nguồn JavaScript do Google phục vụ cho thấy SDK công khai bị đổi action thành `extension_hijack_detected`; 0.3.16 phát hiện và báo `verification_guarded` trước khi gửi thêm generation. Xem [kết quả HTTP desktop](desktop-status-2026-11-02.md).

Runner kiểm chứng: `app/scripts/dev/accept_flow_desktop.py`. Bảy bài kiểm tra HTTP fixture cùng các bài bàn giao xác minh/restart đã đạt; không coi các bài này là bằng chứng ảnh đã tạo thành công.

### Nhánh bridge trong tab

```python
from FlowAPI.client import FlowRequestClient, FlowRequestFailure

flow = FlowRequestClient("http://localhost:8878")
receipt = flow.submit("list_projects", {})
print(flow.wait(receipt["id"]))

# Tạo ảnh thật chỉ khi người dùng chủ động xác nhận:
# receipt = flow.submit("generate_image", {
#     "project_id": "UUID", "prompt": "Mô tả cảnh", "references": []
# }, confirm_generation=True)
# result = flow.wait(receipt["id"])
```

Nếu `submit()` mất phản hồi, exception `FlowRequestFailure.request_id` chứa ID đã dùng. Gọi `flow.receipt(id)` để đối chiếu. **Không tạo ID mới để retry một lần gửi chưa rõ kết quả.**

## Cấu trúc

```mermaid
sequenceDiagram
    participant U as Trang thử / Python client
    participant B as Bridge local + SQLite
    participant E as Extension VideoStudio
    participant F as Tab Flow đã đăng nhập
    U->>B: Lệnh + request ID ổn định
    B->>B: Lưu queued
    E->>B: Poll bằng khóa đã ghép nối
    B->>B: Ghi dispatching trước khi trả lệnh
    B-->>E: Lệnh + biên nhận dispatch riêng
    E->>E: Lưu journal Chrome
    E->>F: Chạy fetch RPC cùng origin
    F-->>E: HTTP status + response
    E->>B: Kết quả gắn đúng request/dispatch
    B->>B: Parse đúng RPC; lưu completed/blocked/uncertain
    U->>B: Đọc lại cùng request ID
```

`flow_api.py`, `flow_browser.py`, `BAN_GIAO.md` là bản thử gốc để tham khảo, không phải entry point được khuyến nghị. Không chạy `flow_browser.py` để nghiệm thu bridge mới: nó có logic mở profile và giả định auth cũ.

`cookie*.txt`, `network.har`, `flow_profile/` bị loại khỏi Git. Không gửi các file này lên repository hoặc kèm báo cáo lỗi. Kho bridge và journal nằm trong `data/` hoặc storage của extension.

## Kiểm tra

```powershell
C:\Python312\python.exe -m unittest discover -s tests -p test_flow_request.py -v
node --test tests/flow-request-page.test.mjs
node --test extensions/videostudio-chatgpt/tests/bridge.test.mjs
```

Các bài kiểm tra dùng dữ liệu tổng hợp và database tạm, không gửi prompt lên tài khoản thật. Kết quả nghiên cứu Auth Helper: [g-labs-research.md](g-labs-research.md).

Kết quả hiện tại: 31 kiểm tra Python (bridge mới và hồi quy API/ChatGPT), 21 kiểm tra Node (13 Flow và 8 giao thức ChatGPT) đều đạt. Bài Chromium cô lập `scripts/test_extension_connection_e2e.cjs` cũng đạt sau khi gộp module. Việc đọc 16 response HAR và probe liệt kê dự án thật là các bằng chứng riêng; **chưa nghiệm thu tạo/tải ảnh thật qua extension mới**.
