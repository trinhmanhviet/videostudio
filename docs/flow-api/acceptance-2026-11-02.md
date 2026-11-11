# Nghiệm thu Flow request — 02/11/2026

**Kết luận: chưa đạt chuỗi tạo ảnh bằng request.** Quyền extension đã được người dùng xác nhận và cấp; tạo project/Character chạy thật qua extension thành công. Cả ba loại request tạo ảnh đều bị Google từ chối. Đối chứng bằng nút tạo gốc của Flow tạo được portrait trên cùng tài khoản, cùng dự án và cùng Character.

## Đối tượng thử cố định

- Run: `cca23b60-4de2-48e1-bce1-377f16450b2e`.
- Project: `bf624dbc-42a2-4aa6-94a8-4765058c9734`, tên `VS Request Test 2026-11-02 03:08 UTC`.
- Character: `eb1486f4-20e7-4995-b65e-f771367c5585`, tên `Minh_Botanist`.
- [Mở dự án trên Flow](https://flow.google.com/project/bf624dbc-42a2-4aa6-94a8-4765058c9734).
- Biên nhận của app: `data/flow-request.sqlite3`; manifest: `data/flow-request-acceptance/cca23b60-4de2-48e1-bce1-377f16450b2e/run.json`. Không gửi lại các ID đã có biên nhận từ chối để thử mù quáng.

## Kết quả request thật

| Bước | Request ID | Kết quả |
|---|---|---|
| Tạo project | `7292223f-afe7-550f-944b-df2608265deb` | Completed; project mở được trong Flow |
| Tạo Character | `04f946eb-0194-5310-b978-dffafe3ed1d0` | Completed; tên/ID đúng trên trang Character |
| Tạo portrait gắn Character | `e297eb51-4ab8-561e-b23c-5082bcfca636` | `PUBLIC_ERROR_UNUSUAL_ACTIVITY` |
| Tạo ảnh có ref | `a4910cc5-6b23-5977-b740-e22bf40ecb90` | `PUBLIC_ERROR_UNUSUAL_ACTIVITY` |
| Tạo ảnh không ref | `29755e9a-1add-5887-b988-9872dfca6853` | `PUBLIC_ERROR_UNUSUAL_ACTIVITY` |

Request có ref được gửi **sau khi** Character đã có portrait thật từ lượt đối chứng dưới đây. Manifest ghi rõ nguồn này là `verified_native_ui_portrait_control`; không ghi nhận portrait RPC đã thành công. Audit trong manifest đối chiếu cả `reference_ids` và `target_character_id` từ command SQLite.

## Đối chứng bằng giao diện gốc

Chỉ tạo một portrait đối chứng, không tạo lại project hoặc Character:

- Transport: `flow_native_ui`, bấm nút Generate bình thường trong trang Character.
- Nội dung: người đàn ông Việt Nam hư cấu, kính tròn, áo khoác xanh rêu, khăn vàng. Đã nhìn thấy ảnh khớp trên trang Character.
- Media ID từ hộp lưu ảnh: `5dd8443f-1563-49c0-94b7-b2d4074c71e1`.
- File: `data/flow-request-acceptance/cca23b60-4de2-48e1-bce1-377f16450b2e/portrait-ui-control.jpg`.
- JPEG đã kiểm tra bằng Pillow: **1376 × 768**.
- SHA-256: `9c730864da3333884e99d07e3badd1bc6d211ce2ed80c1ebf08bec1de65848e8`.

Ảnh đối chứng không được tính thành ảnh tạo bằng request. Chưa có hai ảnh cảnh có ref/không ref được tạo thành công bởi bridge mới.

## Sửa và phát hiện trong lượt này

Payload portrait trong HAR có phần `[batch_id, null, [character_id, [0]]]`. Chỉ `mode=3` và source path của Character là chưa đủ. Đã bổ sung binding này vào codec; bảy kiểm tra protocol đạt sau thay đổi. Server thử 8878 đã nạp bản sửa trước khi chạy request portrait thật.

Các biên nhận cho thấy bridge đã gửi/nhận được RPC trên đúng phiên Chrome. Vì nút gốc tạo được portrait còn request tự dựng bị từ chối, bước cần nghiên cứu tiếp là cơ chế chấp nhận riêng của generation; **chưa đủ bằng chứng để khẳng định chỉ thiếu một header hay một token cụ thể**. Không được đánh dấu nghiệm thu dựa trên việc có cookie, quyền extension hoặc HTTP 200.

Luồng video production vẫn giữ provider Flow hiện hành. Cần tiếp tục trên chính project/Character này, giữ ảnh đối chứng và lịch sử request để đối chiếu.

## Lượt thử bổ sung sau khi sửa bước xác minh

0.3.13 đã bổ sung lời gọi SDK Google hiện có trên trang, dùng kết quả của lần xác minh trong hai trường context của generation và gửi `X-Same-Domain: 1`. Request ảnh không ref lần 2, ID `b59e6491-993f-5ce2-b60b-031963ed9b1e`, vẫn bị `PUBLIC_ERROR_UNUSUAL_ACTIVITY`. Đây là kết quả thực tế sau sửa, không coi lỗi thiếu trường của 0.3.12 là toàn bộ nguyên nhân.

Sau khi đọc `docs/g-labs-flow-analysis-2026-11-02.md`, bản chẩn đoán 0.3.14 xác nhận trên tab thật rằng `verification_sdk`, `verification_key_available` và `verification_guard_detected` đều là `true`. Sự hiện diện của dấu hiệu lớp kiểm tra được ghi trong manifest; vẫn chưa có generation trực tiếp thành công. Xem [phân tích cập nhật](g-labs-research.md).
