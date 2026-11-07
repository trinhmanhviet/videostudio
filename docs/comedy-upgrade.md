# Nâng cấp pipeline hài thống nhất — 2026-11-06

## Phạm vi và nguồn

Yêu cầu chính thức: file đính kèm `4cc80f36-ba2a-4b58-85e8-da7019dec2ca/Pasted text.txt`.
Nguồn nghiên cứu tìm thấy tại `C:/Users/leath/Downloads/phan_tich_kich_ban_gau_hai_huoc_p16.md`.
Không sửa pipeline tài liệu; không xóa dữ liệu, không restart khi còn job đang chạy; không commit/push.

## Audit ban đầu

- `meme_pipeline.py` còn biên kịch/Pillow và điều hướng sang `meme_animation.py` bằng `meme_engine`.
- `meme_animation.py` và `meme_animation_long.py` dùng hai đường viết ngắn/dài; đã có receipt từng phần.
- Dàn ý dài khóa tạo hình nhưng chỉ truyền hai câu trước; chưa có ledger sự kiện/đạo cụ/callback.
- Chưa có Story Architect, phản biện toàn truyện hoặc lịch sử mô-típ phục vụ sáng tác.
- HyperFrames đo WAV, camera/hành động/nhép miệng/SFX đã có; cần tiếp tục tái sử dụng.

## Phương án

Một workflow meme, một bộ cấu hình Playbook, một chuỗi biên kịch cho cả ngắn và dài.
Các bước nội bộ nằm trong stage script hiện tại để giữ queue, API và resume:
phân tích/phát triển truyện → outline + hồ sơ nhân vật → viết theo narrative event
→ critic và sửa cục bộ có giới hạn → JSON HyperFrames. Mỗi phản hồi hợp lệ có receipt.
Metadata sáng tác, trạng thái liên tục và memory dùng SQLite/job artifacts hiện có.
Migration chỉ chuyển đổi job cũ chưa xong, có backup và kiểm tra nguồn; MP4 đã hoàn thành được giữ nguyên.

## Kế hoạch thực hiện và kiểm tra

- [x] Đọc trọn tài liệu tham chiếu, xác nhận khả năng renderer và trạng thái job.
- [x] Playbook có cơ chế/setup/escalation/payoff/compatibility/failure modes và benchmark 20 ý tưởng.
  File: `videostudio/comedy_playbook.json`, `tests/fixtures/comedy-benchmark.json`, tests cấu trúc/offline.
- [x] Một bộ biên kịch có architect, writer, critic, continuity, memory và cache/resume.
  Mở rộng adapter/validator hiện có; test truyện có sẵn, gián đoạn, sửa cục bộ, callback, phản biện.
- [x] Hợp nhất dispatch/UI/API về HyperFrames; migration idempotent cho checkpoint cũ; gỡ prompt/Pillow dư.
  Test job cũ và pipeline tài liệu, không giữ lựa chọn engine cũ/mới.
- [x] Kiểm tra TTS đo thật, khả năng thể hiện đạo cụ/hành động và timing; không tuyên bố hỗ trợ ngoài renderer.
- [x] Chạy kiểm thử offline, render thật khi hệ thống rảnh, lưu đánh giá mẫu và giới hạn chưa nghiệm thu.
- [x] Cập nhật hai hướng dẫn hiện có, bàn giao theo mục A–H trong yêu cầu.

Chỉ ghi hoàn thành từng mục sau khi có kết quả chạy thực tế. Điểm AI không chứng minh mức độ gây cười.

## Thay đổi Claude đã kiểm tra và hợp nhất

Giữ phần dọn asset/Pillow, đầu rig không tai, nguồn nhập nền duy nhất trong memestudio/assets/backgrounds,
danh sách sheet chuyển sang scripts/meme_sheets.py và importer/test tương ứng.
Sửa lại CLI bị quay về hợp đồng engine cũ; receipt CLI trước hợp nhất vẫn tiếp tục cùng job/key.
Thư viện native hiện có72 nền,30 trang phục,126 prop (18FX trong library không được coi là prop).

## Kiểm chứng hiện có

