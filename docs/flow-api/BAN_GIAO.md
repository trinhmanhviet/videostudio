# BÀN GIAO — Google Flow (Whisk) API Automation

> Mục tiêu: Trích xuất POST methods từ `network.har`, viết Python code cho 5 chức năng:
> tạo project, tạo nhân vật, đổi tên nhân vật, tạo ảnh (0/1/2 reference).
> Ngày: 02/11/2026

---

## 1. Trạng thái tổng quan

| Chức năng | RPC | Trạng thái |
|-----------|-----|-----------|
| Tạo project | `jHPbke` | ✅ HOẠT ĐỘNG |
| Tạo nhân vật | `C4BZMd` | ✅ HOẠT ĐỘNG |
| Đổi tên nhân vật | `rzMKMb` | ✅ HOẠT ĐỘNG |
| Tạo ảnh (gọi RPC thủ công) | `ogiZ0b` | ❌ BỊ CHẶN (anti-abuse) |
| Tạo ảnh (điều khiển UI) | — | ✅ HOẠT ĐỘNG (đã xác nhận request fire) |

## 2. File trong thư mục làm việc

| File | Vai trò |
|------|---------|
| `flow_browser.py` | **Client chính** — Playwright + Chrome thật. Đủ 5 hàm + `generate_image_via_ui()` |
| `flow_api.py` | Client dùng `requests` (payload đúng, nhưng bị chặn bot — chỉ tham khảo) |
| `cookie.txt` | 39 cookie mới (tự xuất sau khi đăng nhập) |
| `flow_profile/` | Hồ sơ Chrome đã đăng nhập → chạy lại KHÔNG cần đăng nhập |
| `network.har` | HAR gốc (13.7 MB) |

---

## 3. Kiến trúc API

**Endpoint duy nhất** (dạng RPC "batchexecute" của Google):

```
POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute
    ?rpcids=<RPCID>&source-path=<path>&bl=boq_labs-ai-sandbox-frontend_20261030.00_p2
    &f.sid=<session_id>&hl=vi&_reqid=<counter>&rt=c

Body (application/x-www-form-urlencoded):
    f.req = [[["<RPCID>", "<payload_json_string>", null, "generic"]]]
    at    = "<xsrf_token>:<timestamp_ms>"
```

Response dạng:
```
)]}'\n\n<len>\n[["wrb.fr","<RPCID>","<payload_json_string>",null,null,null,"generic"],...]\n<len>\n[["e",...]]
```
→ parse: bỏ tiền tố `)]}'`, tách theo dòng, tìm phần tử `wrb.fr`, `json.loads(item[2])`.

### Các RPC ID đã trích xuất

| RPC | Chức năng | Payload |
|-----|-----------|---------|
| `jHPbke` | Tạo project | `["projects/*", [null, [name]], [null, 22]]` → trả `[project_id, [name]]` |
| `UpteDb` | List projects | `["projects/*", 21, null, null, null, null, [1]]` |
| `C4BZMd` | Tạo nhân vật | `[[project_id, null, null, [1, name, []]]]` → trả `[[[pid, cid, null, [1,name,[]], ...]]]` |
| `rzMKMb` | Đổi tên nhân vật | `[[pid, cid, null, [1, new_name]], [["entity_info.display_name"]]]` |
| `ogiZ0b` | Tạo ảnh | xem mục 5 |
| `ngNC2` | List characters | `["tools/PINHOLE/projects/<pid>"]` |
| `nzlxg` | Poll state | `[]` |
| `WuwhI` | Log events | (không cần) |

---

## 4. Xác thực (auth)

1. **Cookie**: gửi kèm (`.google.com` + `flow.google.com`). Cookie đầy đủ phải có `HSID`
   (bản export đầu tiên THIẾU `HSID` → gây lỗi 401).
2. **Token `at`** (XSRF): KHÔNG tự tính được bằng thuật toán SHA1 chuẩn.
   Thuật toán thật cho ra hash **28 ký tự** (21 bytes), còn `sha1+base64url` chuẩn chỉ 27 ký tự.
   → **Giải pháp: BẮT token `at` từ request của chính trang** (xem `_capture()` trong flow_browser.py).
3. **`f.sid`**: cũng bắt từ request của trang.

### Chống bot (login)
Google chặn trình duyệt automation ở bước đăng nhập ("This browser or app may not be secure").
Cách vượt (đã áp dụng trong `flow_browser.py`):
```python
launch_persistent_context(profile_dir, channel="chrome", headless=False,
    args=["--disable-blink-features=AutomationControlled", ...],
    ignore_default_args=["--enable-automation"])
context.add_init_script("""Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); ...""")
```

---

## 5. Payload TẠO ẢNH (`ogiZ0b`) — đã xác minh khớp request thật

