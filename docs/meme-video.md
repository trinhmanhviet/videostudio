# Video hài: pipeline thống nhất dùng HyperFrames

Chọn **Video meme / hoạt hình nhân vật**, nhập ý tưởng hoặc truyện, chọn giọng và thời lượng rồi tạo.
Một job xuất một MP4; hiện nhận15–600 giây. Không có lựa chọn engine hoặc phiên bản biên kịch.
Pipeline tài liệu giữ luồng hiện có.

## Đường đi của nội dung

Ý tưởng/truyện → phân tích và phát triển cốt truyện → bố trí cảnh → viết → phản biện toàn truyện
→ sửa cục bộ có giới hạn → JSON HyperFrames → TTS → hoạt hình/SFX → kiểm tra → MP4.

Các bước sáng tác nằm trong stage script, gọi cùng Pipeline.llm_json/parser/bridge, không có service hay hàng đợi mới.

- **Playbook**: comedy_playbook.json có32 kỹ thuật với cơ chế, setup, leo thang, payoff, điều kiện dùng/tránh, lỗi thường gặp; chín kiểu kết. Chọn theo truyện, không ép mọi tập có thảm họa.
- **Architect**: phân biệt ý tưởng mở và truyện hoàn chỉnh. Ý tưởng mở có tối đa ba hướng phát triển rồi chọn một. Truyện có sẵn giữ sự kiện và câu chốt qua source contract. Lập hồ sơ động cơ, điểm yếu, niềm tin, cách suy luận/đối thoại/phản ứng của các vai.
- **Narrative event** là sự kiện kể chuyện, có thể có nhiều render beats. Writer chỉ viết các event được giao, kế thừa nhân vật, trạng thái sự kiện, đạo cụ, setup/payoff còn mở.
- **Thời lượng**: ngân sách âm tiết dùng tốc độ đúng giọng trong WAV của job đã verified; chưa có mẫu thì ghi rõ chưa hiệu chuẩn. Chia phản hồi theo khoảng180 âm tiết mục tiêu. Số beat không phải bằng chứng đủ thời lượng; timeline cuối đo từ WAV.
- **Đạo cụ**: tool giữ state trước; AI chỉ gửi cập nhật đích tại event/render beat cụ thể. Chuyển người cầm/vị trí trên hình cần update tương ứng. State bối cảnh như vườn rau có thể thể hiện bằng ghi chú minh họa, không ép thành đồ cầm tay.
- **Callback**: có marker ở beat gieo và beat trả theo thứ tự thực tế, lưu lại event quan sát được; vị trí có thể khác nhãn gợi ý trong dàn ý. Thiếu setup trước payoff hoặc thiếu payoff bắt buộc vẫn bị chặn. Critic xem cả nội dung, không coi marker là chứng nhận hài hay.
- **Critic**: xem toàn truyện và nguyên bản. Trọng số thử nghiệm: nhân quả20%, setup/payoff25%, mới15%, giọng kể15%, kết15%, khả năng dựng10%. Tối đa hai vòng sửa nội dung, tối đa ba lượt sửa JSON cho mỗi bước. Chỉ sửa câu/sự kiện liên quan và callback phụ thuộc; giữ phần tốt và quỹ đạo đạo cụ.
- Trạng thái: approved, reviewed_with_warnings, rejected. Blocking còn lại thì stage không nhận kịch bản là đạt; major/minor còn lại được ghi rõ. Điểm AI không chứng minh mức độ buồn cười; human_quality_verified vẫn false.

Ngôn ngữ thô, hài chất thải và bạo lực hoạt hình không bị loại khỏi công thức mặc định; cần có vai trò trong tình huống và tuân thủ giới hạn nội dung áp dụng.
Không sao chép tên vai, câu cửa miệng hoặc cốt truyện nhận diện từ nguồn nghiên cứu.

## Hình ảnh và timing

Rig/tủ đồ/mặt/nền trong memestudio/assets; GSAP và SFX cục bộ; không gọi Flow tạo ảnh meme.
Giọng được chọn dùng chung cho các vai; cá tính thể hiện bằng lời thoại, chưa có diễn xuất TTS riêng từng vai.
Tốc độ mặc định1,15×, pitch theo thanh chỉnh. WAV từng câu được giữ riêng, đồng bộ ở30fps.

Đạo cụ dùng PNG thư viện có sẵn; chưa có hình thì dùng thẻ tên minh họa, không giả vờ đã có hình thật.
Schema bổ sung vào beat đầy đủ:

```json
{"props":{"book":{"asset":null,"label":"Cuốn sách"}},
 "beats":[{"props":{"book":{"placement":"held","owner":"toi"}},
           "pause_before":0.2,"pause_after":0.3,"reaction_seconds":0.6}]}
```

Vị trí: held/table/hidden. Dùng trạng thái trước/sau cùng cử chỉ để thể hiện chuyển/giấu/lộ.
Đạo cụ đặt cố định được neo theo nền/bối cảnh, không tự đi theo nhân vật sang phòng khác.
Compiler phân biệt câu chốt đã nằm trong lời đọc với dữ liệu camera; ghi chú trạng thái nằm trong notes, chỉ hiện trong beat liên quan.
Không mô phỏng vật lý hay thao tác ngón tay. Khoảng nghỉ từng beat0–2 giây, cùng nằm trong staging đo thật của lời đọc.
Video mới dùng lời đọc+SFX, không bắt tạo nhạc Stable Audio.
Job chuyển đổi có checkpoint nhạc hợp lệ sẽ giữ và mix nhỏ track cũ sau HyperFrames nếu nhạc vẫn bật; file nhạc gốc được giữ.

## Checkpoint và resume

File trong E:/Videos/<dự án>/data/<job-id>/:
- comedy/inputs.json: snapshot yêu cầu, Playbook, lịch sử và tốc độ giọng.
- comedy/architect.json, outline.json, writer-NNN.json, critic-N.json, repair-N-M.json: kết quả chuẩn hóa và receipt prompt/hash; giữ phản hồi thô/lỗi riêng.
- comedy/quality.json: trạng thái, critic, continuity, ánh xạ narrative/render và giới hạn kiểm chứng.
- animation-script.json: script engine; episode/: HTML, assets riêng, WAV, staging, SFX, log render.
- MP4 ở E:/Videos/<dự án>/video-<job-id>.mp4.

Retry giữ các kết quả hợp lệ; mất mạng ở critic không viết lại writer; retry render không gọi lại TTS/AI.
Chủ động hủy ở script hoạt hình có nút Tiếp tục job đã hủy; phiên ChatGPT bị kẹt được tách khỏi hàng chờ nhưng lịch sử thật được giữ.
Không đổi nguyên bản giữa một bản thảo đã checkpoint; muốn truyện khác thì tạo job mới.

## Dữ liệu cũ

Pillow và hai prompt ngắn/dài cũ đã gỡ khỏi runtime. Giá trị engine cũ trong request chỉ là dữ liệu chuyển đổi.
Job hoàn tất/MP4 gốc không viết lại. Job dở chuyển khi worker có lease hợp lệ; trước mutation có snapshot DB
và bản sao file/hash trong comedy-migration-v1/. Chỉ worker có lease hiện hành mới thu hồi job running do tiến trình trước chết.
Giữ narration, dùng lại WAV/receipt đã khớp chữ/giọng, nhạc và phần viết dài đã hợp lệ; dựng/timing cần thiết được tính lại.
Không suy diễn vai từ sprite Pillow: khi thiếu thông tin dùng rig trung tính, giữ nguyên lời và bản sao gốc.
Nguồn/hash không chứng minh được hoặc thiếu phần giữa thì báo rõ, giữ nguyên dữ liệu, không âm thầm gửi lại.

## Bộ nhớ và đánh giá

Bảng comedy_memory nằm trong SQLite hiện có, keyed theo job. Draft/reviewed/approved/rendered/published/rejected phân biệt.
Verified mới ghi rendered; không suy ra published. Retry bước cũ không ghi đè nội dung cuối hoặc đánh giá người dùng.
Lịch sử hữu hạn giúp tránh lặp cốt truyện/kiểu kết, không cấm tái sử dụng kỹ thuật phổ quát.

tests/fixtures/comedy-benchmark.json có20 nhóm ý tưởng, input, ràng buộc, rubric cấu trúc và ô nhận xét con người.
Unit test dùng fixture/mock, không gọi AI thật. Đánh giá thực tế cần xem video, nhận xét tự nhiên/bất ngờ/nhân quả/hành động/timing.
API nội bộ comedy_memory.feedback(store,job_id,rating,note) nhận điểm1–5 hoặc nhận xét; không phải tùy chọn biên kịch trên UI.

## Kho nhân vật

Trang /characters lưu ngoại hình, phụ kiện và căn chỉnh trong data/characters.json. Mỗi job chụp snapshot roster khi bắt đầu,
nên chỉnh kho không đổi bản thảo đang viết. Tên người trong truyện gốc được giữ, preset chỉ áp ngoại hình.
File hỏng được báo lỗi và giữ nguyên, không tự ghi đè bằng mặc định. Các cập nhật được khóa đọc–sửa–ghi.
Giọng đọc vẫn chọn ở màn hình tạo video; không có lựa chọn giọng riêng theo vai chưa hoạt động.

