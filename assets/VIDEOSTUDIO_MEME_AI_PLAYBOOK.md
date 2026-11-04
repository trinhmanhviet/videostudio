# VIDEO STUDIO — MEME ASSET & ANIMATION AI PLAYBOOK

> **Tệp dành cho AI coding agents (Codex / Claude Code / Gemini CLI), không phải hướng dẫn nhập môn cho người dùng.**
>
> **Version:** `1.0.0` · **Ngày:** `2026-11-03` · **Ngôn ngữ dự án:** tiếng Việt  
> **Asset pack:** `Meme_Animation_Asset_Pack_v1.zip`  
> **Đích tích hợp:** `trinhmanhviet/videostudio` · **Render option:** HyperFrames + GSAP · **Final pipeline:** VideoStudio + FFmpeg.

## 0. CHỈ THỊ DÀNH CHO AGENT — ĐỌC TRƯỚC KHI LÀM VIỆC

Bạn là **Meme Animation Asset Director + Rigging Assistant + Code Animation Engineer** của VideoStudio. Nhiệm vụ: dùng các asset Panda và Banana Cat đã được duyệt để tạo cảnh meme hài có nhân vật nhất quán, tái sử dụng được và **có thể seek đến frame bất kỳ mà không thay đổi kết quả**.

**Bắt buộc:**

1. **Không vẽ lại nhân vật một cách tùy tiện.** Giữ mặt, tỷ lệ, outline và ngôn ngữ hình ảnh theo tham chiếu đã chốt.
2. **Panda:** giữ dạng meme biaoqing trắng–đen 2D, nét đen hơi vụng, biểu cảm cường điệu. **Banana Cat:** giữ dáng chuối vàng cũ hơi thô, mặt mèo sáng màu có texture nhẹ như ảnh tham chiếu; **không** biến thành vector phẳng quá dễ thương, **không** làm vật liệu 3D bóng bẩy.
3. **Không suy đoán nhãn của `component_###.png`.** Đây là tên file tự cắt, chưa phải semantic asset ID. Phải quan sát / kiểm tra và gắn nhãn trước khi cho Motion Director dùng.
4. **Không coi sprite sheet là rig hoàn chỉnh.** Đã có bộ phận dạng hình ảnh, nhưng chưa bảo đảm mọi pose có layer sạch, pivot chính xác, occlusion hợp lý hoặc ảnh tương ứng giữa các góc quay.
5. **Không dùng ảnh có nền bẩn như layer alpha sạch.** Đặc biệt `BananaCat/reference_and_source/banana_cat_rig_source_atlas.png` chỉ là **nguồn tham chiếu / cần cleanup**, không phải production PNG đã rig.
6. **Không làm hỏng pipeline đang chạy.** HyperFrames là một **adapter tùy chọn**, không thay FFmpeg, không tự thay schema `edit_plan` v1, không thay source/checkpoint/scene ID của job hiện hữu.
7. **Không giả định đã cài HyperFrames hoặc adapter.** Trước khi dùng, xác minh dependency, lệnh CLI, phiên bản, license, Windows compatibility và thử một scene độc lập.
8. **Không tự báo “rig-ready”, “test pass”, “render success” khi chưa có bằng chứng.** Có thể dựng bản thử bằng full-pose nếu thiếu rig; phải ghi rõ fallback.
9. Tạo animation dựa trên **ảnh đã có / ref của đúng nhân vật**, không dùng AI-video để sửa lỗi chuyển động theo mặc định.
10. Hoạt động theo cơ chế **quan sát → xác thực → lập kế hoạch → triển khai → kiểm thử → báo cáo**, không lặp tạo asset vô hạn.

---

## 1. CẤU TRÚC THỰC TẾ CỦA BỘ ZIP

Giải nén vào vùng asset riêng, ví dụ `videostudio/assets/meme_pack/` (chỉ là đường dẫn đề xuất, chưa phải thư mục mặc định của repo):

```text
assets/meme_pack/
├── manifest.json
├── BananaCat/
│   ├── production_sheets/
│   │   └── banana_cat_expressions_actions.png
│   ├── auto_sliced/
│   │   └── expressions_actions/
│   │       ├── component_001.png ... component_072.png
│   │       └── components.json
│   └── reference_and_source/
│       ├── banana_cat_original_reference.png
│       └── banana_cat_rig_source_atlas.png       # CHƯA sạch alpha
├── Panda/
│   ├── production_sheets/
│   │   ├── panda_rig_sprite_sheet.png
│   │   ├── panda_expression_asset_sheet.png
│   │   └── panda_actions_props_sheet.png
│   ├── auto_sliced/
│   │   ├── rig/                 # 61 component
│   │   ├── faces_fx/            # 147 component
│   │   └── actions_props/       # 58 component
│   └── reference_and_source/
│       └── panda_original_reference.png
├── examples/
│   ├── manifest.example.json
│   └── hyperframes/
│       ├── index.html
│       └── rig.js
├── tools/
│   └── slice_components.py
└── docs/
    └── Huong_dan_su_dung_Meme_Assets_HyperFrames.docx
```

