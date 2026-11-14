"""Create a short listening sample for every voice that has none (Phòng thử giọng / Kể truyện "nghe mẫu").

Runs the existing offline engine (VieNeu on the GPU), one model load per voice, and writes
data/Voices/Generated-samples/<id-hash>.wav. Existing samples are never replaced unless --force is given.
Run in app/ while no video or voice job is active:  python scripts/make_voice_samples.py
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

from videostudio.paths import DATA_ROOT, RUNTIME_ROOT, VOICE_ROOT  # noqa: E402
from videostudio.speech_worker import SpeechJob  # noqa: E402
from videostudio.voices import Voices, generated_sample_path  # noqa: E402

TEXT = ('Xin chào, đây là giọng đọc mẫu của tôi. Chiều hôm ấy, gió thổi nhẹ qua con ngõ nhỏ, '
        'và câu chuyện của chúng ta bắt đầu từ chính nơi đó.')

parser = argparse.ArgumentParser()
parser.add_argument('--force', action='store_true', help='tạo lại cả mẫu đã có')
args = parser.parse_args()

export = DATA_ROOT / 'voices-export.json'
voices = Voices(VOICE_ROOT, str(export) if export.is_file() else None)
python = os.getenv('VS_SPEECH_PYTHON', str(RUNTIME_ROOT / 'media/.venv/Scripts/python.exe'))
cache = os.getenv('VS_SPEECH_CACHE', str(RUNTIME_ROOT / 'media/model-cache'))
ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
made = 0
for voice in voices.catalog()['voices']:
    if not voice.get('available'):
        continue
    target = generated_sample_path(VOICE_ROOT, voice['id'])
    if voice.get('sample_path') and Path(voice['sample_path']).is_file() and not args.force:
        continue
    if target.is_file() and not args.force:
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f'Đang tạo mẫu: {voice["name"]}…')
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / 'raw.wav'
        try:
            with SpeechJob(python, cache, voices.selected(voice['id']), lambda: None, 1) as job:
                job.write_line(TEXT, raw)
        except Exception as error:
            print(f'  bỏ qua {voice["name"]}: {error}')
            continue
        # Same loudness as finished videos, so voices can be compared fairly.
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(raw), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
                        '-ar', '24000', '-ac', '1', str(target)], check=True)
    made += 1
print(f'Xong: tạo {made} mẫu.')
