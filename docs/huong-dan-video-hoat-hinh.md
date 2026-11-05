# Hướng dẫn tạo video hoạt hình gấu trúc (cho AI agent: Gemini, Codex, Claude)

Tài liệu này để giao cho một AI agent tự tạo video hoạt hình meme gấu trúc tiếng Việt trên máy Windows của người dùng.
Mọi thứ nằm trong **`D:\Projects\videostudio\memestudio`**. Đọc hết trước khi làm. Mọi lệnh đã được chạy thử ngày 2026-11-04.

Tập mẫu làm theo đúng quy trình này: `memestudio\out\ep1.mp4` (60,7 giây, "Bố tôi lần đầu đi thang máy").
Kịch bản của nó: `memestudio\episodes\ep1\script.json`, đọc kỹ để làm theo.

---

## 0. Quy tắc bắt buộc với agent

1. **Chỉ làm việc người dùng yêu cầu.** Không tự nghiên cứu hay sửa những phần không liên quan.
2. **Không sửa pipeline production** (`videostudio\*.py`, `static\`, `extensions\`, `scripts\`) và không khởi động lại VideoStudio.
   Mọi việc làm trong `memestudio\`. Không sửa `memestudio\engine\` hay `memestudio\tools\` nếu người dùng không yêu cầu.
3. **Không xoá** `memestudio\assets\` (bộ phận nhân vật, mặt, tủ đồ, nền, SFX) và `episodes\*\script.json`.
4. **Không commit / push** nếu người dùng chưa bảo. Nếu được bảo commit: không thêm dòng ghi công
   (`Co-Authored-By`, "Generated with ...").
5. **Kịch bản phải tự viết.** Được học định dạng, nhịp, kiểu dàn cảnh của video mẫu người dùng đưa; không chép nguyên
   lời/kịch bản/nhân vật của kênh khác.
6. **Báo cáo trung thực.** Chỉ nói "xong" khi đã chạy đủ các bước kiểm tra ở mục 6 và tự xem ảnh chụp khung hình.
   Bước nào không chạy được thì nói rõ lý do.
7. Không tắt/xoá job video của người dùng. Trước khi tạo giọng đọc, kiểm tra không có job đang chạy (mục 2).

---

## 1. Cấu trúc `memestudio`

```text
memestudio\
├── engine\                 bộ máy dùng chung cho mọi tập (không sửa)
│   ├── make_voice.py       tạo giọng đọc từng câu (VieNeu của VideoStudio) -> episodes\<tập>\assets\voice, voice.json
│   ├── make_episode.py     TỰ DÀN CẢNH: kiểm tra kịch bản, chỗ đứng, khung hình, hành động, nhép miệng, SFX -> index.html
│   └── make_sfx.py         trộn hiệu ứng âm thanh -> episodes\<tập>\assets\sfx.wav
├── tools\                  dựng lại asset nhân vật khi thêm đồ/mặt mới
│   ├── build_rig_faces.py      đầu trống + 10 lớp mặt + miệng tách + mốc mắt/mũi/miệng
│   └── import_rig_wardrobe.py  cắt bảng trang phục/phụ kiện vẽ bằng ChatGPT, đặt lên rig, ảnh duyệt
├── assets\
│   ├── rig\parts\          tay, chân, bóng của gấu
│   ├── rig\source\faces_fx\ 11 đầu gốc (nguồn cho build_rig_faces.py)
│   ├── rig\faces\          head_base.png, face_*.png, mouth_*.png, faces.json
│   ├── rig\wardrobe\       30 trang phục, 8 tóc, 8 mũ, 8 đồ đeo mặt, wardrobe.json, ảnh preview_*.jpg
│   ├── rig\sheets\         8 bảng gốc ChatGPT vẽ; rig\base\torso_core.png (khuôn thân)
│   ├── backgrounds\        72 nền bg_*.png (bản sao; chế độ meme cũ của VideoStudio vẫn dùng bản trong assets\Meme_Animation_Asset_Pack\new)
│   └── sfx\                whoosh, click, impact, chime (CC0, VideoStudio tự tổng hợp)
├── episodes\<tập>\script.json   kịch bản từng tập (agent viết); các file khác trong thư mục tập là file sinh ra
├── out\                    MP4 đã render
├── package.json            HyperFrames 0.9.10 + GSAP 3.13.0 (ghim phiên bản, vá undici 7.30.1)
└── node_modules\           cài bằng `npm install` (không nằm trong git)
```

Luồng một tập: `script.json` → `make_voice.py` → `make_episode.py` → `make_sfx.py` → HyperFrames render → MP4.

---

## 2. Điều kiện trước khi làm (kiểm tra mỗi lần)

Chạy trong PowerShell:

```powershell
Set-Location D:\Projects\videostudio\memestudio
node --version                      # cần v22 trở lên
ffmpeg -version | Select-Object -First 1
python -I -c "import numpy, PIL; print('python ok')"
Test-Path node_modules\hyperframes\bin\hyperframes.mjs                      # False thì chạy: npm install
Test-Path D:\Projects\storyforge\.runtime\media\.venv\Scripts\python.exe   # giọng đọc VieNeu, phải True
# Không có job video nào đang chạy (giọng đọc dùng chung GPU):
python -I -c "import sqlite3; c=sqlite3.connect('file:../data/jobs.sqlite3?mode=ro', uri=True); print('jobs dang chay:', c.execute('select count(*) from jobs where state in (?,?)', ('running','queued')).fetchone()[0])"
```

Nếu số job đang chạy khác 0: dừng, báo người dùng, không tạo giọng đọc.

HyperFrames có gửi telemetry; mỗi phiên PowerShell đặt trước khi render:

```powershell
$env:HYPERFRAMES_NO_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
```

Mọi lệnh dưới đây chạy **trong thư mục `D:\Projects\videostudio\memestudio`**.

---

## 3. Quy trình tạo một tập mới (từng bước)

Ví dụ tập `ep2`. Tên tập: chữ thường, không dấu, không khoảng trắng.

### Bước 1: tạo thư mục tập

```powershell
New-Item -ItemType Directory episodes\ep2
```

### Bước 2: viết `episodes\ep2\script.json` (mục 4), lưu UTF-8

### Bước 3: kiểm tra kịch bản (không tốn GPU)

```powershell
python -I engine\make_episode.py episodes\ep2 --check
```

Phải in `OK: script.json hợp lệ`. Nếu in danh sách lỗi: sửa đúng từng dòng rồi chạy lại cho tới khi OK.

### Bước 4: tạo giọng đọc

```powershell
python -I engine\make_voice.py episodes\ep2
```

In độ dài từng câu và `total speech`. Khoảng 4–5 giây máy cho mỗi câu. Chạy lại chỉ tạo những câu đã đổi chữ hoặc đổi giọng.
**Mỗi lần sửa `text`, `who` hoặc thêm/bớt câu phải chạy lại bước này.**
Bộ dựng kiểm tra cả chữ, thứ tự/người nói, giọng đã chọn và checksum WAV qua `voice.json`/file `.id`.
Sau khi nâng phiên bản bộ dựng, metadata giọng cũ có thể cần chạy lại `make_voice.py`; WAV có cache stamp khớp được dùng lại, không bắt tạo lại mọi câu.


### Bước 5: dựng cảnh và trộn SFX

```powershell
python -I engine\make_episode.py episodes\ep2
python -I engine\make_sfx.py episodes\ep2
```

`make_episode.py` in ví dụ: `23 beats, 6 scenes, 60.7 s, 28 shots, 38 sfx, ...`. Ghi lại để báo cáo.

### Bước 6: kiểm tra composition

```powershell
node node_modules\hyperframes\bin\hyperframes.mjs check episodes\ep2
```

Phải có `0 error(s)` ở mọi mục và dòng `Check passed`. Các `⚠` warning (thiếu id cho Studio, `nested_structure`,
`duplicate_media`, `gsap_repeated_fromto`) là bình thường với bộ dựng này.

### Bước 7: chụp khung hình và tự xem

Lấy các mốc trong `episodes\ep2\staging.json` (`camera`: thời điểm, kiểu khung, nhân vật). Chụp ít nhất 1 khung mỗi cảnh,
mọi khung "close" và mọi cú cắt phản ứng:

```powershell
node node_modules\hyperframes\bin\hyperframes.mjs snapshot episodes\ep2 --at 1.5,4.2,9.5,14.5 --no-end -o snap_ep2
```

Mở `snap_ep2\contact-sheet.jpg` (hoặc từng `frame-*.png`) và kiểm tra theo mục 6.

### Bước 8: render

```powershell
node node_modules\hyperframes\bin\hyperframes.mjs render episodes\ep2 --quiet --fps 30 -o out\ep2.mp4
```

Thời gian render xấp xỉ bằng thời lượng video (60 giây video ≈ 62 giây dựng).

### Bước 9: kiểm tra MP4 (mục 6), rồi báo cáo đường dẫn `memestudio\out\ep2.mp4`

---

## 4. Viết `script.json`

### 4.1 Cấu trúc tổng

```json
{
 "title":  ["DÒNG 1 TIÊU ĐỀ", "DÒNG 2 TIÊU ĐỀ"],
 "payoff": ["DÒNG 1 CÂU CHỐT", "DÒNG 2 CÂU CHỐT"],
 "cast": {
  "bo":  {"name": "Bố", "costume": "ao_ba_ba_nau", "acc": ["mu_coi", "rau_mep"], "face": "noi", "voice": "Xuân Vĩnh"}
 },
 "narrator_voice": "Thiện Minh",
 "scenes": {
  "que": {"bg": "bg_90s_rural_yard", "cast": ["bo", "con"]}
 },
 "beats": [
  {"scene": "que", "who": "N", "focus": "bo", "text": "Bố tôi cả đời ở quê.", "emo": {"bo": "cuoi"}}
 ]
}
```

- `title`: dải trên, **đúng 2 dòng**, chữ IN HOA, mỗi dòng **tối đa 18 ký tự** (18 ký tự đã sát mép).
- `payoff`: dải dưới, đúng 2 dòng, IN HOA, tối đa 18 ký tự/dòng. Là câu móc gây tò mò về cái kết.
- `cast`: mỗi vai một id ngắn (chữ thường không dấu). `name` chỉ để đọc kịch bản.
  - `costume`: một id trang phục (mục 7.2). Váy tự ẩn chân.
  - `acc`: 0–3 phụ kiện: tối đa 1 tóc **hoặc** 1 mũ, thêm đồ đeo mặt nếu muốn.
  - `face`: mặt mặc định lúc mở đầu (mục 7.1).
  - `voice`: id giọng (mục 7.4). Các vai nên khác giọng.
- `narrator_voice`: giọng người kể ("tôi"). Nếu người kể cũng là một vai (ví dụ `con`), dùng cùng giọng với vai đó.
- `scenes`: mỗi bối cảnh một id. `bg` là tên file nền không có `.png` (mục 7.3). `cast` là **1–3 vai, thứ tự trái → phải**.
  Muốn ai chỉ tay vào ai thì xếp họ đứng cạnh nhau.
- `beats`: danh sách câu theo thứ tự thời gian. Các câu liên tiếp cùng `scene` thành một cảnh. Được quay lại bối cảnh đã dùng.

### 4.2 Mỗi câu (`beat`)

| Trường | Bắt buộc | Ý nghĩa |
|---|---|---|
| `scene` | có | id bối cảnh trong `scenes` |
| `who` | có | `"N"` = người kể (lồng tiếng, không nhép miệng) hoặc id vai có trong cảnh (vai đó nói, có nhép miệng) |
| `focus` | khi `who` = `"N"` | vai mà máy quay hướng vào khi người kể nói |
| `text` | có | chữ đưa vào giọng đọc. **Viết số bằng chữ** ("mười hai", không viết "12"); câu 6–14 từ, đọc 1,5–3 giây |
| `caption` | không | chữ hiện phụ đề nếu khác `text` (ví dụ có số: "tầng 12") |
| `emo` | không | đổi mặt khi câu bắt đầu: `{"bo": "gian", "con": "lo"}`. Mặt giữ nguyên tới khi đổi lần sau |
| `act` | không | danh sách hành động (mục 4.3) |
| `punch` | không | câu gây cười: sau câu có cú cắt cận mặt người nghe phản ứng `{"who": "con", "face": "soc"}` (+0,8 giây) |

### 4.3 Hành động (`act`)

| Hành động | Cú pháp | Hiệu ứng | SFX tự thêm |
|---|---|---|---|
| Đi vào | `["walk_in", "yta"]` | vai bắt đầu ngoài khung, bước vào chỗ đứng trong 1 giây. Vai này **chỉ xuất hiện từ câu đó** | whoosh |
| Vung tay | `["gesture", "con"]` | tay phải xoè ngửa, vung khi nói | — |
| Chỉ tay | `["point", "bo", "con"]` | chỉ về phía vai thứ hai, người nghiêng theo | whoosh |
| Lắc đầu giận | `["angry", "bo"]` | lắc đầu nhanh 0,6 giây | impact nhỏ |
| Sốc | `["shock", "bo"]` | mặt sốc, đầu bật lên, hai tay dang ra; máy quay rung | impact |
| Run rẩy | `["tremble", "bo"]` | cả người run suốt câu; máy quay rung | impact |
| Nghiêng về | `["lean", "bo", "con"]` | người nghiêng sát về vai kia (bám, ghé tai) | — |
| Bấm liên tục | `["press", "bo"]` | tay chỉ nhấp liên tục (bấm nút, gõ) | click liên tục |
| Ngửa cổ | `["look_up", "bo"]` | ngửa đầu nhìn lên | — |
| Chuông thang máy | `["ding", 3]` | không có hình, 1–6 tiếng chuông chia đều trong câu | chime |

Tự động, không cần ghi: nói (gật đầu + nhép miệng), thở, khóc (khi vai chính của câu đổi sang mặt `khoc`),
click đầu mỗi câu thoại, whoosh khi đổi cảnh.

### 4.4 Độ dài và nhịp

- Giọng đọc khoảng 3,5–4 âm tiết/giây. Mỗi câu thường 1,7–2,8 giây; bộ dựng thêm 0,3 giây nghỉ giữa câu, 0,8 giây cho mỗi `punch`.
- **1 phút ≈ 22–25 câu**; **3 phút ≈ 65–75 câu** (chia 8–14 cảnh).
- Cấu trúc nên dùng (giống video mẫu): câu đầu móc ngay vào chuyện, người kể ngôi thứ nhất dẫn mạch, thoại của nhân vật
  dùng cho chỗ gây cười, cứ 3–5 câu có một `punch`, cảnh mới khi đổi địa điểm, câu cuối là cú chốt + `punch`.
- Mỗi cảnh 3–8 câu. Cảnh dài hơn nên tách (đổi bối cảnh hoặc quay lại sau).
- Dùng `emo` liên tục để mặt luôn hợp với câu; `soc`/`gian`/`khoc` sẽ được quay cận.

### 4.5 Luật bộ dựng tự áp dụng (để biết kết quả sẽ ra sao)

- **Chỗ đứng**: 1 vai ở giữa; 2 vai ở 1/3 và 2/3; 3 vai chia đều, theo thứ tự `cast` của cảnh.
- **Khung hình**: câu đầu mỗi cảnh = toàn cảnh; câu có cảm xúc mạnh (`soc`, `gian`, `khoc`) hoặc hành động lớn
  (`shock`, `tremble`, `angry`, `press`) = cận mặt; còn lại = trung cảnh vào người nói (hoặc `focus`); không lặp cùng khung
  liên tiếp; câu có `walk_in` = toàn cảnh; mọi khung đều đẩy chậm vào 5%.
- **Phản ứng**: sau câu có `punch`, cắt cận mặt người nghe với mặt đã ghi trong 0,8 giây.
- **Nhép miệng**: chỉ khi `who` là vai; độ mở theo âm lượng 30 lần/giây.
- **Bố cục**: tiêu đề trên (y 0–500), khung truyện 1080×700 (y 500–1200), câu chốt dưới, phụ đề trắng viền đen trong khung.

---

## 5. Video dài

| Loại | Độ dài | Cách làm |
|---|---|---|
| YouTube Shorts | tới 3 phút | một thư mục tập, 65–75 câu |
| Reels Facebook dài | 10–15 phút | chia thành **phần 2–3 phút**, mỗi phần một thư mục (`ep5_p1`, `ep5_p2`, ...) cùng `cast`, render từng phần rồi ghép |

Lý do chia phần: phần nào lỗi thì chỉ làm lại phần đó; một composition dài hơn 1 phút chưa được thử.

Ghép phần (cùng bộ dựng nên ghép không mã hoá lại; đã thử ngày 2026-11-04):

```powershell
Set-Location D:\Projects\videostudio\memestudio\out
"file 'ep5_p1.mp4'`nfile 'ep5_p2.mp4'`nfile 'ep5_p3.mp4'" | Out-File -Encoding ascii parts.txt
ffmpeg -v error -y -f concat -safe 0 -i parts.txt -c copy ep5_full.mp4
```

Phần 2 trở đi: giữ nguyên `title`/`payoff`, câu đầu mỗi phần nối tiếp mạch, không giới thiệu lại.
Ước tính máy: 15 phút ≈ 340 câu ≈ 25–30 phút tạo giọng + khoảng 15–20 phút render.

---

## 6. Kiểm tra và nghiệm thu (bắt buộc trước khi báo xong)

1. `python -I engine\make_episode.py episodes\<tập> --check` → `OK`.
2. `hyperframes check episodes\<tập>` → 0 error ở mọi mục.
3. Xem ảnh chụp khung hình (mục 3 bước 7), từng ảnh:
   - nhân vật không bị che mất mặt bởi vai khác; tay chỉ hướng đúng người;
   - râu/kính/khẩu trang nằm đúng chỗ trên mặt; tóc/mũ đội đúng đầu;
   - phụ đề không tràn quá 2 dòng; tiêu đề và câu chốt không tràn;
   - khung cận thấy rõ mặt người nói/người phản ứng.
4. Kiểm tra MP4:

```powershell
ffprobe -v error -show_entries stream=codec_type,width,height,r_frame_rate,nb_frames -show_entries format=duration -of compact out\ep2.mp4
ffmpeg -v error -i out\ep2.mp4 -f null -          # không in gì = giải mã toàn bộ OK
ffmpeg -hide_banner -i out\ep2.mp4 -af volumedetect -vn -f null - 2>&1 | Select-String "mean_volume|max_volume"
```

   Cần: 1080×1920, 30/1 fps, có stream audio, thời lượng khớp số `make_episode.py` in ra; `max_volume` dưới 0 dB
   (khoảng −1 đến −4 dB), `mean_volume` khoảng −18 đến −22 dB.
5. Báo cáo cho người dùng: đường dẫn MP4, thời lượng, số câu/cảnh/khung hình, kết quả các bước trên, và những chỗ còn
   chưa đẹp nhìn thấy trong ảnh chụp.

---

## 7. Danh sách id được phép

### 7.1 Mặt (`face`, `emo`, `punch.face`)

| id | Biểu cảm | Dùng khi |
|---|---|---|
| `noi` | nói bình thường | mặc định, kể chuyện |
| `lo` | lo lắng | ngại, sợ, khó xử |
| `gian` | giận | cáu, mắng (quay cận) |
| `soc` | sốc, mắt tròn | bất ngờ (quay cận) |
| `khoc` | khóc chảy nước mắt | buồn, bị mắng, thất bại (quay cận, gục đầu) |
| `buon` | buồn | chán, thất vọng nhẹ |
| `cuoi` | cười to | vui, khoe |
| `cuoi_deu` | cười đểu | mỉa, đắc ý |
| `ngap` | ngáp, lim dim | buồn ngủ, ngẩn |
| `chu_moi` | chu môi | làm duyên, hờn |

### 7.2 Trang phục và phụ kiện

- **Áo (24)**: `ao_ba_lo_trang`, `ao_phong_xanh`, `so_mi_ca_vat`, `so_mi_caro`, `ao_len_nau`, `ao_khoac_da`, `blouse_bac_si`,
  `ao_cong_nhan`, `tap_de_dau_bep`, `vest_den`, `ao_bao_ve`, `ao_ba_ba_nau`, `so_mi_hoc_sinh`, `ao_da_bong`, `hoodie_xam`,
  `ao_mua_vang`, `ao_phao_den`, `ao_the_duc`, `ao_hoa_hong`, `ao_ba_ba_hoa`, `so_mi_co_no`, `ao_len_co_lo`, `ao_hai_day`, `cardigan_be`.
- **Váy, ẩn chân (6)**: `vay_hoa_dai`, `dam_do`, `ao_dai_trang`, `vay_yem`, `dam_ngu_hong`, `vay_cuoi`.
  Vai mặc váy không nên `walk_in` (không có chân để bước).
- **Tóc (8)**: `toc_xoan_ngan`, `toc_dai_thang`, `toc_bui_cao`, `toc_hui_cua`, `toc_dung_nguoc`, `hoi_toc_bac`, `toc_tet_bim`, `toc_mai_ngo`.
- **Mũ (8)**: `non_la`, `mu_bao_hiem`, `mu_luoi_trai`, `mu_len`, `mu_dau_bep`, `mu_coi`, `vuong_mien`, `bang_do`.
- **Đồ đeo mặt (8)**: `kinh_ram`, `kinh_can`, `rau_mep`, `rau_quai_non`, `rau_de`, `khau_trang`, `bang_ca_nhan`, `ma_hong`
  (tự đặt theo mắt/mũi/miệng của từng mặt; `khau_trang` che miệng nên không thấy nhép miệng).

Ảnh xem trước: `memestudio\assets\rig\wardrobe\preview_costume.jpg`, `preview_accessories.jpg`, `preview_face_items.jpg`,
`preview_characters.jpg` (12 nhân vật phối sẵn: bố, mẹ, học sinh, bác sĩ, đầu bếp, cô dâu, nông dân, vệ sĩ, công nhân,
cầu thủ, cô gái váy đỏ, người mặc áo phao).

### 7.3 Nền (`bg`, 72 file trong `memestudio\assets\backgrounds`)

- Thập niên 90 thành phố: `bg_90s_apartment_yard`, `bg_90s_bedroom`, `bg_90s_classroom`, `bg_90s_coffee_stall`, `bg_90s_game_shop`,
  `bg_90s_kitchen`, `bg_90s_living_room`, `bg_90s_market`, `bg_90s_post_office`, `bg_90s_street`, `bg_90s_train_station`, `bg_90s_village_house`.
- Thập niên 90 thôn quê: `bg_90s_rural_bamboo_gate`, `bg_90s_rural_communal_house`, `bg_90s_rural_dirt_road`, `bg_90s_rural_grocery`,
  `bg_90s_rural_house_inside`, `bg_90s_rural_kitchen`, `bg_90s_rural_market`, `bg_90s_rural_pond`, `bg_90s_rural_rice_field`,
  `bg_90s_rural_river_ferry`, `bg_90s_rural_school`, `bg_90s_rural_yard`.
- Chung: `bg_airport`, `bg_alley`, `bg_apartment_corridor`, `bg_bank_counter`, `bg_bathroom`, `bg_beach`, `bg_bedroom`, `bg_bedroom_night`,
  `bg_bus_interior`, `bg_bus_stop`, `bg_car_interior`, `bg_cinema`, `bg_classroom`, `bg_clinic`, `bg_coffee_shop`, `bg_construction_site`,
  `bg_countryside`, `bg_elevator`, `bg_farm`, `bg_forest`, `bg_gym`, `bg_hospital_corridor`, `bg_karaoke_room`, `bg_kitchen`, `bg_library`,
  `bg_living_room`, `bg_market`, `bg_meeting_room`, `bg_messy_room`, `bg_mountains`, `bg_office`, `bg_office_night`, `bg_park`,
  `bg_rainy_street`, `bg_restaurant`, `bg_rooftop`, `bg_school_yard`, `bg_space`, `bg_stage`, `bg_store`, `bg_street`, `bg_street_eatery`,
  `bg_street_night`, `bg_supermarket_checkout`, `bg_swimming_pool`, `bg_tet_house`, `bg_train_station`, `bg_wedding_hall`.

Nền là ảnh dọc 720×1280, bộ dựng lấy dải giữa–dưới (tường + sàn) làm khung ngang.

### 7.4 Giọng (`voice`, `narrator_voice`)

| id | Giới tính | Vùng | Phong cách |
|---|---|---|---|
| `Thiện Minh` | nam | Bắc | kể chuyện (người dùng hay dùng làm người kể) |
| `Thanh Bình` | nam | Bắc | kể chuyện |
| `Thiền Tâm Đức` | nam | Bắc | kể chuyện |
| `Xuân Vĩnh` | nam | Bắc | tự nhiên |
| `Phạm Tuyên` | nam | Bắc | tự nhiên |
| `Quốc Tuấn` | nam | Bắc | tự nhiên |
| `Hải Đăng` | nam | Bắc | tự nhiên |
| `Adam bựa` | nam | Bắc | tự nhiên |
| `Minh Đức` | nam | Bắc | tin tức |
| `Quang Sơn` | nam | Trung | tự nhiên |
| `Adam` | nam | Nam | tự nhiên |
| `Thái Sơn` | nam | Nam | kể chuyện |
| `Minh Triết` | nam | Nam | tin tức |
| `Đức Trí` | nam | Nam | đọc truyện |
| `Ngọc Huyền` | nữ | Bắc | tự nhiên |
| `Trúc Ly` | nữ | Bắc | tự nhiên |
| `Đoan Trang` | nữ | Bắc | tự nhiên |
| `Ngọc Linh` | nữ | Bắc | kể chuyện |
| `Quỳnh Anh` | nữ | Bắc | đọc truyện |
| `Mai Anh` | nữ | Bắc | tin tức |
| `Ngọc Trân` | nữ | Trung | tự nhiên |
| `Kim Thanh` | nữ | Nam | đọc truyện |
| `Mỹ Duyên` | nữ | Nam | đọc truyện |
| `Thục Đoan` | nữ | Nam | kể chuyện |
| `Thùy Dung` | nữ | Nam | tin tức |
| `clone:18cad821-0d87-461f-a443-d45db92e36e9` | nữ | — | giọng clone "Vương Bờm - nữ" |
| `clone:d3cb8a12-f26f-4433-8bbe-a1af7d6560b9` | nữ | — | giọng clone "Gấu hài hước - nữ cao" (hợp vai trẻ con) |

Viết id đúng từng dấu. Giọng `clone:...` khác không được dùng nếu người dùng chưa đồng ý.

---

## 8. Thêm asset (chỉ khi người dùng yêu cầu)

- **Nền mới**: thêm `bg_<tên>.png` (dọc 720×1280, cùng phong cách) vào `memestudio\assets\backgrounds`, dùng ngay bằng `"bg": "bg_<tên>"`.
- **Trang phục / phụ kiện mới**: nhờ app ChatGPT vẽ một bảng lưới (áo 3×2, phụ kiện 4×2), nền trong suốt, theo đúng khuôn
  (cách viết prompt và ảnh tham chiếu: `docs\editor-workflow.md`, mục "Thân mới và tủ đồ nhân vật"). Lưu bảng vào
  `memestudio\assets\rig\sheets\`, thêm tên file + danh sách id vào `COSTUMES` hoặc `HEAD_SHEETS` trong
  `tools\import_rig_wardrobe.py`, rồi chạy `python -I tools\import_rig_wardrobe.py` và xem các ảnh `preview_*.jpg`.
- **Dựng lại mặt** (chỉ khi đổi đầu nguồn): `python -I tools\build_rig_faces.py`, xem `assets\rig\faces\preview_landmarks.jpg`.

---

## 9. Lỗi thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `--check` báo `... không có: ...` | id sai chính tả hoặc không có trong mục 7 | sửa đúng id |
| `voice.json không khớp script.json` | sửa kịch bản sau khi tạo giọng | chạy lại `engine\make_voice.py episodes\<tập>` |
| `Cách dùng: ...` | quên thư mục tập trong lệnh | thêm `episodes\<tập>` |
| `make_voice.py` lỗi `Unknown voice` / `Clone reference unavailable` | id giọng sai hoặc giọng clone mất file mẫu | chọn giọng khác ở mục 7.4 |
| `make_voice.py` chậm bất thường hoặc lỗi CUDA | GPU đang bận (job VideoStudio, ComfyUI) | chờ job xong; không dừng job của người dùng |
| Không có `node_modules\hyperframes` | chưa cài | `npm install` trong `memestudio` |
| Tay chỉ bị vai khác che | thứ tự `cast` để người khác đứng giữa | xếp người chỉ và người bị chỉ cạnh nhau |
| Phụ đề 3 dòng, tràn | câu quá dài | tách câu (≤ 14 từ) |
| Render báo lỗi `player ready timeout` | máy bận | đóng ứng dụng nặng, render lại; có thể thêm `--workers 2` |
| Đọc sai số, từ viết tắt | TTS đọc chữ như viết | viết số bằng chữ trong `text`, để số trong `caption` |

---

## 10. Giới hạn hiện tại (nói rõ khi báo cáo, không tự sửa nếu không được yêu cầu)

- Nhân vật luôn nhìn thẳng; chưa có dáng nghiêng/quay lưng; đi vào là trượt ngang + bước chân nhìn thẳng.
- Chỉ có các hành động trong mục 4.3; chưa có chạy, ngã, ngồi, cầm đồ vật.
- Tối đa 3 vai trong một cảnh.
- Nhép miệng theo độ to của tiếng, không khớp từng âm.
- SFX chỉ có 4 loại; chưa có nhạc nền (người dùng chưa cần nhạc). Tập không có SFX vẫn xuất track im lặng đúng thời lượng.
- Chưa tích hợp vào giao diện VideoStudio; chạy bằng lệnh trong `memestudio`.

Chi tiết kỹ thuật và lịch sử xây dựng: `docs\editor-workflow.md` (mục "Kết quả engine spike HyperFrames" và các mục con).
Lưu ý: các mục đó ghi đường dẫn cũ `tmp\hyperframes-spike\` và `assets\Meme_Animation_Asset_Pack\rig\`; nay tất cả đã chuyển vào `memestudio\`.
