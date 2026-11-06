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

from .meme_contract import MUSIC_PROMPT, MemeScriptError

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
        self.props = {}
        library = self.root.parent/'assets/Meme_Animation_Asset_Pack/catalog/library.json'
        if library.is_file():
            for item in json.loads(library.read_text(encoding='utf8')).get('items',[]):
                if item.get('kind')=='prop' and _identifier(item.get('id','')):
                    path=(library.parent/item['file']).resolve()
                    if path.is_relative_to(library.parent.resolve()) and path.is_file():self.props[item['id']]=path
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
        payload += [('prop:'+key,hashlib.sha256(path.read_bytes()).hexdigest()) for key,path in sorted(self.props.items())]
        return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()

    def describe_for_prompt(self):
        return json.dumps({'costumes': sorted(self.costumes), 'accessories': sorted(self.accessories),
                           'faces': sorted(self.faces), 'backgrounds': sorted(self.backgrounds),
                           'actions_actor_arity': ACTIONS, 'props':sorted(self.props)}, ensure_ascii=False)




def validate(data, catalog, request, lenient=False, *, metadata_only=False, enforce_beat_count=True):
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
    if not metadata_only and enforce_beat_count and not low <= len(beats) <= high:
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
        return s.upper().rstrip('.,:;!?-')

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
        clean_acc = []
        for a in acc:
            aid = a.get('id') if isinstance(a, dict) else a
            if isinstance(aid, str) and _known(aid, catalog.accessories):
                clean_acc.append(a)
            else:
                bad(f'cast.{cid}: unknown accessory')
        acc = clean_acc
        face = card.get('face', face_default)
        if not _known(face, catalog.faces):
            bad(f'cast.{cid}: unknown face')
            face = face_default
        acc_ids = tuple(sorted((a.get('id') if isinstance(a, dict) else a) or '' for a in acc))
        identity = (costume, acc_ids)
        if identity in identities:
            for replacement in costume_ids:
                identity = (replacement, acc_ids)
                if identity not in identities:
                    costume = replacement
                    break
            else:
                for accessory in sorted(catalog.accessories):
                    candidate = sorted(set(list(acc_ids) + [accessory]))
                    identity = (costume, tuple(candidate))
                    if identity not in identities:
                        acc = list(acc) + [accessory]
                        break
                else:
                    raise MemeScriptError('Not enough catalog assets to distinguish cast')
        identities.add(identity)
        entry = {'name': _text(card.get('name')) or cid, 'costume': costume,
                 'acc': acc, 'face': face, 'voice': voice}
        if 'costume_offset' in card:
            entry['costume_offset'] = card['costume_offset']
        if 'acc_offsets' in card:
            entry['acc_offsets'] = card['acc_offsets']
        cast[cid] = entry
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

    props={}
    raw_props=data.get('props',{})
    if not isinstance(raw_props,dict):raise MemeScriptError('props must be an object')
    for pid,card in raw_props.items():
        if not _identifier(pid) or not isinstance(card,dict):raise MemeScriptError('Invalid prop ID/definition')
        aid=card.get('asset');label=_text(card.get('label'))
        if aid is not None and not _known(aid,catalog.props):raise MemeScriptError('Unknown prop asset')
        if not label:raise MemeScriptError('A prop needs a display label')
        props[pid]={'asset':aid,'label':label[:64]}
    prop_meta={'props':props} if 'props' in data else {}

    if metadata_only:
        if problems and not lenient:
            raise MemeScriptError('; '.join(problems[:40]))
        return {**bands, **PACING, **prop_meta, 'speed': SPEED, 'narrator_voice': voice,
                'cast': cast, 'scenes': scenes, 'adaptation_note': _text(data.get('adaptation_note'))}

    normalized = []
    for index, beat in enumerate(beats[:high] if lenient and enforce_beat_count else beats):
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
        if isinstance(punch,dict) and 'actor' in punch:
            if 'who' in punch and punch['who']!=punch['actor']:
                raise MemeScriptError('Reaction actor and who conflict')
            punch={**punch,'who':punch['actor']}
        if punch is not None:
            if not (isinstance(punch, dict) and _known(punch.get('who'), here)
                    and _known(punch.get('face'), catalog.faces)):
                bad(f'{where}: invalid punch actor or face')
                punch = None
            else:
                punch = {'who': punch['who'], 'face': punch['face']}
        normalized.append({'scene': scene, 'who': who, 'focus': focus, 'text': text,
                           'emo': emo, 'act': act, 'punch': punch})
        for field in ('pause_before','pause_after','reaction_seconds'):
            if field in beat:
                value=beat[field]
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=2:raise MemeScriptError('Comic pause must be finite, 0–2 seconds')
                normalized[-1][field]=value
        if 'props' in beat:
            values=beat['props']
            if not isinstance(values,dict):raise MemeScriptError('Beat props must be an object')
            clean={}
            for pid,value in values.items():
                if pid not in props or not isinstance(value,dict) or value.get('placement') not in ('held','table','hidden'):raise MemeScriptError('Invalid prop placement')
                owner=value.get('owner')
                if value['placement']=='held' and not _known(owner,here):raise MemeScriptError('Held prop requires an actor in the current scene')
                if owner is not None and not _known(owner,cast):raise MemeScriptError('Unknown prop actor')
                clean[pid]={'placement':value['placement'],'owner':owner}
            normalized[-1]['props']=clean
        if 'notes' in beat:
            notes=beat['notes']
            if not isinstance(notes,list):raise MemeScriptError('State notes must be a list')
            clean_notes=[]
            for note in notes:
                if not isinstance(note,dict) or not _known(note.get('prop'),props) or not _text(note.get('text')):raise MemeScriptError('State note requires a known prop and text')
                clean_notes.append({'prop':note['prop'],'text':_text(note['text'])[:120]})
            normalized[-1]['notes']=clean_notes
    if problems and not lenient:
        raise MemeScriptError('; '.join(problems[:40]))
    if len(normalized) < 2:
        raise MemeScriptError('Script has fewer than two usable beats; narrative text cannot be repaired locally')
    return {**bands, **PACING, **prop_meta, 'speed': SPEED, 'narrator_voice': voice, 'cast': cast, 'scenes': scenes,
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