- Hồi quy trên bản có thay đổi Claude:742 Python pass; CLI sau sửa và tương thích receipt10 pass.
- UI và extension bridge:160 JavaScript pass.
- Review độc lập đã đạt cho nền Playbook/memory, writer/critic/continuity và migration.
  Các lỗi review tìm được đã có test hồi quy (stale memory, rendered fact, callback, prop state,
  local repair, malformed owner/ID, stale running lease và đúng thư mục cache TTS sản xuất).
- Render kỹ thuật thật, giọng giả lập:tmp/comedy-props-6x8fbern/output/video.mp4;
  full decode/audio/timing pass và đã xem ảnh khung hình đạo cụ. Đây không phải mẫu đánh giá chất lượng lời kể.
- Job người dùng bfbee324… đã hoàn tất trước khi nạp backend; không bị dừng để cập nhật.

## Báo cáo bàn giao A–H

### A. Kết quả

Đã hợp nhất pipeline hài, triển khai Playbook/architect/writer/critic/continuity/memory, migration và compiler hình ảnh.
Đã hợp nhất các thay đổi Claude và sửa các điểm nối Kho nhân vật: snapshot theo job, giữ tên nguồn,
không reset file hỏng, cập nhật có khóa, kiểm tra dữ liệu trước khi lưu và cô lập test khỏi dữ liệu thật.
Tùy chọn giọng riêng chưa hoạt động được gỡ khỏi UI; giọng chính được chọn khi tạo video.
Backend đã nạp bản cuối khi không còn job hoạt động. Không commit/push.

### B. Pipeline cuối

Ý tưởng/truyện → architect và hồ sơ vai → layout và state đầu → writer theo narrative event
→ critic toàn truyện, tối đa hai vòng sửa cục bộ → compiler JSON HyperFrames
→ TTS/staging đo WAV → hình/đạo cụ/SFX → kiểm tra MP4 → memory rendered.
Chỉ một chuỗi sinh nội dung và một renderer. Không thay luồng video tài liệu.

### C. Code chính

- comedy_story.py: các bước viết, receipt/cache, critique/repair và state; meme_animation_script.py: schema/canonicalization.
- comedy_playbook.json, comedy_memory.py: kỹ thuật và lịch sử trong SQLite hiện có.
- meme_pipeline.py, meme_animation.py, core.py, meme_migration.py: dispatch duy nhất, migration/backup và TTS reuse.
- make_episode.py, prop_layer.py: đạo cụ/ghi chú, neo vị trí theo nền, nghỉ hài, camera và đồng bộ WAV.
- character_store.py, api.py, characters.html: preset ngoại hình, khóa dữ liệu và kiểm tra đầu vào; không đổi tên nhân vật nguồn.
- auto_meme.py, index.html: UI/CLI thống nhất, receipt CLI cũ vẫn tiếp tục cùng job.
- Đã gỡ các writer/Pillow renderer cũ và giữ thư viện/asset/importer cần thiết. Phần cleanup asset của Claude được giữ.

### D. Chức năng mới

Architect phân biệt ý tưởng mở và truyện có sẵn; các vai có động cơ/lối nói thay vì chỉ quần áo.
Writer nhận state rút gọn và event được giao; compiler phân biệt câu chốt với camera reaction,
và trạng thái bối cảnh với đạo cụ cầm tay. Callback có bằng chứng marker, thứ tự thực tế và event quan sát được.
Critic phân loại blocking/major/minor, sửa đúng câu cần sửa và kiểm tra lại toàn truyện.
Memory phân biệt draft/rejected/approved/rendered/published, bảo vệ đánh giá con người và metadata cuối khi retry.

### E. Kiểm thử

- Full Python đã chạy760 test:759 pass; một WinError5 tạm ở thao tác replace file trong thư mục Temp.
  Chạy lại riêng test_hybrid_references.py:13/13 pass; không sửa module ảnh này.
- Các test trọng tâm sau sửa cuối:31 comedy,9 character-store,7 native animation,11 contract đã qua.
- UI/bridge:160 JavaScript pass. CLI:10 pass, gồm receipt trước hợp nhất.
- Lệnh chính: C:/Python312/python.exe -m unittest discover -s tests -q;
  chạy riêng bằng -p test_comedy_story.py, test_character_store.py, test_meme_migration.py, test_hybrid_references.py.
