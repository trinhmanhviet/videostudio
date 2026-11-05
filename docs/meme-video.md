# Video meme Gấu trúc

Chế độ `workflow_mode: "meme"` tạo video hài dọc 9:16 kiểu "gấu trúc biaoqing": khung 3 dải
(câu móc ở trên, cảnh ở giữa, câu chốt ở dưới), cắt cảnh nhanh theo từng câu kể.

## Cách dùng
Trong VideoStudio chọn **Cách chuẩn bị nội dung → Video meme Gấu trúc**, nhập ý tưởng truyện
(ví dụ "Lần đầu tôi dạy bố dùng điện thoại thông minh"), chọn giọng, đặt 45–90 giây rồi bấm tạo.
Lựa chọn "Ảnh cảnh tạo bằng" không dùng trong chế độ này.

### Hoạt hình tự động HyperFrames (2026-11-05)

Trong chế độ meme, **Bộ dựng → Hoạt hình HyperFrames** là lựa chọn mặc định cho video mới.
Đây là engine đã dùng cho các tập mẫu `ep2–ep5`, được nối vào hàng đợi và checkpoint của VideoStudio.
Dán câu chuyện hoặc nhập ý tưởng, chọn giọng rồi bấm tạo. Tool tự chọn trang phục/phụ kiện khác nhau,
biểu cảm từng câu, hành động, toàn/trung/cận cảnh, phản ứng và nhép miệng theo WAV ở 30fps.
Giọng đã chọn áp dụng cho cả lời kể và nhân vật; tốc độ mặc định **1,15×**, pitch theo thanh chỉnh.
Một job tạo một MP4, một mạch truyện có câu chốt; thời lượng nhập là mục tiêu viết, thời lượng thực đo từ lời đọc.
Chưa có tính năng tự xuất nhiều tập từ một lần nhập.

Kịch bản dài hơn khoảng 90 giây được viết theo **dàn ý chung + các phần tối đa 20 câu mục tiêu/lượt**
(ví dụ 7 phút: 9 phần, tổng mục tiêu 168 câu). Mỗi phản hồi nhỏ được kiểm tra và lưu trong
`data/<job-id>/animation-parts/`; nhân vật, quần áo và danh sách cảnh dùng chung suốt video.
Ngắt kết nối giữa chừng thì tiếp tục từ phần còn thiếu, không viết lại các phần đã hoàn tất và không tự rút ngắn video.
Các phần viết được ghép thành một kịch bản trước khi tạo giọng; không phải nhiều video riêng.
Nếu chủ động hủy ở bước kịch bản hoạt hình, có nút **Tiếp tục job đã hủy**. Tool giữ job/checkpoint,
tách phiên ChatGPT cũ đang kẹt khỏi hàng chờ và mở phiên mới cho cùng job; lịch sử phản hồi thật vẫn được giữ.

- HyperFrames dùng rig/tủ đồ/nền trong `memestudio/assets`, GSAP và SFX cục bộ, **không gọi Flow/Comfy để tạo ảnh hoặc nhạc**.
  Bản tích hợp này có lời đọc + SFX; không tạo nhạc nền. Có thể tắt phụ đề hoặc SFX qua các cờ API hiện có.
- Cần Node.js 22+, FFmpeg/FFprobe, Python có NumPy/Pillow và `npm ci` trong `memestudio`.
  VieNeu và bridge ChatGPT dùng cấu hình hiện có của VideoStudio. Không dùng trình duyệt Flow để render.
- Mỗi job có thư mục riêng: `E:\Videos\<dự án>\data\<job-id>\episode`; không ghi vào các tập mẫu.
  File thành phẩm vẫn ở `E:\Videos\<dự án>\video-<job-id>.mp4`.
- Speech tạo/cache từng câu, áp dụng tempo/pitch rồi dựng timeline đo thật gồm khoảng nghỉ và phản ứng.
  Images xác nhận bản sao tạo hình riêng; music ghi checkpoint im lặng có chủ đích; render chỉ ghép nội dung đã chuẩn bị.
  Retry render không gọi AI/TTS. Receipt giữ đường dẫn/hash MP4 đã xuất để retry không xuất trùng.
- Chọn **Pillow** để dùng bộ dựng cũ. Request/job cũ không có `meme_engine` vẫn dùng Pillow, không đổi checkpoint.

CLI gọi cùng API, không tạo pipeline riêng (chạy server và bridge trước):

```powershell
python auto_meme.py --input story.txt --out out/video.mp4
python auto_meme.py --idea "Bố lần đầu dùng điện thoại thông minh" --seconds 60 --voice "clone:<id>" --out out/video2.mp4
```