**Tổng hiện có:** 338 ảnh `component_*.png` được tách tự động (72 Banana Cat + 266 Panda). **Đây là số lượng component, không phải 338 rig-ready action**. Một component có thể là pose, bộ phận, prop hoặc FX. `components.json` chứa tọa độ crop `bbox`, **không chứa pivot/nhãn ngữ nghĩa đã duyệt**.

Phân biệt ba cấp độ asset:

| Cấp | Ý nghĩa | AI được làm gì? |
|---|---|---|
| `source_only` | Sheet / atlas / ảnh tham chiếu | Quan sát, đo, làm nguồn tách; không trực tiếp đóng vai layer sạch |
| `candidate` | Component tự tách chưa gắn nhãn và QC | Đề xuất nhãn, làm contact sheet, kiểm tra alpha / kích thước |
| `approved` | Asset có nhãn, preview, alpha, pivot và kiểm tra ghép | Được tham chiếu trong motion manifest production |

**Không tự nâng `candidate` lên `approved` vì file tồn tại.**

---

## 2. PHONG CÁCH & CHARACTER IDENTITY LOCK

### Panda (`character_id: panda_meme_v1`)

- 2D đen–trắng, thân tối giản, đầu tròn, tai tròn đen.
- Khuôn mặt meme biểu cảm hơi méo, phi thực tế, cố tình “xấu xấu”.
- Không đổi sang gấu trúc 3D, furry/cute mascot, màu sắc hoặc anatomy giải phẫu chi tiết.
- Khi đổi biểu cảm, giữ silhouette đầu và tai ổn định, chỉ thay vùng mặt/mắt/miệng khi kỹ thuật cho phép.

### Banana Cat (`character_id: banana_cat_rough_v1`)

- Silhouette dạng chuối nhỏ đứng, vỏ vàng hơi sẫm, cuống nâu, tay/chân ngắn.
- Mặt mèo trắng/kem đặc trưng, hơi ngơ hoặc buồn, texture ảnh meme cũ có chút sần.
- Đường nét không quá sạch; texture vừa đủ, không vật liệu bóng, không đổ bóng studio, không ánh sáng điện ảnh.
- Không làm lại thành chibi vector hai chiều với mắt to hoặc thành model 3D bóng mượt.
- **Nguồn nhận dạng ưu tiên:** `BananaCat/reference_and_source/banana_cat_original_reference.png`.

### Khi cần vẽ thêm phần còn thiếu

Giữ nguyên nhận diện và góc camera của **pose gốc**. Vẽ/tách chỉ bộ phận đang thiếu (tay, chân, mắt, miệng, mặt rỗng, prop mask...). Không thay cả nhân vật nếu chỉ cần miệng nói. Trước khi duyệt, chồng layer lên chính ảnh gốc để so silhouette, anchor, màu, rìa và chi tiết nhận dạng. Không đưa ảnh mới vào `approved` nếu xuất hiện biến thể nhận diện ngoài ý muốn.

---

## 3. MỤC TIÊU ĐẦU RA CHO TỪNG SCENE

Với mỗi cảnh, agent phải tạo hoặc cập nhật những artefact này **theo nhu cầu thực tế**:

```text
scenes/<scene_id>/
├── story_beats.json          # ai làm gì, cảm xúc gì, thời điểm nào
├── asset_selection.json      # đúng các approved asset ID được chọn
├── motion_manifest.json     # deterministic, seekable, versioned
├── scene.html               # composition HyperFrames, nếu adapter được chọn
├── output.mp4               # chỉ khi thực sự đã render
└── validation_report.json  # kết quả thật, cảnh báo & fallback
```

Giữ `scene_id`, `character_id`, `asset_id` xuyên suốt từ kịch bản tới bản xuất. Dữ liệu của cùng một scene không được tự tái dùng cho nhân vật/job khác nếu thiếu bằng chứng asset khớp.

### Một scene có thể dùng **2 chiến lược**

1. **Full-pose:** dùng cả hình pose, áp `translate/rotate/scale/squash/shake` + camera + FX. Hợp với chạy, ngã, lăn, nằm, bê thùng, trượt vỏ chuối, hành động nhanh.
2. **Modular rig:** tách `body`, `face`, `eyes`, `mouth`, `arms`, `legs`, `prop`, `fx`, gắn pivot và control chuyển động. Hợp với thoại, chớp mắt, nhìn sang bên, chỉ tay, cầm đồ, phản ứng nhỏ.

**Ưu tiên full-pose nếu rig không đủ sạch.** Chuyển pose ở đúng beat âm thanh quan trọng hơn cố ép mọi pose thành rig giả.

---

## 4. ASSET INVENTORY & CATALOG — BƯỚC BẮT BUỘC TRƯỚC KHI TỰ ĐỘNG HÓA

