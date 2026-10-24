# VideoStudio Auto-Pipeline Implementation Plan

> **Goal:** Tự động hóa hoàn toàn VideoStudio từ ý tưởng đến video hoàn chỉnh: kết nối ChatGPT qua CDP trực tiếp (Phương án A), tận dụng Web Search của ChatGPT để cào và kiểm chứng tư liệu (Lỗi 4), thực thi tuần tự trên GPU với cơ chế xả VRAM triệt để trước và sau mỗi công đoạn (Lỗi 2 & 3), cùng Watchdog tự phục hồi ComfyUI.

---

## 1. Kiến trúc tổng thể

Quy trình tuần tự khép kín không cần tương tác người dùng:

```
[Người dùng nhập 3 thông tin: Ý tưởng + Giọng đọc + Độ dài]
                           │
                           ▼
[1. Kịch bản & Nghiên cứu qua ChatGPT CDP]
    ├── Kết nối trực tiếp Chrome qua CDP (cổng 9222)
    ├── ChatGPT tự Search Web cào & kiểm chứng tư liệu
    └── Nhận JSON kịch bản phân cảnh hoàn chỉnh
                           │
                           ▼
[2. Sinh giọng đọc VieNeu trên GPU]
    ├── Kiểm tra VRAM -> Nạp VieNeu (CUDA)
    ├── Sinh audio -> Đo thời lượng thực tế
    └── Xả sạch VRAM (torch.cuda.empty_cache)
                           │
                           ▼
[3. Sinh ảnh phân cảnh Qwen Image 2.1 trên ComfyUI]
    ├── Kiểm tra VRAM >= 12GB trống -> Gọi POST /free dọn model cũ
    ├── ComfyUI render ảnh 9:16 (768x1376 / 1080x1920) cho từng cảnh
    └── Gọi POST /free xả model ảnh khỏi VRAM
                           │
                           ▼
[4. Sinh nhạc nền Stable Audio 3 trên ComfyUI]
    ├── Kiểm tra VRAM trống hoàn toàn (tránh crash torch_cpu.dll)
    ├── Watchdog tự restart ComfyUI nếu cổng 8188 bị sập
    ├── Render nhạc nền instrumental theo mood & độ dài
    └── Gọi POST /free xả model nhạc khỏi VRAM
                           │
                           ▼
[5. Dựng thành phẩm & Bàn giao]
    ├── Căn phụ đề ASS chuẩn safe-area
    ├── FFmpeg pan/zoom, auto-ducking nhạc nền dưới lời đọc
    ├── Xuất video MP4 vào E:\Videos\<slug>-yyyyMMdd-HHmmss\video.mp4
    └── Gửi thông báo / video hoàn chỉnh về Telegram cho bạn
```

---

## 2. Kế hoạch triển khai chi tiết từng nhiệm vụ

### Nhiệm vụ 1: Module kết nối ChatGPT qua Chrome CDP (`videostudio/cdp_chatgpt.py`)
- Kết nối tới Chrome remote debugging (mặc định `127.0.0.1:9222` hoặc tự đọc `DevToolsActivePort`).
- Tìm tab `chatgpt.com` hiện có hoặc mở tab mới.
- Đưa prompt kèm yêu cầu Web Search để ChatGPT tự cào và xác minh tư liệu lịch sử/khoa học.
- Lắng nghe trạng thái sinh văn bản qua CDP, bóc tách JSON và lưu vào checkpoint `plan` / `script`.

### Nhiệm vụ 2: Điều phối GPU tuần tự & Xả VRAM (`videostudio/gpu_manager.py`)
- Thay thế cơ chế thụ động cũ trong `gpu.py`.
- Hàm `ensure_vram_headroom(min_free_mb)`: Kiểm tra VRAM hiện tại; nếu chưa đủ, gọi ComfyUI `POST /free` với `{"unload_models": true, "free_memory": true}`.
- Hàm `release_vieneu_gpu()`: Xả bộ nhớ đệm PyTorch của VieNeu sau khi đọc xong.
- Hàm `release_comfy_gpu()`: Gọi API ComfyUI xả model ngay sau khi xong khâu ảnh và khâu nhạc.

### Nhiệm vụ 3: Watchdog tự động phục hồi ComfyUI (`videostudio/comfy_watchdog.py`)
- Kiểm tra tính sống còn của cổng 8188.
- Nếu ComfyUI bị crash (lỗi `torch_cpu.dll` hoặc ngắt tiến trình):
  - Tự động kích hoạt lại launcher `Start ComfyUI SageAttention.bat` ở chế độ ngầm.
  - Chờ cổng 8188 phản hồi HTTP 200 tại `/system_stats`.
  - Tiếp tục gửi lại prompt nhạc/ảnh theo ID đã lưu trong SQLite mà không hủy job.

### Nhiệm vụ 4: Căn phụ đề ASS & Dựng video hoàn chỉnh (`videostudio/media.py`)
- Tạo file phụ đề `.ass` với cỡ chữ chuẩn, màu vàng/trắng nổi bật, viền đen chống chìm, đặt trong vùng an toàn 9:16.
- Tạo chuyển động pan/zoom (Ken Burns effect) mượt mà cho từng cảnh ảnh.
- Ghép nhạc nền với bộ lọc `loudnorm` + `sidechaincompress` (ducking tự động giảm 80% âm lượng nhạc khi có tiếng nói).
- Xuất file MP4 H.264 / AAC đạt chuẩn phát trên điện thoại và mạng xã hội.

### Nhiệm vụ 5: Tích hợp đầu cuối và kiểm thử tự động
- Chạy thử 1 luồng tạo video hoàn chỉnh với ý tưởng ngắn.
- Xác nhận các mốc VRAM trước và sau mỗi bước.
- Kiểm tra file video đầu ra tại `E:\Videos\...`.
