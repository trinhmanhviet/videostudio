# Xưởng nội dung — thiết kế đã duyệt, 2026-11-07

**Một theme duy nhất đã chốt:** navy + xanh nhạt, theo mockup Phòng thử giọng được duyệt ngày 2026-11-13.
Nền #101827, panel #1b293c, đường viền #35445b, chữ #f3f6fa,
chữ phụ #a8b7c9, điểm nhấn #79c9ef. Tất cả màn dùng chung bảng màu này; không làm thêm phương án màu hay bộ chọn theme.
Các mockup cho những màn khác chỉ mô tả bố cục/chức năng, giữ nguyên theme đã chốt.
Menu chung Tạo video / Hàng đợi / Kho video / Lịch đăng / Kho tài nguyên / Cài đặt.

## Điều hướng gọn — duyệt ngày 2026-11-13

Trang mặc định là **Tạo video**, dùng chung cho một hoặc nhiều kịch bản. Không còn mục Dự án trên menu chính.
Hàng đợi quản lý tiến độ và phục hồi; Kho video quản lý thành phẩm và các bản xuất.
Mở **Chi tiết** từ hai nơi này dùng lại workspace hiện có và lọc đúng job được chọn.
Giữ project/checkpoint/API bên dưới; dữ liệu cũ vẫn mở được qua `/?view=projects` và phần trợ giúp trong Cài đặt.

Kế hoạch triển khai nhỏ: (1) đổi menu/trang mặc định và liên kết phụ;
(2) nối Chi tiết vào workspace, giữ đường quay lại và lọc đúng job;
(3) kiểm tra JavaScript, test giao diện hiện có và regression cho lọc job, không chạy video hay AI.

Mục tiêu: nhập lô cùng phong cách và thời lượng, chạy lần lượt qua pipeline hiện có, quản lý thành phẩm
và các phiên bản, duyệt bản để tải hoặc lên lịch theo kênh. UI dự án/tạo video, editor và tài nguyên
theo mockup đã duyệt. Trạng thái hệ thống thu gọn và có hành động phục hồi khi cần.

## Kế hoạch thực hiện

### Triển khai mockup đã duyệt — 2026-11-13

Người dùng duyệt bố cục Phòng thử giọng, Tạo video, Hàng đợi, Chi tiết video. Tất cả dùng font/nút theo mockup Tạo video và duy nhất theme navy/xanh nhạt. Không commit/push, không thay renderer hoặc phiên đang chạy. Chỉ restart backend khi không có job video/ảnh/đọc thử hoạt động.

- [x] **Tạo video:** module `static/studio-create.js`/CSS mới, giao diện hai cột danh sách/editor và thiết lập chung. Nhớ tuỳ chọn video trước, tự lưu nháp văn bản/thứ tự/tuỳ chọn. Ô số phút điền từ ước tính giọng/nội dung, tiếp tục cập nhật đến khi người dùng tự sửa; có nút trở về tự tính. Giữ mọi trường payload/import/idempotency/override từng mục, chọn nhiều/áp dụng chung/nhân bản/xoá/đổi thứ tự/lưu nháp và xếp hàng. Test JS cho draft, lựa chọn, phút override và retry không gửi trùng.
- [x] **Bộ đọc KhanhTTS:** adapter bổ sung trong `speech_engine.py`/worker riêng, request `speech_engine` (vieneu mặc định/khanhtts), `khanh_steps` (16/32), `speech_rhythm` (natural/story), `speech_speed`. Giữ hành vi VieNeu cũ khi request không có trường mới, cache bao gồm lựa chọn ảnh hưởng âm thanh, WAV/timing riêng từng utterance. Reference preset lấy từ sample + transcript đã xác minh, không tải ASR. Test không tải model, thử GPU ngắn sau cùng.
- [x] **Phòng thử giọng:** frontend `voice-workspace.js`/CSS và service/API riêng. Dùng thư viện giọng thật; tìm/lọc/yêu thích, clone giữ API hiện có, văn bản/TXT, VieNeu/Khanh, tham chiếu sắc thái thực, nhịp/tốc độ/chất lượng, tạo/nghe/tải MP3-WAV/lưu/đổi tên/xoá/dùng lại thiết lập. Tác vụ bền vững, chờ GPU rảnh, không chạy đè job video, không chạm ba giọng riêng phải giữ. Test service/API và UI logic, không sinh âm thanh thật trong unittest.
- [x] **Hàng đợi/Chi tiết:** giữ backend đang có và các hành động cũ, bổ sung UI theo mockup. Đồng bộ theme/font/nút, summary/stepper, timeline trạng thái, từng tab nội dung/tài nguyên/bản xuất, grid ảnh + inspector và phục hồi đúng bước. Các nút đổi provider phải dùng API resume/reset hiện có phù hợp và giữ checkpoint, hoặc ghi rõ tạo lượt mới nếu tác vụ đó thực sự tạo mới.
- [x] **Tích hợp/nghiệm thu:** đã tích hợp, nạp bản chạy và được người dùng/Gemini xác nhận nghiệm thu ngày 2026-11-14; phạm vi và kết quả báo cáo ghi bên dưới. Không lặp lại test hoặc restart để xác nhận lại báo cáo này.

