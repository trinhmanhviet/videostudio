"""Versioned editing sidecars and scoped, attested media. No generation calls."""
from __future__ import annotations

import array
import copy
import hashlib
import io
import json
import math
import re
import subprocess
import time
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from .core import digest
from .editing_presets import apply_preset, editing_presets, get_preset
from .media import asset, probe, run
from .visual_quality import atomic_json, fingerprint

MAX_UPLOAD = 150 * 1024 * 1024
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,120}$')
COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
EXPORT_STAGES = ('plan', 'research', 'script', 'speech', 'images', 'subtitles', 'music')


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid ' + label)
    return float(value)


def _fields(value, allowed, label, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('Invalid ' + label + ' fields')


def _bool(value, label):
    if type(value) is not bool: raise ValueError('Invalid ' + label)


def _id(value, label='ID'):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value): raise ValueError('Invalid ' + label)


def validate_edit_plan(plan, job, assets):
    """Reject client paths/filter expressions and return an independent normalized plan."""
    _fields(plan, ('schema_version', 'job_id', 'revision', 'preset_id', 'duration', 'canvas', 'tracks', 'clips', 'captions', 'music', 'sfx', 'narration'), 'plan',
            ('schema_version', 'job_id', 'revision', 'preset_id', 'duration', 'canvas', 'tracks', 'clips', 'captions', 'music', 'sfx'))
    if type(plan['schema_version']) is not int or plan['schema_version'] != 1 or plan['job_id'] != job['id']: raise ValueError('Wrong plan version or job')
    if type(plan['revision']) is not int or plan['revision'] < 0: raise ValueError('Invalid revision')
    get_preset(plan['preset_id'])
    duration = _number(plan['duration'], .05, 14400, 'duration')
    narration = plan.get('narration', {'volume': 1, 'muted': False})
    _fields(narration, ('volume', 'muted'), 'narration')
    _number(narration.get('volume', 1), 0, 4, 'narration volume'); _bool(narration.get('muted', False), 'narration muted')
    canvas = plan['canvas']; _fields(canvas, ('width', 'height', 'fps'), 'canvas', ('width', 'height', 'fps'))
    for k in ('width', 'height'):
        if type(canvas[k]) is not int or canvas[k] % 2 or not 64 <= canvas[k] <= 4096: raise ValueError('Canvas dimensions must be even, 64–4096')
    _number(canvas['fps'], 1, 60, 'frame rate')
    tracks = plan['tracks']
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 64: raise ValueError('Invalid tracks')
    track_map = {}
    for track in tracks:
        _fields(track, ('id', 'kind', 'name', 'muted', 'visible', 'locked'), 'track', ('id', 'kind', 'name', 'muted', 'visible', 'locked'))
        _id(track['id'])
        if track['id'] in track_map: raise ValueError('Duplicate track ID')
        if track['kind'] not in ('video', 'image', 'text', 'audio', 'narration', 'music', 'sfx'): raise ValueError('Invalid track kind')
        if not isinstance(track['name'], str) or len(track['name']) > 120: raise ValueError('Invalid track name')
        for k in ('muted', 'visible', 'locked'): _bool(track[k], k)
        track_map[track['id']] = track
    ids = set()
    for collection in ('clips', 'music', 'sfx'):
        clips = plan[collection]
        if not isinstance(clips, list) or len(clips) > 4000: raise ValueError('Invalid clips')
        for clip in clips:
            _fields(clip, ('id', 'track_id', 'kind', 'start', 'end', 'asset_id', 'source_start', 'enabled', 'scene_id', 'fit', 'motion', 'transition', 'opacity', 'text', 'x', 'y', 'width', 'height', 'crop', 'size', 'color', 'background', 'volume', 'fade_in', 'fade_out', 'muted', 'mute', 'chapter_index'), 'clip', ('id', 'track_id', 'start', 'end'))
            _id(clip['id'])
            if clip['id'] in ids: raise ValueError('Duplicate clip ID')
            ids.add(clip['id'])
            _id(clip['track_id'], 'track ID')
            track = track_map.get(clip['track_id'])
            if not track: raise ValueError('Clip track does not exist')
            kind = clip.get('kind', 'audio' if collection != 'clips' else None)
            if kind not in ('image', 'video', 'text', 'audio'): raise ValueError('Invalid clip kind')
            if collection != 'clips' and kind != 'audio': raise ValueError('Audio collection requires audio clips')
            if kind == 'audio' and track['kind'] not in ('audio', 'narration', 'music', 'sfx'): raise ValueError('Audio requires an audio track')
            if kind != 'audio' and track['kind'] not in ('video', 'image', 'text'): raise ValueError('Visual requires a visual track')
            start = _number(clip['start'], 0, duration, 'clip start'); end = _number(clip['end'], 0, duration, 'clip end')
            if end <= start: raise ValueError('Clip end must follow start')
            source_start = _number(clip.get('source_start', 0), 0, 14400, 'source start')
            for flag in ('enabled', 'muted', 'mute'):
                if flag in clip: _bool(clip[flag], flag)
            if kind != 'text':
                _id(clip.get('asset_id'), 'asset ID')
                media = assets.get(clip.get('asset_id'))
                if not media or media['kind'] != kind: raise ValueError('Unknown or incompatible scoped asset')
                if kind == 'video' and source_start + end - start > media['duration'] + .15: raise ValueError('Video trim exceeds source duration')
                if kind == 'audio' and source_start > media['duration']: raise ValueError('Audio trim exceeds source duration')
            else:
                if not isinstance(clip.get('text'), str) or not 1 <= len(clip['text']) <= 4000 or '\x00' in clip['text']: raise ValueError('Invalid text')
                _number(clip.get('size', 48), 8, 300, 'text size')
                for k in ('color', 'background'):
                    if k in clip and clip[k] is not None and (not isinstance(clip[k], str) or not COLOR.fullmatch(clip[k])): raise ValueError('Invalid text color')
            if 'scene_id' in clip: _id(clip['scene_id'], 'scene ID')
            for k in ('x', 'y', 'opacity'): _number(clip.get(k, 1 if k == 'opacity' else .5), 0, 1, k)
            for k in ('width', 'height'):
                if k in clip: _number(clip[k], .01, 1, k)
            if clip.get('fit', 'cover') not in ('cover', 'contain'): raise ValueError('Invalid framing')
            if 'crop' in clip:
                crop = clip['crop']; _fields(crop, ('x', 'y', 'width', 'height'), 'crop', ('x', 'y', 'width', 'height'))
                for k in crop: _number(crop[k], .001 if k in ('width', 'height') else 0, 1, 'crop ' + k)
                if crop['x'] + crop['width'] > 1.000001 or crop['y'] + crop['height'] > 1.000001: raise ValueError('Crop exceeds source')
            motion = clip.get('motion', {'type': 'none', 'amount': 0})
            _fields(motion, ('type', 'amount'), 'motion', ('type',))
            if motion['type'] not in ('none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down'): raise ValueError('Invalid motion')
            _number(motion.get('amount', .05), 0, .5, 'motion amount')
            transition = clip.get('transition', {'type': 'none', 'duration': 0})
            _fields(transition, ('type', 'duration'), 'transition', ('type',))
            if transition['type'] not in ('none', 'fade', 'dissolve', 'slide_left', 'slide_right'): raise ValueError('Invalid transition')
            _number(transition.get('duration', 0), 0, min(5, end - start), 'transition duration')
            _number(clip.get('volume', 1), 0, 4, 'volume')
            for k in ('fade_in', 'fade_out'): _number(clip.get(k, 0), 0, end - start, k)
    caption = plan['captions']
    _fields(caption, ('enabled', 'font_size', 'color', 'accent_color', 'bottom_margin', 'emphasis'), 'captions', ('enabled', 'font_size', 'color', 'accent_color', 'bottom_margin'))
    _bool(caption['enabled'], 'captions enabled'); _number(caption['font_size'], 8, 200, 'caption font size')
    _number(caption['bottom_margin'], 0, 1920, 'caption margin')
    for k in ('color', 'accent_color'):
        if not isinstance(caption[k], str) or not COLOR.fullmatch(caption[k]): raise ValueError('Invalid caption color')
    utterances = job['checkpoints'].get('speech', {}).get('utterances', [])
    if not isinstance(caption.get('emphasis', []), list) or len(caption.get('emphasis', [])) > 4000: raise ValueError('Invalid emphasis cues')
    for cue in caption.get('emphasis', []):
        _fields(cue, ('utterance_index', 'start', 'end', 'text'), 'emphasis', ('utterance_index', 'start', 'end', 'text'))
        index = cue['utterance_index']
        if type(index) is not int or not 0 <= index < len(utterances): raise ValueError('Unknown emphasis utterance')
        utt = utterances[index]
        start = _number(cue['start'], utt['start'], utt['end'], 'utterance emphasis start')
        end = _number(cue['end'], utt['start'], utt['end'], 'utterance emphasis end')
        if end <= start or not isinstance(cue['text'], str) or not cue['text'] or cue['text'] not in utt['narration']: raise ValueError('Emphasis must reference measured utterance text/times')
    return copy.deepcopy(plan)


