# Bàn giao: chế độ video meme và thư viện asset (2026-11-04)

Dành cho phiên Claude Code làm tiếp trên máy người dùng. Đọc kèm `docs/meme-video.md`.

## Mục tiêu của người dùng
VideoStudio (ứng dụng Windows cục bộ, `D:\Projects\videostudio`) phải làm được video meme tiếng Việt kiểu
gấu trúc biaoqing từ asset có sẵn, không tạo ảnh mới cho mỗi video. Thư viện asset phải **chung, dùng lại cho
nhiều ý tưởng**, không bắt chước riêng một video mẫu. Người dùng ngại thao tác tay: ưu tiên tự động hoá.

## Tình trạng hiện tại
- Chế độ `workflow_mode: "meme"` hoạt động, đã chạy end-to-end trước đây (xem `docs/tasks/2026-11-04-meme-e2e*.md`)
  nhưng với bộ asset cũ.
- Thư viện asset mới đã đủ và cùng một style: 80 sprite gấu trúc, 144 đồ vật/hiệu ứng, 86 nền
  (14 vẽ bằng code + 72 file). Chi tiết danh sách và quy tắc style ở `docs/meme-video.md`.
- `python -m unittest tests.test_meme_mode`: 15 test pass. `load_catalog()` thấy đủ 72 nền file; prompt mô tả danh mục
  dài khoảng 9.200 ký tự (`Catalog.describe_for_prompt()`), sẽ lớn thêm khi thêm asset.
- **Chưa render video meme thật nào với thư viện mới.** Việc đầu tiên nên làm là tạo một video thử.
- **Chưa commit gì.** Người dùng chưa yêu cầu commit. Chưa có CLAUDE.md hay AGENTS.md trong repo.
  File mới/sửa chưa commit gồm `videostudio/meme_*.py`, `scripts/{build_meme_catalog,import_meme_library,make_meme_assets,nhan_ten_anh,ingest_asset_zips}.py`,
  `tests/test_meme_mode.py`, `docs/meme-*.md`, `docs/tasks/`, `assets/`, cùng các sửa trong `core.py`, `providers.py`,
  `static/index.html`, `cdp_*.py`.

## Việc đã làm trong phiên này (chỉ phần asset)
1. Vẽ bộ nền và đồ vật chung bằng **ChatGPT app trên Windows** (điều khiển qua computer-use), không dùng web và
   không dùng Chrome riêng. Người dùng nhắc nhiều lần: phải là app ChatGPT.
2. Người dùng đổi hướng phong cách nhiều lần, kết quả cuối cùng là style "đơn giản, hơi xấu, nét mảnh sạch, màu
   đất xỉn" (mô tả ở `docs/meme-video.md`). Toàn bộ asset đã được vẽ lại cho cùng style; bản cũ ở `new/_old_style/`.
3. Thêm 12 nền thành phố thập niên 90 và 12 nền thôn quê thập niên 90.
4. `scripts/import_meme_library.py` thêm hàm `merge_by_grid` (lưới 2×3, 2×4, 3×3) để sheet có vật bị tách mảnh vẫn
   cắt đúng số lượng. `scripts/nhan_ten_anh.py` đổi tên ảnh mới tải về. `scripts/ingest_asset_zips.py` giải ZIP
   từ Downloads vào `new/`.

## Quy trình vẽ thêm asset bằng ChatGPT app
1. Mở app ChatGPT, dùng chat "Vẽ nền hoạt hình" (hoặc chat mới). Gửi MỘT tin cho mỗi lượt gồm 4 ảnh nền dọc 9:16,
   mô tả phong cách chuẩn và 4 cảnh với tên file chính xác. Cuối tin yêu cầu: tạo luôn ZIP tên
   `R<n>_backgrounds.zip` chứa PNG 720x1280 đúng tên và đưa link tải ngay trong câu trả lời.
2. Mỗi lượt mất khoảng 3–5 phút. Đôi khi ChatGPT chỉ vẽ carousel mà không tạo ZIP: gửi tin tiếp
   "Gói đúng 4 ảnh R<n> vừa vẽ thành file ZIP …".
3. Bấm link ZIP; nếu khung xem trước bên phải đang mở thì dùng nút tải ở khung (menu → ZIP), nếu không thì link tự tải.
   Khung xem trước hay kẹt ở file cũ: đóng khung (chọn tab, Ctrl+W) rồi bấm lại. File tải trùng tên `(1)`, `(2)` vô hại.