Không dùng tên file `component_001.png` như semantic label. Agent hoặc một bước bán tự động phải tạo **contact sheet** cho từng collection; đọc `components.json` để biết crop tương ứng trên sheet; kiểm tra độc lập từng file và gắn nhãn.

Mỗi asset đã kiểm tra nên có các trường:

```json
{
  "schema_version": 1,
  "asset_id": "banana_pose_idle_front_v1",
  "character_id": "banana_cat_rough_v1",
  "category": "pose",
  "action": "idle",
  "emotion": "neutral",
  "angle": "front",
  "src": "BananaCat/approved/poses/banana_pose_idle_front_v1.png",
  "source": {
    "sheet": "BananaCat/production_sheets/banana_cat_expressions_actions.png",
    "component_file": "BananaCat/auto_sliced/expressions_actions/component_XXX.png"
  },
  "qc": {
    "status": "approved",
    "alpha_clean": true,
    "geometry_checked": true,
    "identity_checked": true,
    "preview_checked": true
  },
  "render": { "anchor": [0.5, 0.95], "pivot": [0.5, 0.75], "z": 10 },
  "tags": ["default", "static", "dialogue"],
  "notes": "CHỈ VÍ DỤ SCHEMA; component_XXX và file approved không có sẵn cho đến khi được tạo/xác minh."
}
```

**Lưu ý:** Giá trị `anchor`, `pivot` ở đây chỉ minh họa cấu trúc, **không phải kết quả đo từ ảnh gốc**. `bbox` crop là tọa độ trong sheet; pivot là tọa độ khớp chuyển động trên chính asset. Phải đo pivot dựa vào bộ phận thực tế.

### Danh mục ngữ nghĩa tối thiểu

```text
character_id       panda_meme_v1 | banana_cat_rough_v1
category           pose | face | eyes | mouth | arm | leg | body | prop | fx | shadow
emotion            neutral | joy | sad | angry | shock | panic | smug | confused | tired
angle              front | three_quarter_left | side_left | back | side_right | three_quarter_right
action             idle | talk | run | sit | stand | point | wave | fall | jump | faint | hold | ...
rig_readiness      none | partial | ready
qc.status          unreviewed | needs_cleanup | approved | rejected
```

Không gán một pose có cả điện thoại + tay + mặt vào `prop: phone` đơn lẻ. Nếu không thể tách sạch, giữ ở dạng **composite full-pose** và gắn thẻ `pose_with_prop`.

---

## 5. QUY TẮC RIG — PHẢI ÁP DỤNG CHO TỪNG MEME/POSE

Mục tiêu dài hạn là mỗi pose quan trọng đều có một mô tả rig riêng; **không phải 1 rig dùng ép cho mọi góc và mọi hành động**.

### 5.1. Layout layer đề xuất

```text
actor-root       translate / rotate / scale toàn nhân vật
  ├── shadow     (độc lập, thường không xoay cùng thân)
  ├── back-leg
  ├── back-arm
  ├── body       (thân + đầu hoặc vỏ chuối)
  ├── face       (khi mặt là miếng thay được)
  │   ├── eyes
  │   └── mouth
  ├── front-leg
  ├── front-arm
  ├── held-prop  (pivot khớp với bàn tay)
  └── fx-front
```

Chỉ tạo node cho layer **thực sự tồn tại**. Không vẽ mắt/miệng “giả” bằng cách đè lên mặt sẵn có nếu gây hai bộ mắt/miệng.

### 5.2. Khớp & bản đồ pivot

- Tay quay quanh **vai**, cẳng tay quanh **khuỷu**, vật cầm quanh **vị trí nắm**.
- Chân quay quanh **hông**; full-pose chạy có thể dùng chuỗi sprite thay vì xoay hai chân.
- Mắt/miệng neo vào hệ tọa độ mặt; khi mặt biến dạng / đổi góc, phải đổi attachment phù hợp.
- `pivot` là tọa độ chuẩn hóa `[0..1, 0..1]` trong *PNG đã cắt*, được đo và lưu. Không tự dùng một giá trị cho toàn bộ pose.
- Sprite cần **khoảng trống viền** tránh bị cắt khi xoay; lưu `anchor`/`bounds`/`canvas` ổn định.
- Layer có vật che trước–sau phải dùng thứ tự Z/mask nhất quán; khi không đủ mask, dùng full-pose.

### 5.3. Cấu trúc rig theo pose

```json
{
  "schema_version": 1,
  "rig_id": "panda_point_front_v1",
  "character_id": "panda_meme_v1",
  "source_pose_id": "panda_pose_point_front_v1",
  "status": "partial",
  "canvas": { "width": 512, "height": 512 },
  "layers": [
    { "id": "body", "asset_id": "panda_body_front_v1", "z": 10 },
    { "id": "arm_front", "asset_id": "panda_arm_point_right_v1", "z": 30,
      "parent": "body", "pivot": [0.15, 0.2], "attachment": "right_shoulder" }
  ],
  "capabilities": ["idle", "point", "small_bounce"],
  "unavailable_capabilities": ["phoneme_lipsync", "walk_cycle"],
  "fallback_pose_id": "panda_pose_point_front_v1"
}
```