### Rà soát UI/UX ngày 2026-11-13 — cơ sở của bản triển khai

Phạm vi kiểm tra: mã HTML/CSS/JavaScript và luồng hiện hành, đối chiếu ảnh người dùng; chưa nghiệm thu trực tiếp browser hay các kích thước màn hình. Giữ navy hiện tại và backend/worker/checkpoint đang chạy; thay đổi UX làm theo từng màn, không đổi renderer trong đợt này.

**Phòng thử giọng đã duyệt về bố cục:** [mockup](mockups/voice-workspace-20261113.png). Ba cột: thư viện giọng dạng dòng nhỏ có tìm/lọc/yêu thích → nhập văn bản, chọn VieNeu/KhanhTTS, nhịp đọc, tốc độ và tạo bản đọc → lịch sử audio có tải MP3/WAV, đổi tên, xoá, dùng lại thiết lập. Tác vụ audio dùng độc lập, không cần tạo video. Giữ manhviet, Vương Bờm và Gấu hài hước. Chỉ hiện tuỳ chọn thực sự có tác dụng theo engine; 16/32 bước riêng KhanhTTS. Sắc thái theo audio tham chiếu, nhịp B là khoảng nghỉ; không giả có điều khiển cảm xúc bằng style hay bật các thẻ người dùng đã bác. Đây là mockup, chưa phải chức năng đã tích hợp. Metadata giới tính/vùng miền trong hình chỉ là minh hoạ; triển khai lấy từ catalog thật.

| Ưu tiên | Màn | Nhận xét từ mã hiện tại | Đề xuất |
|---|---|---|---|
| Cao | Tạo video | Mỗi mục lặp sáu nhóm cài đặt, batch TTS hiện ở phần chính. `rememberRow()` chỉ giữ cài đặt; nội dung lô ở `state.batchRows`, chưa thấy lưu nháp khi nhập. | Cài đặt chung + áp dụng nhiều mục; danh sách kịch bản thu gọn và chỉ mở mục đang sửa; batch sang nâng cao nhưng vẫn chỉnh được; tự lưu nháp/khôi phục sau F5. Giữ kéo thả file/thư mục và sửa riêng từng video. |
| Cao | Chi tiết video | Đang tái dùng `viewWorkspace`/`renderProjectJobs` cũ; đã lọc đúng job nhưng các chức năng rải ở hero, job card, scene editor và editor riêng. | Một trang theo video: trạng thái/bước hiện tại và hành động chính trên cùng; tab kịch bản, hình, âm thanh, phụ đề, bản xuất. Cho biết phần đã giữ và bước sẽ chạy lại. Không xoá các công cụ phục hồi hiện có. |
| Cao | Hàng đợi | Đã nhóm đang chạy/chờ/cần xử lý/đã xong. `queueAction(retry)` tiếp tục item, nhưng `rerunItem()` gọi POST `/api/factory/batches` để tạo lô mới khi đổi provider. | Giữ bố cục nhóm; làm rõ “Tiếp tục từ bước…” khác “Tạo lượt mới bằng…”, tránh hiểu nhầm chạy tiếp sẽ không mất công đoạn đã có. Không tự thay semantics retry trong lúc sửa nhãn. |
| Vừa | Kho video | Đã có lọc/phân trang, bản xuất, player chuyển dọc/ngang, Sổ đăng và đã đăng & dọn. | Giữ player hiện tại; làm card nhẹ hơn, rõ bản xuất đang chọn và thao tác chính; thêm chọn nhiều để tải/dọn khi triển khai API an toàn tương ứng. Không đưa lại form xác nhận dài đã bỏ. |
| Vừa | Kho tài nguyên/nhân vật | Đang dùng chung grid/inspector cho nhiều loại, trong đó giọng không cần thumbnail lớn. Phòng nhân vật và tài nguyên là các trang/iframe riêng. | Giọng dùng mockup đã duyệt; hình/đạo cụ/nền vẫn giữ grid. Đồng bộ tìm kiếm, thanh công cụ, trạng thái lưu và thông báo lỗi giữa các phòng; không ép mọi loại tài nguyên thành cùng một dạng danh sách. |
| Vừa | Cài đặt và bảng nổi | Cài đặt vẫn chứa clone giọng, cùng kết nối tạo nội dung và kênh đăng. Bảng nổi extension còn liệt kê nhiều session bên cạnh Hàng đợi. | Quản lý giọng tập trung ở Phòng thử giọng; Cài đặt giữ hệ thống/kênh. Bảng nổi ưu tiên kết nối và tác vụ cần can thiệp, giữ các nút mở Chrome/phục hồi; tránh lặp cả danh sách thành phẩm. |
| Sau | Bàn dựng / meme | Đã có preview, timeline/filmstrip, inspector và trạng thái chưa lưu. Meme preview là MP4 đã xuất, cần xuất lại để thấy chỉnh sửa. | Tinh chỉnh trạng thái bản đang xem so với thay đổi đã lưu/chưa xuất, phạm vi sửa cảnh/tập, thuật ngữ và đường quay về. Không làm lại toàn bộ timeline hoặc hợp nhất renderer. |
| Sau | Lịch đăng | Đã có tuần/danh sách, trạng thái kênh và UTC+7. | Chỉ tinh chỉnh sau khi nghiệm thu đăng thật; hiện chưa cần thiết kế lại. |