def _metadata(path, kind, ffprobe='ffprobe'):
    if kind == 'image':
        with Image.open(path) as im: return {'width': im.width, 'height': im.height, 'duration': 0}
    try:
        # Capture probe diagnostics so rejected uploads do not write arbitrary stderr.
        data = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], stderr=subprocess.PIPE, timeout=20))
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        raise ValueError('Media could not be decoded') from error
    stream = next((s for s in data['streams'] if s['codec_type'] == ('audio' if kind == 'audio' else 'video')), None)
    if not stream: raise ValueError('Decoded media does not contain the expected stream')
    duration = _number(float(data['format'].get('duration', stream.get('duration', 0))), .001, 14400, 'media duration')
    return {'duration': duration, 'width': stream.get('width'), 'height': stream.get('height')}


class EditPlanService:
    def __init__(self, store, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self.store, self.ffmpeg, self.ffprobe = store, ffmpeg, ffprobe
        with store.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS edit_plan_heads(job TEXT PRIMARY KEY, revision INTEGER NOT NULL, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS edit_plan_assets(job TEXT,id TEXT,value TEXT NOT NULL,PRIMARY KEY(job,id));
                CREATE TABLE IF NOT EXISTS edit_plan_exports(child TEXT PRIMARY KEY,parent TEXT NOT NULL,revision INTEGER NOT NULL,snapshot_sha256 TEXT NOT NULL);''')

    def _registry(self, job, *, verify_sources=True, include_metadata=True):
        result = {}
        for stage in ('images', 'speech', 'music'):
            checkpoint = job['checkpoints'].get(stage, {})
            for attested in checkpoint.get('assets', []):
                path = Path(attested['path']).resolve()
                kind = 'image' if stage == 'images' and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') else 'audio' if stage in ('speech', 'music') and path.suffix.lower() in ('.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg') else None
                if not kind: continue
                identity = stage + '-' + hashlib.sha256((str(path) + attested['sha256']).encode()).hexdigest()[:24]
                section = next((s for s in checkpoint.get('sections', []) if str(Path(s.get('path', '')).resolve()) == str(path)), None)
                if section and section.get('asset_id'): identity = section['asset_id']
                row = {'id': identity, 'path': str(path), 'sha256': attested['sha256'], 'kind': kind, 'name': path.name, 'source': stage}
                if verify_sources and (not path.is_file() or digest(path) != row['sha256']): raise ValueError('Source checkpoint asset missing or changed')
                if include_metadata: row.update(_metadata(path, kind, self.ffprobe))
                for index, scene in enumerate(checkpoint.get('scenes', [])):
                    if isinstance(scene.get('path'),str) and Path(scene['path']).resolve() == path: row.update(scene_id=scene.get('scene_id', f'scene-{index:04}'))
                if section: row['chapter_index'] = section.get('chapter_index', 0)
                result[identity] = row
        with self.store.db() as c:
            for record in c.execute('SELECT value FROM edit_plan_assets WHERE job=?', (job['id'],)):
                row = json.loads(record['value']); result[row['id']] = row
        # Procedural local effects have explicit provenance and content hashes.
        from .edit_audio import ensure_sfx_library
        library = ensure_sfx_library(self.store.path.parent / 'editor-sfx')
        for identity, row in library.items():
            result[identity] = dict(row, id=identity, kind='audio', name=row.get('name', identity), source='procedural_sfx')
        return result

    def _default(self, job, assets):
        preset = get_preset(job.get('request', {}).get('edit_preset', 'documentary'), fallback=True)
        tracks = [{'id': identity, 'kind': kind, 'name': name, 'muted': False, 'visible': True, 'locked': False}
                  for identity, kind, name in (('visual', 'video', 'Video'), ('labels', 'text', 'Titles'), ('narration', 'narration', 'Narration'), ('music', 'music', 'Music'), ('sfx', 'sfx', 'SFX'))]
        cp = job['checkpoints']; scenes = cp.get('images', {}).get('scenes', []); utterances = cp.get('speech', {}).get('utterances', [])
        if not scenes or not utterances: raise ValueError('Editor is available after speech and images complete')
        by_path = {str(Path(a['path']).resolve()): a['id'] for a in assets.values()}
        clips = []; at = 0
        for index, scene in enumerate(scenes):
            end = at + float(scene['duration']); sid = scene.get('scene_id') or next((u.get('scene_id') for u in utterances if u.get('scene_index', index) == index and u.get('scene_id')), f'scene-{index:04}')
            transition = copy.deepcopy(preset['transition']); transition['duration'] = min(transition['duration'], end-at)
            clips.append({'id': f'visual-{index:04}', 'track_id': 'visual', 'kind': 'image', 'scene_id': sid, 'asset_id': by_path[str(Path(scene['path']).resolve())], 'start': at, 'end': end, 'source_start': 0, 'enabled': True, 'fit': 'cover', 'opacity': 1, 'motion': copy.deepcopy(preset['motion']), 'transition': transition})
            if scene.get('image_provider',cp.get('images',{}).get('image_provider',job.get('request',{}).get('image_provider'))) == 'flow':
                clips[-1]['crop']={'x':0,'y':0,'width':1,'height':.94}
            at = end
        duration = max(at, float(cp['speech'].get('duration_seconds', utterances[-1]['end'])))
        paths = [str(Path(u['path']).resolve()) for u in utterances]
        combined = by_path.get(str(Path(cp['speech'].get('path', '')).resolve()))
        for index, utt in enumerate(utterances):
            path = str(Path(utt['path']).resolve())
            # The combined narration includes the original job's pitch processing.
            # Trim that attested stem rather than reverting to unprocessed utterances.
            clips.append({'id': f'narration-{index:04}', 'track_id': 'narration', 'kind': 'audio', 'asset_id': combined or by_path[path], 'start': float(utt['start']), 'end': float(utt['end']), 'source_start': float(utt['start']) if combined or paths.count(path) > 1 else 0, 'volume': 1, 'fade_in': 0, 'fade_out': 0, 'enabled': True})
        title = str(cp.get('script', {}).get('title') or cp.get('plan', {}).get('title') or job['request'].get('idea', '')).splitlines()[0][:100].strip()
        if title:
            clips.append(dict(id='title', track_id='labels', kind='text', text=title, start=0, end=min(duration, 4), enabled=True, x=.5, y=.12, **preset['label']))
        chapter_names = {chapter.get('index', index+1): chapter.get('title', chapter.get('name', '')) for index, chapter in enumerate(cp.get('script', {}).get('chapters', [])) if isinstance(chapter, dict)}
        seen_chapters = set()
        for utterance in utterances:
            chapter = utterance.get('chapter_index')
            if chapter is None or chapter in seen_chapters or not chapter_names.get(chapter): continue
            seen_chapters.add(chapter)
            start = float(utterance['start'])
            clips.append(dict(id=f'chapter-label-{len(seen_chapters):04}', track_id='labels', kind='text', text=str(chapter_names[chapter])[:160], start=start, end=min(duration, start+3), enabled=True, x=.5, y=.2, **preset['label']))
        music = []
        sections = cp.get('music', {}).get('sections', [])
        if not sections and cp.get('music', {}).get('path'):
            sections = [{'path': cp['music']['path'], 'start': 0, 'end': duration}]
        for index, section in enumerate(sections):
            identity = by_path.get(str(Path(section.get('path', '')).resolve()))
            if not identity: continue
            start = max(0, float(section.get('start', 0))); end = min(duration, float(section.get('end', duration)))
            if end <= start: continue
            music.append({'id': f'music-{index:04}', 'track_id': 'music', 'kind': 'audio', 'asset_id': identity, 'start': start, 'end': end, 'source_start': 0, 'volume': float(job['request'].get('music_volume', .35)), 'fade_in': min(.5, (end-start)/2), 'fade_out': min(.8, (end-start)/2), 'enabled': True})
        from .edit_audio import default_sfx_events
        sfx = default_sfx_events(utterances, cp.get('script', {}).get('chapters', []), preset['id'])
        for index, event in enumerate(sfx):
            event.setdefault('id', f'sfx-event-{index:04}'); event.setdefault('track_id', 'sfx'); event.setdefault('kind', 'audio'); event.setdefault('enabled', True)
        if not job['request'].get('music_enabled', True): music = []
        if not job['request'].get('sfx_enabled', True): sfx = []
        preset['captions']['enabled'] = job['request'].get('captions_enabled', True)
        return {'schema_version': 1, 'job_id': job['id'], 'revision': 0, 'preset_id': preset['id'], 'duration': duration, 'canvas': {'width': 1080, 'height': 1920, 'fps': 30}, 'tracks': tracks, 'clips': clips, 'captions': preset['captions'], 'music': music, 'sfx': sfx, 'narration': {'volume': 1, 'muted': False}}

    def _plan(self, job, assets):
        snapshot = job['checkpoints'].get('images', {}).get('edit_plan_snapshot')
        if snapshot: return load_edit_snapshot(job)['plan']
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            head = c.execute('SELECT value FROM edit_plan_heads WHERE job=?', (job['id'],)).fetchone()
            if head: plan = json.loads(head['value'])
            else:
                plan = validate_edit_plan(self._default(job, assets), job, assets)
                c.execute('INSERT INTO edit_plan_heads VALUES(?,?,?)', (job['id'], 0, json.dumps(plan, ensure_ascii=False)))
                self._sidecar(job, plan)
        return plan

    def _sidecar(self, job, plan):
        root = Path(job['output']); history = root / 'edit-plan-revisions'; history.mkdir(parents=True, exist_ok=True)
        atomic_json(history / f"{plan['revision']:08}.json", plan)
        atomic_json(root / 'edit_plan.json', plan)

    def automatic_snapshot(self, job):
        """Freeze opt-in automatic defaults without altering a user's saved editor draft."""
        assets=self._registry(job)
        plan=validate_edit_plan(self._default(job,assets),job,assets)
        used={clip['asset_id'] for collection in ('clips','music','sfx') for clip in plan[collection] if clip.get('asset_id')}
        resolved={identity:assets[identity] for identity in used}
        cache=self.store.path.parent/'editor-visual-cache';cache.mkdir(parents=True,exist_ok=True)
        snapshot={'schema_version':1,'parent_job':job['id'],'plan':plan,'resolved_assets':resolved,'cache_directory':str(cache.resolve())}
        path=Path(job['output'])/'automatic-edit-plan-snapshot.json';atomic_json(path,snapshot)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            head=c.execute('SELECT revision FROM edit_plan_heads WHERE job=?',(job['id'],)).fetchone()
            if not head or head['revision']==0:
                c.execute('INSERT OR REPLACE INTO edit_plan_heads(job,revision,value) VALUES(?,?,?)',(job['id'],0,json.dumps(plan,ensure_ascii=False)))
                self._sidecar(job,plan)
        return path

    def _public_asset(self, jid, row):
        url = f"/api/jobs/{jid}/edit-plan/assets/{row['id']}"
        return {**{k: row[k] for k in ('id', 'kind', 'name', 'duration', 'width', 'height', 'source', 'scene_id', 'chapter_index') if k in row}, 'url': url, 'thumbnail_url': url + '?thumb=true' if row['kind'] in ('image', 'video') else None}

    def view(self, jid):
        job = self.store.get(jid)
        snapshot = job['checkpoints'].get('images', {}).get('edit_plan_snapshot')
        assets = load_edit_snapshot(job)['resolved_assets'] if snapshot else self._registry(job)
        plan = self._plan(job, assets)
        editable = not snapshot and job['state'] in ('completed','failed','awaiting_visual_review')
        missing = [s for s in EXPORT_STAGES if s not in job['checkpoints']]
        with self.store.db() as c:
            scene_version = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scene_editor_heads'").fetchone()
            row = c.execute('SELECT version FROM scene_editor_heads WHERE job=?', (jid,)).fetchone() if scene_version else None
        utterances = [{k: u[k] for k in ('narration', 'start', 'end', 'scene_id', 'scene_index', 'chapter_index') if k in u} for u in job['checkpoints'].get('speech', {}).get('utterances', [])]
        chapters = [{k: chapter[k] for k in ('title', 'name', 'index', 'chapter_index', 'start', 'end') if k in chapter} for chapter in job['checkpoints'].get('script', {}).get('chapters', []) if isinstance(chapter, dict)]
        capabilities = {'motion': ['none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down'], 'transition': ['none', 'fade', 'dissolve', 'slide_left', 'slide_right'], 'fit': ['cover', 'contain'], 'crop': True, 'visual_layers': True, 'text': True, 'audio_import': True, 'video_import': True}
        return {'job_id': jid,'parent_job':load_edit_snapshot(job,verify_assets=False)['parent_job'] if snapshot else None, 'revision': plan['revision'], 'editable': editable, 'can_export': editable and not missing, 'duration': plan['duration'], 'plan': plan, 'assets': [self._public_asset(jid, a) for a in assets.values()], 'presets': editing_presets(), 'warnings': ['Missing export checkpoints: ' + ', '.join(missing)] if missing else [], 'scene_editor_version': row['version'] if row else 0, 'job_state': job['state'], 'utterances': utterances, 'chapters': chapters, 'capabilities': capabilities}

    def _mutable(self, c, jid, revision):
        job = self.store.get(jid)
        from .project_lifecycle import reject_retired_job
        reject_retired_job(c, jid)
        if job['checkpoints'].get('images', {}).get('edit_plan_snapshot'): raise ValueError('Frozen export is immutable')
        if job['state'] not in ('completed','failed','awaiting_visual_review'): raise ValueError('Wait for completion or resume the original job before editing')
        head = c.execute('SELECT * FROM edit_plan_heads WHERE job=?', (jid,)).fetchone()
        if type(revision) is not int or not head or revision != head['revision']: raise ValueError('Stale edit-plan revision; refresh before saving')
        return job

    def save(self, jid, revision, plan):
        job = self.store.get(jid); assets = self._registry(job); self._plan(job, assets)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE'); self._mutable(c, jid, revision)
            normalized = validate_edit_plan(plan, job, assets)
            if normalized['revision'] != revision: raise ValueError('Stale plan revision')
            normalized['revision'] = revision + 1
            self._sidecar(job, normalized)
            c.execute('UPDATE edit_plan_heads SET revision=?,value=? WHERE job=?', (normalized['revision'], json.dumps(normalized, ensure_ascii=False), jid))
            self.store.event(c, jid, 'render', 'edit_plan_saved', str(normalized['revision']))
        return self.view(jid)

    def preset(self, jid, revision, preset_id):
        plan = apply_preset(self.view(jid)['plan'], preset_id)
        return self.save(jid, revision, plan)

    def import_asset(self, jid, raw, name):
        view = self.view(jid)
        if not view['editable']: raise ValueError('Job is not editable')
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_UPLOAD: raise ValueError('Upload must be 1 byte–150 MB')
        name = re.sub(r'[^\w. -]', '_', str(name).replace('\\', '/').split('/')[-1])[:120].replace('..', '_') or 'media'
        extension = Path(name).suffix.lower()
        kind = 'image' if extension in ('.png', '.jpg', '.jpeg', '.webp') else 'video' if extension in ('.mp4', '.mov', '.webm', '.mkv') else 'audio' if extension in ('.wav', '.mp3', '.m4a', '.ogg', '.flac', '.aac') else None
        if not kind: raise ValueError('Unsupported media type')
        identity = 'import-' + uuid.uuid4().hex
        folder = self.store.path.parent / 'editor-imports' / jid; folder.mkdir(parents=True, exist_ok=True)
        path = folder / (identity + ('.png' if kind == 'image' else extension))
        try:
            if kind == 'image':
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as im:
                        if im.format not in ('PNG', 'JPEG', 'WEBP') or getattr(im, 'n_frames', 1) != 1 or im.width * im.height > 20_000_000 or max(im.size) > 8192: raise ValueError('Unsafe image dimensions/format')
                        im.load(); ImageOps.exif_transpose(im).convert('RGBA').save(path, format='PNG')
            else:
                path.write_bytes(raw)
                metadata = _metadata(path, kind, self.ffprobe)
                if kind == 'video' and (metadata['width'] * metadata['height'] > 20_000_000 or max(metadata['width'], metadata['height']) > 8192): raise ValueError('Unsafe video dimensions')
                run([self.ffmpeg, '-v', 'error', '-xerror', '-i', path, '-map', '0:v:0' if kind == 'video' else '0:a:0', '-f', 'null', '-'], lambda: None, timeout=90)
            row = dict(id=identity, kind=kind, name=name, path=str(path.resolve()), sha256=digest(path), source='import', **_metadata(path, kind, self.ffprobe))
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE'); self._mutable(c, jid, view['revision'])
                c.execute('INSERT INTO edit_plan_assets VALUES(?,?,?)', (jid, identity, json.dumps(row)))
            return {'asset': self._public_asset(jid, row), 'revision': view['revision']}
        except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError, ValueError) as error:
            path.unlink(missing_ok=True)
            raise ValueError('Invalid or unsafe media: ' + str(error)) from error

    def asset_file(self, jid, asset_id, thumbnail=False):
        _id(asset_id, 'asset ID'); job = self.store.get(jid)
        assets = load_edit_snapshot(job,verify_assets=False)['resolved_assets'] if job['checkpoints'].get('images', {}).get('edit_plan_snapshot') else self._registry(job,verify_sources=False,include_metadata=False)
        row = assets.get(asset_id)
        if not row: raise ValueError('Scoped asset not found')
        path = Path(row['path'])
        if not path.is_file() or digest(path) != row['sha256']: raise ValueError('Asset missing or changed')
        if thumbnail and row['kind'] == 'video':
            folder = self.store.path.parent / 'editor-thumbnails'; folder.mkdir(parents=True, exist_ok=True)
            target = folder / (row['sha256'] + '.jpg')
            if not target.is_file(): run([self.ffmpeg, '-v', 'error', '-y', '-i', path, '-frames:v', '1', '-vf', 'scale=320:568:force_original_aspect_ratio=decrease', target], lambda: None)
            return target
        return path

    def waveform(self, jid, asset_id):
        path = self.asset_file(jid, asset_id); job = self.store.get(jid)
        registry = load_edit_snapshot(job,verify_assets=False)['resolved_assets'] if job['checkpoints'].get('images', {}).get('edit_plan_snapshot') else self._registry(job,verify_sources=False,include_metadata=False)
        if registry[asset_id]['kind'] != 'audio': raise ValueError('Waveform requires audio')
        folder = self.store.path.parent / 'editor-waveforms'; folder.mkdir(parents=True, exist_ok=True)
        target = folder / (registry[asset_id]['sha256'] + '.json')
        if target.is_file(): return dict(json.loads(target.read_text()), asset_id=asset_id)
        raw = run([self.ffmpeg, '-v', 'error', '-i', path, '-ac', '1', '-ar', '1000', '-f', 'f32le', '-'], lambda: None)
        samples = array.array('f'); samples.frombytes(raw)
        step = max(1, math.ceil(len(samples) / 256))
        bins = [round(min(1, max(abs(x) for x in samples[i:i+step])), 5) for i in range(0, len(samples), step)]
        duration=registry[asset_id].get('duration') or _metadata(path,'audio',self.ffprobe)['duration']
        result = {'asset_id': asset_id, 'duration': duration, 'bins': bins}
        atomic_json(target, result)
        return result

    def export(self, jid, revision, key):
        if not isinstance(key, str) or not 1 <= len(key) <= 150: raise ValueError('Idempotency-Key required (max 150)')
        parent = self.store.get(jid); assets = self._registry(parent); plan = self._plan(parent, assets); idem = 'edit-plan-export:' + key
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT j.id,e.parent,e.revision FROM jobs j LEFT JOIN edit_plan_exports e ON e.child=j.id WHERE j.idem=?', (idem,)).fetchone()
            from .core import reject_retired_idempotency
            reject_retired_idempotency(c,idem)
            if old:
                if old['parent'] != jid or old['revision'] != revision: raise ValueError('Idempotency key already used for another snapshot')
                child = old['id']
            else:
                self._mutable(c, jid, revision)
                # Read the head under the write lock: no save can interleave the frozen export.
                plan = json.loads(c.execute('SELECT value FROM edit_plan_heads WHERE job=?', (jid,)).fetchone()['value'])
                validate_edit_plan(plan, parent, assets)
                for stage in EXPORT_STAGES:
                    if stage not in parent['checkpoints']: raise ValueError('Required source checkpoint missing: ' + stage)
                    for row in parent['checkpoints'][stage].get('assets', []):
                        if not Path(row['path']).is_file() or digest(row['path']) != row['sha256']: raise ValueError('Source checkpoint changed')
                used = {clip['asset_id'] for collection in ('clips', 'music', 'sfx') for clip in plan[collection] if clip.get('asset_id')}
                resolved = {identity: assets[identity] for identity in used}
                for row in resolved.values():
                    if not Path(row['path']).is_file() or digest(row['path']) != row['sha256']: raise ValueError('Selected asset changed')
                from .output_layout import allocate_output
                child = str(uuid.uuid4()); output = allocate_output(self.store, c, parent['request'], child)
                cache = self.store.path.parent / 'editor-visual-cache'; cache.mkdir(parents=True, exist_ok=True)
                snapshot = {'schema_version': 1, 'parent_job': jid, 'plan': plan, 'resolved_assets': resolved, 'cache_directory': str(cache.resolve())}
                path = output / 'edit-plan-snapshot.json'; atomic_json(path, snapshot)
                checkpoints = {stage: copy.deepcopy(parent['checkpoints'][stage]) for stage in EXPORT_STAGES}
                checkpoints['images']['edit_plan_snapshot'] = str(path)
                checkpoints['images']['assets'].append(asset(path))
                checkpoints['images'].pop('reuse_audio', None)
                checkpoints['images']['visual_qa_required'] = False
                checkpoints['images']['visual_qa_status'] = 'not_checked'
                checkpoints['images']['automatic_visual_review'] = False
                checkpoints['images']['review_source'] = 'quick'
                now = time.time(); request = copy.deepcopy(parent['request'])
                atomic_json(output / 'brief.json', dict(request, job_id=child, parent_job=jid, revision_type='edit_plan'))
                atomic_json(output / 'edit_plan.json', plan)
                c.execute('INSERT INTO jobs(id,idem,request,state,stage,output,created,updated) VALUES(?,?,?,?,?,?,?,?)', (child, idem, json.dumps(request, ensure_ascii=False), 'queued', 'render', str(output), now, now))
                for stage, cp in checkpoints.items():
                    c.execute('INSERT INTO checkpoints VALUES(?,?,?)', (child, stage, json.dumps(cp, ensure_ascii=False))); atomic_json(output / (stage + '.json'), cp)
                c.execute('INSERT INTO edit_plan_exports VALUES(?,?,?,?)', (child, jid, revision, digest(path)))
                self.store.event(c, child, 'render', 'edit_plan_export_created', jid + ' revision ' + str(revision))
        return self.store.get(child)


def load_edit_snapshot(job, *, verify_assets=True):
    checkpoint = job['checkpoints'].get('images', {})
    path = Path(checkpoint.get('edit_plan_snapshot', ''))
    attested = next((a for a in checkpoint.get('assets', []) if Path(a['path']).resolve() == path.resolve()), None)
    if not attested or not path.is_file() or digest(path) != attested['sha256']: raise ValueError('Frozen edit-plan snapshot missing or changed')
    result = json.loads(path.read_text(encoding='utf8'))
    # Validation uses the parent's plan identity but the exact child's speech timings.
    validate_edit_plan(result['plan'], dict(job, id=result['parent_job']), result['resolved_assets'])
    if verify_assets:
        for row in result['resolved_assets'].values():
            if not Path(row['path']).is_file() or digest(row['path']) != row['sha256']: raise ValueError('Frozen source asset missing or changed')
    return result