**Đây là mẫu hợp đồng dữ liệu cần triển khai / đối chiếu, không phải ID đã kiểm chứng có thật trong ZIP.** Nếu asset ID không tồn tại, chặn build rig đó; không tự dùng file gần giống.

### 5.4. Trạng thái rig

| `rig_readiness` | Cách render |
|---|---|
| `none` | Full-pose + camera/transform/FX |
| `partial` | Phần đã tách sạch được animate, phần còn lại giữ nguyên; tuyệt đối không dựng layer giả |
| `ready` | Cho dùng eye/mouth/arm/prop controls đã được nghiệm thu |

Mỗi pose phải có test nhỏ: **composite lại tất cả layer ở frame chuẩn** và so với ảnh pose tham chiếu; phải thấy mép tay, đầu, quần/vỏ, trật Z, điểm neo, nền bẩn nếu có.

---

## 6. MOTION DIRECTOR — QUY TRÌNH TỪ KỊCH BẢN ĐẾN CHUYỂN ĐỘNG

### 6.1. Đầu vào cần đọc

- `scene_id`, danh sách actor `character_id` và actor instance ID.
- Câu thoại + mốc thời gian đọc thật theo câu/đoạn.
- Mô tả hành động và **comedic beats**: setup, anticipation, reaction, payoff.
- Asset catalog `approved`; asset capability; trạng thái rig; thời lượng; khung ngang/dọc; fps.
- Quy định fallback và giới hạn thời gian/chi phí.

### 6.2. Bộ motion primitive được phép

```text
camera_push, camera_pan, camera_shake, camera_recoil
actor_idle_breathe, actor_bob, actor_squash_stretch
actor_walk_fake, actor_run_translate, actor_jump, actor_fall
pose_swap, face_swap, eye_blink, eye_look
mouth_three_state, head_nod, head_shake
arm_wave, arm_point, arm_hold
prop_appear, prop_move, prop_drop
fx_impact, fx_dust, fx_sweat, fx_speed_lines, fx_pop
```

Nếu bộ phận thiếu, chọn primitive thấp hơn. Không sinh/chạy JavaScript không kiểm soát từ văn bản kịch bản. Agent chọn **tên primitive + tham số đã validate**, renderer mới thực thi.

### 6.3. Quy tắc dựng hài (ưu tiên hiệu quả hơn phức tạp)

1. Setup hình tĩnh 0.4–1.5 s (tùy nội dung).
2. Nét mặt / động tác báo trước 0.15–0.4 s.
3. Reaction hoặc payoff lớn 0.1–0.6 s: `snap pose`, `squash`, `camera_shake`, SFX.
4. Giữ reaction thêm 0.2–0.8 s nếu cần người xem “ngấm” câu hài.
5. Không lắc camera liên tục; không xếp chồng 5 FX che mặt.
6. Dialogue beat bám audio measured cue. Không tự nhận đã có phoneme alignment từ timing câu.

### 6.4. Mouth animation

- V1 chỉ có `closed | half | open`, dựa theo âm lượng và silence của WAV theo frame hoặc interval đã tính trước.
- **Không** gọi đây là lip-sync âm vị hay tự khớp từng từ.
- Ưu tiên thay ảnh miệng bằng các element/sprite clip có timing rõ ràng; tránh callback dùng real-time.
- Không có mouth assets đã QC thì dùng `head_bob`/`face_swap` hoặc giữ nguyên full-pose.

---

## 7. MOTION MANIFEST — DỮ LIỆU CHUẨN DÀNH CHO AI & RENDERER

```json
{
  "schema_version": 1,
  "manifest_id": "scene_0007_motion_v1",
  "scene_id": "scene_0007",
  "fps": 30,
  "duration_frames": 120,
  "canvas": { "width": 1080, "height": 1920 },
  "seed": 20261103,
  "source_hashes": {},
  "engine": { "kind": "hyperframes", "version": "PIN_WHEN_VERIFIED" },
  "actors": [
    {
      "instance_id": "panda_01",
      "character_id": "panda_meme_v1",
      "strategy": "full_pose",
      "asset_id": "panda_pose_idle_front_v1",
      "x": 0.33,
      "y": 0.74,
      "scale": 1.0
    },
    {
      "instance_id": "banana_01",
      "character_id": "banana_cat_rough_v1",
      "strategy": "full_pose",
      "asset_id": "banana_pose_idle_front_v1",
      "x": 0.72,
      "y": 0.74,
      "scale": 1.0
    }
  ],
  "events": [
    { "frame": 0, "target": "panda_01", "primitive": "actor_idle_breathe", "params": { "intensity": 0.02 } },
    { "frame": 36, "target": "panda_01", "primitive": "face_swap", "params": { "emotion": "angry", "on_missing": "keep_pose" } },
    { "frame": 52, "target": "banana_01", "primitive": "pose_swap", "params": { "action": "shock", "on_missing": "squash" } },
    { "frame": 75, "target": "banana_01", "primitive": "actor_run_translate", "params": { "dx": 0.5, "duration_frames": 35 } },
    { "frame": 75, "target": "scene", "primitive": "fx_dust", "params": { "actor": "banana_01" } }
  ],
  "fallback_policy": "automatic_optional_motion_only"
}
```

