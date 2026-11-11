# Bàn giao: video meme và thư viện asset (cập nhật 2026-11-06)

Dành cho phiên làm tiếp. Đọc kèm `docs/meme-video.md` và `docs/huong-dan-video-hoat-hinh.md`.

## Mục tiêu của người dùng
VideoStudio (Windows, `D:\Projects\videostudio`) làm video meme tiếng Việt kiểu gấu trúc biaoqing từ asset có sẵn, không tạo ảnh mới
mỗi video. Thư viện asset phải CHUNG, dùng lại cho nhiều ý tưởng. Người dùng ngại thao tác tay: ưu tiên tự động hoá.
**Quyết định 2026-11-06: chỉ dùng HyperFrames; engine Pillow cũ và asset riêng của nó đã gỡ.** Gấu trúc KHÔNG có tai (chỉ đầu).

## Tình trạng
- Engine duy nhất: HyperFrames (`memestudio`). Asset và vị trí: bảng trong `docs/meme-video.md`.
- Đã xoá tai ở `memestudio\assets\rig\faces\head_base.png` (đầu của rig; các file `face_*` không có tai).
- Đã xoá hẳn (còn trong lịch sử git): sprite `catalog\panda\` + `panda.json`, `videostudio/meme_catalog.py`, `scripts/build_meme_catalog.py`,
  `tests/test_meme_mode.py`, asset pack gốc (`Panda`, `BananaCat`, `docs`, `examples`, `tools`, `manifest.json`, `README.txt`, `PROMPT_CHATGPT.md`, `.bat`),
  72 nền trùng trong `new\`, `assets/VIDEOSTUDIO_MEME_AI_PLAYBOOK.md`, `assets/Huong_dan_su_dung_Meme_Assets_HyperFrames.docx`,
  `scripts/make_meme_assets.py` (danh sách sheet chuyển sang `scripts/meme_sheets.py`), `scripts/nhan_ten_anh.py`, `scripts/probe_chatgpt_image_dom.py`.
  Thêm test `tests/test_import_meme_library.py`. `ingest_asset_zips.py` giờ đưa nền thẳng vào `memestudio\assets\backgrounds`.
- Còn giữ: `core.py` chấp nhận `meme_engine: "pillow"` chỉ để job cũ được chuyển sang HyperFrames.
- Chưa commit gì (người dùng chưa yêu cầu). Chưa dựng thử video với đầu không tai.

## Việc đang chờ
1. **Vẽ 16 sheet đồ vật mới (131 món)** bằng ChatGPT app: 4 tin, mỗi tin 4 sheet, ZIP tên `S1_sheets.zip` ... `S4_sheets.zip`.
   Nội dung 4 tin đầy đủ: `data\memestudio\prompt_chatgpt_sheets.txt` (tạo bằng `python scripts/meme_sheets.py`).
   Sheet: prop_fruit, prop_street_food, prop_kitchenware, prop_bathroom, prop_electronics, prop_retro_90s, prop_village, prop_animals2,
   prop_nature, prop_street, prop_office2, prop_jobs, prop_romance; fx_weather, fx_marks, fx_emotion2 (3 sheet fx không được HyperFrames nạp).
   ZIP về Downloads thì chạy `python scripts/ingest_asset_zips.py`, xem ảnh ghép kiểm tra style, rồi `python scripts/import_meme_library.py`.
2. Dựng thử một tập để xem đầu không tai đội cùng tóc, mũ, kính có đẹp không; nếu tóc/mũ lộ khoảng trống chỗ cũ của tai thì chỉnh trong wardrobe.

## Quy trình vẽ asset bằng ChatGPT app
1. Mở app ChatGPT (không dùng web, không dùng Chrome riêng của VideoStudio), chat "Vẽ nền hoạt hình" hoặc chat mới.
2. Mỗi lượt gửi MỘT tin (phần đầu + các dòng `File ...` + dòng yêu cầu ZIP). Mỗi lượt 3–5 phút; nếu chỉ ra ảnh mà không có ZIP thì nhắn
   "Gói đúng các ảnh vừa vẽ thành file ZIP ... và đưa link tải".
3. Bấm link ZIP; nếu khung xem trước kẹt thì đóng khung rồi bấm lại. File `(1)`, `(2)` vô hại.
4. Khi điều khiển app, chụp màn hình kiểm tra ô nhập trước khi gửi; xong việc thì nhả quyền điều khiển máy.

## Ràng buộc đã thoả thuận
- Không giả header, không phát lại token, không vượt reCAPTCHA khi làm với Google Flow.
- Không commit cookie, HAR, profile trình duyệt. Không commit nếu người dùng chưa bảo.
- Chỉ xoá file tạm do mình tạo hoặc file người dùng yêu cầu xoá.
