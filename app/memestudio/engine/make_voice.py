"""Voice every beat of script.json with VideoStudio's VieNeu worker; writes assets/voice/*.wav + voice.json.

Narrator lines use narrator_voice, character lines the character's voice. Cached by text+voice.
Run from memestudio/:  python engine/make_voice.py episodes/<tập>
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

def fail(message):
    """Print a (Vietnamese) error to stdout as UTF-8 and stop; stderr on Windows mangles the accents."""
    sys.stdout.reconfigure(encoding='utf-8')
    print(message)
    raise SystemExit(1)


MS = Path(__file__).resolve().parents[1]          # memestudio/
ROOT = MS.parent                                   # videostudio repo (voices, speech worker)
_args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not _args:
    fail('Cách dùng: python engine\\make_voice.py episodes\\<tập>')
HERE = Path(_args[0]).resolve()                    # episode folder (script.json lives here)
OUT = HERE / 'assets' / 'voice'
STORYFORGE = Path('D:/Projects/storyforge')
SPEECH_PY = STORYFORGE / '.runtime/media/.venv/Scripts/python.exe'
CACHE = STORYFORGE / '.runtime/media/model-cache'


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main():
    script = json.loads((HERE / 'script.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from videostudio.voices import Voices
    export = ROOT.parent / 'data' / 'voices-export.json'
    voices = Voices(STORYFORGE, export if export.is_file() else None)
    # Old voice.json files can be upgraded from the existing text+voice stamps.
    # If a previous WAV checksum exists, also use it to detect damaged cache files.
    previous = {}
    try:
        rows = json.loads((HERE / 'voice.json').read_text(encoding='utf-8'))
        previous = {row['file']: row for row in rows if isinstance(row, dict) and 'file' in row}
    except (OSError, ValueError, TypeError):
        pass
    speed = float(script.get('speed', 1.0))
    result = []
    for n, beat in enumerate(script['beats']):
        who = beat['who']
        vid = script['narrator_voice'] if who == 'N' else script['cast'][who]['voice']
        voice = voices.selected(vid)
        wav = OUT / f'{n:02}_{who}.wav'
        payload = {'t': beat['text'], 'v': voice}
        if speed != 1.0:
            payload['s'] = speed
        ident = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        stamp = wav.with_suffix('.id')
        relative = f'assets/voice/{wav.name}'
        old_hash = previous.get(relative, {}).get('wav_sha256')
        cached = wav.is_file() and stamp.is_file() and stamp.read_text() == ident
        if cached and old_hash:
            cached = hashlib.sha256(wav.read_bytes()).hexdigest() == old_hash
        if not cached:
            if speed != 1.0:
                raw_wav = OUT / f'{n:02}_{who}.raw.wav'
                if wav.is_file() and stamp.is_file() and not raw_wav.is_file() and (not old_hash or hashlib.sha256(wav.read_bytes()).hexdigest() == old_hash):
                    shutil.copyfile(wav, raw_wav)
                if not raw_wav.is_file():
                    payload_json = json.dumps({'text': beat['text'], 'voice': voice, 'cache': str(CACHE), 'output': str(raw_wav)}, ensure_ascii=False)
                    subprocess.run([str(SPEECH_PY), '-m', 'videostudio.speech_worker', payload_json], cwd=ROOT, check=True, timeout=900,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw_wav), '-af', f'atempo={speed}', str(wav)], check=True)
            else:
                payload = json.dumps({'text': beat['text'], 'voice': voice, 'cache': str(CACHE), 'output': str(wav)}, ensure_ascii=False)
                subprocess.run([str(SPEECH_PY), '-m', 'videostudio.speech_worker', payload], cwd=ROOT, check=True, timeout=900,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stamp.write_text(ident)
        result.append({'n': n, 'who': who, 'voice': vid, 'file': relative, 'duration': round(duration(wav), 3),
                       'text': beat['text'], 'resolved_voice': voice, 'source_id': ident,
                       'wav_sha256': hashlib.sha256(wav.read_bytes()).hexdigest()})
        print(n, who, result[-1]['duration'], flush=True)
    (HERE / 'voice.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print('total speech', round(sum(r['duration'] for r in result), 2), 's')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