**Điểm cần sửa về mobile:** menu chính hiện sáu mục nhưng CSS `.studio-nav` dưới 760px vẫn chia cố định bảy cột, nhãn 9px. Kho tài nguyên lại dùng navigation ngang ở breakpoint khác. Cần thống nhất điều hướng di động, bớt mục hiển thị trực tiếp và dành chỗ cho nội dung; đây là phát hiện từ CSS, chưa phải kết quả nghiệm thu trên điện thoại.

Thứ tự đề xuất: Phòng thử giọng đã duyệt → Tạo video → Chi tiết/Hàng đợi → Kho video/tài nguyên/Cài đặt → tinh chỉnh editor và lịch. Menu Kể truyện chưa có màn hoạt động để rà soát; bố cục gameplay và tiêu chí giọng đã lưu ở TODO, không coi là đã triển khai.

- [x] Dữ liệu lô và hàng đợi trong jobs.sqlite3. Mỗi mục có request cố định, khóa idempotency và checkpoint job hiện có.
  Tạm dừng sau video hiện tại, đổi thứ tự mục chờ, giữ lỗi riêng và tiến hành mục kế khi tài nguyên đã rảnh.
  API dùng lại admission/preflight/bridge của /api/jobs. Kiểm thử mất phản hồi, resume, thứ tự và pause.
- [x] Kho thành phẩm có lọc/phân trang, các bản xuất, duyệt bản theo hash, trạng thái đăng theo kênh,
  tải MP4/caption/subtitle theo lựa chọn. Chỉ chấp nhận bản thật đã verified.
- [x] Giao diện chính navy theo mockup, form tạo đơn/nhập lô, preview kịch bản trước khi xếp hàng,
  dự án, hàng đợi, kho video, lịch và cài đặt/kết nối. Tái sử dụng chức năng tạo job/dự án đang có.
- [ ] Editor video lớn, filmstrip và một inspector theo mục đang chọn. Kho nhân vật/đạo cụ/nền/giọng
  dùng chung giao diện tài nguyên, giữ các thao tác upload/gán/chỉnh/căn/tải đã có.
- [x] Lịch SQLite bền vững theo giờ Việt Nam và bản video đã duyệt. Adapter đăng chỉ hoạt động khi
  tài khoản có quyền và kết nối thật. UI thể hiện riêng chờ kết nối, gửi đi, đã đăng, lỗi, chưa rõ kết quả.
  Không tự đăng bài trong lúc nghiệm thu. YouTube có lịch native; TikTok cần quyền/dịch vụ phù hợp.
- [ ] Hồi quy API/worker/bridge, UI đọc dữ liệu thật, kiểm tra thao tác browser khi được môi trường hỗ trợ.
  Nạp backend khi không có job hoạt động. Không commit/push nếu người dùng chưa yêu cầu.

Rà soát 2026-11-08: lô/hàng đợi, kho video, lịch, giao diện navy và kho tài nguyên đã chạy trên dữ liệu thật.
Hàng đợi bổ sung ảnh thu nhỏ, lọc theo phong cách, tìm kiếm, cột độ dài, video mới nhất ở trên; các trang hiện
"Đang tải…" khi chờ dữ liệu; trang dự án bỏ emoji, tiêu đề video lấy từ ý tưởng, nút Workflow chuyển lên đầu trang.
Còn lại: editor video lớn/filmstrip chưa rà soát so với mockup; đăng thật chờ người dùng kết nối YouTube/Facebook Page.
Ảnh cảnh mặc định ComfyUI vì Flow đang bị chặn.

## Quyết định vận hành

### Đã đăng & dọn — Sổ đăng

