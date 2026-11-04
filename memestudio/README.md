# memestudio

Bộ dựng video hoạt hình meme gấu trúc tiếng Việt: viết kịch bản `episodes\<tập>\script.json`, công cụ tự tạo giọng đọc,
tự dàn cảnh (chỗ đứng, khung hình, biểu cảm, nhép miệng, SFX) và render MP4 1080×1920 bằng HyperFrames.

Hướng dẫn đầy đủ (cả cho AI agent như Gemini): [`docs/huong-dan-video-hoat-hinh.md`](../docs/huong-dan-video-hoat-hinh.md).

Nhanh (PowerShell, trong thư mục này):

```powershell
npm install                                                     # lần đầu
python -I engine\make_episode.py episodes\ep1 --check
python -I engine\make_voice.py episodes\ep1
python -I engine\make_episode.py episodes\ep1
python -I engine\make_sfx.py episodes\ep1
$env:HYPERFRAMES_NO_TELEMETRY = '1'; $env:DO_NOT_TRACK = '1'
node node_modules\hyperframes\bin\hyperframes.mjs render episodes\ep1 --quiet --fps 30 -o out\ep1.mp4
```