Mặc định giọng Vương Bờm của máy hiện tại; máy khác dùng `--voice` với ID trong danh sách giọng.
CLI tự tìm bridge sẵn sàng; có thể chỉ định `--scope` và `--server` localhost.
Receipt `<output>.auto-meme.json` lưu khóa idempotency/job, không lưu nguyên câu chuyện. Chạy lại cùng lệnh sẽ
theo dõi cùng job; nếu job failed thì mở Studio và retry từ bước lỗi. Không ghi đè file MP4 đã tồn tại.

Mã tích hợp: `meme_animation_script.py` (hợp đồng AI + danh mục thật), `meme_animation.py` (các stage),
`auto_meme.py` (CLI). Thêm đồ/mặt cho engine xem [hướng dẫn hoạt hình](huong-dan-video-hoat-hinh.md).

Muốn AI chọn nền 90s hoặc thôn quê, ghi rõ bối cảnh trong ý tưởng ("thập niên 90, ở quê"). Tag nền trong
prompt là tên file bỏ `bg_`, dấu `_` đổi thành khoảng trắng (ví dụ `bg_90s_rural_pond` → "90s rural pond").

## Luồng chạy của bộ dựng Pillow cũ
| Bước | Chế độ meme làm gì |
|---|---|
| plan | Kiểm tra điều kiện chạy; nạp asset mới trong `new/` nếu có |
| research | Bỏ qua |
| script | ChatGPT/Gemini viết truyện + danh sách cảnh, chỉ được dùng id trong danh mục; sai id thì viết lại tối đa 3 lượt, lượt cuối tự thay bằng mặc định |
| speech, subtitles, music | Giữ nguyên như video thường (VieNeu, Stable Audio) |
| images | Không tạo ảnh; chỉ kiểm tra asset còn đủ |
| render | `videostudio/meme_render.py`: Pillow ghép khung + FFmpeg mã hoá 1080x1920 30fps, nhạc + SFX tổng hợp |
| verify | Kiểm tra thời lượng, giải mã toàn bộ, âm thanh |

## Chọn độ dài video
- Thời lượng nói = số âm tiết ÷ khoảng 3,5 (giọng tiếng Việt đọc 3–4 âm tiết/giây).
- Trình viết kịch bản (`videostudio/meme_script.py`) **không đọc nguyên văn** ý tưởng. Ý tưởng chỉ là dữ liệu;
  AI viết lại thành các beat, mỗi beat một câu 6–14 từ và một khung hình, `SECONDS_PER_BEAT = 2.4`.
  Số beat mục tiêu = thời lượng ÷ 2,4 (cho phép 0,7×–1,35×): 60 giây ≈ 25 beat, 90 giây ≈ 38 beat.
- Giới hạn nhập: 15–600 giây (`videostudio/core.py`); giao diện tự đưa về 60 giây nếu đặt quá 600. Nên dùng 45–90 giây.
- Một truyện dài hơn thì nén vào 90 giây sẽ mất tiếng cười. Cách làm: mỗi video một mạch truyện có punchline riêng
  (45–120 giây), truyện nhiều đoạn thì tách thành nhiều video.
- Ví dụ truyện "bạn tôi lấy vợ" (1.589 âm tiết, 5 đoạn): đọc nguyên văn ≈ 7,5 phút. Từng đoạn nguyên văn:
  nhà văn ≈ 1,5 phút, con bạc ≈ 1 phút, xe ôm + viên đá ≈ 2,7 phút, nhà thầu ≈ 2 phút, kết ≈ 0,5 phút.
- Chưa có chế độ đọc nguyên văn bằng asset meme. Đề xuất ở `docs/meme-handoff.md`.

## Asset
Danh mục nạp bởi `videostudio/meme_catalog.py` (`load_catalog()`): 224 sprite/đồ vật + 86 nền.

- **Gấu trúc:** 80 sprite, `assets/Meme_Animation_Asset_Pack/catalog/panda.json` (+ ảnh trong `catalog/panda/`),
  cắt từ 3 sheet gốc bằng `scripts/build_meme_catalog.py` (cần opencv, chỉ chạy lại khi sheet đổi).
- **Thư viện đồ vật/hiệu ứng:** 144 món (126 prop + 18 fx), `catalog/library.json` + `catalog/library/*.png`,
  cắt tự động từ 17 sheet trong `new/` bằng `scripts/import_meme_library.py` (xem "Thêm asset mới").
  Sheet: `prop_animals, prop_clothes, prop_daily, prop_food, prop_furniture, prop_home, prop_kitchen_tech,
  prop_medical, prop_party, prop_school, prop_shopping, prop_sports, prop_study_office, prop_tet, prop_tools,
  prop_vehicles, fx_more, fx_stickers`.