Trong Kho video hoặc cửa sổ xem video, chọn **Đã đăng & dọn**, rồi xác nhận trong popup một bước;
không cần nhập tên/kênh/ngày/link. Tool lấy metadata đã có; bài đăng qua scheduler giữ kênh và link thật,
bài đăng thủ công chưa lưu thông tin được ghi là Khác, thời gian là lúc xác nhận. Nút cuối là xác nhận của người dùng,
không phải tín hiệu upload tự động. Tính năng không tự đăng bài hay tự đánh dấu các video sẵn có.

Sổ đăng nằm trong Kho video, có tìm kiếm không dấu, lọc nền tảng và phân trang 10/20/30.
Nó giữ metadata bài đăng và biên nhận chống thao tác trùng; nội dung job, checkpoint, prompt riêng,
ảnh, audio, video, phụ đề và media nhập riêng của job được dọn. Giữ tài nguyên/giọng/model dùng chung
và số đo tốc độ giọng dạng số nhỏ gọn. Nếu job khác còn dùng nguồn, lịch đăng chưa kết thúc,
ảnh cảnh chưa rõ kết quả hoặc editor/social writer đang chạy, thao tác bị chặn trước khi xóa.

Tệp được chuyển vào vùng cách ly của đúng ổ đĩa với journal phục hồi. Nếu giao dịch thất bại,
khôi phục file; sau commit mới xóa vật lý. File đang bận hiển thị **Chờ dọn**, được thử lại có backoff
và có nút thử lại thủ công trong Sổ đăng. Khởi động lại backend tiếp tục dọn các biên nhận đã commit,
không tạo lại job. Các API ghi chỉ nhận yêu cầu cùng origin/loopback và không nhận đường dẫn tùy ý.
Không có tác vụ dọn video thật nào được chạy trong kiểm thử; các test dùng SQLite/file tạm.

Sửa timeout: HTTP trả ngay sau khi commit biên nhận/chuyển file, phần xóa vật lý chạy nền và được
đánh thức ngay. Kiểm tra chia sẻ cache kết quả resolve theo đường dẫn trong từng lượt, không bỏ guard
symlink/junction. Nếu mạng/HTTP timeout/5xx, UI tự GET đối soát receipt rồi retry đúng body/key cũ,
tối đa 3 POST trong 3 phút; lỗi 409/422 không tự thực hiện lại. GET status không ghi/xóa dữ liệu.
Phép đo chỉ đọc trên cùng job giảm bước shared validation 44,226 → 5,525 giây; không dùng video thật để thử xóa.

Kiểm tra 2026-11-12: 21 test service dọn/phục hồi, 4 test tích hợp API và 42 test UI/import đạt;
hồi quy lifecycle (22), hàng đợi (31), publishing (12), scene editor (17), edit plan (11), timing giọng (10) đạt.
Có một assertion fixture kịch bản hài cũ (`test_single_beat_repair_does_not_rewrite_other_lines`) vẫn lỗi;
đã tái hiện cùng lỗi khi nạp `core.py` từ HEAD, không chỉnh pipeline hài trong tính năng dọn.

Kiểm tra trước merge 2026-11-12: toàn bộ Python 1008 test, chỉ còn assertion fixture hài nêu trên;
toàn bộ test JavaScript đạt. Runtime/model/audio thử/database/profile nằm trong data hoặc ngoài repo,
không đưa lên Git. Bộ gói CUDA tùy chọn được ghim trong app/requirements-speech-cuda.txt để tái lập môi trường.

### Nhập kịch bản và thời lượng theo giọng (2026-11-11)

Các form tạo đơn/hàng loạt và node giọng trên Workflow cho nhập **Batch giọng đọc**: mặc định **256**,
số nguyên **1–512**, không yêu cầu bội số 16. Lưu riêng theo request/video; CPU/ONNX vẫn xử lý tuần tự.
Thay batch không vô hiệu hóa WAV/receipt đúng đã có. Request cũ không bị tự thêm trường mặc định khi retry.
Màn xem video dùng một player, đổi định dạng Dọc/Ngang và cập nhật đúng link tải; form hàng loạt căn ô 42px,
3/2/1 cột theo màn hình, giữ thao tác nhập file/thư mục và bộ đếm từ/ký tự.

Trang Tạo hàng loạt dùng ô nhập nhỏ: bấm để chọn một/nhiều TXT hoặc JSON, hoặc kéo thả file/thư mục.
Thả ở bất kỳ đâu trên giao diện chính sẽ mở Tạo hàng loạt và dùng cùng luồng nhập, không tự chạy video.
Mỗi bài hiển thị số từ/ký tự và có lựa chọn ảnh riêng: ComfyUI, Google Flow, ChatGPT hoặc Meta AI;
video meme vẫn dùng bộ asset của engine và hiển thị rõ lựa chọn ảnh không áp dụng.
Thư mục được đọc cả các thư mục con; nội dung vẫn hiện thành các hàng chỉnh sửa trước khi người dùng xếp hàng.
Trên điện thoại có nút chọn file và chọn thư mục (khả năng chọn thư mục tùy trình duyệt).

