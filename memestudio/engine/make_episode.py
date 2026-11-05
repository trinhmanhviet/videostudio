"""Auto-stage an episode from script.json + voice.json into a HyperFrames composition (index.html).

The script only says, per beat: scene, who speaks (N = narrator voice-over), focus, emotions, actions, punch
(a reaction cut after the line). Everything else is decided here by rules:
  * timing      - from the measured voice of each beat (+ gap, + reaction cut)
  * blocking    - cast order per scene -> evenly spaced marks; entering characters start off-stage
  * camera      - wide on a new scene, medium on the speaker/focus, close-up on strong emotion or action,
                  never the same shot twice in a row, slow push-in during every shot, shake on impacts
  * reactions   - after a "punch" line, a close-up of the listener with the given face
  * lip sync    - character lines only (narration is voice-over), from the loudness of the line
  * sound       - SFX from actions, scene changes and reactions -> sfx.json (mixed by make_sfx.py)
Layout follows the reference format: title band on top, a landscape story window, payoff band below,
captions inside the window.
Run from memestudio/:  python engine/make_voice.py episodes/<tập>  ;  python engine/make_episode.py episodes/<tập>
                       python engine/make_sfx.py episodes/<tập>    ;  node node_modules/hyperframes/bin/hyperframes.mjs render episodes/<tập> ...
Check a script only:   python engine/make_episode.py episodes/<tập> --check
"""
import hashlib
import json
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

def fail(message):
    """Print a (Vietnamese) error to stdout as UTF-8 and stop; stderr on Windows mangles the accents."""
    sys.stdout.reconfigure(encoding='utf-8')
    print(message)
    raise SystemExit(1)


MS = Path(__file__).resolve().parents[1]          # memestudio/
ROOT = MS.parent                                   # videostudio repo (voices, speech worker)
_args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not _args:
    fail('Cách dùng: python engine\\make_episode.py episodes\\<tập> [--check]')
HERE = Path(_args[0]).resolve()                    # episode folder (script.json lives here)
PACK = MS / 'assets'
WARD = PACK / 'rig' / 'wardrobe'
PARTS = PACK / 'rig' / 'parts'
BACKGROUNDS = PACK / 'backgrounds'
A = HERE / 'assets'
A.mkdir(parents=True, exist_ok=True)

FACES = json.loads((PACK / 'rig' / 'faces' / 'faces.json').read_text(encoding='utf-8'))
CATALOG = {i['id']: i for i in json.loads((WARD / 'wardrobe.json').read_text(encoding='utf-8'))['items']}
ACTIONS = {'walk_in': 1, 'gesture': 1, 'angry': 1, 'shock': 1, 'tremble': 1, 'press': 1, 'look_up': 1,
           'point': 2, 'lean': 2, 'ding': 0}      # name -> number of character ids it takes (ding takes a count)


def validate(script):
    """Every id must exist; returns a list of problems (empty = OK)."""
    bad = []
    faces = set(FACES['faces'])
    for k in ('title', 'payoff'):
        if not (isinstance(script.get(k), list) and len(script[k]) == 2):
            bad.append(f'{k}: cần đúng 2 dòng')
    for cid, c in script.get('cast', {}).items():
        item = CATALOG.get(c.get('costume'))
        if not item or item['kind'] != 'costume':
            bad.append(f'cast.{cid}.costume không có: {c.get("costume")}')
        for a in c.get('acc', []):
            if a not in CATALOG or CATALOG[a]['kind'] == 'costume':
                bad.append(f'cast.{cid}.acc không có: {a}')
        if c.get('face') not in faces:
            bad.append(f'cast.{cid}.face không có: {c.get("face")}')
        if not c.get('voice'):
            bad.append(f'cast.{cid}.voice trống')
    for sid, s in script.get('scenes', {}).items():
        if not (BACKGROUNDS / f"{s.get('bg')}.png").is_file():
            bad.append(f'scenes.{sid}.bg không có file: {s.get("bg")}')
        if not 1 <= len(s.get('cast', [])) <= 3:
            bad.append(f'scenes.{sid}.cast phải có 1-3 vai')
        for cid in s.get('cast', []):
            if cid not in script.get('cast', {}):
                bad.append(f'scenes.{sid}.cast có vai lạ: {cid}')
    for i, b in enumerate(script.get('beats', [])):
        where = f'beats[{i}]'
        scene = script.get('scenes', {}).get(b.get('scene'))
        if not scene:
            bad.append(f'{where}.scene không có: {b.get("scene")}')
            continue
        here = scene['cast']
        if b.get('who') != 'N' and b.get('who') not in here:
            bad.append(f'{where}.who phải là "N" hoặc vai có trong cảnh: {b.get("who")}')
        if b.get('who') == 'N' and b.get('focus') not in here:
            bad.append(f'{where}.focus phải là vai có trong cảnh: {b.get("focus")}')
        if not str(b.get('text', '')).strip():
            bad.append(f'{where}.text trống')
        for cid, f in b.get('emo', {}).items():
            if cid not in here or f not in faces:
                bad.append(f'{where}.emo sai: {cid}={f}')
        for a in b.get('act', []):
            if not a or a[0] not in ACTIONS:
                bad.append(f'{where}.act không hỗ trợ: {a}')
            elif a[0] == 'ding':
                if len(a) != 2 or not isinstance(a[1], int) or not 1 <= a[1] <= 6:
                    bad.append(f'{where}.act ding cần số lần 1-6: {a}')
            elif len(a) != 1 + ACTIONS[a[0]] or any(x not in here for x in a[1:]):
                bad.append(f'{where}.act {a[0]} cần {ACTIONS[a[0]]} vai có trong cảnh: {a}')
        p = b.get('punch')
        if p and (p.get('who') not in here or p.get('face') not in faces):
            bad.append(f'{where}.punch sai: {p}')
    return bad