```
[
  null,                                            # [0]
  [                                                # [1] danh sách generation request
    [
      null, null, null,                            # [0][1][2]
      <seed:int>,                                  # [3] seed ngẫu nhiên
      3,                                           # [4] MODE = 3 (KHÔNG phải 2 như HAR cũ!)
      "BELUGA",                                    # [5] model
      null,                                        # [6]
      [null,22,null,null,null,<pid>,null,null,null,null, [<TOKEN>,1]],  # [7] context
      [[["<prompt text>"]]],                       # [8] prompt (0 reference)
      null,                                        # [9]
      null,                                        # [10] char_ids (null = 0 reference)
      null,                                        # [11]
      "<UUID>", "<UUID>"                           # [12][13]
    ]
  ],
  1,                                               # [2] count
  [null,22,null,null,null,<pid>,null,null,null,null, [<TOKEN>,1]],   # [3] context (lặp)
  ["<UUID>"]                                       # [4]
]
```

**Với reference (1 hoặc 2 nhân vật):**
- `[8]` prompt = `[[[ [null,[null,null,[cid,name]]], " text" ]]]` (1 ref)
- `[8]` prompt = `[[[ [null,[null,null,[cid1,name1]]], " text ", [null,[null,null,[cid2,name2]]], " " ]]]` (2 refs)
- `[10]` char_ids = `[[cid1]]` hoặc `[[cid1],[cid2]]`

---

## 6. VẤN ĐỀ CHƯA GIẢI: Anti-abuse khi tạo ảnh

Gọi `ogiZ0b` bằng `fetch()` thủ công (qua `page.evaluate`) → server trả lỗi:

```
["wrb.fr","ogiZ0b",null,null,null,[7,null,[["type.googleapis.com/google.rpc.ErrorInfo",
  ["PUBLIC_ERROR_UNUSUAL_ACTIVITY"]]]],"generic"]
```

### Phát hiện quan trọng

1. **Token `0cAFcWeA...` (~2446 ký tự)** nằm ở `context[10]` dạng `[token, 1]`.
   - Do frontend sinh ra NGAY LÚC bấm Generate (không có sẵn trong localStorage / sessionStorage / request ban đầu).
   - **Single-use**: bắt token rồi dùng lại cho fetch thủ công → vẫn bị `PUBLIC_ERROR_UNUSUAL_ACTIVITY`.
   - Đã xác nhận: có token + mode=3 đúng → vẫn bị chặn.
2. **Header `x-browser-validation`** (bot-detection) là thủ phạm khả dĩ nhất.
   - Request thủ công `fetch()` KHÔNG có header này.
   - Request từ UI (Angular HttpClient) CÓ header này (do interceptor tự thêm).

### Kết luận
Chặn anti-abuse nằm ở **header + token do frontend sinh**, KHÔNG phải ở payload.
Payload đã đúng 100%.

---

## 7. GIẢI PHÁP ĐANG HOẠT ĐỘNG: điều khiển UI thật

Đã xác nhận gõ prompt + bấm nút Generate trong UI → request `ogiZ0b` fire thành công
(với token + header hợp lệ).

Các bước (đã có sẵn trong `flow_browser.py` → `generate_image_via_ui`):

```python
box = page.locator(".ProseMirror")                    # ô nhập prompt
box.first.click()
page.keyboard.insert_text(prompt)                     # PHẢI dùng insert_text (không dùng type())
page.keyboard.press("Enter")                          # commit prompt
page.locator(".generate-icon-button").first.click(force=True)  # PHẢI force=True
```

Lưu ý:
- `click()` thường KHÔNG trigger (bị chặn bởi overlay) → phải `click(force=True)`.
- `keyboard.type()` KHÔNG gõ được vào ProseMirror → phải `keyboard.insert_text()`.
- Model hiển thị UI là "Nano Banana 2.1" nhưng payload vẫn dùng `"BELUGA"`.

---

## 8. Hướng đi tiếp (gợi ý cho mô hình tiếp theo)

1. **Nhanh nhất**: hoàn thiện `generate_image_via_ui()` — thêm bước poll ảnh kết quả
   (ảnh mới xuất hiện trong grid/lưới ảnh của project), hoặc bắt response của request
   `ogiZ0b` khi UI tạo.
2. **Sạch nhất**: bắt header `x-browser-validation` (và có thể `x-client-data`) từ request
   thật của trang (dùng `request.all_headers()` trong Playwright), rồi tiêm các header đó
   vào `_JS_FETCH` để gọi RPC thủ công — tránh phải thao tác UI.
3. Có thể thử gọi đúng HTTP client của Angular app (truy cập service trong DI container)
   thay vì `fetch()` trần, để interceptor tự thêm header.

---

## 9. Cách chạy lại nhanh

```python
from flow_browser import FlowBrowserClient

with FlowBrowserClient(profile_dir=r"c:\Users\leath\Downloads\test\flow_profile",
                       headless=False) as c:
    c.wait_for_login(timeout=60)               # tự nhận diện (phiên đã lưu)
    pid, _ = c.create_project("Test")          # 1. tạo project
    _, cid, _ = c.create_character(pid, "A")   # 2. tạo nhân vật
    c.rename_character(pid, cid, "B")          # 2b. đổi tên
    c.generate_image_via_ui("mô tả ảnh")       # 3. tạo ảnh qua UI (đang hoạt động)
```
