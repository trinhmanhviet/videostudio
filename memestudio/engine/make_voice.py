"""Voice every beat of script.json with VideoStudio's VieNeu worker; writes assets/voice/*.wav + voice.json.

Narrator lines use narrator_voice, character lines the character's voice. Cached by text+voice.
Run from memestudio/:  python engine/make_voice.py episodes/<tập>
"""
import hashlib
import json
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
    export = ROOT / 'data' / 'voices-export.json'
    voices = Voices(STORYFORGE, export if export.is_file() else None)
    result = []
    for n, beat in enumerate(script['beats']):
        who = beat['who']
        vid = script['narrator_voice'] if who == 'N' else script['cast'][who]['voice']
        voice = voices.selected(vid)
        wav = OUT / f'{n:02}_{who}.wav'
        ident = hashlib.sha256(json.dumps({'t': beat['text'], 'v': voice}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        stamp = wav.with_suffix('.id')
        if not (wav.is_file() and stamp.is_file() and stamp.read_text() == ident):
            payload = json.dumps({'text': beat['text'], 'voice': voice, 'cache': str(CACHE), 'output': str(wav)}, ensure_ascii=False)
            subprocess.run([str(SPEECH_PY), '-m', 'videostudio.speech_worker', payload], cwd=ROOT, check=True, timeout=900,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stamp.write_text(ident)
        result.append({'n': n, 'who': who, 'voice': vid, 'file': f'assets/voice/{wav.name}', 'duration': round(duration(wav), 3)})
        print(n, who, result[-1]['duration'], flush=True)
    (HERE / 'voice.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print('total speech', round(sum(r['duration'] for r in result), 2), 's')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