if '--check' in sys.argv:
    target = HERE / 'script.json'
    problems = validate(json.loads(target.read_text(encoding='utf-8')))
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(problems) if problems else f'OK: {target.name} hợp lệ')
    raise SystemExit(1 if problems else 0)

SCRIPT = json.loads((HERE / 'script.json').read_text(encoding='utf-8'))
_problems = validate(SCRIPT)
if _problems:
    fail('script.json lỗi:\n' + '\n'.join(_problems))

def voices_match(script, rows):
    """Verify the requested source and measured WAV without loading the speech runtime."""
    if not isinstance(rows, list) or len(rows) != len(script['beats']):
        return False
    try:
        speed = float(script.get('speed', 1.0))
        for n, (row, beat) in enumerate(zip(rows, script['beats'])):
            who = beat['who']
            vid = script['narrator_voice'] if who == 'N' else script['cast'][who]['voice']
            if (row['n'] != n or row['who'] != who or row['text'] != beat['text']
                    or row['voice'] != vid or row['resolved_voice']['id'] != vid
                    or row['file'] != f'assets/voice/{n:02}_{who}.wav'):
                return False
            payload = {'t': beat['text'], 'v': row['resolved_voice']}
            if speed != 1.0:
                payload['s'] = speed
            ident = hashlib.sha256(json.dumps(payload,
                                               sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            wav = HERE / row['file']
            if (row['source_id'] != ident or wav.with_suffix('.id').read_text() != ident
                    or hashlib.sha256(wav.read_bytes()).hexdigest() != row['wav_sha256']):
                return False
    except (KeyError, TypeError, OSError):
        return False
    return True


try:
    VOICE = json.loads((HERE / 'voice.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    fail('voice.json thiếu hoặc lỗi: chạy lại engine/make_voice.py')
if not voices_match(SCRIPT, VOICE):
    fail('voice.json không khớp script.json: chạy lại engine/make_voice.py')
HEAD_SCALE, HEAD_CHIN, HEADS = 0.6372, FACES['head']['chin'], list(FACES['faces'])
NECK, SHOULDER_L, SHOULDER_R = (3, -52), (-29, -52), (31, -52)

# ---- layout (1080x1920): title band, story window, payoff band
WIN_X, WIN_Y, WIN_W, WIN_H = 0, 500, 1080, 700
WORLD_W, WORLD_H = 1600, 1037               # stage coordinates; wide shot shows all of it
K0 = WIN_W / WORLD_W
S = 2.6                                     # rig units -> stage px
HIP_Y = 760                                 # hip line on stage
MARKS = {1: [800], 2: [560, 1040], 3: [430, 800, 1170]}
SHOTS = {'wide': (None, 1.0), 'medium': (-150, 1.9), 'close': (-250, 3.0)}   # (aim above hip, zoom)
START = float(SCRIPT.get('start', 0.15 if SCRIPT.get('speed', 1.0) != 1.0 else 0.3))
GAP = float(SCRIPT.get('gap', 0.12 if SCRIPT.get('speed', 1.0) != 1.0 else 0.3))
REACT = float(SCRIPT.get('react', 0.45 if SCRIPT.get('speed', 1.0) != 1.0 else 0.8))
TAIL = float(SCRIPT.get('tail', 0.6 if SCRIPT.get('speed', 1.0) != 1.0 else 1.0))
FPS = 30


def copy(src, name):
    shutil.copyfile(src, A / name)
    return f'assets/{name}'


# ------------------------------------------------------------------ timing
BEATS, cursor = [], START
for i, (beat, v) in enumerate(zip(SCRIPT['beats'], VOICE)):
    b = {**beat, 'i': i, 'file': v['file'], 'dur': v['duration'], 'start': cursor, 'end': cursor + v['duration']}
    cursor = b['end'] + GAP
    if beat.get('punch'):
        b['react'] = (b['end'] + 0.05, b['end'] + 0.05 + REACT)
        cursor = b['react'][1] + 0.1
    BEATS.append(b)
D = round(cursor + TAIL, 2)
SCENE_ORDER, _seen = [], {}
for b in BEATS:
    if not SCENE_ORDER or SCENE_ORDER[-1]['scene'] != b['scene']:
        _seen[b['scene']] = _seen.get(b['scene'], 0) + 1
        sid = b['scene'] if _seen[b['scene']] == 1 else f"{b['scene']}_{_seen[b['scene']]}"
        SCENE_ORDER.append({'id': sid, 'scene': b['scene'], 'start': 0.0 if not SCENE_ORDER else b['start'] - 0.15, 'beats': []})
    SCENE_ORDER[-1]['beats'].append(b)
for n, sc in enumerate(SCENE_ORDER):
    sc['end'] = SCENE_ORDER[n + 1]['start'] if n + 1 < len(SCENE_ORDER) else D

# ------------------------------------------------------------------ blocking
for sc in SCENE_ORDER:
    cast = SCRIPT['scenes'][sc['scene']]['cast']
    sc['x'] = dict(zip(cast, MARKS[len(cast)]))
    sc['enters'] = {a[1]: b['start'] for b in sc['beats'] for a in b.get('act', []) if a[0] == 'walk_in'}


def inst(sc, cid):
    return f"{sc['id']}_{cid}"


# ------------------------------------------------------------------ character DOM
def head_box(p, size):
    k = p['scale']
    w, h = size
    ax, ay = p['anchor'][0] * k, p['anchor'][1] * k
    left, top = p['at'][0] - HEAD_CHIN[0] - ax, p['at'][1] - HEAD_CHIN[1] - ay
    rot = p.get('rotation', 0)
    turn = f'; transform:rotate({rot}deg); transform-origin:{ax:.2f}px {ay:.2f}px' if rot else ''
    return f'left:{left:.2f}px; top:{top:.2f}px; width:{w * k:.2f}px; height:{h * k:.2f}px{turn}'


def placed(item):
    k = item['scale']
    w, h = item['size']
    return (f"left:{item['place'][0] - item['anchor'][0] * k:.2f}px; top:{item['place'][1] - item['anchor'][1] * k:.2f}px; "
            f"width:{w * k:.2f}px; height:{h * k:.2f}px")


def character(sc, cid):
    I = inst(sc, cid)
    card = SCRIPT['cast'][cid]
    costume = CATALOG[card['costume']]
    dress = costume['hides_legs']
    p = {n: copy(PARTS / f'component_{n:03}.png', f'p{n:03}.png') for n in (17, 22, 25, 40, 41, 55)}
    chin = f'left:{-HEAD_CHIN[0]}px; top:{-HEAD_CHIN[1]}px'
    heads = [f'<img src="{copy(PACK / "rig" / "faces" / "head_base.png", "head_base.png")}" alt="" style="{chin}" />']
    face_items = [CATALOG[a] for a in card.get('acc', []) if CATALOG[a]['kind'] == 'face']
    for name in HEADS:
        fd = FACES['faces'][name]
        src = copy(PACK / 'rig' / 'faces' / fd['file_nomouth'], f'face_{name}_nomouth.png')
        msrc = copy(PACK / 'rig' / 'faces' / fd['mouth_file'], f'mouth_{name}.png')
        px, py = fd['mouth_pivot']
        inner = [f'<img src="{src}" alt="" style="{chin}" />',
                 f'<div id="{I}_m_{name}" class="joint" style="left:{px - HEAD_CHIN[0]:.2f}px; top:{py - HEAD_CHIN[1]:.2f}px">'
                 f'<img src="{msrc}" alt="" style="left:{-px:.2f}px; top:{-py:.2f}px" /></div>']
        for item in face_items:
            inner.append(f'<img src="{copy(WARD / item["file"], "w_" + item["id"] + ".png")}" alt="" '
                         f'style="{head_box(item["per_face"][name], item["size"])}" />')
        heads.append(f'<div id="{I}_h_{name}" class="joint" style="opacity:{1 if name == card["face"] else 0}">'
                     + ''.join(inner) + '</div>')
    for a in card.get('acc', []):
        item = CATALOG[a]
        if item['kind'] != 'face':
            heads.append(f'<img src="{copy(WARD / item["file"], "w_" + a + ".png")}" alt="" style="{head_box(item, item["size"])}" />')
    legs = '' if dress else (
        f'<div id="{I}_legs" class="joint"><div class="limb legsize">'
        f'<img id="{I}_leg0" src="{p[40]}" alt="" style="left:-66.5px; top:-40px" />'
        f'<img id="{I}_leg1" src="{p[41]}" alt="" style="left:-66px; top:-40px; opacity:0" />'
        f'<div class="flip"><img id="{I}_leg2" src="{p[41]}" alt="" style="left:-66px; top:-40px; opacity:0" /></div>'
        f'</div></div>')
    return f'''
          <div id="{I}" class="joint" style="left:{sc['x'][cid]}px; top:{HIP_Y}px"><div class="joint unit">
            <img src="{p[55]}" alt="" style="position:absolute; left:-60px; top:{30 if dress else 36}px; width:120px; height:31px; opacity:.35" />{legs}
            <div id="{I}_body" class="joint">
              <div id="{I}_armL" class="joint" style="left:{SHOULDER_L[0]}px; top:{SHOULDER_L[1]}px"><div class="limb armsize">
                <div class="flip"><img id="{I}_armL_hang" src="{p[17]}" alt="" style="left:-19px; top:-10px" /></div>
                <img id="{I}_armL_point" src="{p[22]}" alt="" style="left:-114px; top:-9px; opacity:0" /></div></div>
              <div id="{I}_armR" class="joint" style="left:{SHOULDER_R[0]}px; top:{SHOULDER_R[1]}px"><div class="limb armsize">
                <img id="{I}_armR_hang" src="{p[17]}" alt="" style="left:-19px; top:-10px" />
                <div class="flip"><img id="{I}_armR_palm" src="{p[25]}" alt="" style="left:-103px; top:-8px; opacity:0" />
                <img id="{I}_armR_point" src="{p[22]}" alt="" style="left:-114px; top:-9px; opacity:0" /></div></div></div>
              <img src="{copy(WARD / costume['file'], 'w_' + card['costume'] + '.png')}" alt="" style="{placed(costume)}" />
              <div id="{I}_neck" class="joint" style="left:{NECK[0]}px; top:{NECK[1]}px"><div class="limb headsize">
                {''.join(heads)}
              </div></div>
            </div>
          </div></div>'''


# ------------------------------------------------------------------ actions -> seek-safe GSAP
js, sfx = [], []
L = '...later'


def t_(v):
    return f'{v:.3f}'


def face(I, name, t):
    js.append(f'tl.set({json.dumps(["#" + I + "_h_" + h for h in HEADS])}, {{ opacity: 0 }}, {t_(t)}); '
              f'tl.set("#{I}_h_{name}", {{ opacity: 1 }}, {t_(t)});')


def arm(I, side, variant, t):
    ids = ['hang', 'point'] if side == 'L' else ['hang', 'palm', 'point']
    js.append(f'tl.set({json.dumps(["#" + I + "_arm" + side + "_" + v for v in ids])}, {{ opacity: 0 }}, {t_(t)}); '
              f'tl.set("#{I}_arm{side}_{variant}", {{ opacity: 1 }}, {t_(t)});')


def yoyo(sel, prop, a, b, period, t0, t1, ease='sine.inOut'):
    n = max(1, int((t1 - t0) / period) // 2 * 2 - 1)
    js.append(f'tl.fromTo("{sel}", {{ {prop}: {a} }}, {{ {prop}: {b}, duration: {period}, ease: "{ease}", yoyo: true, repeat: {n}, {L} }}, {t_(t0)});')


def talk(I, t0, t1):
    yoyo(f'#{I}_neck', 'rotation', 0, 4, 0.18, t0, t1)
    yoyo(f'#{I}_body', 'y', 0, -2.5, 0.18, t0, t1)


def gesture(I, t0, t1):
    arm(I, 'R', 'palm', t0)
    yoyo(f'#{I}_armR', 'rotation', -20, 12, 0.4, t0, t1)
    arm(I, 'R', 'hang', t1)
    js.append(f'tl.set("#{I}_armR", {{ rotation: 0 }}, {t_(t1)});')


def point(I, t0, t1, right):
    side, lean = ('R', 5) if right else ('L', -5)
    arm(I, side, 'point', t0)
    js.append(f'tl.fromTo("#{I}_arm{side}", {{ rotation: {-45 if right else 45} }}, {{ rotation: 0, duration: 0.3, ease: "back.out(2.5)", {L} }}, {t_(t0)});')
    js.append(f'tl.fromTo("#{I}_body", {{ rotation: 0 }}, {{ rotation: {lean}, duration: 0.3, ease: "power2.out", {L} }}, {t_(t0)});')
    js.append(f'tl.to("#{I}_body", {{ rotation: 0, duration: 0.2 }}, {t_(t1 - 0.2)});')
    arm(I, side, 'hang', t1)
    js.append(f'tl.set("#{I}_arm{side}", {{ rotation: 0 }}, {t_(t1)});')
    sfx.append(('whoosh', t0, 0.8))


def walk(I, t0, t1, x0):
    js.append(f'tl.fromTo("#{I}", {{ x: {x0} }}, {{ x: 0, duration: {t_(t1 - t0)}, ease: "power1.out", {L} }}, {t_(t0)});')
    legs = json.dumps([f'#{I}_leg0', f'#{I}_leg1', f'#{I}_leg2'])
    steps = int((t1 - t0) / 0.1)
    for k in range(steps):
        js.append(f'tl.set({legs}, {{ opacity: 0 }}, {t_(t0 + k * 0.1)}); tl.set("#{I}_{("leg0", "leg1", "leg0", "leg2")[k % 4]}", {{ opacity: 1 }}, {t_(t0 + k * 0.1)});')
    js.append(f'tl.set({legs}, {{ opacity: 0 }}, {t_(t1)}); tl.set("#{I}_leg0", {{ opacity: 1 }}, {t_(t1)});')
    yoyo(f'#{I}_body', 'y', 0, -5, 0.1, t0, t1, 'sine.out')
    js.append(f'tl.set(["#{I}_armL", "#{I}_armR"], {{ rotation: 0 }}, {t_(t1)});')
    sfx.append(('whoosh', t0, 0.9))


def shock(I, t, hold):
    face(I, 'soc', t)
    js.append(f'tl.fromTo("#{I}_neck", {{ y: 0, scale: 1 }}, {{ y: -8, scale: 1.12, duration: 0.25, ease: "back.out(3)", {L} }}, {t_(t)});')
    js.append(f'tl.fromTo("#{I}_armL", {{ rotation: 0 }}, {{ rotation: 35, duration: 0.2, ease: "back.out(3)", {L} }}, {t_(t)});')
    js.append(f'tl.fromTo("#{I}_armR", {{ rotation: 0 }}, {{ rotation: -35, duration: 0.2, ease: "back.out(3)", {L} }}, {t_(t)});')
    js.append(f'tl.to("#{I}_neck", {{ y: 0, scale: 1, duration: 0.2 }}, {t_(t + hold)});')
    js.append(f'tl.to(["#{I}_armL", "#{I}_armR"], {{ rotation: 0, duration: 0.2 }}, {t_(t + hold)});')
    sfx.append(('impact', t, 1.0))


def angry(I, t, dur=0.6):
    yoyo(f'#{I}_neck', 'rotation', -9, 9, 0.08, t, t + dur, 'none')
    js.append(f'tl.set("#{I}_neck", {{ rotation: 0 }}, {t_(t + dur)});')
    sfx.append(('impact', t, 0.6))


def tremble(I, t0, t1):
    yoyo(f'#{I}_body', 'x', -3, 3, 0.05, t0, t1, 'none')
    js.append(f'tl.set("#{I}_body", {{ x: 0 }}, {t_(t1)});')
    sfx.append(('impact', t0, 0.8))


def lean(I, t0, t1, right):
    js.append(f'tl.fromTo("#{I}_body", {{ rotation: 0, x: 0 }}, {{ rotation: {8 if right else -8}, x: {25 if right else -25}, duration: 0.25, ease: "power2.out", {L} }}, {t_(t0)});')
    js.append(f'tl.to("#{I}_body", {{ rotation: 0, x: 0, duration: 0.25 }}, {t_(t1)});')


def press(I, t0, t1, right):
    side = 'R' if right else 'L'
    arm(I, side, 'point', t0)
    yoyo(f'#{I}_arm{side}', 'rotation', 0, -12 if right else 12, 0.11, t0, t1, 'power1.inOut')
    arm(I, side, 'hang', t1)
    js.append(f'tl.set("#{I}_arm{side}", {{ rotation: 0 }}, {t_(t1)});')
    k = t0
    while k < t1 - 0.1:
        sfx.append(('click', k, 1.8))
        k += 0.22


def look_up(I, t0, t1):
    js.append(f'tl.fromTo("#{I}_neck", {{ rotation: 0, y: 0 }}, {{ rotation: -7, y: -4, duration: 0.4, ease: "power2.out", {L} }}, {t_(t0)});')
    js.append(f'tl.to("#{I}_neck", {{ rotation: 0, y: 0, duration: 0.3 }}, {t_(t1)});')


def cry(I, t0, t1):
    js.append(f'tl.fromTo("#{I}_neck", {{ rotation: 0, y: 0 }}, {{ rotation: -10, y: 3, duration: 0.5, ease: "power2.out", {L} }}, {t_(t0)});')
    js.append(f'tl.to("#{I}_neck", {{ rotation: 0, y: 0, duration: 0.2 }}, {t_(t1)});')


def mouth_track(path):
    with wave.open(str(path)) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    hop = rate // FPS
    rms = np.array([np.sqrt(np.mean(data[i:i + hop] ** 2)) + 1e-9 for i in range(0, len(data) - hop + 1, hop)])
    db = np.convolve(20 * np.log10(rms / 32768), np.ones(2) / 2, mode='same')
    level = np.clip((db - (np.percentile(db, 95) - 24)) / 24, 0, 1)
    out, last, held = [], None, 0
    for v in level:
        s = 0.35 if v < 0.3 else 0.65 if v < 0.7 else 1.0
        if last is not None and s != last and held < 2:
            s = last
        held = held + 1 if s == last else 1
        out.append(s)
        last = s
    out[-1] = 0.35
    return out


def lipsync(I, path, t0):
    mouths = json.dumps([f'#{I}_m_{h}' for h in HEADS])
    prev = None
    track = mouth_track(HERE / path)
    for k, s in enumerate(track):
        if s != prev:
            js.append(f'tl.set({mouths}, {{ scaleY: {s} }}, {t_(t0 + k / FPS)});')
            prev = s
    js.append(f'tl.set({mouths}, {{ scaleY: 1 }}, {t_(t0 + len(track) / FPS + 0.05)});')


# ------------------------------------------------------------------ camera
CAM = []        # (scene, t, shot, subject)


def cam_values(sc, shot, subj, push=1.0):
    aim, zoom = SHOTS[shot]
    zoom *= push
    if shot == 'wide':
        cx, cy = WORLD_W / 2, WORLD_H / 2
    else:
        cx, cy = sc['x'][subj], HIP_Y + aim
    vw, vh = WORLD_W / zoom, WORLD_H / zoom
    cx = min(max(cx, vw / 2), WORLD_W - vw / 2)
    cy = min(max(cy, vh / 2), WORLD_H - vh / 2)
    k = K0 * zoom
    return round(WIN_W / 2 - cx * k, 2), round(WIN_H / 2 - cy * k, 2), round(k, 5)


def shot(sc, t0, t1, kind, subj):
    x0, y0, k0 = cam_values(sc, kind, subj)
    x1, y1, k1 = cam_values(sc, kind, subj, 1.05)
    js.append(f'tl.fromTo("#{sc["id"]}_world", {{ x: {x0}, y: {y0}, scale: {k0} }}, '
              f'{{ x: {x1}, y: {y1}, scale: {k1}, duration: {t_(max(0.2, t1 - t0))}, ease: "none", {L} }}, {t_(t0)});')
    CAM.append((sc['id'], round(t0, 2), kind, subj))


def shake(sc, t, amp=14):
    js.append(f'tl.fromTo("#{sc["id"]}_shake", {{ x: 0, y: 0 }}, {{ keyframes: [{{ x: {-amp}, y: 5 }}, {{ x: {amp}, y: -6 }}, '
              f'{{ x: {-amp // 2}, y: 3 }}, {{ x: {amp // 3}, y: -2 }}, {{ x: 0, y: 0 }}], duration: 0.45, ease: "none", {L} }}, {t_(t)});')


STRONG = {'soc', 'gian', 'khoc'}
BIG_ACTS = {'shock', 'tremble', 'angry', 'press'}

# ------------------------------------------------------------------ direct every scene
for n, sc in enumerate(SCENE_ORDER):
    cast = SCRIPT['scenes'][sc['scene']]['cast']
    js.append(f'tl.set("#{sc["id"]}_shake", {{ x: 0, y: 0 }}, 0);')
    for cid in cast:
        I = inst(sc, cid)
        off = (900 if sc['x'][cid] > WORLD_W / 2 else -900) if cid in sc['enters'] else 0
        js.append(f'tl.set("#{I}", {{ x: {off} }}, 0); tl.set("#{I}_body", {{ rotation: 0, x: 0, y: 0, scaleY: 1 }}, 0); '
                  f'tl.set(["#{I}_armL", "#{I}_armR"], {{ rotation: 0 }}, 0); tl.set("#{I}_neck", {{ rotation: 0, y: 0, scale: 1 }}, 0);')
        js.append(f'tl.set({json.dumps(["#" + I + "_m_" + h for h in HEADS])}, {{ scaleY: 1 }}, 0);')
        period = 0.7 + 0.1 * cast.index(cid)
        yoyo(f'#{I}_body', 'scaleY', 1, 1.02, period, sc['start'], sc['end'])
    if n:
        sfx.append(('whoosh', sc['start'], 0.5))
    prev = None
    for j, b in enumerate(sc['beats']):
        t0, t1 = b['start'], b['end']
        speaker = None if b['who'] == 'N' else b['who']
        subj = speaker or b.get('focus') or cast[0]
        for cid, f in b.get('emo', {}).items():
            face(inst(sc, cid), f, t0)
        acts = b.get('act', [])
        for a in acts:
            I = inst(sc, a[1]) if len(a) > 1 and isinstance(a[1], str) else None
            if a[0] == 'walk_in':
                walk(I, t0, t0 + 1.0, 900 if sc['x'][a[1]] > WORLD_W / 2 else -900)
            elif a[0] == 'gesture':
                gesture(I, t0, t1 + 0.1)
            elif a[0] == 'point':
                point(I, t0, t1 + 0.2, sc['x'][a[2]] > sc['x'][a[1]])
            elif a[0] == 'angry':
                angry(I, t0)
            elif a[0] == 'shock':
                shock(I, t0, max(0.4, t1 - t0 - 0.1))
            elif a[0] == 'tremble':
                tremble(I, t0, t1)
            elif a[0] == 'lean':
                lean(I, t0, t1, sc['x'][a[2]] > sc['x'][a[1]])
            elif a[0] == 'press':
                others = [c for c in cast if c != a[1]]
                press(I, t0, t1, not others or sc['x'][a[1]] < WORLD_W / 2)
            elif a[0] == 'look_up':
                look_up(I, t0, t1)
            elif a[0] == 'ding':
                for k in range(a[1]):
                    sfx.append(('chime', t0 + 0.15 + k * (t1 - t0) / a[1], 1.0))
        if b.get('emo', {}).get(subj) == 'khoc':
            cry(inst(sc, subj), t0, t1)
        if speaker:
            if not any(a[0] in ('tremble', 'angry') and a[1] == speaker for a in acts):
                talk(inst(sc, speaker), t0, t1)
            lipsync(inst(sc, speaker), b['file'], t0)
            sfx.append(('click', t0, 0.9))
        # camera: rules, never the same shot twice in a row
        strong = b.get('emo', {}).get(subj) in STRONG or any(a[0] in BIG_ACTS for a in acts)
        kind = 'wide' if j == 0 else 'close' if strong else 'medium'
        if (kind, subj) == prev:
            kind = 'close' if kind == 'medium' else 'medium'
        walking = [a for a in acts if a[0] == 'walk_in']
        if walking and kind != 'wide':
            kind, subj = 'wide', subj
        end = b['react'][0] if b.get('react') else (sc['beats'][j + 1]['start'] if j + 1 < len(sc['beats']) else sc['end'])
        shot(sc, t0 if j else sc['start'], end, kind, subj)
        prev = (kind, subj)
        if any(a[0] in ('shock', 'tremble') for a in acts):
            shake(sc, t0 + 0.05)
        if b.get('react'):
            r0, r1 = b['react']
            who = b['punch']['who']
            face(inst(sc, who), b['punch']['face'], r0)
            rend = sc['beats'][j + 1]['start'] if j + 1 < len(sc['beats']) else sc['end']
            shot(sc, r0, rend, 'close', who)
            prev = ('close', who)
            sfx.append(('whoosh', r0, 0.6))
            if b['punch']['face'] == 'khoc':
                cry(inst(sc, who), r0, r1)

# ------------------------------------------------------------------ page
sets = []
for sc in SCENE_ORDER:
    spec = SCRIPT['scenes'][sc['scene']]
    bg = copy(BACKGROUNDS / f"{spec['bg']}.png", f"{spec['bg']}.png")
    chars = ''.join(character(sc, cid) for cid in spec['cast'])
    sets.append(f'''
      <div id="{sc['id']}_set" class="set clip" data-start="{sc['start']:.3f}" data-duration="{sc['end'] - sc['start']:.3f}">
        <div id="{sc['id']}_shake" class="joint"><div id="{sc['id']}_world" class="world">
          <img class="bg" src="{bg}" alt="" />{chars}
        </div></div>
      </div>''')
caps, audio = [], []
for b in BEATS:
    end = (b['react'][1] if b.get('react') else b['end'] + GAP)
    caps.append(f'<div id="cap{b["i"]}" class="cap clip" data-start="{b["start"]:.3f}" data-duration="{end - b["start"]:.3f}">'
                f'<span>{b.get("caption", b["text"])}</span></div>')
    audio.append(f'<audio id="v{b["i"]}" src="{b["file"]}" data-start="{b["start"]:.3f}" data-duration="{b["dur"]:.3f}" data-volume="1"></audio>')
audio.append(f'<audio id="sfx" src="assets/sfx.wav" data-start="0" data-duration="{D}" data-volume="1"></audio>')
shutil.copyfile(MS / 'node_modules' / 'gsap' / 'dist' / 'gsap.min.js', A / 'gsap.min.js')   # gsap 3.13.0, local
shutil.copyfile(Path('C:/Windows/Fonts/arialbd.ttf'), A / 'arialbd.ttf')                              # Vietnamese glyphs
t1, t2 = SCRIPT['title']
p1, p2 = SCRIPT['payoff']
html = f'''<!doctype html>
<html lang="vi" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="assets/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "Bold"; src: url("assets/arialbd.ttf"); font-weight: 700; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: #f3ead6; }}
      #root {{ position: relative; width: 1080px; height: 1920px; overflow: hidden; font-family: "Bold", Arial, sans-serif; background: #f3ead6; }}
      .deco {{ position: absolute; }}
      .band {{ position: absolute; left: 0; width: 1080px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; z-index: 5; }}
      .band b {{ display: block; font-size: 92px; line-height: 1.12; color: #2b1a0e; letter-spacing: 1px;
                 text-shadow: -4px -4px 0 #fff, 4px -4px 0 #fff, -4px 4px 0 #fff, 4px 4px 0 #fff, 0 7px 0 #e9b44c; }}
      #win {{ position: absolute; left: {WIN_X}px; top: {WIN_Y}px; width: {WIN_W}px; height: {WIN_H}px; overflow: hidden; background: #ddd; z-index: 2;
              border-top: 8px solid #2b1a0e; border-bottom: 8px solid #2b1a0e; }}
      .set {{ position: absolute; left: 0; top: 0; width: {WIN_W}px; height: {WIN_H}px; overflow: hidden; }}
      .world {{ position: absolute; left: 0; top: 0; width: {WORLD_W}px; height: {WORLD_H}px; transform-origin: 0 0; }}
      .bg {{ position: absolute; left: 0; top: -1227px; width: {WORLD_W}px; height: 2844px; }}
      .joint {{ position: absolute; left: 0; top: 0; width: 0; height: 0; }}
      .joint > img, .flip > img, .limb > img {{ position: absolute; display: block; }}
      .flip {{ position: absolute; left: 0; top: 0; width: 0; height: 0; transform: scaleX(-1); transform-origin: 0 0; }}
      .limb {{ position: absolute; left: 0; top: 0; width: 0; height: 0; transform-origin: 0 0; }}
      .unit {{ transform: scale({S}); transform-origin: 0 0; }}
      .legsize {{ transform: scale(0.72); }}
      .armsize {{ transform: scale(0.66); }}
      .headsize {{ transform: scale({HEAD_SCALE}); }}
      .cap {{ position: absolute; left: 40px; top: {WIN_Y + WIN_H - 128}px; width: 1000px; height: 110px; z-index: 6;
              display: flex; align-items: center; justify-content: center; text-align: center;
              font-size: 46px; line-height: 1.15; color: #fff;
              text-shadow: -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 3px 3px 0 #000, 0 4px 6px rgba(0,0,0,.6); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{D}" data-width="1080" data-height="1920">
      <div id="decoTop" class="deco clip" data-start="0" data-duration="{D}" style="left:0;top:0;width:1080px;height:500px">
        <div style="position:absolute;left:-60px;top:330px;width:420px;height:120px;background:#e98a3a;transform:rotate(-12deg)"></div>
        <div style="position:absolute;right:-70px;top:40px;width:300px;height:300px;background:#3fbf9f;transform:rotate(30deg)"></div>
      </div>
      <div id="decoBottom" class="deco clip" data-start="0" data-duration="{D}" style="left:0;top:1200px;width:1080px;height:720px">
        <div style="position:absolute;left:-80px;top:420px;width:520px;height:160px;background:#e98a3a;transform:rotate(14deg)"></div>
        <div style="position:absolute;right:-90px;top:80px;width:260px;height:260px;background:#3fbf9f;transform:rotate(-24deg)"></div>
      </div>
      <div id="title" class="band clip" data-start="0" data-duration="{D}" style="top:60px;height:400px"><b>{t1}</b><b>{t2}</b></div>
      <div id="payoff" class="band clip" data-start="0" data-duration="{D}" style="top:1290px;height:420px"><b>{p1}</b><b>{p2}</b></div>
      <div id="win" class="clip" data-start="0" data-duration="{D}">{''.join(sets)}
      </div>
      {''.join(caps)}
      {''.join(audio)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      const later = {{ immediateRender: false }};
      {chr(10).join('      ' + x for x in js).strip()}
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
'''
(HERE / 'index.html').write_text(html, encoding='utf-8')
for name, body in (('hyperframes.json', {'paths': {'assets': 'assets'}}), ('meta.json', {'id': HERE.name, 'name': HERE.name})):
    if not (HERE / name).is_file():                # HyperFrames project files, once per episode
        (HERE / name).write_text(json.dumps(body, indent=1), encoding='utf-8')
(HERE / 'sfx.json').write_text(json.dumps({'duration': D, 'events': [
    {'asset': a, 't': round(t, 3), 'gain': g} for a, t, g in sorted(sfx, key=lambda e: e[1])]}, indent=1), encoding='utf-8')
(HERE / 'staging.json').write_text(json.dumps({'duration': D, 'scenes': [
    {'id': s['id'], 'start': round(s['start'], 2), 'end': round(s['end'], 2), 'marks': s['x']} for s in SCENE_ORDER],
    'camera': CAM}, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'{len(BEATS)} beats, {len(SCENE_ORDER)} scenes, {D:.1f} s, {len(CAM)} shots, {len(sfx)} sfx, {len(js)} timeline calls')