- **Nền: 86** = 14 vẽ bằng code (`plain_*`, `room_day/night`, `outdoor_day/night`, `rays_*`, `flashback`)
  + 72 file `bg_*.png` 720x1280 trong `assets/Meme_Animation_Asset_Pack/new/`:
  - 48 nền chung: airport, alley, apartment_corridor, bank_counter, bathroom, beach, bedroom, bedroom_night,
    bus_interior, bus_stop, car_interior, cinema, classroom, clinic, coffee_shop, construction_site, countryside,
    elevator, farm, forest, gym, hospital_corridor, karaoke_room, kitchen, library, living_room, market,
    meeting_room, messy_room, mountains, office, office_night, park, rainy_street, restaurant, rooftop, school_yard,
    space, stage, store, street, street_eatery, street_night, supermarket_checkout, swimming_pool, tet_house,
    train_station, wedding_hall.
  - 12 nền thành phố thập niên 90 (`bg_90s_*`): apartment_yard, bedroom, classroom, coffee_stall, game_shop,
    kitchen, living_room, market, post_office, street, train_station, village_house.
  - 12 nền thôn quê thập niên 90 (`bg_90s_rural_*`): rice_field, dirt_road, yard, pond, communal_house,
    bamboo_gate, kitchen, house_inside, grocery, river_ferry, school, market.
- **Bản cũ** bị thay thế được giữ ở `new/_old_style/` (xoá được nếu không cần).

### Phong cách chuẩn (mọi asset phải giống nhau)
Chốt theo video mẫu của người dùng: phẳng 2D rất đơn giản, MỌI vật thể có nét viền mảnh, sạch, một nét liền màu
nâu đậm (không dày, không run); tô phẳng màu đất xỉn (be, kem, nâu nhạt, xanh rêu xỉn, xám xanh), bầu trời xanh
xám nhạt phẳng; hơi xấu như meme vẽ vội, vài vệt ố trên tường; cảnh trống không có người; sàn/mặt đất chiếm 1/3
dưới; không chữ. Không dùng: kiểu tranh sơn, đổ bóng, gradient, ánh sáng phát sáng/phản chiếu, neon, màu rực, 3D, hiện đại.
Nền thập niên 90 thêm đồ cổ điển (ti vi CRT, quạt trần/quạt bàn, điện thoại bàn, xe đạp, xe Cub, mái ngói, cột điện gỗ);
nền thôn quê không có đồ hiện đại.

### Thêm asset mới
- Nền: bỏ `bg_<tên>.png` (720x1280) vào `assets/Meme_Animation_Asset_Pack/new/` là dùng ngay.
- Sheet đồ vật: đặt đúng tên như `scripts/make_meme_assets.py` (`prop_food.png`, `fx_stickers.png`, ...) → tự cắt
  theo thứ tự lưới (2×3, 2×4 hoặc 3×3 khi vật bị tách mảnh) và đặt tên; một ảnh một vật thì đặt `prop_<tên>.png`.
  Video meme kế tiếp tự nạp (`scripts/import_meme_library.py`); sheet đếm sai số vật sẽ bị bỏ qua và ghi lý do.
- Vẽ bằng ChatGPT app (ảnh meme KHÔNG vẽ trong Chrome riêng của VideoStudio, chỗ đó chỉ để viết kịch bản):
  xem quy trình ở `docs/meme-handoff.md`. ZIP tải về Downloads nhập bằng
  `python scripts/ingest_asset_zips.py` (thêm `--replace` để ZIP mới thay file cũ; bản cũ chuyển vào `new/_old_style/`).

## Phục hồi và cập nhật asset

- ID asset/FX sai kiểu dữ liệu đi qua vòng sửa kịch bản tối đa ba lượt; reply bị từ chối có receipt `meme-script-attempt-XX.rejected.json`. Resume bỏ qua lượt đã biết sai, giữ nguyên phản hồi gốc để xem lỗi; hết lượt dùng fallback cục bộ khi còn đủ nội dung.
- Danh mục và cache ảnh dựa vào hash nội dung. Một Catalog là snapshot nhất quán; job mới nạp Catalog mới sẽ thấy ảnh thay thế cùng tên/kích thước, không cần restart để xóa cache ảnh. Bộ nhập library cũng phát hiện nguồn thay đổi dù giữ nguyên thời gian file.
- Khi nhập nhiều ZIP có `--replace`, chọn nguồn mới nhất cho từng tên file trước khi ghi; giữ bản bị thay trong `_old_style/` và giữ thời gian nguồn để chạy lại không thay lặp.
- Video meme chưa hỗ trợ editor ảnh/timeline của video thường. Các nút sửa/tạo lại ảnh được ẩn ở thẻ và hero; đổi giọng vẫn dùng được.

## Kiểm thử
`python -m unittest tests.test_meme_mode` (15 test, pass sau khi nhập bộ asset mới).