Thời lượng tự tính dùng tốc độ của đúng giọng: ưu tiên các video hoàn tất đã kiểm chứng, sau đó đến
mẫu preview có lời đọc và danh tính giọng khớp. Nhịp phát nhanh/chậm trong dữ liệu cũ được chuẩn hóa.
Không chạy thêm AI hay tạo lời đọc để đo. Nếu chưa có số đo đáng tin, UI ghi rõ tạm tính.
Mỗi video có thể đổi sang Tự nhập thời lượng; đổi giọng hoặc sửa kịch bản không ghi đè số nhập tay.
Đây là ước lượng/mục tiêu sản xuất: video có lời đọc sẵn vẫn giữ đủ lời, timeline cuối theo audio thật,
không cắt lời chỉ để khớp tuyệt đối số giây đã nhập.

Chạy tuần tự là mặc định. Người dùng duyệt thành phẩm trước khi đăng. Một video có nhiều bản xuất và nhiều trạng thái kênh.
Lịch ghim đường dẫn/hash bản được duyệt, không tự chuyển sang bản mới. Lịch local cần máy chạy để gửi bài;
nơi hỗ trợ lịch native sẽ nhận video trước giờ công khai. Các bước cần kết nối tài khoản được hiển thị để người dùng hoàn tất.

Các hình duyệt nằm trong C:/Users/leath/.codex/generated_images/01a17e49-04b8-70a3-a3ad-c87d41485c8a/:
exec-1bcd88e4-7777-4b82-879c-8588d055cd43.png (màu A),
exec-162519fd-d144-4e40-8d9a-796e7b7a368e.png (hàng đợi),
exec-eaf24d73-1b1a-4c68-b1f5-f97ebf365869.png (kho video/lịch),
exec-42a461ee-8fba-4c02-97be-8206c29ec031.png (editor),
exec-21bfd7c3-2a68-4248-9cfb-5862b4e45d5e.png (tài nguyên).


## Trạng thái bàn giao UI — 2026-11-13

Bốn màn Phòng thử giọng, Tạo video, Hàng đợi, Chi tiết video đã triển khai và nạp vào backend thật cổng 8877 khi active_jobs=0. Font/nút dùng cùng bộ theo Tạo video; một theme navy/xanh nhạt. Giọng riêng manhviet, Vương Bờm, Gấu hài hước giữ nguyên. Không commit/push. Không chạy lại video AI đầy đủ.

Kiểm tra đã thực hiện trước khi người dùng yêu cầu dừng mở rộng: 1.042 Python test có đúng một lỗi cũ `test_single_beat_repair_does_not_rewrite_other_lines`; các test bổ sung JobDetails/guard sau đó đạt. 142 JavaScript test đạt. Browser fixture riêng cổng 8891, worker tắt: nhập phút/override/F5/nhớ tuỳ chọn/import TXT/xếp lô qua API; tìm/phân trang cảnh/các tab; voice search/favorites/giọng riêng/import tham chiếu/queued task/MP3-WAV/save/rename/reuse; layout 1920×1080 và 390×844. Hai đoạn đọc THẬT khoảng 5 giây đã qua API/worker production: VieNeu và KhanhTTS, kiểm tra WAV+MP3 giải mã, không clipping. Log ở `data/ui-qa-20261113/live-speech.json`. Backend/browser fixture đã đóng; bản thử không sửa DB video thật. Ảnh/audio fixture chỉ minh hoạ kiểm tra UI, không phải bằng chứng chất lượng giọng.

Giới hạn cần giữ rõ: ảnh đang tạo dở chỉ xem tiến độ, phải hoàn tất checkpoint mới chỉnh riêng bằng scene editor. Đổi provider qua reset-images tạo lại TOÀN BỘ ảnh sau xác nhận, giữ script/speech/music/subtitles; resume cùng job giữ những tài nguyên hợp lệ. Khanh dùng reference preset cục bộ (chuẩn bị bằng VieNeu lần đầu nếu thiếu); clone cần đúng transcript hoặc mẫu riêng, không tải ASR. Khanh chia lô GPU nội bộ tối đa 8; batch yêu cầu không đồng nghĩa số câu đồng thời của mọi engine. Lịch sử audio đã mở xem/nghe/tải dùng chung mọi browser từ 2026-11-14; thao tác sửa/xoá vẫn giữ scope browser tạo. Chưa triển khai menu Kể truyện/gameplay.

Theo yêu cầu mới của người dùng: hạn chế tự kiểm tra; mặc định bàn giao kèm prompt để Gemini/người dùng nghiệm thu. Không tự lặp full suite, chạy thêm video, sinh nhiều clip hay tiếp tục thử GPU nếu không được yêu cầu. Guard không restart khi có tác vụ vẫn bắt buộc. Các thay đổi cuối ở guard admission Khanh và ghi chú retry được nối/nạp sau lượt hồi quy lớn; để Gemini kiểm tra, chưa tuyên bố đã nghiệm thu hết.

