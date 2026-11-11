"""Draw missing pose sheets automatically with ChatGPT in the dedicated Chrome, then import them.

For each costume: render the standing rig in that costume (poses/reference/<costume>_standing.png), send it with
the canonical sheet (poses/sheets/ao_ba_lo_trang.png) to ChatGPT through the VideoStudio CDP daemon
(/api/images/generate with attachments), save the reply as poses/sheets/<costume>.png and run the importer.
The canonical sheet fixes the layout, so the neck points of tools/import_rig_poses.py apply unchanged.

  python tools/make_pose_sheet.py ao_len_nau vest_den        draw these costumes
  python tools/make_pose_sheet.py --missing episodes/ep2     draw what episodes/ep2/script.json needs
  add --again to draw a costume again (a new request instead of the saved receipt)

Needs the VideoStudio CDP daemon (port 8879) with ChatGPT signed in in the dedicated Chrome. A request is
journaled by the daemon: running the same costume again resumes/reads the same reply instead of resending.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

MS = Path(__file__).resolve().parents[1]
POSES_DIR = MS / 'assets' / 'rig' / 'poses'
DAEMON = 'http://127.0.0.1:8879'
sys.path.insert(0, str(MS / 'tools'))
import import_rig_poses as importer  # noqa: E402
import import_rig_wardrobe as wardrobe_tool  # noqa: E402

PROMPT = ('The SECOND attached image is a sprite sheet of 10 headless cartoon body poses. Redraw that exact sheet: '
          'same 10 poses, same order, same 5 x 2 layout, same positions, same size and same drawing style, every body '
          'headless with the same short neck stub, plain pure white background, no text, no numbers, no shadows. The '
          'ONLY change: the body wears the clothes shown on the character in the FIRST attached image ({label}), '
          'drawn to fit each pose (folds, side view where the pose is seen from the side). Keep the black panda arms, '
          'white mitten hands and black stubby legs{legs}.')


def wardrobe():
    return {i['id']: i for i in json.loads((MS / 'assets/rig/wardrobe/wardrobe.json').read_text(encoding='utf-8'))['items']}


def reference(costume: str) -> Path:
    """The standing rig in this costume on white, with a plain face (the head is not redrawn)."""
    item = wardrobe()[costume]
    card = np.array(wardrobe_tool.character(item, [], 'noi', S=4.0))
    beige = (card[:, :, 0] == 236) & (card[:, :, 1] == 230) & (card[:, :, 2] == 214)
    card[beige] = [255, 255, 255, 255]
    path = POSES_DIR / 'reference' / f'{costume}_standing.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(card).convert('RGB').save(path)
    return path


def missing_for(episode: Path) -> list[str]:
    """Costumes whose characters take a drawn pose in the script but have no sheet yet."""
    script = json.loads((episode / 'script.json').read_text(encoding='utf-8'))
    have = {p.stem for p in (POSES_DIR / 'sheets').glob('*.png')}
    need = set()
    for beat in script.get('beats', []):
        for cid, spec in (beat.get('pose') or {}).items():
            kind = spec if isinstance(spec, str) else spec[0]
            costume = script['cast'].get(cid, {}).get('costume')
            if kind not in ('stand', 'bend') and costume and costume not in have:
                need.add(costume)
    return sorted(need)


def draw(costume: str, again: bool = False) -> Path:
    items = wardrobe()
    if costume not in items or items[costume]['kind'] != 'costume':
        raise SystemExit(f'Không có trang phục: {costume}')
    item = items[costume]
    ref = reference(costume)
    canonical = POSES_DIR / 'sheets' / f'{importer.CANONICAL}.png'
    label = costume.replace('_', ' ')
    legs = '; it is a long dress or skirt, so the dress covers the legs' if item.get('hides_legs') else ''
    # Same costume + same references -> same task id, so a crash or rerun reads the journaled reply.
    seed = f'pose-sheet:{costume}:{importer.CANONICAL}' + (f':{uuid.uuid4()}' if again else '')
    task = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
    print(f'{costume}: gửi ChatGPT vẽ bảng dáng (1-3 phút)...', flush=True)
    reply = httpx.post(f'{DAEMON}/api/images/generate', timeout=960, trust_env=False,
                       headers={'X-VS-Client': 'videostudio'},
                       json={'task_id': task, 'prompt': PROMPT.format(label=label, legs=legs),
                             'attachments': [str(ref), str(canonical)], 'layout': 'sheet', 'timeout': 600})
    data = reply.json()
    if not data.get('ok'):
        raise SystemExit(f'{costume}: ChatGPT chưa vẽ được ({data.get("code")}): {data.get("error")}')
    target = POSES_DIR / 'sheets' / f'{costume}.png'
    with Image.open(data['data']['file_path']) as image:
        image.convert('RGB').save(target)
    print(f'{costume}: đã lưu {target.relative_to(MS)}', flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('costumes', nargs='*')
    parser.add_argument('--missing', type=Path, help='episode folder: draw the costumes its script needs')
    parser.add_argument('--again', action='store_true')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    costumes = list(args.costumes) + (missing_for(args.missing.resolve()) if args.missing else [])
    if not costumes:
        print('Không thiếu bảng dáng nào.')
        return
    for costume in dict.fromkeys(costumes):
        draw(costume, args.again)
    importer.main()
    print('Xem lại ảnh ghép: ' + ', '.join(f'assets/rig/poses/preview_{c}.jpg' for c in dict.fromkeys(costumes)))


if __name__ == '__main__':
    main()
