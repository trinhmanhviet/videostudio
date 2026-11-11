"""Mix sound effects into one track for the scene (assets/sfx.wav).

Events come from sfx.json (written by make_scene.py from the measured dialogue timings). Library: the CC0
procedural SFX in memestudio/assets/sfx (whoosh, click, impact, chime; copied from VideoStudio data/editor-sfx). Each event is delayed to its time and gained
per event; the mix is peak-limited so it never clips the voices. Run after make_scene.py:
  python engine/make_sfx.py episodes/<tập>
"""
from collections import defaultdict
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
    fail('Cách dùng: python engine\\make_sfx.py episodes\\<tập>')
HERE = Path(_args[0]).resolve()                    # episode folder (script.json lives here)
LIB = MS / 'assets' / 'sfx'
OUT = HERE / 'assets' / 'sfx.wav'
TRACK_GAIN = 1.4        # whole SFX track; peaks land ~7 dB under the loudest voice peaks


def main():
    plan = json.loads((HERE / 'sfx.json').read_text(encoding='utf-8'))
    duration = float(plan['duration'])
    events = plan['events']
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        # amix has no zero-input form; emit a real, correctly timed PCM track.
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'anullsrc=r=48000:cl=stereo', '-t', f'{duration:.3f}',
                        '-c:a', 'pcm_s16le', str(OUT)], check=True)
        print('sfx track:', OUT, 0, 'events,', round(duration, 2), 's')
        return
    manifest = json.loads((LIB / 'manifest.json').read_text(encoding='utf-8'))
    known = {a['id'].replace('sfx-', ''): a for a in manifest['assets']}

    # Deduplicate input files to keep command line short on Windows
    unique_assets = list(dict.fromkeys(ev['asset'] for ev in events))
    asset_indices = {name: idx for idx, name in enumerate(unique_assets)}
    asset_counts = defaultdict(int)
    for ev in events:
        if ev['asset'] not in known:
            raise SystemExit(f"unknown sfx: {ev['asset']}")
        asset_counts[ev['asset']] += 1

    cmd = ['ffmpeg', '-v', 'error', '-y']
    for name in unique_assets:
        cmd += ['-i', str((LIB / f"{name}.wav").resolve())]

    filter_lines = []
    # asplit each unique asset as many times as it is triggered
    split_names = {}
    for name, idx in asset_indices.items():
        cnt = asset_counts[name]
        labels = [f"u_{idx}_{k}" for k in range(cnt)]
        split_names[name] = labels
        filter_lines.append(f"[{idx}:a]asplit={cnt}{''.join(f'[{l}]' for l in labels)}")

    asset_used = defaultdict(int)
    event_labels = []
    for i, ev in enumerate(events):
        name = ev['asset']
        used = asset_used[name]
        src_label = split_names[name][used]
        asset_used[name] += 1
        ms = max(0, round(ev['t'] * 1000))
        filter_lines.append(
            f"[{src_label}]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={ev['gain'] * TRACK_GAIN:.3f},adelay={ms}|{ms}[e{i}]"
        )
        event_labels.append(f'[e{i}]')

    mix = ''.join(event_labels) + f'amix=inputs={len(event_labels)}:normalize=0:duration=longest,'
    mix += f'apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},alimiter=limit=0.89:level=false[a]'
    filter_lines.append(mix)

    filter_script = OUT.parent / 'sfx_filter.txt'
    filter_script.write_text(';\n'.join(filter_lines), encoding='utf-8')
    cmd += ['-filter_complex_script', str(filter_script.resolve()), '-map', '[a]', '-c:a', 'pcm_s16le', str(OUT)]
    try:
        subprocess.run(cmd, check=True)
    finally:
        try:
            filter_script.unlink(missing_ok=True)
        except OSError:
            pass
    print('sfx track:', OUT, len(events), 'events,', round(duration, 2), 's')


if __name__ == '__main__':
    main()