**Mẫu schema để implement, chưa phải format native của HyperFrames hoặc VideoStudio.** Tất cả `asset_id` trong ví dụ là *logical ID đề xuất*, chỉ được render sau khi map vào catalog thật. `source_hashes` phải được backend điền bằng SHA-256 thực tế; không chấp nhận hash rỗng khi export production. Tham số đo từ frame: `seconds = frame / fps`. Tất cả khoảng thời gian có cùng quy tắc làm tròn. Không dùng `Date.now()`, `Math.random()` chưa seed, CSS animation theo wall clock hoặc promise/network thay đổi theo thời gian để quyết định pose ở frame N.

### Validate manifest (bắt buộc)

```python
# Pure validation example: import into your backend layer after adapting catalog schema.
from pathlib import Path

ALLOWED = {
    'camera_push', 'camera_pan', 'camera_shake', 'camera_recoil',
    'actor_idle_breathe', 'actor_bob', 'actor_squash_stretch',
    'actor_walk_fake', 'actor_run_translate', 'actor_jump', 'actor_fall',
    'pose_swap', 'face_swap', 'eye_blink', 'eye_look', 'mouth_three_state',
    'head_nod', 'head_shake', 'arm_wave', 'arm_point', 'arm_hold',
    'prop_appear', 'prop_move', 'prop_drop',
    'fx_impact', 'fx_dust', 'fx_sweat', 'fx_speed_lines', 'fx_pop'
}

def validate_motion_manifest(manifest, catalog):
    fps = manifest['fps']
    frames = manifest['duration_frames']
    assert isinstance(fps, int) and 1 <= fps <= 60
    assert isinstance(frames, int) and frames > 0
    for actor in manifest['actors']:
        asset = catalog[actor['asset_id']]
        assert asset['character_id'] == actor['character_id']
        assert asset['qc']['status'] == 'approved'
        assert asset['qc']['alpha_clean'] is True
        assert Path(asset['resolved_path']).is_file()  # server-side resolved only
    for event in manifest['events']:
        assert 0 <= event['frame'] < frames
        assert event['primitive'] in ALLOWED
    return True
```

Hàm trên chỉ kiểm tra các invariant cơ bản; khi đưa vào production phải dùng schema validation có lỗi rõ ràng, kiểm tra kiểu số, range, snapshot hash, ownership, path traversal, capability/asset requirements, duplicate IDs và event bounds. **Không cho input web/client tự điền `resolved_path` tuyệt đối.**

---

## 8. HYPERFRAMES + GSAP — CÁCH DỰNG DEMO TỪ ASSET HIỆN CÓ

Thông tin tham chiếu đã đối chiếu với tài liệu chính thức (03/11/2026):

- https://hyperframes.app/docs/1-startup/2-quickstart
- https://hyperframes.app/docs/2-concepts/1-compositions
- https://hyperframes.app/docs/3-guides/3-gsap-animation
- https://hyperframes.app/docs/5-packages/cli

HyperFrames dùng HTML composition, clip có `data-start`, `data-duration`, `data-track-index`, GSAP timeline `paused: true` được đăng ký vào `window.__timelines[composition_id]`. **Không dùng JS điều khiển play/pause media** hoặc xử lý wall-clock timeline; runtime kiểm soát seek.

### 8.1. Demo HTML tối thiểu (đường dẫn có thật trong ZIP)

Lưu ví dụ sau thành `Meme_Animation_Asset_Pack/examples/hyperframes/ai_demo.html`, hoặc thay nội dung `index.html` **trong bản copy demo**. Các đường dẫn ảnh `../../Panda/...` và `../../BananaCat/...` là có thật trong pack; chỉ dùng để kiểm tra kết nối, **chưa có nghĩa `component_001` là đúng biểu cảm/pose theo kịch bản**.

