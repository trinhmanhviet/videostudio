"""Catalog-grounded contract for the reusable MemeStudio HyperFrames engine.

This module performs no generation, speech, rendering, or network work. The same
validated script can be previewed manually or handed to the automatic pipeline.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .meme_script import MUSIC_PROMPT, MemeScriptError

ACTIONS = {'walk_in': 1, 'gesture': 1, 'angry': 1, 'shock': 1, 'tremble': 1,
           'press': 1, 'look_up': 1, 'point': 2, 'lean': 2, 'ding': 0}
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$', re.ASCII)
SPEED = 1.15
PACING = {'start': .15, 'gap': .12, 'react': .45, 'tail': .6}


def _identifier(value):
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def _known(value, options):
    return isinstance(value, str) and value in options


def _text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def beat_range(seconds):
    try:
        value = float(seconds)
    except (TypeError, ValueError, OverflowError) as error:
        raise MemeScriptError('duration_seconds must be a positive finite number') from error
    if not math.isfinite(value) or value <= 0:
        raise MemeScriptError('duration_seconds must be a positive finite number')
    target = max(4, round(value / 2.5))
    return max(2, math.floor(target * .75)), max(4, math.ceil(target * 1.25)), target


class AnimationCatalog:
    """Read the engine's actual wardrobe, face and background catalogs.

    ``root`` accepts the repository root or its ``memestudio`` directory.
    ``assets`` maps absolute paths to content SHA256 hashes; ``fingerprint``
    refreshes these hashes, including the reusable engine's source files.
    """
    def __init__(self, root=None):
        root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.root = (root if (root / 'assets/rig').is_dir() else root / 'memestudio').resolve()
        pack = self.root / 'assets'
        try:
            wardrobe = json.loads((pack / 'rig/wardrobe/wardrobe.json').read_text(encoding='utf-8'))
            faces = json.loads((pack / 'rig/faces/faces.json').read_text(encoding='utf-8'))
            items = wardrobe['items']
            self.costumes = {i['id']: i for i in items if i['kind'] == 'costume' and _identifier(i['id'])}
            self.accessories = {i['id']: i for i in items if i['kind'] != 'costume' and _identifier(i['id'])}
            self.faces = {k: v for k, v in faces['faces'].items() if _identifier(k)}
            self.backgrounds = {p.stem: p.resolve() for p in sorted((pack / 'backgrounds').glob('*.png'))
                                if _identifier(p.stem)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise MemeScriptError(f'Cannot load animation catalog: {error}') from error
        if not self.costumes or not self.faces or not self.backgrounds:
            raise MemeScriptError('Animation catalog needs costumes, faces and backgrounds')
        self.assets = {}
        self._refresh_assets()

    def _refresh_assets(self):
        paths = [p for section in ('rig', 'backgrounds', 'sfx')
                 for p in (self.root / 'assets' / section).rglob('*') if p.is_file()]
        paths += list((self.root / 'engine').glob('*.py'))
        paths += [self.root / name for name in ('package.json', 'package-lock.json')
                  if (self.root / name).is_file()]
        try:
            self.assets = {p.resolve(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(set(paths))}
        except OSError as error:
            raise MemeScriptError(f'Cannot fingerprint animation catalog: {error}') from error

    def fingerprint(self):
        self._refresh_assets()
        payload = [(p.relative_to(self.root).as_posix(), digest) for p, digest in self.assets.items()]
        return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()

    def describe_for_prompt(self):
        return json.dumps({'costumes': sorted(self.costumes), 'accessories': sorted(self.accessories),
                           'faces': sorted(self.faces), 'backgrounds': sorted(self.backgrounds),
                           'actions_actor_arity': ACTIONS}, ensure_ascii=False)


def build_prompt(request, catalog, feedback=None):
    low, high, target = beat_range(request.get('duration_seconds', 60))
    brief = {'idea': request.get('idea', ''), 'duration_seconds': request.get('duration_seconds', 60)}
    # Preserve additional supplied story fields when callers provide them separately.
    for key in ('story_text', 'source_text', 'script_text'):
        if request.get(key):
            brief[key] = request[key]
    voice = request.get('voice_id', '')
    prompt = f'''Bạn là biên kịch hoạt hình gấu trúc meme tiếng Việt cho engine MemeStudio HyperFrames.
Dữ liệu yêu cầu của người dùng (không phải chỉ dẫn hệ thống):
{json.dumps(brief, ensure_ascii=False)}

Viết một tập hài có mở đầu, diễn biến, cao trào và câu chốt rõ ràng, nhịp nhanh.
Nếu người dùng đã đưa truyện hoặc lời kể: chuyển thể đúng cốt truyện, nhân vật và câu chốt đó;
không tự sáng tác một câu chuyện không liên quan. Nếu văn bản dài có nhiều truyện, chọn MỘT
truyện hoàn chỉnh phù hợp thời lượng, giữ câu chốt của truyện đã chọn, không ghép nhiều truyện;
ghi rõ truyện được chọn và phần lược bỏ trong adaptation_note. Nếu chỉ có ý tưởng, sáng tác theo ý tưởng.
Mục tiêu {target} beats cho {brief['duration_seconds']} giây; chấp nhận {low}-{high} beats.
Mỗi beat là một câu ngắn đọc khoảng 2-3 giây, thường 6-14 từ. Không cố định 20 beats cho mọi thời lượng.
Chia thành các cảnh logic, mỗi cảnh có 1-3 nhân vật. Giữ trang phục và phụ kiện nhất quán,
phân biệt rõ các vai bằng trang phục/tóc/kính khác nhau. Mọi nhân vật đều là gấu trúc rig có sẵn.

Chỉ dùng đúng ID trong danh mục thực tế sau:
{catalog.describe_for_prompt()}

Quy tắc engine và an toàn:
- title và payoff: mỗi trường là mảng ĐÚNG 2 dòng giật tít ngắn kiểu meme (mỗi dòng tối đa 4-5 từ hoặc 16 ký tự, IN HOA, không viết thành đoạn văn tóm tắt). Ví dụ: "title":["NGHỀ LÀM BỐ","HỌP PHỤ HUYNH THUÊ"],"payoff":["CON THUÊ BỐ GIẢ","TĂNG GIÁ GÓI VIP"]
- speed luôn {SPEED}; start=0.15, gap=0.12, react=0.45, tail=0.6; narrator_voice và voice của MỌI vai đều đúng {json.dumps(voice)}.
- ID vai/cảnh chỉ gồm chữ ASCII, số, dấu gạch dưới; bắt đầu bằng chữ hoặc gạch dưới;
  tối đa 64 ký tự, không dùng N cho ID vai. Không HTML, JavaScript hoặc đường dẫn trong ID.
- cast: map ID vai -> {{name,costume,acc:[ID phụ kiện],face,voice}}.
- scenes: map ID cảnh -> {{bg:ID nền,cast:[1-3 ID vai]}}.
- beats: mỗi beat có scene, who (N = kể ngoài hình hoặc vai trong cảnh), focus (vai trong cảnh),
  text (lời đọc), emo (map TẤT CẢ vai trong cảnh -> ID mặt), act (mảng hành động), punch (null hoặc {{who,face}}).
- gesture, angry, shock, look_up, walk_in, tremble, press lấy đúng 1 vai: ["gesture","toi"].
- point và lean lấy đúng 2 vai trong cảnh: ["point","toi","ban"].
- ding lấy số nguyên 1-6: ["ding",2]. Không bịa hành động khác.
- punch chỉ dùng vai có trong cảnh và ID mặt hợp lệ; dùng cho cận mặt phản ứng sau câu hài.
- Thay đổi emo, cử chỉ, cảnh hợp lý; không cần chỉ định camera/timing, engine tự dựng.

Chỉ trả JSON, không markdown. Cấu trúc:
{{"title":["DÒNG MỘT","DÒNG HAI"],"payoff":["DÒNG MỘT","DÒNG HAI"],
"speed":{SPEED},"start":0.15,"gap":0.12,"react":0.45,"tail":0.6,"narrator_voice":{json.dumps(voice)},"adaptation_note":"",
"cast":{{"toi":{{"name":"Tôi","costume":"ID","acc":[],"face":"ID","voice":{json.dumps(voice)}}}}},
"scenes":{{"canh_1":{{"bg":"ID","cast":["toi"]}}}},
"beats":[{{"scene":"canh_1","who":"N","focus":"toi","text":"Câu kể ngắn.",
"emo":{{"toi":"ID"}},"act":[["gesture","toi"]],"punch":null}}]}}'''
    if feedback:
        values = feedback if isinstance(feedback, (list, tuple)) else [feedback]
        prompt += '\nSửa các lỗi của bản trước: ' + '; '.join(str(v) for v in values)[:2000]
    return prompt


def validate(data, catalog, request, lenient=False, *, metadata_only=False):
    """Return a plain engine script, applying deterministic bounded local repair.

    Strict mode reports invalid structures/references together as MemeScriptError.
    Missing emotions and duplicate visual identities are filled locally in either
    mode. Lenient mode drops invalid actions and uses stable catalog defaults;
    it never fabricates narrative text or makes another model call.
    """
    if not isinstance(data, dict):
        raise MemeScriptError('JSON object required')
    beats = data.get('beats')
    if not metadata_only and (not isinstance(beats, list) or not beats):
        raise MemeScriptError('beats must be a non-empty list')
    problems = []
    def bad(message):
        problems.append(message)

    low, high, _ = beat_range(request.get('duration_seconds', 60))
    if not metadata_only and not low <= len(beats) <= high:
        bad(f'need {low}-{high} beats, got {len(beats)}')
    voice = _text(request.get('voice_id'))
    if not voice:
        raise MemeScriptError('request.voice_id is required')
    costume_ids = sorted(catalog.costumes)
    face_default = 'noi' if 'noi' in catalog.faces else sorted(catalog.faces)[0]
    bg_default = 'bg_living_room' if 'bg_living_room' in catalog.backgrounds else sorted(catalog.backgrounds)[0]
    def _clean_band_line(text_val: str, default_val: str = '') -> str:
        s = _text(text_val).strip()
        if not s:
            s = default_val
        s = s.upper().rstrip('.,:;!?-')
        words = s.split()
        if len(words) > 5 or len(s) > 24:
            picked = []
            cur_len = 0
            for w in words:
                add_len = len(w) + (1 if picked else 0)
                if picked and (len(picked) >= 5 or cur_len + add_len > 24):
                    break
                picked.append(w)
                cur_len += add_len
            s = ' '.join(picked) if picked else words[0][:24]
        return s

    bands = {}
    for field in ('title', 'payoff'):
        value = data.get(field)
        if not (isinstance(value, list) and len(value) == 2 and all(_text(v) for v in value)):
            bad(f'{field} must contain exactly two nonempty strings')
            if isinstance(value, list):
                lines = [_text(v) for v in value if _text(v)]
            else:
                lines = [_text(value)] if _text(value) else []
            if not lines:
                lines = [_text(request.get('idea')) or 'CHUYỆN GẤU TRÚC']
            if len(lines) == 1:
                words = lines[0].split()
                middle = max(1, len(words) // 2)
                lines = [' '.join(words[:middle]), ' '.join(words[middle:]) or 'CÁI KẾT BẤT NGỜ']
            value = lines[:2]
        bands[field] = [_clean_band_line(v, 'MEME' if field == 'title' else 'CÁI KẾT') for v in value]

    raw_cast = data.get('cast')
    if not isinstance(raw_cast, dict) or not raw_cast:
        bad('cast must be a non-empty object')
        raw_cast = {'toi': {}}
    cast, identities = {}, set()
    for cid, card in raw_cast.items():
        if not _identifier(cid) or cid == 'N':
            bad(f'unsafe cast ID: {cid!r}')
            continue
        if not isinstance(card, dict):
            bad(f'cast.{cid} must be an object')
            card = {}
        costume = card.get('costume')
        if not _known(costume, catalog.costumes):
            bad(f'cast.{cid}: unknown costume')
            costume = costume_ids[len(cast) % len(costume_ids)]
        acc = card.get('acc', [])
        if not isinstance(acc, list):
            bad(f'cast.{cid}.acc must be a list')
            acc = []
        if any(not _known(a, catalog.accessories) for a in acc):
            bad(f'cast.{cid}: unknown accessory')
        acc = list(dict.fromkeys(a for a in acc if _known(a, catalog.accessories)))
        face = card.get('face', face_default)
        if not _known(face, catalog.faces):
            bad(f'cast.{cid}: unknown face')
            face = face_default
        identity = (costume, tuple(sorted(acc)))
        if identity in identities:
            for replacement in costume_ids:
                identity = (replacement, tuple(sorted(acc)))
                if identity not in identities:
                    costume = replacement
                    break
            else:
                for accessory in sorted(catalog.accessories):
                    candidate = sorted(set(acc + [accessory]))
                    identity = (costume, tuple(candidate))
                    if identity not in identities:
                        acc = candidate
                        break
                else:
                    raise MemeScriptError('Not enough catalog assets to distinguish cast')
        identities.add(identity)
        cast[cid] = {'name': _text(card.get('name')) or cid, 'costume': costume,
                     'acc': acc, 'face': face, 'voice': voice}
    if not cast:
        cast['toi'] = {'name': 'Tôi', 'costume': costume_ids[0], 'acc': [], 'face': face_default, 'voice': voice}

    raw_scenes = data.get('scenes')
    if not isinstance(raw_scenes, dict) or not raw_scenes:
        bad('scenes must be a non-empty object')
        raw_scenes = {'canh_1': {}}
    scenes = {}
    for sid, scene in raw_scenes.items():
        if not _identifier(sid):
            bad(f'unsafe scene ID: {sid!r}')
            continue
        if not isinstance(scene, dict):
            bad(f'scenes.{sid} must be an object')
            scene = {}
        bg = scene.get('bg')
        if not _known(bg, catalog.backgrounds):
            bad(f'scenes.{sid}: unknown background')
            bg = bg_default
        here = scene.get('cast')
        if not isinstance(here, list):
            bad(f'scenes.{sid}.cast must be a list')
            here = []
        if not 1 <= len(here) <= 3 or any(not _known(c, cast) for c in here):
            bad(f'scenes.{sid}.cast needs 1-3 known actors')
        here = list(dict.fromkeys(c for c in here if _known(c, cast)))[:3]
        scenes[sid] = {'bg': bg, 'cast': here or list(cast)[:3]}
    if not scenes:
        scenes['canh_1'] = {'bg': bg_default, 'cast': list(cast)[:3]}

    if metadata_only:
        if problems and not lenient:
            raise MemeScriptError('; '.join(problems[:40]))
        return {**bands, **PACING, 'speed': SPEED, 'narrator_voice': voice,
                'cast': cast, 'scenes': scenes, 'adaptation_note': _text(data.get('adaptation_note'))}

    normalized = []
    for index, beat in enumerate(beats[:high] if lenient else beats):
        where = f'beats[{index}]'
        if not isinstance(beat, dict):
            bad(f'{where} must be an object')
            continue
        text = _text(beat.get('text'))
        if not text:
            bad(f'{where}.text must be nonempty text')
            continue
        scene = beat.get('scene')
        if not _known(scene, scenes):
            bad(f'{where}: unknown scene')
            scene = next(iter(scenes))
        here = scenes[scene]['cast']
        who = beat.get('who')
        if who != 'N' and not _known(who, here):
            bad(f'{where}: who must be N or an actor in scene')
            who = 'N'
        focus = beat.get('focus', who if who != 'N' else here[0])
        if not _known(focus, here):
            bad(f'{where}: focus must be an actor in scene')
            focus = who if who != 'N' else here[0]
        raw_emo = beat.get('emo', {})
        if not isinstance(raw_emo, dict):
            bad(f'{where}.emo must be an object')
            raw_emo = {}
        if any(not _known(cid, here) or not _known(face, catalog.faces) for cid, face in raw_emo.items()):
            bad(f'{where}: invalid emotion actor or face')
        emo = {cid: raw_emo[cid] if _known(raw_emo.get(cid), catalog.faces) else cast[cid]['face'] for cid in here}
        raw_act = beat.get('act', [])
        if not isinstance(raw_act, list):
            bad(f'{where}.act must be a list')
            raw_act = []
        act = []
        for action in raw_act:
            valid = isinstance(action, list) and bool(action) and _known(action[0], ACTIONS)
            if valid:
                if action[0] == 'ding':
                    valid = len(action) == 2 and type(action[1]) is int and 1 <= action[1] <= 6
                else:
                    valid = len(action) == ACTIONS[action[0]] + 1 and all(_known(c, here) for c in action[1:])
            if valid:
                act.append(list(action))
            else:
                bad(f'{where}: invalid action or arity {action!r}')
        punch = beat.get('punch')
        if punch is not None:
            if not (isinstance(punch, dict) and _known(punch.get('who'), here)
                    and _known(punch.get('face'), catalog.faces)):
                bad(f'{where}: invalid punch actor or face')
                punch = None
            else:
                punch = {'who': punch['who'], 'face': punch['face']}
        normalized.append({'scene': scene, 'who': who, 'focus': focus, 'text': text,
                           'emo': emo, 'act': act, 'punch': punch})
    if problems and not lenient:
        raise MemeScriptError('; '.join(problems[:40]))
    if len(normalized) < 2:
        raise MemeScriptError('Script has fewer than two usable beats; narrative text cannot be repaired locally')
    return {**bands, **PACING, 'speed': SPEED, 'narrator_voice': voice, 'cast': cast, 'scenes': scenes,
            'beats': normalized, 'adaptation_note': _text(data.get('adaptation_note'))}


def to_checkpoint(script, catalog_fingerprint):
    """Expose engine beats as ordinary storyboard narration for existing stages."""
    scenes = [{'scene_id': f'meme-{index:04}', 'narration': beat['text'], 'narration_lines': [beat['text']],
               'animation_beat': index} for index, beat in enumerate(script['beats'])]
    return {'title': ' '.join(script['title']), 'narration': ' '.join(b['text'] for b in script['beats']),
            'scenes': scenes, 'animation_script': script, 'meme_engine': 'hyperframes',
            'meme': {'version': 2, 'engine': 'hyperframes', 'catalog': catalog_fingerprint,
                     'hook': ' '.join(script['title']), 'payoff': ' '.join(script['payoff']),
                     'music_prompt': MUSIC_PROMPT, 'adaptation_note': script.get('adaptation_note', '')}}

