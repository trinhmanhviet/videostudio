# Bàn dựng tùy chọn và Workflow canvas

Cập nhật: **2026-11-03**. Đây là tài liệu duy nhất cho phần bàn dựng mới/workflow: trạng thái, hướng dẫn dùng, thiết kế, schema, API, cơ chế render và kế hoạch nghiệm thu được cập nhật tại đây.

**UI cũ và luồng tạo video hiện hành được giữ nguyên.** Bản mới đã qua kiểm tra fixture/browser; nghiệm thu video AI dài và restart Windows vẫn do người dùng thực hiện riêng. Không tự chuyển request cũ sang bộ dựng/preset/nhạc mới.

## Mục lục

1. [Trạng thái, bằng chứng và việc còn lại](#status)
2. [Hướng dẫn dùng editor, preset, âm thanh và canvas](#guide)
3. [Kiến trúc, JSON schema, API, lưu trữ và cache](#architecture)
4. [Hợp đồng tích hợp và tiêu chí hoàn thành](#implementation)
5. [Kế hoạch thêm animation bằng asset và code — chưa triển khai](#code-animation)

README chỉ giữ cách khởi động và đường dẫn vào tài liệu; TODO giữ các việc chưa làm. Không tách thêm guide/architecture/status/spec/plan riêng cho tính năng này.


<a id="status"></a>
## Trạng thái, bằng chứng và nghiệm thu

### Trạng thái tổng thể

**Đã triển khai và nghiệm thu bằng dữ liệu tổng hợp**, gồm lưu kế hoạch, dựng MP4 thật và thao tác workflow trên trình duyệt. UI mới là lựa chọn thêm; Studio cũ vẫn là mặc định. Nhánh triển khai: `codex/editor-workflow`; checkout sử dụng hằng ngày: `D:\Projects\videostudio`.

Nghiệm thu video AI dài và restart Windows do người dùng thực hiện sau, theo thỏa thuận. Các phép thử dưới đây không thay thế hai nghiệm thu đó và không gọi provider AI thật.

### Đã có code

| Hạng mục | Hiện trạng |
|---|---|
| `edit_plan.json` | Schema/revision/sidecar, scoped assets, import và waveform, immutable child export |
| Ba preset | Documentary/Science/Everyday; áp dụng local, không thêm LLM |
| Nhạc chương | Nhóm theo speech/chapter, stable receipts, reuse, crossfade/normalization |
| SFX | Bốn sample procedural, source/license/hash, placement thưa, mixer |
| Renderer | Image/video layers, camera/crop/opacity/transition, transparent text theo stack, captions/emphasis, mux/verify/cache |
| Editor UI | Library, preview, inspector, multi-track timeline, drag/trim/split, chữ, undo/redo, save/export/status |
| Workflow | Typed graph, CRUD/history, compiler, canvas kéo/nối/config, templates/JSON/Run |
| Legacy compatibility | Opt-in mới; request cũ không tự bật renderer/music mới; UI cũ chỉ thêm entry tùy chọn |

Các thành phần được kiểm tra bằng schema/API/model tests, media tổng hợp thật và các thao tác trình duyệt ghi dưới đây.

### Bằng chứng đã quan sát

- Full Python: **619/619 đạt** (`python -m unittest discover -s tests -q`, 111,3 giây). Sau đó bổ sung assertion route Studio/editor/connector-test và chạy lại nhóm integration **5/5 đạt**; source backend không đổi sau lượt full.
- Full JavaScript: **139/139 đạt**, gồm toàn bộ test extension và `tests/*.test.mjs`, chạy lại sau sửa preview cuối.
- Renderer dùng MP4 thật, decode toàn bộ, so pixel thứ tự ảnh/chữ, motion/transition, thời gian, cache reuse và giữ hash nguồn.
- Nhạc/SFX dùng WAV thật để kiểm tra timing, fades/gain/mute, ducking, batching và stem reuse. Manual quiet mix không bị coi nhầm là model sinh âm thanh lỗi.
- Test cũ phụ thuộc voice inventory/batch receipt của máy chính đã được thay bằng fixture cục bộ, không sửa admission/voice production để chiều test.
- Log cục bộ: `data/final-python-tests.log`, `data/final-js-tests.log` (không đưa vào Git).

#### Nghiệm thu browser đã làm

Trên dữ liệu tổng hợp riêng tại localhost:8886:

1. Mở library, preview, inspector và timeline.
2. Chọn clip và đổi motion, lưu revision.
3. Thêm/sửa chữ `KHÁM PHÁ VŨ TRỤ`, xác nhận label trên timeline.
4. Undo/redo lấy đúng nội dung trước/sau.
5. Kéo clip và cắt mép, thấy timing đổi; lưu draft.
6. Bấm Xuất video từ UI → child job → worker fixture render/verify → **completed**; UI hiện link tải MP4.
7. Mở canvas, chọn node, cấu hình idea/duration/provider/voice và tắt nhạc; tham chiếu tự tắt khi chọn provider ảnh không hỗ trợ native ref.
8. Save graph thành revision 1, kéo node và lưu revision 2; ngắt/nối lại dây speech → captions.
9. Nhân bản, xuất JSON xuống file rồi nhập lại; UI xác nhận đã nhập/lưu workflow riêng.
10. Run tạo job thử `24c39776-dee2-4a69-88ec-9baeb0a65229`; đọc request xác nhận idea/duration 8 giây, voice fixture, Comfy batch 1, refs=false, music=false, sfx=true và graph có tọa độ node mới.
11. Bản xuất cuối `3b2efde8-5176-4c5d-8097-333bda0f4c8c` đã qua Worker render/verify → completed bằng renderer cuối; UI hiện link tải MP4.
12. Responsive desktop 1440×900 và khung hẹp đã được kiểm tra; viewport thử đã trả về mặc định.

Workflow Run đi qua API admission hiện hành; fixture chỉ giả preflight và không chạy model. Route mặc định, route workspace tùy chọn và connector-test có kiểm tra integration riêng.

#### Lỗi đã tìm và sửa trong quá trình thử

- Slider set value trước min/max/step làm tròn sai: đã sửa thứ tự khởi tạo.
- Select bị ép qua Number tạo NaN: giữ string cho enum.
- Text nhập chưa vào model trước save/undo: đồng bộ input và giữ focus khi redraw.
- Save response cũ ghi đè phần vừa gõ: giữ newer draft, tăng revision server đúng.
- Pointer-up bỏ sample cuối: áp tọa độ cuối khi kéo/cắt.
- Registry đọc `speech.scenes.path` không tồn tại: chấp nhận metadata scene không có file path.
- Mỗi lần stream một media lại rehash toàn bộ nguồn: chỉ kiểm tra asset được phục vụ; save/export/render vẫn kiểm tra đủ.
- Nhạc nhỏ user chọn bị hiểu nhầm là model sinh âm thanh lỗi: verify manual mix phân biệt chủ ý.
- Service không nhận executable FFmpeg/FFprobe cấu hình riêng: đã truyền từ pipeline.
- Preview dissolve tối/khác export: căn hold frame + entry alpha; video trim giữ frame cuối.
- Text luôn nằm trên mọi ảnh trong export: dùng PNG alpha thật và compose đúng track; pixel regression đạt.

### Phạm vi nghiệm thu và giới hạn

- Bàn dựng có thao tác thực trên media/timeline; các cửa sổ render dài được chia theo đoạn 30 giây, tối đa 24 decoder mỗi lượt compose. Preview chuẩn bị chỉ mục lớp khi nạp plan, giữ tối đa 32 ảnh cache không active, giải phóng audio/video đã ra khỏi đoạn đang phát.
- Preview thể hiện motion, crop, alpha, Z-order, subtitle và phát audio; đây là preview thời gian thực, không hứa khớp từng sample/font với FFmpeg. Âm lượng preview HTML audio giới hạn 100%; gain trên 100% vẫn được áp dụng đầy đủ khi xuất. Độ chính xác cue theo câu, không timing từng từ.
- Text dài được wrap trong vùng 86% chiều rộng bằng libass; renderer text cache đã đổi version để không dùng lại frame chữ cũ. Pan và caption scale có regression test.
- Cache media trên đĩa chưa có chính sách dọn tự động tổng quát. Không xóa asset được child export tham chiếu. Thư viện SFX có metadata nguồn; nếu đổi thuật toán sinh mẫu, cần version/migrate cache.
- Workflow hiện dùng các provider và thứ tự pipeline đã tích hợp; không phải trình chạy code/node tùy ý. Video song song thật, cài máy khác và nghiệm thu AI dài/reboot vẫn là công việc riêng trong TODO.
- Không cần reload extension cho bản editor này vì không thay source extension. Nạp backend chỉ khi `scripts/active_jobs.py` trả 0; F5 Studio để thấy entry tùy chọn.

### Server fixture và cách tiếp tục kiểm tra

Các script nằm ở `scripts/dev/create_editor_fixture.py` và `scripts/dev/editor_fixture_server.py`. Chúng khóa DB/output vào `data/editor-fixture` của checkout; không dùng E:\Videos hoặc DB production, không gọi Comfy/ChatGPT/Flow.

```powershell
& C:\Python312\python.exe -m scripts.editor_fixture_server --port 8886
```

Fixture hiện đã tạo:

```text
Source job: f5616ef4-d03f-4a15-88e3-edbeacde1629
Export browser completed: 3650e392-8b61-4085-b5c1-28f6d8d755aa
Editor: http://127.0.0.1:8886/editor.html?job=f5616ef4-d03f-4a15-88e3-edbeacde1629
```

`GET /fixture/info` xác nhận đây là fixture. `POST /fixture/advance-export` chỉ xử lý render-only child thuộc thư mục fixture; workflow job mới chỉ queued, không được biến thành lời gọi model thật trong test này.

Khi tiếp tục, kiểm tra process/endpoint hiện còn chạy trước khi thao tác. Không coi một log/lock cũ là chứng cứ tiến trình vẫn sống; cũng không restart chỉ vì một lần quan sát timeout.

### Yêu cầu không được bỏ quên

Người dùng đã nhấn mạnh: **đây chỉ là UI khác, UI cũ vẫn phải chạy mượt**. Không tự bật preset/nhạc chương cho form cũ, không đổi source/checkpoint job đang chạy, không yêu cầu duyệt bắt buộc và không đưa lại luồng retry LLM vô hạn. Canvas node đã được người dùng yêu cầu làm ngay; chuỗi nhiều LLM tự do và nhiều video chạy thật song song vẫn chưa thuộc nghiệm thu này.

<a id="guide"></a>
## Hướng dẫn sử dụng

### 1. Hai UI cùng tồn tại

- **Studio/UI cũ**: giữ form tạo video, lịch sử job, float ChatGPT/Chrome và editor ảnh từng cảnh hiện hành. Không bắt người dùng đổi cách làm.
- **Bàn dựng mới**: lựa chọn thêm để chỉnh media, lớp chữ, chuyển động, phụ đề, nhạc và SFX trên timeline.
- **Workflow canvas**: tab của UI mới, cho kéo/nối/cấu hình các bước và gửi yêu cầu tạo video vào pipeline thật.
- Không phải mọi job cũ được tự áp preset hoặc chuyển sang nhạc theo chương. Bộ dựng tự động mới chỉ bật khi request chủ động có `edit_preset`, `workflow` hoặc các tùy chọn node mới.
- Mở bàn dựng của video cũ tạo sidecar chỉnh sửa riêng; ảnh, WAV, nhạc, timing lời đọc và video đã xuất không bị ghi đè.

Trong Studio có **Bàn dựng mới (tùy chọn)** trên thẻ video/hero và **Workflow canvas (tùy chọn)** gần form tạo video. Nút **Xem / sửa ảnh từng cảnh** cũ vẫn giữ nguyên.

### 2. Mở bàn dựng

1. Mở Studio như hiện tại.
2. Chọn một video đã có lời đọc và ảnh.
3. Bấm **Bàn dựng mới (tùy chọn)**.
4. Trang mới có bốn khu vực: thư viện bên trái, preview giữa, thuộc tính bên phải và timeline bên dưới.

Đường dẫn trực tiếp khi backend mới đã được nạp:

```text
http://localhost:8877/editor.html?job=<job-id>
```

Để chạy workflow bằng extension ChatGPT, nên mở từ Studio đang kết nối. Liên kết này mang đúng connector scope và sử dụng route production hiện có:

```text
/story-video/projects/<scope>/production?workspace=editor&job=<job-id>&scope=<scope>
```

Không tự điền scope khác hoặc mở lại hàng loạt phiên ChatGPT. Phép ghép request/response và heartbeat của bridge vẫn do hệ thống cũ quản lý.

### 3. Thư viện media

- **Media**: ảnh/video/âm thanh đã tạo và media nhập thêm, lọc theo loại hoặc tìm theo tên.
- **Chữ**: các mẫu tiêu đề, nhãn thông tin và mốc thời gian; nội dung sửa ở Thuộc tính.
- **Âm thanh**: các stem lời đọc/nhạc đang có.
- **SFX**: whoosh, impact, chime, click tạo cục bộ.
- **Phong cách**: Documentary, Science, Everyday.
- **Phụ đề**: kiểu chữ, màu, vị trí và nhấn cụm từ theo cue thật.

Bấm **＋** để nhập media. Bản hiện tại nhận:

| Loại | Định dạng |
|---|---|
| Ảnh | PNG, JPG/JPEG, WebP một khung |
| Video | MP4, MOV, WebM, MKV |
| Âm thanh | WAV, MP3, M4A, OGG, FLAC, AAC |

Giới hạn API là 150 MB/tệp. Ảnh/video bị giới hạn kích thước; ảnh nhập được giải mã, áp EXIF orientation và lưu PNG. Video/âm thanh được probe và giải mã kiểm tra. Tên người dùng không trở thành đường dẫn chạy lệnh; server đặt ID/tên lưu riêng.

Bấm một media để thêm vào timeline hoặc kéo vào lớp phù hợp. Ảnh/video thêm qua thư viện ưu tiên lớp hình trống hoặc tạo lớp mới, giữ các cảnh nguồn. Đổi kích thước, vị trí và crop trong Thuộc tính. Không phát sinh lượt tạo ảnh AI khi thao tác media đã có.

### 4. Timeline và preview

#### Thao tác cơ bản

- Bấm clip để chọn và xem thuộc tính.
- Kéo thân clip để đổi thời gian; kéo mép để cắt.
- Bấm/kéo trên thước để tua; dùng nút phát/dừng và tốc độ preview.
- **Bắt dính** hỗ trợ đặt cạnh clip/con trỏ gần các mốc có sẵn.
- Thanh zoom, **Vừa video**, nút **＋ Lớp**, tách/nhân bản/xóa hỗ trợ bố trí bản dựng.
- Clip chồng thời gian được xếp thành các hàng con để đọc được, không che lẫn tên.
- Bấm tên lớp để đổi tên, khóa, mute/ẩn, đổi thứ tự lớp hình/chữ hoặc bỏ lớp khỏi bản dựng.
- Bỏ clip/lớp chỉ bỏ tham chiếu trong kế hoạch dựng; tệp nguồn vẫn giữ lại.

Thứ tự lớp hình/chữ trong timeline tương ứng thứ tự che phủ khi xuất. Phụ đề là lớp tổng hợp trên cùng; timing lấy từ lời đọc đã đo. Nếu tự đổi thời gian clip lời đọc, cần kiểm tra lại sự khớp với phụ đề; không tự sinh lại lời đọc để sửa việc này.

#### Thuộc tính clip

| Nhóm | Điều khiển |
|---|---|
| Thời gian | Bắt đầu, kết thúc, bật/tắt clip |
| Hình/video | Cover/contain, crop, vị trí, kích thước lớp, opacity |
| Chuyển động | Tĩnh, zoom vào/ra, pan trái/phải/lên/xuống |
| Chuyển cảnh | Cut, fade, dissolve, slide trái/phải |
| Chữ | Nội dung, cỡ chữ, màu chữ, nền nhãn, vị trí |
| Âm thanh | Gain, mute, source offset, fade in/out |
| Phụ đề | Bật/tắt, cỡ/màu chữ, màu nhấn, khoảng cách đáy, cụm từ nhấn |

Màu nhấn chỉ dùng cụm từ có nguyên văn trong cue, nằm trong khoảng thời gian cue đã đo. Không giả định có alignment từng từ. Margin mặc định là 576 px trên canvas 1080×1920, ở trên dải 30% phía dưới dùng bởi giao diện Shorts/Reels.

Crop mặc định của ảnh Flow tiếp tục bỏ khoảng 6% đáy; ảnh Comfy fallback hoặc ảnh nhập không tự bị áp crop Flow.

#### Phím tắt

| Phím | Tác dụng |
|---|---|
| Space | Phát/dừng preview |
| ← / → | Tua khoảng 0,1 giây |
| Shift + ← / → | Tua khoảng 1 giây |
| S | Tách clip đã chọn tại con trỏ |
| Delete / Backspace | Bỏ clip đã chọn |
| Ctrl+Z | Undo |
| Ctrl+Shift+Z hoặc Ctrl+Y | Redo |
| Ctrl+S | Lưu bản dựng |

Trong ô nhập văn bản, các phím gõ/undo văn bản được ưu tiên; Ctrl+S vẫn lưu kế hoạch dựng. Undo/redo của bàn dựng lưu trong phiên trình duyệt; lịch sử revision đã lưu còn ở phía server.

### 5. Lưu và xuất

**Lưu** ghi kế hoạch dựng, không gọi lại ChatGPT, Flow hay Comfy. Revision tăng sau khi server nhận bản hợp lệ. Nếu cửa sổ khác đã lưu trước, server trả conflict; không âm thầm ghi đè.

Khi save đang chạy mà bạn tiếp tục gõ, thay đổi mới được giữ ở draft; phản hồi save cũ không ghi đè nó. Trạng thái trên header cho biết còn thay đổi chưa lưu hay đã lưu revision nào.

**Xuất video**:

1. Lưu draft đang có.
2. Bấm Xuất video → Bắt đầu xuất.
3. Hệ thống tạo **child job chỉ render/verify**, đóng băng plan và hash media nguồn.
4. Dùng lại ảnh/lời đọc/nhạc; các clip visual không đổi được lấy từ cache.
5. Chờ trạng thái hoàn tất rồi tải MP4 mới.

Bản xuất cũ không bị ghi đè. Nhiều lần xuất có các job/file riêng trong cùng dự án. Mất phản hồi không được hiểu là chưa nhận job: UI giữ Idempotency-Key để đối chiếu, tránh tạo bản xuất thay thế ngoài ý muốn.

Bản xuất đóng băng là read-only trong UI mới. Chọn **Mở bản dựng gốc** để sửa draft rồi xuất tiếp; việc này giữ bằng chứng của bản đã phát hành.

### 6. Ba preset

| ID / tên UI | Hướng dựng |
|---|---|
| `documentary` / Documentary | Nhãn ấm, chuyển động chậm, zoom vào nhẹ, fade, điểm nhấn âm thanh thưa |
| `science` / Science | Màu lạnh, nhãn rõ, pan nhẹ, dissolve, chime |
| `everyday` / Everyday | Màu ấm, chữ dễ đọc, zoom ra nhẹ, fade, click/điểm nhấn nhẹ |

Preset dùng dữ liệu kịch bản/tiêu đề/chương có sẵn, không thêm lượt LLM để chấm điểm hoặc dựng lại liên tục. Chọn preset không tạo ảnh mới. Có thể tiếp tục chỉnh riêng từng clip. Khi áp preset, UI tạm khóa thao tác bản dựng trong thời gian lưu/áp dụng để tránh mất thay đổi.

### 7. Nhạc theo chương và SFX

- Luồng mới chủ động bật mới chia nhạc theo chương/phần có metadata và thời gian speech thật.
- Không có `chapter_index` thì dùng một phần nhạc, không suy ra một bài cho mỗi câu phụ đề.
- Mỗi phần nhạc có receipt ID ổn định, dùng lại khi retry, loop/crossfade đến độ dài phần và chuẩn hóa mức âm.
- Lời đọc được giữ rõ bằng ducking; chỉnh nhạc/SFX sẽ mix lại từ stems gốc, không dùng nhầm soundtrack đã trộn trước.
- Tắt node nhạc thì không gọi model nhạc. Checkpoint sẽ ghi rõ intentional mute, không giả đó là âm thanh do model sinh.
- SFX mặc định thưa ở tiêu đề/chuyển chương. Bốn sample là tổng hợp toán học cục bộ, có manifest nguồn, hash và CC0-1.0; không tải sample không rõ bản quyền.
- Có thể thêm, đổi thời gian, cắt, gain/mute/fade SFX trong timeline.

### 8. Workflow canvas

Canvas không thay UI cũ. Nó cấu hình các bước/provider đã có trong VideoStudio, không tự bổ sung mọi model có trong menu của công cụ tham khảo.

#### Kéo, nối và cấu hình

1. Mở tab Workflow.
2. Chọn template hoặc workflow đã lưu.
3. Kéo tiêu đề node để đổi bố cục; kéo nền để pan; cuộn để zoom; dùng Vừa khung khi cần.
4. Bấm cổng ra rồi cổng vào để nối. Bấm dây hoặc nút × trong kết nối vào để ngắt.
5. Chọn tiêu đề node để sửa cấu hình trong inspector.
6. Lưu, nhân bản hoặc nhập/xuất JSON.
7. Bấm Chạy workflow để gửi một yêu cầu tạo video thật qua cơ chế job/bridge hiện hành.

Các bước bắt buộc: input, script, speech, images, render, output. Các bước tùy chọn: research, references, captions, music, sfx.

| Node | Cấu hình chính |
|---|---|
| Input | Ý tưởng/lời có sẵn, thời lượng, chế độ |
| Research / Script | Text provider đang tích hợp; hai bước dùng cùng kết nối text |
| Speech | Giọng có trong thư viện, pitch |
| References | Bật/tắt tham chiếu nhân vật Flow |
| Images | Flow/ChatGPT/Comfy, batch Flow đã nghiệm thu, quality mode |
| Captions | Bật/tắt phụ đề đầu ra |
| Music | Bật/tắt nhạc, mức nhạc; luồng mới dùng phần/chương |
| SFX | Bật/tắt điểm nhấn cục bộ |
| Render | Preset |
| Output | Trạng thái và video kết quả |

Tắt/xóa nghiên cứu có nghĩa dùng lời đọc có sẵn; hãy nhập lời đọc hoàn chỉnh thay vì chỉ một chủ đề. Tham chiếu nhân vật native hiện yêu cầu Flow; chọn provider ảnh khác sẽ tắt node ref trong UI, và server chặn graph yêu cầu tính năng không được hỗ trợ. Flow fallback sang Comfy vẫn có cơ chế dùng lại ref đã tải của luồng Flow.

Graph phải có typed ports phù hợp, đủ input, không có chu trình hoặc node rời khỏi output. Bản này dùng các loại bước của pipeline hiện có và một node mỗi loại; không chạy code tùy ý hay một chuỗi nhiều LLM tự do. Các đường song song trên canvas không có nghĩa worker/GPU đang xử lý nhiều video đồng thời.

### 9. Gặp lỗi thì làm gì?

| Tình huống | Thao tác |
|---|---|
| Save báo stale/conflict | Giữ draft, kiểm tra cửa sổ khác; tải lại bản server rồi áp thay đổi cần thiết |
| Tệp nguồn đổi/mất | Không tạo lại cả video; kiểm tra nguồn/backup hoặc nhập media hợp lệ |
| Preview khác export | Giữ plan/revision và bản xuất để đối chiếu; bản này vẫn đang nghiệm thu |
| Export failed | Đọc lỗi và bấm tiếp tục xuất; không tạo lại ảnh/lời đọc/nhạc |
| Graph compile lỗi | Sửa node/port/provider được báo, không thử gửi job liên tục |
| Bridge scope/heartbeat thiếu | Về Studio, nối bridge đúng phiên; không tự giả heartbeat hoặc gửi lại prompt |
| Không thấy nút UI mới trên production | Mã tính năng có thể chưa được tích hợp/nạp; không tự restart khi job còn chạy |

<a id="architecture"></a>
## Kiến trúc và kỹ thuật

### 1. Biên tương thích

```mermaid
flowchart LR
  Old[Studio cũ] --> Jobs[API jobs hiện hành]
  New[Editor + Workflow tùy chọn] --> PlanAPI[Edit-plan API]
  New --> GraphAPI[Workflow API]
  GraphAPI --> Compile[Kiểm tra / compile graph]
  Compile --> Jobs
  Jobs --> Worker[Worker tuần tự]
  Worker --> Legacy[Luồng cũ khi không opt-in]
  Worker --> Optional[Luồng dựng mới khi opt-in]
  PlanAPI --> Frozen[Snapshot + child render-only job]
  Frozen --> Worker
  Legacy --> Output[MP4 riêng mỗi job]
  Optional --> Output
```

Không thay `STAGES` hiện hành: plan → research → script → speech → images → subtitles → music → render → verify. Compiler graph chỉ nhận cấu trúc có dependency mà pipeline này thực thi được. Những nhánh tắt có thể vẫn có checkpoint đánh dấu bỏ qua hoặc mute rõ ràng; chúng không được biến thành lời gọi model ngầm.

`editing_opted_in(job)` kiểm tra sự hiện diện của `edit_preset`, `workflow`, `references_enabled`, `captions_enabled`, `music_enabled`, `sfx_enabled`. Request từ form cũ không được tự thêm các trường này. Với opt-in, plan handler thêm `editing_version: 1`; speech scene của kịch bản nhiều chương giữ `chapter_index`.

Ở render:

1. Có `images.edit_plan_snapshot`: render chính xác snapshot, lỗi thì báo lỗi; không xuất kiểu khác thay thế.
2. Opt-in tự động: tạo snapshot default, render mới; lỗi metadata/hiệu ứng cục bộ có thể log warning rồi dùng renderer cũ. Không nuốt lệnh hủy.
3. Không opt-in: dùng render/music hiện hành.

### 2. Module và trách nhiệm

| File | Trách nhiệm |
|---|---|
| `static/editor.html`, `editor.css`, `editor.js` | Shell UI, library, inspector, timeline, save/export/status |
| `static/editor-model.mjs` | Edit bất biến, trim/split/move, stack order, packing hàng, undo/redo, timing preview |
| `static/editor-preview.mjs` | Canvas preview và phát audio theo plan; không sửa media |
| `static/workflow-canvas.js/.css` | Canvas node, dây, inspector, thư viện, JSON, Run |
| `videostudio/edit_plan.py` | Schema, asset registry, revision, sidecar, immutable export |
| `videostudio/edit_plan_api.py` | Same-origin API, upload giới hạn, media/waveform |
| `videostudio/editing_presets.py` | Ba preset local, không gọi model |
| `videostudio/edit_render.py` | Cache visual/text, composite theo stack, caption ASS, mux và verify |
| `videostudio/edit_audio.py` | Phần nhạc, SFX local, mix/duck/fade/stem cache |
| `videostudio/workflow.py` | Typed graph, validation, compile, CRUD và revisions |
| `videostudio/workflow_api.py` | API graph và compile |
| `videostudio/providers.py` | Điểm opt-in vào pipeline; giữ nhánh legacy |
| `videostudio/core.py`, `api.py` | Trường request mới, compilation tại admission, đăng ký routes |

Frontend là static ES modules; không cần npm build để phục vụ app. `static/package.json` chỉ khai báo module cho công cụ/test Node. Backend dùng dependencies hiện có: FastAPI, Pillow, FFmpeg/FFprobe và SQLite.

### 3. Plan schema v1

Ví dụ minh họa; `asset_id` phải lấy từ view của đúng job, không tự bịa ID/path:

```json
{
  "schema_version": 1,
  "job_id": "<job-uuid>",
  "revision": 0,
  "preset_id": "science",
  "duration": 8,
  "canvas": {"width": 1080, "height": 1920, "fps": 30},
  "tracks": [
    {"id":"visual","kind":"video","name":"Hình ảnh","muted":false,"visible":true,"locked":false},
    {"id":"labels","kind":"text","name":"Chữ","muted":false,"visible":true,"locked":false},
    {"id":"narration","kind":"narration","name":"Lời đọc","muted":false,"visible":true,"locked":false},
    {"id":"music","kind":"music","name":"Nhạc","muted":false,"visible":true,"locked":false},
    {"id":"sfx","kind":"sfx","name":"SFX","muted":false,"visible":true,"locked":false}
  ],
  "clips": [
    {"id":"visual-0000","track_id":"visual","kind":"image","scene_id":"scene-0000","asset_id":"<scoped-image-id>","start":0,"end":8,"source_start":0,"enabled":true,"fit":"cover","opacity":1,"motion":{"type":"zoom_in","amount":0.06},"transition":{"type":"fade","duration":0.3}},
    {"id":"title","track_id":"labels","kind":"text","text":"Một góc nhìn mới","start":0,"end":3,"enabled":true,"x":0.5,"y":0.18,"size":58,"color":"#FFFFFF","background":null},
    {"id":"narration-0000","track_id":"narration","kind":"audio","asset_id":"<scoped-speech-id>","start":0,"end":8,"source_start":0,"volume":1,"enabled":true}
  ],
  "captions":{"enabled":true,"font_size":52,"color":"#FFFFFF","accent_color":"#72D5FF","bottom_margin":576,"emphasis":[]},
  "narration":{"volume":1,"muted":false},
  "music":[{"id":"music-0000","track_id":"music","kind":"audio","asset_id":"music-section-0000","start":0,"end":8,"source_start":0,"volume":0.35,"fade_in":0.4,"fade_out":0.8,"enabled":true}],
  "sfx":[]
}
```

Các collection clip là `clips`, `music`, `sfx`. Narration clip nằm trong `clips`; không được giả định tất cả phần tử của `clips` đều là ảnh. Trường `plan.narration` là điều khiển gain/mute chung.

Các ràng buộc chính:

- ID ASCII chữ/số/`_`/`-`, tối đa 120 ký tự; không trùng giữa các collection.
- Thời gian hữu hạn, start ≥ 0, end > start và end ≤ duration.
- Canvas chẵn, mỗi cạnh 64–4096; fps 1–60. Plan duration 0,05–14.400 giây. Giới hạn admission job thông thường vẫn là 8–7200 giây.
- Asset phải có đúng kind, đúng registry của job. Video trim không vượt nguồn; audio có source offset và có thể dùng loop theo mixer.
- `x/y/opacity` 0–1; `width/height` lớp 0,01–1; crop normalized và không vượt khung nguồn.
- Motion amount 0–0,5; transition duration không vượt 5 giây hoặc độ dài clip. UI tự điều chỉnh hiệu ứng của clip quá ngắn khi trim/split/add.
- Color là hex sáu chữ số. Không nhận filter expression hoặc đường dẫn từ client.
- Emphasis có `utterance_index/start/end/text`, phải nằm trong cue speech thật và là nguyên văn trong narration cue đó.

### 4. Lưu, revision và snapshot

SQLite thêm các bảng:

| Bảng | Ý nghĩa |
|---|---|
| `edit_plan_heads` | Plan hiện hành và revision của mỗi job |
| `edit_plan_assets` | Asset nhập thuộc đúng job |
| `edit_plan_exports` | Child/parent/revision/hash snapshot |
| `workflows` | Graph hiện hành và revision |
| `workflow_revisions` | Lịch sử graph |

Plan lưu bằng optimistic concurrency: client gửi revision, server lấy write lock, kiểm tra head, validate, ghi revision mới và sidecar atomically. Stale trả 409. File JSON không thay thế cơ chế kiểm tra revision trong DB.

```text
<job-output>/
  edit_plan.json
  edit-plan-revisions/
    00000000.json
    00000001.json
  automatic-edit-plan-snapshot.json   # opt-in automatic defaults, nếu có
```

Export có `Idempotency-Key`; tạo job mới ở stage render, giữ các checkpoint nguồn, thêm `images.edit_plan_snapshot` và attestation hash của manifest. Snapshot chứa plan, parent job, resolved asset IDs/path/hash và cache directory riêng do server tạo.

```text
<child-output>/
  edit_plan.json
  edit-plan-snapshot.json
  brief.json
  ... các checkpoint nguồn tham chiếu lại media hợp lệ ...
```

Không cho client ghi resolved paths. Khi xuất/render, kiểm tra hash snapshot và toàn bộ media đã đóng băng. Xem media xác minh đúng asset được yêu cầu thay vì rehash tất cả nguồn mỗi thumbnail. Export và render vẫn kiểm tra đầy đủ, không nới lỏng vì tối ưu preview.

### 5. Bộ dựng FFmpeg

```mermaid
flowchart TD
  Snapshot[Snapshot + source hashes] --> Validate[Validate exact plan/assets]
  Validate --> Images[Cached image/video camera clips]
  Validate --> Text[Cached transparent text PNG layers]
  Images --> Stack[Composite đúng thứ tự track]
  Text --> Stack
  Stack --> Captions[ASS captions + emphasis]
  Validate --> Audio[Narration + chapter music + SFX mix]
  Captions --> Mux[Mux MP4]
  Audio --> Mux
  Mux --> Check[Probe + full decode + frozen canvas/timeline check]
  Check --> Publish[Publish file riêng cho child job]
```

Visual cache key gồm source hash, canvas/fps, loại clip, source trim, fit/crop, motion, opacity/transition, kích thước và độ dài liên quan. Đổi placement/text/audio không mặc nhiên xin ảnh AI mới. Text raster có cache/hash riêng, alpha thật và được composite ở đúng vị trí track; không vẽ tất cả chữ lên trên mọi ảnh ở pass cuối.

Composite chia thành cửa sổ 30 giây, tối đa 24 input decoder mỗi pass để tránh giới hạn command line/decoder trên Windows. Dissolve giữ frame cuối clip trước trong khoảng entry fade của clip sau; preview được căn lại chính sách này, gồm giữ đúng frame cuối video đã trim. Fade/slide và opacity được áp vào layer, crop/zoom/pan ở camera clip.

Cache runtime nằm cạnh DB, gồm `editor-visual-cache`, `editor-audio-cache`, `editor-sfx`, `editor-thumbnails`, `editor-waveforms`, `editor-imports/<job-id>`. Đây là dữ liệu local, không đưa vào Git. Chưa có cơ chế dọn cache tự động tổng quát; không xóa cache/asset dùng chung tùy tiện khi child job còn phụ thuộc.

Service editor nhận đúng executable từ pipeline (`VS_FFMPEG`, `VS_FFPROBE`), không ép dùng PATH khi máy đã cấu hình đường dẫn riêng.

### 6. Audio và nhạc chương

`music_sections` nhóm các speech scene liên tiếp theo `chapter_index`, giữ timing đo được. Không có index thì một section. `generate_chapter_music` sử dụng receipt ổn định từng phần, summary `chapter-music.json`, normalization và covered-loop files; đoạn cuối giữ tail overlap để crossfade thực sự khớp metadata.

Checkpoint nhạc có path/duration/assets và danh sách sections với id, asset_id, chapter_index, start/end/section_end, duration, path/hash, source_start, volume, fades và provenance. Checkpoint nhạc cũ hợp lệ được dùng nguyên, không tái sinh để chạy editor.

Mixer lấy các clip audio từ plan, resolve asset ID, áp trim/delay/gain/mute/fades, dựng stem theo loại, duck nhạc dưới lời đọc rồi mux. Stem không đổi có thể tái dùng khi chỉ đổi nhạc/SFX/nhãn. Có batching để số input lớn không thành command line quá dài.

SFX `whoosh/impact/chime/click` là toán học cục bộ, manifest ghi `videostudio-procedural-synthesis-v1`, SHA-256 và CC0-1.0. Khi thay đổi generator ở bản sau, phải xem xét version/migration sample: không âm thầm thay bytes mà snapshot cũ đang tham chiếu.

Verify bản dựng thủ công kiểm tra stream, canvas/fps, thời lượng và decode toàn bộ. Gain nhỏ/mute do user chọn không bị gán nhầm là model sinh âm thanh lỗi. Automatic defaults vẫn có kiểm tra audio chất lượng tương ứng; không dùng đường manual để giả nghiệm thu model output.

### 7. Graph và admission

Graph schema v1: `id/name/revision/nodes/edges/viewport`. Node có `id/type/x/y/config`; edge có `id/source/source_port/target/target_port`. Validate duplicate IDs/type, typed ports, required inputs, cycle, rank và output contribution.

Compiler sinh request có graph chuẩn hóa, `edit_preset`, provider/voice/pitch/batch và các boolean `references_enabled/captions_enabled/music_enabled/sfx_enabled`. Native references yêu cầu image provider Flow. Hai node văn bản dùng cùng text provider đang tích hợp. Tắt research chuyển sang provided narration, bảo toàn lựa chọn lời đọc có sẵn.

Compilation nằm ở `POST /api/jobs` và compile API. `core.validate_request` chỉ validate graph, không compile đè scalar fields mỗi lần revalidate; đổi giọng/derivative giữ voice/pitch mới, không bị node speech cũ ép về giọng trước.

Những request không có graph hoặc field opt-in giữ contract cũ. Vẫn dùng exact connector scope, preflight/heartbeat/smoke và idempotency hiện hành. Giữ key cho request chưa rõ kết quả; không tự resubmit sau mất callback.

### 8. API

Các mutation giữ same-origin check. Tệp/thumbnail/waveform chỉ resolve asset thuộc registry job/snapshot.

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/api/edit-presets` | Danh sách ba preset |
| GET | `/api/jobs/{id}/edit-plan` | View public, assets, capabilities, revision |
| PUT | `/api/jobs/{id}/edit-plan` | `{revision, plan}` |
| POST | `.../edit-plan/preset` | `{revision, preset_id}` |
| POST | `.../edit-plan/assets?name=...` | Raw upload giới hạn 150 MB |
| GET | `.../edit-plan/assets/{asset_id}` | Stream asset; `thumb=true` tùy chọn |
| GET | `.../edit-plan/waveform?asset_id=...` | Bins từ audio thật, cache theo hash |
| POST | `.../edit-plan/export` | `{revision}` + Idempotency-Key, child job |
| GET | `/api/workflows` | Saved graphs, templates, node types |
| POST | `/api/workflows` | `{graph, revision}` |
| GET | `/api/workflows/{id}` | Một graph |
| GET | `/api/workflows/{id}/revisions` | Lịch sử graph |
| DELETE | `/api/workflows/{id}` | Xóa workflow/lịch sử; không xóa video |
| POST | `/api/workflows/compile` | `{graph, request}` → request/graph/order |

HTTP quan trọng: 409 stale/conflict, 422 dữ liệu không hợp lệ, 413 upload quá lớn, 404 job/asset không có. UI không được đổi các lỗi này thành báo xuất thành công.

### 9. Kiểm thử và triển khai

Các nhóm test mới: edit-plan persistence/API, real FFmpeg renderer, audio/SFX, workflow graph/API/integration, opt-in compatibility, JS timeline model và save-race. Tests dùng nguồn tổng hợp; kết quả fixture không được dùng làm bằng chứng model/provider thật đã đạt.

Chạy toàn bộ trước khi release, với thư mục TEMP riêng trong checkout. Async/TestClient có thể cần quyền chạy loopback ngoài sandbox; không sửa production để chữa lỗi test socketpair.

```powershell
$env:TEMP = (Resolve-Path data/test-tmp).Path
$env:TMP = $env:TEMP
& C:\Python312\python.exe -m unittest discover -s tests -p 'test_*.py'

# Node test files của extension và tests/*.test.mjs, không chạy script E2E thật ngoài ý muốn.
```

Chỉ nạp backend khi đủ kiểm tra và không có job đang chạy. Không tự restart Windows; nghiệm thu reboot/video dài do người dùng thực hiện. Không đổi provider production sang nhánh FlowAPI HTTP thử nghiệm.

<a id="implementation"></a>
## Hợp đồng tích hợp và tiêu chí hoàn thành

### Phạm vi đã thống nhất

- Có edit_plan.json thực sự, giữ revision và ID cảnh ổn định; tái sử dụng ảnh/âm thanh hợp lệ khi chỉnh dựng.
- Có ba preset tài liệu, khoa học, đời sống; không thêm vòng LLM duyệt/chấm điểm hoặc bắt người dùng xác nhận từng bộ ref/hiệu ứng.
- Có nhạc theo chương/phần và SFX thưa, mix/fade/duck thực sự trong bản xuất.
- Có editor tối kiểu CapCut với thư viện, preview, inspector, timeline nhiều lớp và thao tác sửa thật.
- Có canvas kéo/nối/cấu hình/save/load/import/export/Run thật; không thay bằng sơ đồ tiến độ hoặc menu model chưa tích hợp.
- Mọi phần trên là UI tùy chọn. Không thay thế Studio cũ hoặc tự thay checkpoint/scene ID của job đã có.
- Video dài và restart máy thật do người dùng nghiệm thu riêng; không tự thực hiện reboot hoặc chạy video AI để đánh dấu hai việc này xong.

Tham khảo đã xem: video-tool.mp4 (55,89 giây) và FB_IMG_1793509205695.jpg, FB_IMG_1793509269896.jpg, FB_IMG_1793509278355.jpg. Các ảnh/clip chỉ là tham khảo bố cục/chức năng, không là bằng chứng mọi model/provider trong sản phẩm đó hoạt động ở VideoStudio.

### Chữ ký tích hợp

Các API nội bộ chính, cần đối chiếu code khi sửa:

```text
EditPlanService(store, ffmpeg='ffmpeg', ffprobe='ffprobe')
  view(jid)
  save(jid, revision, plan)
  preset(jid, revision, preset_id)
  import_asset(jid, raw, name)
  asset_file(jid, asset_id, thumbnail=False)
  waveform(jid, asset_id)
  export(jid, revision, key)
  automatic_snapshot(job)

register_edit_plan_routes(app, store, same_origin, public_job=None, *,
                          ffmpeg='ffmpeg', ffprobe='ffprobe')
render_edit_plan(job, check, ffmpeg='ffmpeg', ffprobe='ffprobe')
verify_edit_render(job, check, ffmpeg='ffmpeg', ffprobe='ffprobe')

music_sections(job, preset_id)
generate_chapter_music(pipeline, job, check)
ensure_sfx_library(folder)
default_sfx_events(scenes, chapters, preset_id)
mix_edit_audio(job, plan, resolved_assets, output, check, ffmpeg, ffprobe)

WorkflowService(store)
default_workflow(preset_id)
validate_workflow(graph)
compile_workflow(graph, base_request)
register_workflow_routes(app, store, same_origin)

mountWorkflowCanvas(container, {api, onRun, job})
  -> ready, getGraph(), isDirty(), setJob(), updateJob(), load(), destroy()
```

View edit-plan còn có utterances/chapters/capabilities và parent_job cho bản xuất đóng băng. Trả asset public bằng URL/ID, không trả private resolved paths ở view này. Endpoint export dùng định dạng public job hiện hành; không suy rộng quy tắc bỏ path của asset view thành tuyên bố mọi endpoint cũ đều đã bỏ path.

onRun nhận request đã compile; việc tạo job phải đi qua admission/connector scope thật. Không bypass owner tab, heartbeat, smoke, capability batch hoặc preflight. Không compile lại graph trong mỗi lần revalidate làm mất voice/pitch/preset vừa sửa của derivative.

### Trách nhiệm sửa code

- Nhóm plan/render: edit_plan.py, editing_presets.py, edit_render.py, edit_plan_api.py và tests tương ứng.
- Nhóm audio: edit_audio.py, procedural samples/metadata và tests.
- Nhóm graph: workflow.py, workflow_api.py, workflow-canvas.js/css và tests.
- Điểm tích hợp chung: core.py, api.py, providers.py, Studio navigation và editor.html/js/css. Phải thống nhất contract trước khi nhiều người cùng sửa các file này.

### Cách chốt công việc

1. Giữ kiểm tra regression của UI cũ và opt-in rõ ràng.
2. Test schema/API/race/revision/cache trước hoặc cùng sửa lỗi; không chỉ kiểm tra manifest có cờ xanh.
3. Render/giải mã MP4 và WAV tổng hợp thật, so pixel/thời gian/nguồn/hash; đổi chữ phải tái dùng clip hình không đổi, đổi motion phải invalid đúng clip.
4. Thao tác browser thật: kéo/cắt/select, inspector, preset, undo/redo, save/reload, playback, audio/SFX/crop/caption, workflow kéo/nối/config/save/compile/Run và tiến độ xuất.
5. Đối chiếu desktop và khung hẹp với tham khảo; không che điều khiển chính hay tạo overflow không dùng được.
6. Kiểm tra lỗi source/asset và request chưa rõ kết quả: giữ snapshot/receipt, không tạo thay thế hoặc giả trạng thái đã sẵn sàng.
7. Chạy full suite cuối, review, kiểm tra nguồn production không có xung đột và idle-job trước khi tích hợp/nạp backend.
8. Chỉ đánh dấu hoàn thành khi từng yêu cầu có bằng chứng thực tế. Module đã viết, lượt test thành phần hoặc screenshot đẹp chưa đủ.

Mọi cập nhật sau tiếp tục sửa tài liệu này và TODO, không tạo thêm một bộ handoff/status/plan trùng lặp.

<a id="code-animation"></a>
## Kế hoạch mở rộng: animation bằng asset và code

**Trạng thái: TODO, chưa triển khai.** Ghi nhận ngày 2026-11-03 từ đề xuất “Nâng cấp Story Video Pipeline sang Code-Driven Animation bằng HyperFrames”. Nội dung được điều chỉnh theo code hiện tại, không áp dụng nguyên văn các lệnh “implement”, “thay renderer chính” trong đề xuất. Việc tham khảo UI HyperFrames trước đây không có nghĩa VideoStudio đã dùng engine đó.

### Điểm giữ lại và điểm cần điều chỉnh

| Nội dung đề xuất | Áp dụng cho VideoStudio hiện tại |
|---|---|
| Thay chuỗi image → AI-video bằng code animation | Luồng đang dùng ảnh Flow/Comfy và FFmpeg, không có bước AI-video bắt buộc cần loại bỏ. Thêm khả năng animation nhiều lớp trên nền này. |
| Tạo scene planner/timeline/audio mới | Tái dùng scene ID, speech timing, `edit_plan.json`, asset registry, preset, chapter music, SFX, editor và workflow canvas. Không tạo pipeline song song cùng quản lý một timeline. |
| Comfy là nguồn asset duy nhất | Giữ cả Flow/Comfy và ref sẵn có; layer PNG alpha/mask/pose là capability bổ sung. Ảnh phẳng vẫn dùng được. |
| HyperFrames là renderer chính ngay | Chỉ là ứng viên engine cần kiểm chứng. Tích hợp qua adapter tùy chọn; FFmpeg tiếp tục mux/audio/verify và dựng các cảnh thường. |
| Word/phoneme timestamps đã có | Hiện dùng timing câu lời đọc đo được. Không suy ra thời gian từng từ/viseme chính xác từ timing câu. Alignment là khả năng bổ sung, không chặn video thường. |
| Ưu tiên 1920×1080, dọc để sau | Dọc 1080×1920 đang là mặc định của editor. Giữ mặc định đó và thử cả hai hướng ở demo mới. |
| Phải có đầy đủ rig/action/FX ở mọi cảnh | Phân loại theo asset thực có; thiếu bộ phận thì giảm motion hoặc dùng ảnh thường. Không ép thêm nhiều lượt AI cho mọi cảnh. |
| Tạo doc motion-engine riêng | Ghi thiết kế trong tài liệu này, tiến độ trong TODO; README chỉ dẫn vào đây. |

### Luồng tích hợp dự kiến

```mermaid
flowchart TD
  Story[Kịch bản và scene ID hiện có] --> Assets[Ảnh/ref Flow hoặc Comfy đã xác nhận]
  Story --> Speech[TTS và timing đo được hiện có]
  Assets --> Pack[Asset pack và capability từng cảnh]
  Speech --> Director[Motion Director chọn preset và tham số]
  Pack --> Director
  Director --> Manifest[Motion manifest có version, seed và frame timing]
  Manifest --> Plan[Revision và snapshot kế hoạch dựng]
  Plan --> Choice{Cảnh có motion phù hợp?}
  Choice -->|Có| Engine[Adapter animation, engine cần kiểm chứng]
  Choice -->|Không hoặc fallback tự động đã quy định| Simple[Dựng ảnh/pan/chữ hiện có]
  Engine --> Clips[Clip cảnh được cache]
  Simple --> Clips
  Clips --> Final[FFmpeg, mix voice/nhạc/SFX/sub, verify và xuất]
  Speech --> Final
```

Đây là sơ đồ trách nhiệm, không phải thay thứ tự checkpoint đang chạy. Khi triển khai cần quyết định adapter nằm trong bước render hay có checkpoint con; không tự thêm stage top-level, đổi dependency của job cũ hoặc chuyển job đang chạy sang engine mới. Một video có thể dùng cả cảnh animation và cảnh ảnh thường.

### Hợp đồng dữ liệu và thư viện motion

- `edit_plan` vẫn là kế hoạch dựng tổng; asset pack/motion manifest là dữ liệu con có version và tham chiếu bằng scene ID/asset ID. Không lưu hai bản thời gian có thể lệch nhau; cue câu đã đo được quy đổi sang frame và giữ quy tắc làm tròn thống nhất. Schema v1 hiện kiểm tra field chặt, nên phải thiết kế version/migration trước khi mở rộng.
- Asset pack ghi nền, tiền cảnh, nhân vật, đạo cụ, mask, pose, mắt/miệng và metadata depth/pivot/anchor/bounds khi thực sự tồn tại. File đi qua registry hiện có, có hash; không chấp nhận đường dẫn tùy ý hoặc coi mask/alpha là có sẵn chỉ từ tên prompt. Capability phải kiểm tra cả nhóm asset cần cho một action.
- Motion Director dùng mô tả cảnh, mood, asset capability và audio timing để chọn từ thư viện đã cho phép: camera, parallax, micro motion, sprite/pose, prop/mask, FX và SFX events. LLM chỉ chọn preset/tham số, không sinh/chạy JavaScript tùy ý theo cảnh. Có đường chọn preset cục bộ khi không cần thêm lượt LLM.
- Mỗi primitive có schema tham số, version, giới hạn intensity và asset requirements; có thể phối hợp qua hierarchy/channel transform để blink, mouth, breathe, camera không ghi đè nhau. Random phải có seed; render lấy frame index làm đầu vào, không phụ thuộc đồng hồ realtime hoặc thứ tự seek.
- Cache/receipt bao gồm source hashes, manifest, preset/engine version, seed, fps, canvas và timing. Bản xuất đóng băng toàn bộ tham chiếu; đổi chữ/motion không sinh lại ảnh, giọng hoặc nhạc còn hợp lệ. Engine/primitive chưa cài hoặc khác version phải được phát hiện trước render.

### Tự động hóa và hạ cấp khi thiếu khả năng

Người dùng chọn kiểu video; tool tự kiểm tra và chọn motion phù hợp. Không yêu cầu user tự rig, tạo mask hoặc duyệt mọi scene trong luồng tự động. Asset nhập thủ công vẫn được hỗ trợ như lựa chọn nâng cao. Bắt đầu bằng một ảnh với camera/chữ; chỉ tạo/tách thêm layer có ích, trong ngân sách định trước và dùng lại ref đã xác nhận. Chưa mặc định rằng Comfy hiện đã có model/workflow tách bộ phận nhân vật.

Thứ tự hạ cấp dự kiến: motion đầy đủ → pose/layer đơn giản → camera/chữ trên ảnh phẳng → bộ dựng hiện hành. Mỗi trường hợp phải có giới hạn retry/timeout, trạng thái tiến độ, receipt và lý do fallback nhìn được trong UI. Không bỏ qua kiểm tra nguồn hoặc resubmit Flow khi kết quả cũ còn chưa rõ. Thiếu animation không được biến thành vòng lặp sinh lại asset/ref cho đến khi user can thiệp.

Nhánh tự động có thể hạ cấp theo chính sách đã ghi trong snapshot. Với export manual đã đóng băng, không âm thầm thay hiệu ứng user chọn: lỗi rõ ràng và cho user chọn bản xuất hạ cấp mới. Giữ checkpoint lời đọc/nhạc/ảnh và cho tiếp tục đúng phần còn thiếu. AI-video không phải đường cứu mặc định; chỉ xem xét sau, khi có provider khả dụng và user chủ động bật.

Lip sync đầu tiên có thể dùng closed/half/open theo năng lượng audio và khoảng ngắt, giới hạn tốc độ đổi miệng. Phải ghi là mouth animation theo audio, không tuyên bố khớp âm vị. Khi có alignment đáng tin mới bổ sung word/phoneme/viseme. Không có mouth/eye variants thì dùng head/camera motion, không chặn job. SFX gắn cùng event/frame của motion; mục tiêu sai số tối đa một frame cho event đã có timing, không áp đặt độ chính xác giả lên nội dung lời nói.

### Thứ tự thực hiện và tiêu chí nghiệm thu

1. **Engine spike:** kiểm tra package/phiên bản/license/API, deterministic seek, render headless, Windows, font và tài nguyên của ứng viên HyperFrames. Nếu không phù hợp, giữ contract và chọn adapter khác sau khi đánh giá; chưa thêm dependency vào production. Không cần áp đặt TypeScript/Zod lên backend Python và static ES modules hiện tại.
2. **Demo end-to-end:** asset thử cố định có một nhân vật blink/breathe/mouth, push/pan/parallax, đạo cụ + mask, particles/glint/flash, voice/SFX/sub; xuất MP4 30 fps cả dọc/ngang. Dùng synthetic assets trước để kiểm tra engine mà không tốn lượt AI. Seek lại frame cho cùng ảnh; không gọi AI-video.
3. **Tự động asset/Director:** thêm capability detection, asset preparation đã kiểm chứng và preset selection với ngân sách hữu hạn. Mở rộng camera/micro-motion trước; pose/action/impact/dash/weapon/FX phong phú làm dần sau khi đường cơ bản ổn.
4. **Editor/workflow:** thêm lựa chọn engine/style và inspector motion/capability trên UI sẵn có, không xây lại editor. Preview và export dùng chung manifest/primitive. Chỉ thêm node/port sau khi compiler/pipeline thật hỗ trợ; UI cũ giữ mặc định.
5. **Độ bền:** thử video hỗn hợp 30–100+ cảnh, cache reuse, bộ nhớ, hủy/resume, lỗi engine giữa chừng và fallback; chạy regression pipeline cũ. Runtime dùng tài nguyên theo cảnh/chunk, không giữ mọi asset full resolution hoặc mở browser mới cho từng layer.

<a id="engine-spike"></a>
### Kết quả engine spike HyperFrames (2026-11-04)

> **Vị trí hiện tại:** bộ dựng hoạt hình gấu trúc đã chuyển vào `memestudio/` (engine, tools, asset rig/mặt/tủ đồ/nền/SFX,
> các tập trong `memestudio/episodes/`, video trong `data/memestudio/out/`). Các mục dưới ghi đường dẫn cũ lúc thử nghiệm
> (`tmp/hyperframes-spike/...`, `memestudio/assets/rig/...`, `scripts/build_rig_faces.py`,
> `scripts/import_rig_wardrobe.py`). Thư mục `tmp/hyperframes-spike` (các cảnh thử, ảnh chụp, video thử ngoài `ep1.mp4`)
> đã xoá ngày 2026-11-04 theo yêu cầu người dùng. Hướng dẫn làm tập mới: [huong-dan-video-hoat-hinh.md](huong-dan-video-hoat-hinh.md).

Thư mục thử `tmp/hyperframes-spike/` (git bỏ qua): `scene/index.html` là composition, `out/` là kết quả. Cài: `npm install --save-exact hyperframes@0.9.10 gsap@3.13.0`; dự án tạo bằng `npx hyperframes init scene --non-interactive --example blank --resolution portrait --skip-skills`. Mọi lệnh chạy với `HYPERFRAMES_NO_TELEMETRY=1` và `DO_NOT_TRACK=1` (CLI có gửi telemetry mặc định).

Cảnh thử 8 giây, 4 shot, dùng bố cục 3 dải của `meme_render.py` (nhân 1,5 lên 1080×1920), nền `bg_90s_rural_yard`, sprite catalog `stand_talk`, `face_shock`, `run`, `facepalm`, FX `exclaim/smoke/sweat`, prop `table/phone`, 8 giây âm thanh lấy từ video meme thử số 3. Có: camera push, parallax nền/tiền cảnh, pop-in, nhún khi nói ~8 Hz, punch-in + rung camera theo keyframe cố định, flash, chạy ngang + khói, mồ hôi trượt, điện thoại rơi nảy, đổi phụ đề theo shot.

| Kiểm tra | Kết quả đo |
|---|---|
| `hyperframes check` | 0 lỗi; cảnh báo cấu trúc (nên tách shot thành sub-composition) và chữ hiện dưới 1,5 giây |
| MP4 | H.264 1080×1920, 30 fps, đúng 240 khung, 8,000 giây; AAC 48 kHz stereo, mức âm giữ nguyên (mean −21,5 dB, max −4,9 dB như file nguồn) |
| Chữ tiếng Việt | Hiển thị đủ dấu với font Arial Bold nhúng bằng `@font-face` |
| Tất định | Chuỗi PNG 1 worker (tua tuần tự) và 6 worker (tua nhảy vào giữa): 240/240 khung giống hệt từng pixel. Snapshot theo thứ tự xáo trộn và tăng dần: 7/7 giống hệt |
| Tốc độ (12 nhân) | MP4 8 giây: 31 giây lần đầu, 19 giây lần sau (worker tự chọn); PNG 1 worker 70 giây, 6 worker 32 giây. Bộ dựng Pillow hiện tại: video 45,6 giây trong 21,9 giây. HyperFrames chậm hơn khoảng 8 lần trên mỗi giây video, chưa đo với video dài |

Điều rút ra cho bước tiếp:
- Cắt cảnh/đổi pose dùng clip có `data-start`/`data-duration`; chuyển động chỉ dùng `set/to/from/fromTo` trên một timeline gốc (không `call()`, không random, không đồng hồ). Đó là lý do tua ra cùng kết quả.
- Catalog hiện chỉ có pose/mặt nguyên khối, **không có mắt/miệng tách lớp**: chớp mắt và miệng 3 trạng thái chưa làm được nếu chưa gắn nhãn bộ phận trong `Panda/auto_sliced/rig` hoặc vẽ thêm.
- Phụ thuộc kéo theo: HyperFrames tự tải Chrome riêng vào `~/.cache/hyperframes` (~272 MB); `hyperframes@0.9.10` ghim `undici@7.25.0`, bị `npm audit` báo lỗ hổng mức high (proxy SOCKS5, Set-Cookie, cache, CRLF, WebSocket). HyperFrames chỉ dùng `undici` để tải media từ URL công khai; render từ file cục bộ không đi qua nó. Đã vá trong thư mục thử bằng `"overrides": {"undici": "7.30.1"}` trong `package.json`: `npm audit` còn 0 lỗ hổng, render lại 240/240 khung giống hệt bản trước khi vá. Không dùng `npm audit fix --force` (hạ HyperFrames xuống 0.8.214). Khi tích hợp: giữ override này, chỉ cho composition dùng file cục bộ, chạy `npm audit` mỗi lần nâng phiên bản.
- Snapshot và render chụp theo hai đường khác nhau (chênh trung bình 0,26/255), nên kiểm tra tất định phải so trong cùng một đường chụp.

#### Rig nhân vật có khớp đầu tiên (2026-11-04)

Mục tiêu: kiểu hoạt hình cắt ghép (cut-out) như video mẫu người dùng gửi, nhân vật ghép từ bộ phận và cử động quanh khớp. Dự án thử `tmp/hyperframes-spike/rig/`, kết quả `tmp/hyperframes-spike/out/rig_v2.mp4` (bản đầu `rig.mp4` tay chân to, tay buông ngược).

- Bộ phận lấy từ `Panda/auto_sliced/rig` (cắt từ `panda_rig_sprite_sheet.png`): thân trên kèm đầu #6, chân đứng #40, chân bước #41 (và bản lật), tay buông #17, tay chỉ #22, tay ngửa #25, bóng #55. Các số khác trên sheet: chân #39 chạy, #42 ngồi xổm, #44 quỳ, #46 xếp bằng; tay #20 chặn, #21 like, #24 nắm, #23 cầm; thân #38 dang tay, #36 vỗ tay, #35 chắp tay; góc nghiêng/sau #1, #2, #5; FX #47–#61.
- Cách dựng: mỗi khớp là một khối 0×0 đặt đúng tại khớp, ảnh bên trong lệch để điểm khớp trùng gốc; đơn vị bên trong là pixel của sheet, phóng ×3,6. Hông = mép dưới thân (#6 y=141), vai trái/phải tại (±41, −63) so với hông, vai của #17 ở (19, 10), của #22 ở (114, 9), của #25 ở (103, 8), cạp quần #40/#41 ở (66,5, 8) và chồng lên thân 10 px. Tay nằm trong khối thân nên thân nhún/nghiêng thì tay theo. Tay phải và chân bước B dùng khối lật `scaleX(-1)`.
- Tỉ lệ meme (người dùng chốt 2026-11-04): không cố đúng giải phẫu; đầu/thân to, tay chân nhỏ. Tay thu ×0,66, chân ×0,72 bằng khối scale tĩnh bên trong khớp (điểm khớp giữ nguyên); chân đẩy lên (cạp quần ở −40 thay vì −18 đơn vị chân) để phần quần nấp sau thân. Tay buông #17 vẽ sẵn là tay bên phải màn hình: dùng nguyên ở vai phải, lật ở vai trái (bản đầu bị ngược).
- Động tác trong 8 giây: thở (co giãn thân từ hông), nói (đổi sang tay ngửa, vung tay, thân lắc), chỉ tay (đổi tay, bật lên với `back.out`), đi (đổi 3 khung chân mỗi 0,1 giây, thân nhún, hai tay vung ngược nhau, di chuyển ngang). Đổi bộ phận bằng `tl.set` opacity; có `tl.set` trạng thái gốc ở giây 0 cho mọi khớp.
- Kiểm tra: `hyperframes check` 0 lỗi; MP4 1080×1920, 30 fps, 240 khung, render 16 giây. Render tuần tự và 6 worker: 211/240 khung giống hệt, 29 khung còn lại lệch tối đa 2/255 mỗi kênh (làm tròn khử răng cưa khi xoay, ở đoạn chỉ tay), không lệch tư thế.
- Giới hạn: đầu dính liền thân nên chưa quay đầu hay đổi mặt riêng được; chưa có mắt/miệng tách lớp; chân chỉ có dáng nhìn thẳng nên đi ngang vẫn quay mặt ra trước; ảnh nguồn nhỏ (thân 118×147 px) nên phóng lên hơi mềm; có đường viền ở chỗ nối thân/quần. Muốn giống video mẫu cần thêm: đầu tách khỏi thân, bộ mặt biểu cảm, quần áo cho từng vai, ảnh nguồn độ phân giải cao hơn.

#### Khớp cổ và đổi biểu cảm (2026-11-04)

Dự án thử `tmp/hyperframes-spike/rig_head/` (sinh bằng script; asset và `assets/heads.json` trong đó), kết quả `tmp/hyperframes-spike/out/rig_head.mp4`.

- Thân không đầu `torso.png`: thân #6 giữ nguyên khung ảnh, xóa mọi pixel phía trên y=85 (cằm đầu cũ ở y≈87, ngay dưới là cổ áo đen). Offset trong rig không đổi.
- Đầu: 10 đầu biểu cảm trong `panda_expression_asset_sheet.png`, `Panda/auto_sliced/faces_fx` #9 nói, #10 lo, #11 giận, #12 sốc, #13 khóc, #14 buồn, #15 cười to, #16 cười đểu, #17 ngáp, #18 chu môi. Sheet còn 8 đầu trống #1–#8 (thẳng, nghiêng, sau, cúi), 12 cặp mắt và 10 miệng rời, FX và bàn tay.
- Khớp cổ nằm trong khối thân tại (3, −52) so với hông, vẽ trên lớp tay. Mỗi đầu thu ×0,72 (đầu cũ cao ~81 px, đầu biểu cảm ~116 px) và đặt theo điểm cằm tính tự động: đáy vùng đặc, tâm x của 6 hàng dưới cùng (không lấy tai). Vai dời xuống (−36, −50) và (38, −50) để nằm trên thân đã cắt.
- Đổi biểu cảm bằng `tl.set` opacity trên các đầu xếp chồng. Động tác thử: gật khi nói, lắc nhanh khi cười, bật lên + phóng to khi sốc (tay dang), lắc mạnh khi giận, gục nghiêng khi khóc, nghiêng chậm khi cười đểu, ngửa rồi gục khi ngáp. Xoay tới ±12° không lộ đầu cũ hay hở cổ.
- Kiểm tra: `hyperframes check` 0 lỗi; MP4 1080×1920, 30 fps, 240 khung, render 14 giây.
- Trang phục theo cách người dùng chốt: chỉ thay thân (thân mặc áo cùng khuôn `torso.png`), tay chân giữ nguyên; váy thì ẩn chân.

#### Thân mới và tủ đồ nhân vật (2026-11-04)

- **Thân mới `rig/base/torso_core.png`** (người dùng duyệt): hai mảng đen hai bên thân #6 thực ra là tay vẽ liền, nên đã cắt bỏ; chỉ giữ vùng bụng trắng + viền (lấy vùng sáng nối với tâm (58, 115), nới 3 px). Khung ảnh giữ nguyên 118×147, vai dời vào (−29, −52) và (31, −52). Tay vẽ **sau** thân/áo để tay áo che gốc tay.
- **Tủ đồ** trong `memestudio/assets/rig/`: `sheets/` là 8 bảng gốc vẽ bằng app ChatGPT (PNG nền trong suốt thật), `wardrobe/` là 54 món đã cắt: 30 trang phục (`costume/`, gồm 6 váy dài ẩn chân), 8 tóc (`hair/`), 8 mũ/đồ đội (`hat/`), 8 đồ đeo mặt (`face/`). `wardrobe/wardrobe.json` ghi cho từng món: file, điểm neo trong ảnh, vị trí trên rig, tỉ lệ, `hides_legs` cho váy. Ảnh duyệt: `preview_costume.jpg`, `preview_accessories.jpg`, `preview_characters.jpg` (12 nhân vật phối sẵn: bố, mẹ, học sinh, bác sĩ, đầu bếp, cô dâu, nông dân, vệ sĩ, công nhân, cầu thủ, cô gái váy đỏ, người mặc áo phao).
- **Cắt và khớp**: `python scripts/import_rig_wardrobe.py`. Tách món theo khe trống giữa hàng/cột; nếu một món có nhiều mảnh rời (hai vết má hồng) thì gom theo ô lưới đều. Áo: một tỉ lệ chung = chiều cao thân (55 đơn vị) / trung vị chiều cao các áo, đỉnh giữa áo đặt tại đỉnh thân (1, −56). Váy được vẽ nhỏ hơn để đủ chỗ phần váy, nên tỉ lệ riêng theo bề rộng vai so với áo. Phụ kiện đặt theo toạ độ của đầu #9 (cằm (77, 122)) rồi gắn vào khớp cổ, nên đi theo mọi động tác đầu; điểm neo từng món ghi trong `HEAD_SHEETS` (nón lá và mũ bảo hiểm neo theo tỉ lệ chiều cao vì có quai thòng).
- **Cách nhờ ChatGPT vẽ thêm** (đã dùng): đính kèm ảnh tham chiếu nhân vật + khuôn (`tmp/hyperframes-spike/costume/tham_chieu_than.png` cho áo, `tham_chieu_dau.png` cho đồ trên đầu), xin MỘT bảng lưới 3×2 (áo) hoặc 4×2 (phụ kiện) theo thứ tự đánh số, giữ đúng khuôn/cùng cỡ, nét đen dày như gấu, tô phẳng, không đầu/tay/chân/chữ/logo, các món không chạm nhau, nền trong suốt (hoặc #FF00FF); phụ kiện tóc để trống phần mặt. Các bảng sau gửi tiếp trong cùng chat để giữ nét. Tải bằng nút lưu trên ảnh → Download (không tạo link chia sẻ). Bảng mới: thêm tên file và danh sách id vào `COSTUMES`/`HEAD_SHEETS` rồi chạy lại script.
- Giới hạn còn lại (tủ đồ): tóc dài vẽ đè lên đầu nên tai gấu vẫn lộ phía trên; nón lá hơi che mắt với một số mặt; áo ngắn để lộ một dải quần trắng phía dưới. Chưa lắp tủ đồ vào composition HyperFrames (mới ghép bằng Pillow để duyệt).

#### Cảnh 3 vai từ tủ đồ (2026-11-04)

Dự án thử `tmp/hyperframes-spike/scene3/`, sinh bằng `make_scene.py`, kết quả `tmp/hyperframes-spike/out/scene3.mp4` (11 giây, 1080×1920, 30 fps, 330 khung, render 20 giây, `hyperframes check` 0 lỗi, giải mã toàn bộ OK, chưa có âm thanh).

- Thẻ nhân vật = trang phục + phụ kiện + đầu mặc định; script đọc `wardrobe.json` để đặt áo theo đỉnh thân và phụ kiện vào khớp cổ (phụ kiện nằm ngoài khối thu đầu ×0,72, toạ độ tính từ cổ). Váy tự bỏ chân. Thứ tự lớp: bóng → chân → tay → áo → đầu → phụ kiện, nên tay áo che gốc tay.
- Vai: Mẹ (áo bà ba hoa, tóc xoăn) x=185, Bố (ba lỗ, hói tóc bạc, râu mép) x=540, Con (sơ mi học sinh, húi cua) x=895; rig ×2,45, hông ở y=1400; nền `bg_90s_living_room`. Phụ đề trong khung trắng viền đen, tên người nói tô màu.
- Hành động là các hàm sinh lệnh GSAP an toàn khi tua: `walk` (đổi 3 khung chân, di chuyển, nhún, vung tay), `talk` (gật đầu + nhún), `gesture` (tay ngửa vung), `point_right`, `shock` (đầu bật + dang tay), `angry_shake`, `cry`, `face` (đổi đầu biểu cảm), thở lệch nhịp cho từng vai. Kịch bản thử: con đi vào khoe điểm 10 → mẹ hỏi → con "môn ngủ trưa" → bố sốc, mẹ lắc đầu giận → bố chỉ tay mắng → con khóc, mẹ cười đểu.
- Bài học bố cục: vai phải đứng cách nhau đủ xa (~355 px ở ×2,45) và người bị chỉ phải đứng cạnh người chỉ, nếu không tay bị vai khác che (lớp vẽ sau đè lớp trước).
- Chưa có: lời đọc/âm thanh và đồng bộ miệng theo tiếng, nhìn nghiêng/quay lưng, bước đi theo hướng, bộ tự dàn cảnh từ kịch bản.

#### Tách mặt và mốc mặt (2026-11-04)

Lý do: mỗi đầu biểu cảm #9–#18 là một hình vẽ riêng, mũi/miệng nằm lệch nhau và khuôn đầu cũng hơi khác nhau, nên râu đặt theo một toạ độ cố định bị lệch khi đổi mặt (người dùng phát hiện ở râu của Bố). Người dùng yêu cầu "dù làm meme nhưng cũng phải chuẩn".

- `python scripts/build_rig_faces.py` → `memestudio/assets/rig/faces/`: `head_base.png` (đầu trống #5, bỏ hai vạch cổ), `face_<tên>.png` cho 10 mặt (nói, lo, giận, sốc, khóc, buồn, cười, cười đểu, ngáp, chu môi), `faces.json`, `preview_landmarks.jpg`.
- Tách mặt: vùng trong đầu = bao lồi của vùng trắng nối với trán (giữ được nước mắt chạm viền, bỏ tai); lớp mặt = nét tối trong vùng đó (co vào 3 px để bỏ viền), alpha theo độ tối. Mỗi mặt được căn về đầu trống theo bề rộng và tâm của vùng trong đầu.
- Mốc mặt (mắt trái/phải, đáy mũi, mép trên/dưới miệng, tâm và bề rộng miệng) lấy từ các mảng nét đã đánh số; mảng nào là mắt/mũi/miệng được chọn bằng mắt trên ảnh đánh số và ghi trong `FEATURES` (đo tự động bằng chiếu hàng/cột sai ở mặt sốc, cười vì mũi dính miệng). Mày dính mắt thì lấy đáy mảng; mặt cười có mũi dính nếp má thì đáy mũi = mép trên miệng − 3.
- Rig mới: đầu = `head_base` ×0,6372 (cùng cỡ đầu cũ), cằm (86,5, 143) đặt tại khớp cổ. Mỗi biểu cảm là một nhóm "lớp mặt + đồ đeo mặt đặt theo mốc của chính mặt đó"; đổi biểu cảm = bật/tắt nhóm. Tóc và mũ đặt một chỗ trên đầu trống nên khớp với mọi mặt.
- `wardrobe.json` lên version 2: tóc/mũ có `at` (toạ độ đầu), `anchor`, `scale`; đồ đeo mặt có `per_face` cho 10 mặt (kính ở giữa hai mắt, rộng 2,1–2,15 lần khoảng cách mắt, nghiêng theo mắt; râu mép giữa đáy mũi và mép trên miệng, rộng 0,95 lần miệng; râu dê dưới mép dưới miệng; khẩu trang từ trên đáy mũi tới dưới miệng; má hồng dưới mắt). Ảnh duyệt `preview_face_items.jpg`: mọi đồ đeo mặt trên đủ 10 mặt.
- Cảnh 3 vai dựng lại theo rig mới: `tmp/hyperframes-spike/out/scene3_v2.mp4` (11 giây, 330 khung, render 16 giây, check 0 lỗi, giải mã OK). Râu của Bố nằm đúng giữa mũi và miệng qua các mặt nói/sốc/giận/lo.

#### Lời đọc cho cảnh 3 vai (2026-11-04)

- `tmp/hyperframes-spike/scene3/make_voice.py` tạo từng câu thoại bằng `videostudio.speech_worker` (VieNeu, Python và cache của StoryForge như pipeline), giọng tra bằng lớp `Voices` như pipeline (API HTTP không trả đường dẫn mẫu clone). Ghi `assets/voice/<n>_<vai>.wav` + `voice.json` (độ dài đo bằng ffprobe); chạy lại bỏ qua câu không đổi chữ/giọng. 5 câu mất khoảng 39 giây trên GPU.
- Giọng: Bố = Thiện Minh (nam, Bắc, kể chuyện; giọng người dùng hay dùng), Mẹ = clone "Vương Bờm - nữ", Con = clone "Gấu hài hước - nữ cao". Số "10" đọc thành "mười" trong lời, phụ đề vẫn ghi "10". Mức âm từng câu: trung bình −18 đến −19 dB, đỉnh −2 đến −5 dB.
- `make_scene.py` dựng timeline từ `voice.json`: con đi vào im lặng 1,1 giây, mỗi câu cách nhau 0,35 giây, khoảng lặng 1,2 giây cho phản ứng sốc, giữ 1,2 giây cuối; phụ đề và hành động (nói/gật, tay, đổi mặt, chỉ tay, khóc) bám đúng đầu/cuối từng câu. Mỗi câu là một `<audio>` có `data-start`.
- Kết quả `tmp/hyperframes-spike/out/scene3_voice.mp4`: 14,3 giây, 1080×1920, 30 fps, 429 khung, AAC 48 kHz stereo, render 24 giây, giải mã OK. `silencedetect` cho thấy tiếng bắt đầu ở 1,16 / 3,59 / 6,00 / 8,97 / 11,12 giây, lệch phụ đề dưới 0,1 giây (khoảng lặng đầu câu của TTS); mean −20,9 dB, max −2,0 dB.
- Chưa có: nhạc nền và tiếng động (miệng nhép: xem mục dưới).

#### Miệng nhép theo tiếng (2026-11-04)

- `scripts/build_rig_faces.py` tách thêm miệng của mỗi mặt: lấy đúng các mảng "miệng" trong `FEATURES`, nới 3 px để lấy cả viền môi mờ → `mouth_<tên>.png` và `face_<tên>_nomouth.png` (cùng khung với `head_base`); `faces.json` có `file_nomouth`, `mouth_file`, `mouth_pivot` = (tâm miệng, mép trên miệng).
- Rig: trong mỗi nhóm mặt, miệng là một khối 0×0 đặt tại `mouth_pivot`; nhép = co giãn theo chiều dọc quanh mép trên (môi trên đứng yên, môi dưới đóng/mở), nên giữ đúng kiểu miệng của biểu cảm. Ba mức: khép 0,35 (nhỏ hơn thì miệng thành sợi chỉ), nửa 0,65, mở 1,0; không nói thì về 1,0 (miệng tự nhiên của biểu cảm).
- Độ mở lấy từ âm lượng từng khung hình (30 lần/giây) của chính câu thoại: RMS → dB, làm mượt 2 khung, so với mức 95% của câu (dưới 24 dB coi là im); < 0,3 khép, < 0,7 nửa, còn lại mở; mỗi hình giữ tối thiểu 2 khung để không giật; khung cuối luôn khép. Đổi hình bằng `tl.set` (an toàn khi tua). Thống kê lưu ở `scene3/lipsync.json` (mỗi câu khoảng 1/3 mở, 1/3 nửa, 1/3 khép).
- Kết quả `tmp/hyperframes-spike/out/scene3_lipsync.mp4` (14,3 giây, 429 khung, render 24 giây, check 0 lỗi, giải mã OK); `lipsync_frames.jpg` đặt miệng của Con cạnh cột âm lượng từng khung để soát.
- Đây là nhép theo năng lượng âm thanh, không khớp từng âm vị (a/o/m...). Muốn khớp âm vị cần căn chỉnh lời–tiếng (forced alignment), chưa làm.

#### SFX cho cảnh 3 vai (2026-11-04)

- Nhạc nền không dùng theo yêu cầu của người dùng; chỉ có hiệu ứng âm thanh.
- Thư viện: `data/editor-sfx/` (do `ensure_sfx_library` của VideoStudio tạo; 4 file tổng hợp bằng toán, giấy phép CC0, không lấy mẫu thu âm): `whoosh`, `click`, `impact`, `chime`. Thư mục `data/` nằm ngoài git.
- `make_scene.py` ghi `sfx.json` theo mốc lời đọc và hành động: whoosh lúc con đi vào; click đầu mỗi câu thoại (5 lần); impact khi bố sốc; whoosh khi bố chỉ tay; chime khi con khóc và mẹ cười đểu.
- `make_sfx.py` trộn thành `assets/sfx.wav`: đặt mỗi hiệu ứng đúng thời điểm (adelay), gain riêng từng loại, track nhân 1,4, amix không chuẩn hoá, giới hạn đỉnh 0,89 để không clip. `<audio id="sfx">` trong composition phát track này.
- Kiểm tra: đo mức âm 0,12 giây tại mỗi điểm đặt đều có tiếng và đoạn trước đó im (chime trùng đuôi click cách 0,3 giây). File `tmp/hyperframes-spike/out/scene3_sfx.mp4`: 14,3 giây, 429 khung, render 24 giây, giải mã OK; mức âm trung bình −20,4 dB, đỉnh −1,6 dB.

Tiêu chí cuối là video tự chạy hết, giữ nguồn/checkpoint và không cần can thiệp khi chỉ thiếu motion tùy chọn. Có demo đẹp hoặc unit test không đủ để mặc định thay renderer cho mọi video. Các mục triển khai tương ứng vẫn để chưa hoàn thành trong TODO.