```html
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <style>
    html, body { margin: 0; }
    #scene { position: relative; overflow: hidden; background: #faf8f3; }
    .character { position: absolute; object-fit: contain; transform-origin: 50% 90%; }
    #panda  { width: 360px; height: 440px; left: 70px; top: 800px; }
    #banana { width: 370px; height: 500px; right: 85px; top: 750px; }
    #title  { position: absolute; left: 50px; right: 50px; top: 420px;
              font: bold 65px Arial, sans-serif; text-align: center; }
  </style>
</head>
<body>
  <div id="scene" data-composition-id="meme-ai-demo"
       data-start="0" data-duration="4" data-width="1080" data-height="1920">
    <img id="panda" class="clip character"
         data-start="0" data-duration="4" data-track-index="0"
         src="../../Panda/auto_sliced/rig/component_001.png" alt="Panda" />
    <img id="banana" class="clip character"
         data-start="0" data-duration="4" data-track-index="1"
         src="../../BananaCat/auto_sliced/expressions_actions/component_001.png"
         alt="Banana Cat" />
    <div id="title" class="clip" data-start="0" data-duration="4"
         data-track-index="2">Sếp: Việc này 5 phút thôi!</div>
  </div>

  <!-- Khi cần reproducible/offline render, vendor và pin GSAP bản cục bộ. -->
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.from('#panda', { x: -90, opacity: 0, duration: 0.25 }, 0);
    tl.from('#banana', { x: 90, opacity: 0, duration: 0.25 }, 0.25);
    tl.to('#panda', { rotation: -8, duration: 0.10, yoyo: true, repeat: 3 }, 1.0);
    tl.to('#banana', { x: 250, rotation: 12, duration: 0.45, ease: 'power2.in' }, 2.3);
    window.__timelines = window.__timelines || {};
    window.__timelines['meme-ai-demo'] = tl;
  </script>
</body>
</html>
```

Để chạy demo, làm việc trong một thư mục project HyperFrames với file entry `index.html` đã xác nhận, hoặc sao chép `ai_demo.html` thành `index.html` trong thư mục demo copy; tránh ghi đè ví dụ gốc nếu đang dùng. HyperFrames theo docs yêu cầu Node.js 22+, npm và FFmpeg; agent phải kiểm tra thực tế trên máy trước.

```powershell
# Chạy trong thư mục project HyperFrames có index.html.
npx hyperframes lint
npx hyperframes check
npx hyperframes preview
npx hyperframes render --output demo.mp4
```

`lint` kiểm tra hợp đồng static; `check`/preview kiểm tra runtime và hình ảnh; **chỉ render và decode file thật mới chứng minh MP4 hoạt động**. Không tuyên bố CLI chạy thành công nếu chưa thực thi.

### 8.2. Đổi pose / mặt chính xác theo thời gian

- Với **full-pose**, ưu tiên clip HTML riêng có khoảng `data-start/data-duration` rõ ràng, thay vì callback dựa vào thời gian thực.
- Với **rig**, biểu cảm/miệng cần deterministic state theo frame (`frame => state`) và cùng hệ tọa độ đã QC. Kiểm tra seek ngẫu nhiên tới frame 27, 81 rồi về frame 27 phải cho **cùng pixel**.
- Không dùng `setInterval`, `requestAnimationFrame` tự tăng tiến độ, CSS animation vô hạn hoặc `tl.call()` với side effect không phục hồi được state khi seek lùi.
- Khi cần mouth animation, **biên dịch trước** cue audio thành keyframe/clip thời gian rõ ràng hoặc dùng `tl.set` các trạng thái visual tại mốc tuyệt đối; kiểm thử seek tiến/lùi trước khi cho production.

---

## 9. CÂU LỆNH STORY-TO-MOTION — PROMPT NGẮN CHO AI

Đầu vào ví dụ:

> **“Panda đang giải thích rất nghiêm túc. Mèo chuối lướt điện thoại, nghe đến câu ‘mai nộp báo cáo’ thì đứng hình, khóc rồi bỏ chạy.”**

Agent cần xuất cấu trúc đã validate tương tự:

```json
{
  "scene_id": "scene_0007",
  "style": "awkward_meme_comedy",
  "beats": [
    { "start": 0.0, "end": 1.2, "actor": "panda_01", "action": "explain", "emotion": "serious" },
    { "start": 0.0, "end": 1.2, "actor": "banana_01", "action": "phone", "emotion": "neutral" },
    { "start": 1.2, "end": 1.6, "actor": "banana_01", "action": "freeze", "emotion": "shock" },
    { "start": 1.6, "end": 2.2, "actor": "banana_01", "action": "cry", "emotion": "sad" },
    { "start": 2.2, "end": 3.3, "actor": "banana_01", "action": "run", "emotion": "panic" }
  ]
}
```

Sau đó chọn asset theo quy tắc:

```text
1. Chọn character_id đúng bản tham chiếu.
2. Tìm exact approved asset hỗ trợ action/emotion/angle.
3. Nếu có full-pose phù hợp -> dùng full-pose.
4. Nếu action nhỏ và rig của pose đó ready -> dùng rig.
5. Nếu chỉ có partial rig -> dùng phần được nghiệm thu.
6. Nếu không có asset hợp lệ -> dùng pose gần nhất CÓ CHỨNG CỨ + primitive nhẹ.
7. Nếu không có phương án nào đúng nhận diện -> đánh dấu missing_asset và xuất yêu cầu vẽ/tách cụ thể.
8. Mỗi fallback ghi lại scene, reason, original request, chosen replacement.
```

Không yêu cầu người dùng tự chỉnh 20 tham số cho mỗi cảnh. Agent nên tự chọn preset mặc định, nhưng **không được bịa độ chính xác** hoặc giả scene đã render.

---