- node --test tests/*.test.mjs extensions/videostudio-chatgpt/tests/*.test.mjs.

Hai mẫu AI/TTS/HyperFrames thật đều completed,1080x1920/30fps, full decode pass, audio hữu hạn/không clipping:

1. c7d6af74-9319-4d4b-9503-549f66609ffd — ý tưởng mở,31,733 giây.
   E:/Videos/nghiem-thu-comedy-moi/video-c7d6af74-9319-4d4b-9503-549f66609ffd.mp4.
2. 196ac658-8070-4e21-96a1-ce0f33024c3a — truyện có sẵn,36,5 giây cho mục tiêu35 giây.
   E:/Videos/nghiem-thu-comedy-moi/video-196ac658-8070-4e21-96a1-ce0f33024c3a.mp4.
   Câu chốt cuối trong script: “Rau sạch nhà tôi hóa ra trồng bằng cần câu.”

Đã xem khung hình. Các lỗi format/state phát hiện trong lượt chạy thật được sửa ở tool rồi retry cùng job,
giữ phản hồi và checkpoint; không sửa tay nội dung video để giả lập thành công.

### F. Giới hạn

Cả hai mẫu có trạng thái reviewed_with_warnings; các góp ý còn lưu trong comedy/quality.json.
Không tuyên bố tác phẩm buồn cười hơn từ điểm AI. Chưa chạy toàn bộ20 ý tưởng bằng AI hoặc khảo sát người xem.
Full decode/audio không xác minh ngữ nghĩa toàn bộ lời đọc. Đạo cụ có thể là hình thư viện hoặc thẻ minh họa;
chưa mô phỏng vật lý, thao tác ngón tay hoặc diễn xuất TTS riêng từng vai.
Mẫu đầu được dùng để phát hiện lỗi đạo cụ bàn theo sang phòng; mã renderer cuối đã có test neo theo bối cảnh.

### G. Vận hành

F5 Studio, chọn Video meme / hoạt hình nhân vật, nhập ý tưởng/truyện, chọn giọng/thời lượng rồi tạo.
Không chọn engine/architect/critic. Chỉnh Kho nhân vật áp dụng cho job mới; không đổi snapshot job dở.
Job lỗi có thể tiếp tục từ checkpoint; báo cáo critic và lỗi JSON giữ trong thư mục data của job.
CLI giữ nguyên python auto_meme.py --input story.txt --out out/video.mp4.

### H. Tiếp theo có căn cứ

Cho người dùng chấm các mẫu và20 benchmark; ưu tiên cải thiện độ bất ngờ/câu kết theo nhận xét thật.
Tốc độ giọng đã hiệu chỉnh (2026-11-07) từ 39 job đã kiểm chứng: 3,99 tiếng/giây ở tốc độ thường, job khác atempo được quy đổi
về 1,15× thay vì trộn thô; video meme dành 88,8% thời lượng cho lời đọc. Trọng số critic chờ điểm chấm thật (benchmark), hiện
weighted_score chỉ được ghi lại, không quyết định sửa/đạt. Bổ sung hình đạo cụ còn đang là thẻ tên.
Các việc cài máy khác và nhiều video song song vẫn ngoài phạm vi nâng cấp này.

## Giới hạn phải giữ khi bàn giao

Điểm critic và test schema chỉ kiểm soát cấu trúc; chưa thay thế đánh giá tiếng cười của người xem.
Chưa chạy AI trên toàn bộ20 benchmark. TTS chưa có diễn xuất riêng theo vai; vật thể chuyển/giấu/lộ
bằng trạng thái đặt/cầm/ẩn và cử chỉ, không mô phỏng vật lý/ngón tay. Đạo cụ chưa có ảnh dùng thẻ tên minh họa.
Adapter dữ liệu Pillow cũ giữ lời và file gốc, dùng rig trung tính khi không còn danh tính nhân vật.
Chưa commit hoặc push trong đợt nâng cấp này.
