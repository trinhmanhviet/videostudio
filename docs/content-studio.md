# Xưởng nội dung — thiết kế đã duyệt, 2026-11-07

Màu A: nền #101827, panel #1b293c, đường viền #35445b, chữ #f3f6fa,
chữ phụ #a8b7c9, điểm nhấn #79c9ef. Menu chung Dự án / Hàng đợi / Kho video / Lịch đăng / Kho tài nguyên.

Mục tiêu: nhập lô cùng phong cách và thời lượng, chạy lần lượt qua pipeline hiện có, quản lý thành phẩm
và các phiên bản, duyệt bản để tải hoặc lên lịch theo kênh. UI dự án/tạo video, editor và tài nguyên
theo mockup đã duyệt. Trạng thái hệ thống thu gọn và có hành động phục hồi khi cần.

## Kế hoạch thực hiện

- [ ] Dữ liệu lô và hàng đợi trong jobs.sqlite3. Mỗi mục có request cố định, khóa idempotency và checkpoint job hiện có.
  Tạm dừng sau video hiện tại, đổi thứ tự mục chờ, giữ lỗi riêng và tiến hành mục kế khi tài nguyên đã rảnh.
  API dùng lại admission/preflight/bridge của /api/jobs. Kiểm thử mất phản hồi, resume, thứ tự và pause.
- [ ] Kho thành phẩm có lọc/phân trang, các bản xuất, duyệt bản theo hash, trạng thái đăng theo kênh,
  tải MP4/caption/subtitle theo lựa chọn. Chỉ chấp nhận bản thật đã verified.
- [ ] Giao diện chính navy theo mockup, form tạo đơn/nhập lô, preview kịch bản trước khi xếp hàng,
  dự án, hàng đợi, kho video, lịch và cài đặt/kết nối. Tái sử dụng chức năng tạo job/dự án đang có.
- [ ] Editor video lớn, filmstrip và một inspector theo mục đang chọn. Kho nhân vật/đạo cụ/nền/giọng
  dùng chung giao diện tài nguyên, giữ các thao tác upload/gán/chỉnh/căn/tải đã có.
- [ ] Lịch SQLite bền vững theo giờ Việt Nam và bản video đã duyệt. Adapter đăng chỉ hoạt động khi
  tài khoản có quyền và kết nối thật. UI thể hiện riêng chờ kết nối, gửi đi, đã đăng, lỗi, chưa rõ kết quả.
  Không tự đăng bài trong lúc nghiệm thu. YouTube có lịch native; TikTok cần quyền/dịch vụ phù hợp.
- [ ] Hồi quy API/worker/bridge, UI đọc dữ liệu thật, kiểm tra thao tác browser khi được môi trường hỗ trợ.
  Nạp backend khi không có job hoạt động. Không commit/push nếu người dùng chưa yêu cầu.

## Quyết định vận hành

Chạy tuần tự là mặc định. Người dùng duyệt thành phẩm trước khi đăng. Một video có nhiều bản xuất và nhiều trạng thái kênh.
Lịch ghim đường dẫn/hash bản được duyệt, không tự chuyển sang bản mới. Lịch local cần máy chạy để gửi bài;
nơi hỗ trợ lịch native sẽ nhận video trước giờ công khai. Các bước cần kết nối tài khoản được hiển thị để người dùng hoàn tất.

Các hình duyệt nằm trong C:/Users/leath/.codex/generated_images/01a17e49-04b8-70a3-a3ad-c87d41485c8a/:
exec-1bcd88e4-7777-4b82-879c-8588d055cd43.png (màu A),
exec-162519fd-d144-4e40-8d9a-796e7b7a368e.png (hàng đợi),
exec-eaf24d73-1b1a-4c68-b1f5-f97ebf365869.png (kho video/lịch),
exec-42a461ee-8fba-4c02-97be-8206c29ec031.png (editor),
exec-21bfd7c3-2a68-4248-9cfb-5862b4e45d5e.png (tài nguyên).
