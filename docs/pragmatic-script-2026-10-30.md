# Kịch bản: một lượt kiểm tra, lược chi tiết chưa rõ

Theo yêu cầu của người dùng, luồng `research` không còn sửa rồi kiểm lại nội dung đến bốn lần. Một bản nháp dùng được chỉ cần một lượt nhận xét: các cảnh có khẳng định không được nguồn hỗ trợ sẽ bị lược bỏ ngay tại máy. Nhận xét về văn phong hoặc thiếu độ chính xác của chi tiết phụ không chặn video. Prompt viết bài cũng yêu cầu bỏ chi tiết chưa rõ thay vì sáng tác hoặc khẳng định rằng hồ sơ không xác nhận nó.

Khi tiếp tục job đã lỗi, dùng bản nháp lưu gần nhất và nhận xét tương ứng. Nếu chúng đã có trên đĩa, không gửi thêm prompt để sửa/đối chiếu. Các bản nháp/nhận xét gốc giữ nguyên; `script-quality.json` ghi quyết định sau lược bỏ, `model_accepted`, chỉ số các cảnh đã bỏ và `independent_fact_verification: false`. Không đổi phản hồi từ chối gốc thành một chứng nhận kiểm chứng nguồn độc lập.

Nếu không còn cảnh dùng được hoặc phản hồi có chỉ số cảnh không hợp lệ thì báo lỗi thực, không tạo kịch bản rỗng. Các kiểm tra cấu trúc, phụ đề, âm thanh và render vẫn giữ nguyên. Luồng nguồn văn bản với trích dẫn chính xác và luồng lời đọc do người dùng cung cấp không đổi.

Job `8085d8e4-14ab-4988-a20e-0408f2d2732b`: kiểm tra bản nháp/nhận xét thứ tư tại máy cho kết quả 287 → 275 cảnh, bỏ 12 cảnh chưa rõ; toàn bộ lời đọc còn lại qua kiểm tra phụ đề, không gọi thêm ChatGPT. Đây chưa phải xác nhận video hoàn tất.

Đã cập nhật đúng server đang giữ cổng 8877 qua launcher kiểm tra idle và cho job trên retry qua API hiện có. API xác nhận checkpoint `script` với 275 cảnh đã lưu, job chuyển sang `running / speech`, lỗi rỗng. 24 kiểm tra Python liên quan đều qua. Chưa chờ toàn bộ bước ảnh/nhạc/render hoàn tất.
