# Xưởng nội dung — thiết kế đã duyệt, 2026-11-07

Màu A: nền #101827, panel #1b293c, đường viền #35445b, chữ #f3f6fa,
chữ phụ #a8b7c9, điểm nhấn #79c9ef. Menu chung Dự án / Hàng đợi / Kho video / Lịch đăng / Kho tài nguyên.

Mục tiêu: nhập lô cùng phong cách và thời lượng, chạy lần lượt qua pipeline hiện có, quản lý thành phẩm
và các phiên bản, duyệt bản để tải hoặc lên lịch theo kênh. UI dự án/tạo video, editor và tài nguyên
theo mockup đã duyệt. Trạng thái hệ thống thu gọn và có hành động phục hồi khi cần.

## Kế hoạch thực hiện

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
