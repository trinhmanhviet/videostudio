import subprocess, json, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

video_path = Path(r'E:\Videos\1-000-nam-tien-hoa-cua-ao-giap-chau-au-cuoc-chay-dua-giua-th-20261025-032619\video.mp4')
print('VIDEO EXISTS:', video_path.is_file())
print('SIZE BYTES:', video_path.stat().st_size)
print('SIZE MB:', f"{video_path.stat().st_size / (1024*1024):.2f} MB")

# Probe
r = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video_path)]))
f = r['format']
print('DURATION:', f['duration'], 'TARGET: 600.0s')
print('BITRATE:', f.get('bit_rate'))

for s in r['streams']:
    if s['codec_type'] == 'video':
        print(f"VIDEO STREAM: {s['codec_name']}, {s['width']}x{s['height']}, fps={s.get('r_frame_rate')}, pix_fmt={s.get('pix_fmt')}")
    elif s['codec_type'] == 'audio':
        print(f"AUDIO STREAM: {s['codec_name']}, {s['sample_rate']}Hz, channels={s['channels']}")

# Full decode check
print('RUNNING FULL DECODE CHECK...')
dec = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video_path), '-f', 'null', '-'], capture_output=True, text=True)
print('FULL DECODE RETURN CODE:', dec.returncode)
if dec.stderr:
    print('DECODE WARNINGS/ERRORS:', dec.stderr[:500])
else:
    print('DECODE CLEAN: No errors or corruptions!')
