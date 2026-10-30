# Flow: dùng ảnh 1K khi tải 2K không thành công

Theo yêu cầu người dùng, không dừng video chỉ vì không nâng/tải được 2K. Adapter chờ tải 2K tối đa 30 giây, sau đó mở lại menu của đúng `media_id` và tải 1K một lần. Không bấm tạo ảnh mới. Bản tải 1K hợp lệ được chuyển thành PNG và tiếp tục pipeline. Nếu tải cả 1K cũng không thành công, giữ biên nhận ảnh hiện có để tải lại thay vì tạo ảnh thay thế.

Biên nhận lưu `download_resolution_requested`, `download_fallback_reason`, kích thước/hash thực tế. Sự kiện 2K đến muộn vẫn được giữ theo cùng frame; file ở độ phân giải khác của cùng media được ghi riêng với `alternate_resolution_download_guids`. Các tải bình thường vẫn từ chối nhiều file khác nhau. Chỉ nhận file hợp lệ, không dùng ảnh thumbnail quá nhỏ và không chuyển sang một media card khác.

Kiểm tra: 32 kiểm tra Flow cũ và 6 kiểm tra tải dự phòng đều qua. Hai fixture tải cũ được cập nhật để hỗ trợ kwargs click thực tế và bật frame correlation như callback sản phẩm.

Đã restart đúng daemon lúc không có job chạy, giữ Chrome hiện có. Job `70374f8d-6cef-42bd-934f-9edb7a96a178` được tiếp tục qua API retry. Trên luồng thật, task `3d0d0def-f4a7-562b-bb33-88624658f1e0` tải thành công qua menu 1K sau timeout 2K: cùng media `c5187e70-6bb0-4057-86a3-46780df2dffb`, PNG 768×1376, giải mã và hash khớp. Pipeline đã chuyển sang tạo cảnh kế tiếp. Đây chưa phải xác nhận toàn bộ video hoàn tất.