## Kết quả nghiệm thu người dùng/Gemini cung cấp — 2026-11-14

Người dùng xác nhận đã kiểm tra xong bản cập nhật và gửi kết quả sau. Đây là báo cáo được tiếp nhận, không phải một lượt kiểm tra mới do Codex thực hiện.

- Bộ Python mới được báo cáo **35/35 PASS**: `test_voice_studio.py` 10, `test_speech_engine.py` 12, `test_job_details.py` 9, `test_voice_integration_guards.py` 2, `test_media_motion.py` 2.
- Bộ JavaScript chọn lọc được báo cáo **43/43 PASS**: `studio-create.test.mjs`, `studio-details.test.mjs`, `voice-workspace.test.mjs`, `content-studio-ui.test.mjs`.
- Runtime 8877 hoạt động; API Phòng thử giọng nhận đúng `X-Voice-Owner` và trả HTTP 200; API Chi tiết video đã live.
- `active_jobs=0` tại thời điểm người dùng/Gemini kiểm tra. Không dùng số này làm bảo đảm hệ thống vẫn rảnh vào thời điểm khác hoặc thay cho guard trước khi restart.

Chốt nghiệm thu đợt UI/API này theo xác nhận của người dùng. Kết quả các bộ chọn lọc không thay thế kết quả toàn bộ suite; báo cáo này không xác nhận đã sửa lỗi cũ `test_single_beat_repair_does_not_rewrite_other_lines` từng ghi ở trên. Không chạy lại test, restart hay sửa thêm code trong lượt tiếp nhận này.

## Prompt nghiệm thu giao cho Gemini (2026-11-13)

Bạn là người REVIEW/NGHIỆM THU bản UI mới của VideoStudio. Repo THẬT: `D:\Projects\videostudio`; mã trong `app/`. Không dùng checkout cũ ở C, không đọc StoryForge. Người dùng yêu cầu bạn kiểm tra vì muốn giảm việc Codex tự chạy test. Chỉ báo lỗi, không tự sửa/commit/push/reset/checkout/restart/cài gói/tải model hay thay môi trường.

### 1. Phạm vi và bản thiết kế chuẩn

Đọc trạng thái bàn giao ngay phía trên. So sánh bốn mockup trong cùng repo:
- `docs/mockups/voice-workspace-20261113.png`
- `docs/mockups/create-workspace-20261113.png`
- `docs/mockups/queue-workspace-20261113.png`
- `docs/mockups/video-details-20261113.png`

Chỉ một theme navy + xanh nhạt. Lấy FONT và NÚT theo ảnh Tạo video; không đòi các ảnh AI dùng font giống nhau vì người dùng đã nhận ra ảnh không nhất quán. Bố cục, vị trí chức năng, nút và luồng sử dụng phải đủ. Không thiết kế thêm màu hay tính năng mới. Menu Kể truyện/gameplay/ảnh+motion không thuộc lượt này.

### 2. An toàn khi kiểm tra

Production ở `http://127.0.0.1:8877`, chỉ GET/điều hướng/nghe/tải dữ liệu đã có. Không bấm tạo video, thử lại, đổi provider, xuất, xoá/dọn hay clone trên dữ liệu thật. Nếu kiểm tra hành động ghi, dùng DB/output fixture riêng và worker tắt. Có sẵn script `data/ui_qa_server.py` để mở fixture ở 8891 (đã tắt sau QA); file kiểm tra và screenshot trong `data/ui-qa-20261113/`. Không restart backend/CDP/Comfy/Chrome. Không mở ChatGPT/Flow hay gửi prompt. Không chạy video dài, stress batch, full GPU benchmark hoặc tự sinh thêm audio; hai mẫu ngắn đã có log thật. Dùng Chrome/profile thử riêng, không đụng profile người dùng. Không xoá bất kỳ giọng riêng/reference/asset cũ nào. Không coi tín hiệu/giải mã đạt là bằng chứng giọng hay hoặc đọc đúng mọi chữ.

### 3. Kiểm tra Tạo video