## 10. QUY TẮC TỰ TẠO ASSET BỔ SUNG (KHÔNG GÂY STYLE DRIFT)

**Khi thiếu bộ phận để rig một pose cụ thể**, tạo một `asset_request` riêng thay vì thay nhân vật toàn cục:

```json
{
  "request_id": "assetreq_scene0007_banana_mouth_01",
  "character_id": "banana_cat_rough_v1",
  "source_pose_id": "banana_pose_phone_front_v1",
  "part_needed": "mouth_open_small",
  "same_view_as_source": true,
  "requirements": [
    "retain exact face silhouette and identity",
    "match existing yellow shell/cream cat texture",
    "transparent PNG, no halo",
    "no glossy 3D shading",
    "keep original head/eye positions"
  ],
  "output_status": "candidate"
}
```

Đầu ra phải trải qua **alpha QC → compositing alignment → expression test → human/visual acceptance nếu cần → catalog**. Không tự lặp tạo lại mặt/nhân vật vô giới hạn. Nếu không thể vẽ sạch, quay về full-pose.

**Đặc biệt với Banana Cat:** không thay atlas nền bẩn bằng `remove background` cắt ẩu làm mất ria mèo/cạnh vỏ. Cần so ảnh ghép trên nền trắng, xám và đen để phát hiện viền màu/halo.

---

## 11. TÍCH HỢP VÀO VIDEOSTUDIO — KHÔNG PHÁ HỆ THỐNG CŨ

**Vui lòng đọc repo thật trước khi sửa:**

- `README.md`
- `TODO.md`
- `docs/editor-workflow.md` (mục `code-animation`)
- `videostudio/edit_plan.py`, `videostudio/edit_render.py`, `videostudio/providers.py`
- `videostudio/workflow.py`, `videostudio/workflow_api.py`
- `static/editor*`, `static/workflow-canvas*` nếu triển khai UI

### Contract đề xuất

```text
Script/Plan (scene ID hiện hữu)
  -> AssetCatalog (approved asset IDs, SHA-256)
  -> MotionDirector (typed primitives, no arbitrary JS)
  -> motion_manifest.json (version, fps, frame times, seed)
  -> Renderer adapter (HyperFrames optional; existing still/FFmpeg fallback)
  -> Scene MP4 (frozen scene assets + hash)
  -> Existing FFmpeg editor (voice, captions, music, SFX, final mix)
  -> Existing verify/checkpoint/export
```

- **Không** thêm stage top-level mới hoặc đổi `STAGES` nếu chưa có hợp đồng và regression test.
- **Không** sửa trực tiếp `edit_plan` schema v1 bằng field không khai báo; thiết kế sidecar/version/migration và snapshot trước.
- **Không** dùng đường dẫn tùy ý do client cung cấp; resolved paths và hash do backend quản lý.
- **Không** chạy đồng thời nhiều browser/worker/GPU chỉ vì scene nhiều; tôn trọng resource lock hiện có.
- **Không** gửi lại request Flow/ChatGPT/Comfy đang ở trạng thái uncertain delivery.
- Với child export manual có snapshot cố định: engine/asset lỗi phải **báo lỗi và để chọn bản xuất fallback mới**, không thay style âm thầm.
- Chỉ bật bằng explicit opt-in, ví dụ `animation_mode = "meme_motion"` qua một contract được validate và lưu version. UI cũ phải tiếp tục chạy như trước.

### Adapter interface tham khảo (chưa phải API có sẵn của repo)

```python
from typing import Protocol
from pathlib import Path

class SceneAnimationAdapter(Protocol):
    def preflight(self) -> dict: ...
    def validate(self, manifest: dict, catalog: dict) -> None: ...
    def render(self, manifest: dict, output: Path) -> Path: ...

# Ví dụ lựa chọn: HyperFramesAdapter nếu preflight pass;
# nếu thiếu optional motion -> ExistingStillSceneAdapter.
# Không implement một interface và tuyên bố đã tích hợp production.
```

---

## 12. KIỂM THỬ, FALLBACK & DEFINITION OF DONE

### Asset gates

- [ ] `asset_id` không trùng, path có trong pack, extension/alpha hợp lệ.
- [ ] Gắn semantic category/action/emotion/angle bằng kiểm tra hình.
- [ ] Phân loại `full_pose`, `rig_part`, `fx`, `prop`; không lẫn component rác.
- [ ] Giữ nguyên nhận diện Panda / Banana Cat đã chốt.
- [ ] Rig part có pivot/anchor **được đo**, compositing không lộ seams/halo.
- [ ] Có ít nhất ba nền kiểm tra (trắng/xám/đen) và ảnh preview nhiều trạng thái.

### Scene gates

- [ ] Timing frame khớp speech cue (theo độ chính xác thực tế đang có).
- [ ] Seek frame N theo thứ tự ngẫu nhiên vẫn giống render tuyến tính.
- [ ] Không frame rỗng, không nhân vật nhảy vị trí sai, không prop rời tay.
- [ ] Face/eyes/mouth không chồng đúp với mặt full-pose.
- [ ] FPS/canvas/duration và audio/subtitle được xác minh bằng output thật.
- [ ] Cache key gồm source hash + manifest + engine version + fps/canvas + seed.
- [ ] Không sinh lại asset/TTS/nhạc hợp lệ chỉ vì đổi hiệu ứng.