4. Chạy `python scripts/ingest_asset_zips.py` (thêm `--replace` khi vẽ lại file đã có), sau đó xem mắt một ảnh ghép
   các nền mới cạnh các nền chuẩn để chắc cùng style.
5. Sheet đồ vật: một ảnh lưới (2×3, 2×4 hoặc 3×3) nền trong suốt, đặt đúng tên trong `SHEET_ITEMS` của
   `scripts/make_meme_assets.py`, rồi để `refresh_library()` cắt khi chạy video kế tiếp.

Lưu ý khi điều khiển app: ô nhập tin ở khoảng giữa dưới màn hình (lệch trái khi khung xem trước mở); menu Start hoặc
cửa sổ nổi "Claude is using your computer" có lúc chiếm focus nên gõ trượt, cần chụp màn hình kiểm tra ô nhập trước khi gửi.
ChatGPT từng chạm giới hạn ảnh sau vài lượt; `make_meme_assets.py --patient` chờ 30 phút giữa các lượt (tối đa 6 giờ).

## Việc còn lại và đề xuất
1. **Chạy thử một video meme thật** (ví dụ ý tưởng "hồi nhỏ ở quê thập niên 90 …", 60–90 giây). Kiểm tra: AI có chọn
   `bg_90s_rural_*` không (tag nền là tiếng Anh từ tên file, ý tưởng tiếng Việt; nếu chọn kém thì thêm mô tả tiếng
   Việt cho tag nền), prompt có quá dài không, nền và đồ vật có hợp style với sprite gấu trúc không.
2. [x] **Đồng bộ STYLE (xong 2026-11-04).** `STYLE` trong `scripts/make_meme_assets.py` và mọi prompt trong
   `assets/Meme_Animation_Asset_Pack/PROMPT_CHATGPT.md` đã theo phần "Phong cách chuẩn" (nét mảnh sạch nâu đậm,
   tô phẳng màu đất xỉn, không bóng/gradient/neon/3D). Nền thêm "vài vệt ố mờ trên tường".
3. **Rà lại các sheet đồ vật vẽ trước khi chốt style** (các sheet từ `prop_kitchen_tech` đến `fx_more`, cùng
   `fx_stickers`): chưa xem lại kỹ độ dày nét. Ba sheet `prop_food`, `prop_furniture`, `prop_home` đã vẽ lại và
   kiểm tra. Nền ngoài trời (cây, trời) hơi tươi hơn nền trong nhà.
4. **Chế độ "meme + lời sẵn" (nếu người dùng muốn đọc nguyên văn truyện dài).** Hiện ý tưởng chỉ là dữ liệu và bị viết lại
   thành beat 2,4 giây. Ý tưởng: tái dùng cách `provided_narration` tách từng dòng lời đọc; mỗi câu (hoặc nhóm câu
   ngắn) là một beat; một lượt LLM chỉ gán shot/pose/bg/prop/motion/sfx cho từng câu, KHÔNG viết lại chữ; thời lượng do
   TTS quyết định; nâng hoặc bỏ giới hạn 600 giây. Truyện 7,5 phút ≈ 190 khung, nên cần xoay vòng pose/nền để bớt lặp.
   Chưa làm, chờ người dùng quyết định (họ mới hỏi cách chọn độ dài, chưa chốt cách nào).
5. Người dùng tự dọn tay (mình không xoá được): các file `R*_backgrounds*.zip` và `VideoStudio_*.zip` trong
   Downloads, `assets/Meme_Animation_Asset_Pack/catalog/_to_delete/` (6 PNG pose thừa), `tmp/check_*.png`.
   `new/_old_style/` xoá được nếu không cần bản cũ.

## Ràng buộc đã thoả thuận với người dùng
- Không giả header, không phát lại token, không vượt reCAPTCHA khi làm việc với Google Flow.
- Không commit file cookie, HAR hay profile trình duyệt. Không commit nếu người dùng chưa bảo.
- Chỉ xoá file tạm do mình tạo hoặc file người dùng yêu cầu xoá.
- Ảnh meme vẽ trong ChatGPT app, không dùng Chrome riêng của VideoStudio.
- Khi xong việc computer-use thì nhả quyền điều khiển máy.