Nguồn chính: `app/static/studio-create.js`, CSS tương ứng, `content-studio.js`, `studio-unified.css`.
- Có header và thiết lập chung: phong cách, bộ đọc, giọng + nghe mẫu, ảnh, số PHÚT, nhịp đọc, nâng cao, áp dụng mục đã chọn.
- Với một video, thay lựa chọn chung phải thực sự đổi cấu hình gửi; nhiều video chỉ áp dụng cho mục được chọn và giữ override riêng.
- Phút mặc định là số tool ước tính theo văn bản/giọng/tốc độ. Nếu chưa sửa thì cập nhật khi nội dung/giọng đổi. Khi gõ trực tiếp (kể cả đúng bằng số tự tính) chuyển manual và giữ nguyên; có Tự tính để reset. Chặn rỗng/0/âm/NaN. Gửi backend bằng giây, ví dụ 3,5 phút = 210 giây.
- Nhớ đầy đủ tuỳ chọn video trước, gồm engine, voice, rhythm/speed, steps/batch và phút manual. Thêm/nhân bản/import/đổi thứ tự không làm mất cấu hình. Không đem transcript của giọng clone cũ sang giọng khác.
- Lưu nháp cả nội dung, thứ tự, cài đặt, lựa chọn, bản gửi chưa xác định; F5 không mất bài. Giữ key/body khi retry mất phản hồi; không tạo trùng.
- Đủ kéo thả/click file, nhiều TXT/JSON/thư mục, chọn file/folder trên browser hỗ trợ; danh sách gọn, editor một bài, checkbox/chọn tất cả/áp dụng/nhân bản/xoá/lên xuống/lưu nháp/nút xếp hàng, số từ/ký tự/tổng thời lượng. Footer không che nội dung trên mobile.
- JSON import và tạo lượt mới giữ engine/steps/rhythm/speed/voice. Khanh clone thiếu transcript phải có lỗi có thể xử lý trước khi mắc ở hàng đợi; ô lời mẫu có trong Nâng cao khi chọn clone + Khanh.

### 4. Kiểm tra Hàng đợi và Chi tiết

Nguồn: `content-studio.js`, `studio-details.js/.css`, `videostudio/job_details.py`, route API hiện có.
- Đúng số đếm đang chạy/chờ/cần xử lý/hoàn tất; job đã nhận nhưng state queued không báo đang chạy. Giữ tìm/lọc, reorder mục chưa bắt đầu, dừng, bỏ qua, pause sau video hiện tại, tiếp tục queue, mở chi tiết và kho video.
- Phân biệt resume CÙNG job, tạo lượt mới, reset TOÀN BỘ ảnh. Thông báo và checkpoint được giữ phải khớp API thật, không có câu 'chạy lại từ đầu' đi kèm nút resume mà không giải thích.
- Chi tiết mở đúng job, có back, header/meta, folder (chỉ khi có video xác nhận), menu công cụ phục hồi, trạng thái/bước, lỗi, các tab kịch bản/hình/giọng-nhạc/phụ đề/bản xuất.
- Grid ảnh có tìm, lọc, chọn nhiều/tải, phân trang, inspector đúng cảnh/lời kể/prompt/provider. Có regenerate/upload/chọn kho/restore/candidate apply qua API có version/idempotency; trạng thái không đủ điều kiện phải khoá và nêu rõ lý do, không nút giả.
- Partial images dùng receipt + SHA để xem, không tạo checkpoint giả. Completed images/editor edits và bản dựng kế thừa phải hiển thị đúng ảnh/nhạc của nguồn đã chứng thực. Không truy cập path tuỳ ý hay ghi đè nguồn.
- Export chỉ bật khi đủ điều kiện; bản cũ giữ nguyên. Meme dùng phòng sửa meme, không ép vào editor không tương thích. Giữ đường mở phòng sửa cảnh/bàn dựng/công cụ phục hồi cũ.
- Mở mọi tab/đổi cảnh không mất text đang sửa, poll không giật focus; ảnh/video/audio không phát tiếp khi đóng màn. Kiểm tra thao tác thật, không chỉ tìm chuỗi nhãn trong mã.

### 5. Kiểm tra Phòng thử giọng

Nguồn: `voice-workspace.js/.css`, `resources.js/html`, `voice_studio.py`, `voice_studio_api.py`.
- Ba cột gọn: giọng dạng dòng/search/filter/favorites/private/pages/nghe mẫu; editor text/TXT+engine+voice+nhịp/tốc độ/chất lượng; lịch sử kết quả. Metadata thật, ba giọng riêng manhviet/Vương Bờm/Gấu hài hước còn nguyên.
- VieNeu/KhanhTTS chọn được, 16/32 bước chỉ hiện với Khanh. Không có cảm xúc/style giả hoặc ba thẻ cười/thở dài/hắng giọng mặc định. Nhịp B là khoảng nghỉ; sắc thái phụ thuộc reference.
- Thêm mẫu reference WAV + transcript đúng, nghe/lựa chọn/xoá theo điều kiện; không thay reference gốc. Clone hiện có vẫn mở được dialog, có guard GPU.
- Tạo audio ĐỘC LẬP, không tạo video. Có queued/running/completed/failed, cancel/retry, F5 theo dõi được. Đủ player/tua/MP3/WAV/lưu thư viện/đổi tên/xoá/dùng lại thiết lập/lọc saved/phân trang. Tải/play phải có bytes đúng và scope owner phù hợp; báo nếu history theo browser gây bất tiện, không tự đổi quyền.
- Bản tạo thật phải đi qua adapter/worker thật; backend không dùng file fixture làm âm thanh thật. Không thực hiện lại GPU test nếu không cần: xem `data/ui-qa-20261113/live-speech.json` và log.

