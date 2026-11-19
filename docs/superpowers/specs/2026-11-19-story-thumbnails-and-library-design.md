# Ảnh bìa truyện vẽ bằng Comfy và Kho video theo đầu truyện

Chủ kênh duyệt ngày 2026-11-19. Hai phần, làm theo thứ tự.

## Phần 1: ảnh bìa từng chương, vẽ bằng ComfyUI, nhân vật theo nội dung chương

Code: `app/videostudio/story_promo.py`. Dữ liệu: `data/story-promo/<book id>/`.

- ChatGPT chỉ viết chữ (qua route chat của daemon):
  - mỗi bộ một lần (`sheet.json`): thể loại, một phong cách vẽ, ngoại hình 2–4 nhân vật chính;
  - mỗi chương (`<episode>/promo.json`): tiêu đề YouTube, chữ in trên ảnh, một cảnh then chốt, 1–3 nhân vật có mặt
    trong cảnh theo đúng nội dung chương, nhân vật mới (chỉ nhân vật chính hoặc gắn bó mật thiết với nhân vật chính;
    nhân vật quá phụ bỏ qua) kèm ngoại hình, và ghi chú ngoại hình riêng của chương (đổi nhẹ: trang phục, vết thương,
    tuổi) nếu có.
- Bộ nhân vật lớn dần theo truyện (tối đa 16), lưu trong `sheet.json`. Mỗi nhân vật có một chân dung Comfy cố định
  (`cast/<id>.png`, vẽ một lần, hạt giống cố định).
- Ảnh cảnh: Comfy (Qwen Image 2.1, cùng mô hình và cách dùng ảnh mẫu như cảnh video) với chân dung của tối đa 2 nhân vật
  quan trọng nhất trong cảnh làm ảnh mẫu (một người mỗi ảnh mẫu: ảnh nhóm làm Comfy vẽ thêm người lạ).
  Gương mặt, tóc, dáng theo chân dung; trang phục theo chân dung trừ khi chương ghi khác.
- GPU: chỉ vẽ khi không có video hay tác vụ ảnh nào đang chạy; giải phóng bộ nhớ GPU sau mỗi tập. Phần chữ vẫn chạy khi
  máy bận để tiêu đề sẵn sàng trước giờ lên lịch.
- Hỏng 3 lần: nền trơn + chữ; 6 giờ sau vẽ lại (tối đa 2 lần).
- Trọng Sinh tập 1–8 vẽ lại bằng Comfy (giữ tiêu đề đã có); tả lại ngoại hình nhân vật bị cắt ở 600 ký tự.

## Phần 2: Kho video xem theo đầu truyện

- Thẻ "Kể truyện" của Kho video: lưới thẻ nhỏ các đầu truyện (ảnh bìa, tên, số chương, số đã đăng), chọn 12/24/48 truyện
  mỗi trang.
- Bấm một bộ: nút quay lại, tên bộ; dải bộ nhân vật (chân dung nhỏ + tên, bấm xem lớn + vai); chương dạng dòng gọn xếp
  theo số tập: ảnh nhỏ, số tập, tên, thời lượng, máy/Drive, trạng thái đăng; đủ nút Xem, Đăng/hẹn giờ, Mở trên Drive,
  Đã đăng & dọn; Chọn nhiều/xoá; lọc Duyệt video; 20/50/100 chương mỗi trang.
- Ô tìm kiếm: ra thẳng các chương khớp của mọi bộ.
- Các thẻ Tất cả, Vụ án, Tin tức, Meme giữ nguyên.