### Production gates

- [ ] Regression UI cũ và API cũ qua.
- [ ] Nghiệm thu demo Panda + Banana Cat 2 nhân vật, ít nhất 3 reaction, 1 prop, 1 đoạn thoại, 1 FX.
- [ ] Thử cả 1080×1920 và 1920×1080.
- [ ] Kiểm tra resume/cancel/cache/fallback; log lý do.
- [ ] Stress test video hỗn hợp nhiều cảnh trước khi bật rộng; không tuyên bố đã đạt nếu chưa thử.

### Fallback theo thứ tự

```text
Full rig animation  -> nếu thiếu capability
Partial rig         -> nếu thiếu layer/mask
Full pose + FX      -> nếu chỉ có pose đã duyệt
Still + pan/zoom    -> nếu không có chuyển động phù hợp
Fail with report    -> nếu không có asset đúng character identity
```

**Không fallback sang một nhân vật khác hoặc ảnh AI mới làm lệch nhận diện.**

---

## 13. KHUÔN MẪU BÁO CÁO MỖI LẦN AGENT THỰC THI

```markdown
### Meme Animation Execution Report
- Repo revision / branch: ...
- Asset pack version: ...
- Character(s): ...
- Scene IDs: ...
- Strategy per scene: full_pose | partial_rig | ready_rig
- New assets: ... (candidate / approved)
- Modified files: ...
- Rig validation: PASS / FAIL / NOT RUN
- HyperFrames preflight: PASS / FAIL / NOT RUN
- Lint / Check / Render: ...
- Output MP4 path + duration + fps: ... (nếu có thật)
- Fallbacks and reasons: ...
- Known blockers: ...
- Existing UI/pipeline regression: ...
```

Không dùng từ `PASS` nếu chỉ mới đọc tài liệu hoặc sinh code.

---

## 14. PROMPT SẴN ĐỂ ĐƯA VÀO CODEX/AGENT

> **ROLE:** You are the Meme Asset and Code Animation Engineer for the existing VideoStudio repo. Read `VIDEOSTUDIO_MEME_AI_PLAYBOOK.md`, `docs/editor-workflow.md`, and the asset pack's `manifest.json` before coding. Preserve the legacy pipeline, job checkpoints, scene IDs and existing UI. Build an inventory of real PNG components; do not invent semantic labels from `component_###` filenames. Maintain approved identity for black-white rough 2D Panda and rough, lightly textured original Banana Cat (not glossy 3D or flat-vector chibi). Validate alpha, asset categories, pivots and rig readiness. Prefer deterministic full-pose animation for large actions and modular rig for confirmed parts. Produce typed motion manifests and an optional HyperFrames/GSAP adapter; keep FFmpeg for media mix/verify and preserve scene-level cache/resume. Run one isolated synthetic end-to-end demo first; test frame seeking, lint, check, MP4 output, old UI regression. If an engine, asset, mouth shape or action is not available, log a bounded fallback; never fabricate completion or redraw the characters without control. Report exact files changed, commands run, test results and outstanding risks.

### Gợi ý câu lệnh đầu tiên cho agent

```text
Đọc VIDEOSTUDIO_MEME_AI_PLAYBOOK.md và toàn bộ manifest của
Meme_Animation_Asset_Pack_v1.zip. Chưa sửa pipeline production.
Bước 1: sinh asset inventory + contact sheet + báo cáo QC.
Bước 2: đề xuất mapping semantic cho các component thực sự dùng được.
Bước 3: dựng 1 scene thử Panda nói, Banana Cat sốc rồi chạy bằng
full-pose + camera + FX, giữ nguyên nhận diện.
Bước 4: verify deterministic seek và MP4. Chỉ sau đó đề xuất
rigging/tích hợp optional HyperFrames vào VideoStudio.
```

---

## 15. TÀI LIỆU LIÊN QUAN

- VideoStudio: https://github.com/trinhmanhviet/videostudio
- Design + roadmap hiện hành: `docs/editor-workflow.md#code-animation`
- HyperFrames quickstart: https://hyperframes.app/docs/1-startup/2-quickstart
- HyperFrames compositions: https://hyperframes.app/docs/2-concepts/1-compositions
- HyperFrames GSAP: https://hyperframes.app/docs/3-guides/3-gsap-animation
- HyperFrames CLI: https://hyperframes.app/docs/5-packages/cli

> **Nguyên tắc cuối:** Asset pack là nguyên liệu, **catalog đã QC + rig manifest + motion manifest + renderer được kiểm thử** mới là hệ thống animation dùng được. Giữ nét meme xấu tự nhiên và tính nhất quán của nhân vật quan trọng hơn hiệu ứng phức tạp.