## Cài đặt và CLI

Node.js22+, FFmpeg/FFprobe, Python NumPy/Pillow; npm ci trong memestudio.
Mở hệ thống và bridge như bình thường. CLI gọi cùng API:

```powershell
python auto_meme.py --input story.txt --out out/video.mp4
python auto_meme.py --idea "Hai người bạn mở dịch vụ trả lời hộ câu hỏi khó" --seconds 60 --voice "clone:<id>" --out out/video2.mp4
```

Receipt <output>.auto-meme.json theo dõi cùng job khi chạy lại cùng lệnh, không ghi đè MP4.
Thêm assets/engine thủ công: [huong-dan-video-hoat-hinh.md](huong-dan-video-hoat-hinh.md).
Báo cáo triển khai/kiểm thử/giới hạn: [comedy-upgrade.md](comedy-upgrade.md).


## Asset HyperFrames dùng (kiểm tra ở đây)
| Thành phần | Vị trí |
|---|---|
| Đầu gấu (KHÔNG còn tai, xoá 2026-11-06) | `memestudio\assets\rig\faces\head_base.png` (bản gốc: `tmp\backup-rig-head-20261106\`) |
| Nét mặt, miệng | `memestudio\assets\rig\faces\face_*.png`, `mouth_*.png` (không chứa tai) |
| Thân | `memestudio\assets\rig\base\torso_core.png` |
| Tủ đồ: tóc, mũ, áo, kính... | `memestudio\assets\rig\wardrobe\` + `wardrobe.json` |
| Nền: 72 file `bg_*.png` 720x1280 | `memestudio\assets\backgrounds\` (nơi duy nhất) |
| Đồ vật: 144 món | `assets\Meme_Animation_Asset_Pack\catalog\library.json` + `catalog\library\*.png`; chỉ mục `kind: prop` được nạp, `fx` thì không. Sheet gốc để cắt: `assets\Meme_Animation_Asset_Pack\new\prop_*.png`, `fx_*.png` |
| SFX | `memestudio\assets\sfx\` |

Mỗi lần dựng một tập, `make_episode.py` chép asset từ `rig` vào `episodes\<tập>\assets`; sửa asset xong chỉ cần dựng lại.

## Thêm asset mới
- **Đồ vật**: vẽ sheet bằng ChatGPT app (prompt ở `docs/meme-handoff.md`), ZIP về Downloads, rồi chạy
  `python scripts/ingest_asset_zips.py` và `python scripts/import_meme_library.py` (HyperFrames KHÔNG tự nhập khi chạy job;
  quên chạy thì món mới không xuất hiện). Tên và thứ tự món theo `SHEET_ITEMS` trong `scripts/meme_sheets.py`; `python scripts/meme_sheets.py` in prompt ra `tmp/prompt_chatgpt_sheets.txt`
  (lưới 2x4 hoặc 3x3; sheet đếm sai số món sẽ bị bỏ qua và ghi lý do).
- **Nền**: `ingest_asset_zips.py` đưa `bg_*.png` thẳng vào `memestudio\assets\backgrounds` (bản bị thay chuyển vào `_old_style\` trong đó).
- **Trang phục, tóc, nét mặt**: xem `docs/huong-dan-video-hoat-hinh.md` và `memestudio/tools/`.

## Phong cách chuẩn (mọi asset vẽ thêm phải giống nhau)
Phẳng 2D rất đơn giản, mọi vật thể có nét viền mảnh, sạch, một nét liền màu nâu đậm (không dày, không run); tô phẳng màu đất xỉn
(be, kem, nâu nhạt, xanh rêu xỉn, xám xanh), bầu trời xanh xám nhạt phẳng; hơi xấu như meme vẽ vội; cảnh trống không có người;
không chữ. Không dùng: tranh sơn, đổ bóng, gradient, phát sáng, neon, màu rực, 3D, hiện đại. Nền thập niên 90 thêm đồ cổ điển
(ti vi CRT, quạt, điện thoại bàn, xe đạp, mái ngói); nền thôn quê không có đồ hiện đại.

## Kiểm thử
`python -m unittest discover -s tests -p 'test_meme*.py'`.
Các test dựng (`test_meme_animation_pipeline`, `test_memestudio_consistency`, `test_meme_migration`) cần máy Windows
(font Arial, ghi file tạm); trong môi trường Linux hạn chế chúng lỗi vì lý do hạ tầng.