### 6. Kiểm tra kỹ thuật và hồi quy có chọn lọc

`api.py` đăng ký service một lần; cùng serial worker, chờ video/ảnh/GPU rảnh; không thêm thread synth chạy đè. Guard active_jobs/system idle tính cả audio và clone. Cancel/shutdown không để worker con giữ GPU; restart phục hồi task an toàn. File serving/deletion chỉ đúng file task, không xoá voice/reference dùng chung. Không tải ASR/model tự động.

Adapter ở `speech_engine.py`, `khanh_speech_worker.py`, `speech_worker.py` và các điểm gọi providers/meme/factory/workflow/core. Request cũ không có field mới vẫn VieNeu cũ, cache WAV cũ vẫn reuse; engine/steps/reference hash+transcript/rhythm/speed phải tham gia cache mới. WAV từng utterance và thứ tự/timing giữ nguyên. Có thể xem log/test hiện có trước; không mặc định chạy full suite hoặc render thêm. Python backend là `C:\Python312\python.exe`, cwd chạy tests là `D:\Projects\videostudio\app` (không dùng Python miniconda mặc định). Media runtime VieNeu và runtime Khanh riêng trong `data/runtime`, không cài/upgrades vào chúng.

Đối chiếu desktop 1920×1080, laptop 1366×768 và mobile 390×844; chú ý horizontal overflow, footer che nút, popup/menu vượt màn, focus khi polling và cache asset cũ. Ảnh trong mockup là minh hoạ; ảnh dữ liệu thật có thể khác, không báo lỗi chỉ vì thumbnail khác ảnh AI.

### 7. Kết quả bắt buộc

Trả về tiếng Việt:
1. Lỗi thực tế theo P0/P1/P2, có file:dòng, các bước tái hiện, mong đợi/thực tế và nguyên nhân từ source/API. Không đưa nhận định chưa chứng minh thành bug.
2. Bảng đối chiếu các nhóm nút/chức năng mockup: Có/Thiếu/Sai điều kiện/Chưa kiểm chứng.
3. Screenshot thực tế cần thiết và cách kiểm tra đã dùng. Phân biệt đọc source với bấm UI, fixture với production, fake renderer với TTS thật.
4. Rủi ro ảnh hưởng pipeline/job/checkpoint cũ và phần đã ổn nên giữ.
5. Việc chưa kiểm chứng và thứ tự sửa đề nghị. Không nói 'đạt hoàn toàn' chỉ vì test pass hoặc chỉ nhìn mockup.

Chưa sửa code. Đưa báo cáo để người dùng quyết định giao việc sửa tiếp.


## Cập nhật nhanh Giây/Phút và lịch sử chung — 2026-11-14

- Đã thay các khối chuyển đơn vị Gemini đang sửa dở trong `studio-create.js`; bản trước sửa lưu ở `data/ui-quickfix-20261114/before`. Không git reset/restore và không bỏ các thay đổi UI/engine trước đó.
- Chọn Giây/Phút ở thiết lập chung và từng video; đổi đơn vị giữ tổng thời lượng, không làm tròn ép lên 1 giây; auto vẫn tính theo nội dung/giọng. Khi nhập số chuyển manual, F5/nháp/video kế tiếp nhớ cả đơn vị và số. Đã bỏ đoạn migration và refresh cũ ép mọi thứ về Phút.
- Lịch sử đọc thử dùng chung cho mọi browser, gồm cả bản cũ. GET history/detail/audio chia sẻ phần đọc; không chuyển owner, không copy hoặc xoá record cũ. Kiểm tra file/hash/đường dẫn giữ nguyên. Sửa/xoá/cancel/retry/reference vẫn giữ phân quyền cũ; UI khoá các nút ghi khi xem bản từ browser khác. Đây là phương án chia sẻ đọc an toàn sau khi auto-review từ chối mở cả quyền ghi/xoá chéo browser.
- Theo yêu cầu tiết kiệm usage: không chạy lại test suite, browser, video hay GPU. Chỉ kiểm tra cú pháp. Gemini kiểm tra tiếp: 90 giây ↔ 1,5 phút; 1 giây đổi qua lại; auto đổi đơn vị không thành manual; nhập override rồi sửa nội dung/F5; nhớ đơn vị video trước; dùng hai browser thấy cùng lịch sử cũ, nghe/tải được, phân trang/saved đúng; mutation vẫn theo owner gốc.
