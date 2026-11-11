"""Measured chapter soundtracks and non-destructive editor audio mixing.

Only the server's resolved asset registry supplies file paths. Client clip data is
converted to numeric FFmpeg filters; it never supplies paths or filter strings.
"""
from __future__ import annotations

import array
from functools import lru_cache
import hashlib
import io
import json
import math
import random
import threading
import uuid
from pathlib import Path
import wave

from .core import digest, PermanentError
from .media import asset, probe, run

_SFX_DURATIONS = {'whoosh': .65, 'impact': .55, 'chime': .9, 'click': .12}
_MIX_POLICY = 'edit-audio-v4-48k-duck-limiter-original-stems'
_SFX_LOCK = threading.RLock()


def _number(value, name, minimum=0, maximum=1_000_000):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Invalid audio {name}')
    return float(value)


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _write_json(path, value):
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if path.is_file() and path.read_text(encoding='utf8') == payload:
        return
    partial = path.with_name(path.stem + '-' + uuid.uuid4().hex + '.part.json')
    try:
        partial.write_text(payload, encoding='utf8')
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def _measured_duration(job):
    cp = job.get('checkpoints', {})
    value = cp.get('speech', {}).get('duration_seconds')
    if value is None:
        value = cp.get('verify', {}).get('duration_seconds')
    if value is None:
        value = job.get('request', {}).get('duration_seconds', 0)
    return _number(value, 'measured duration', .001)


def _scene_times(scenes):
    cursor = 0.0
    result = []
    for scene in scenes:
        start = _number(scene.get('start', cursor), 'scene start')
        end = _number(scene.get('end', start + scene.get('duration', 0)), 'scene end')
        if end <= start:
            raise ValueError('Invalid measured scene interval')
        result.append((scene, start, end))
        cursor = end
    return result


def music_sections(job, preset_id='documentary'):
    """Group contiguous measured scenes by explicit semantic chapter, never by caption.

    Legacy scripts without chapter indices deliberately produce one section even
    when every scene has a music prompt. No new language-model planning is needed.
    """
    cp = job.get('checkpoints', {})
    duration = _measured_duration(job)
    script = cp.get('script', {})
    source = cp.get('speech', {}).get('scenes') or cp.get('speech', {}).get('utterances') or []
    script_scenes = script.get('scenes', [])
    timed = []
    for ordinal, (scene, start, end) in enumerate(_scene_times(source)):
        scene = dict(scene)
        script_index = scene.get('scene_index', ordinal)
        if scene.get('chapter_index') is None and isinstance(script_index, int) and 0 <= script_index < len(script_scenes):
            scene['chapter_index'] = script_scenes[script_index].get('chapter_index')
        timed.append((scene, start, end))
    has_chapters = any(scene.get('chapter_index') is not None for scene, _, _ in timed)
    groups = []
    if has_chapters:
        for scene, start, end in timed:
            chapter = scene.get('chapter_index')
            # A missing index inherits its current chapter; do not turn it into a
            # fabricated scene-level music request.
            if chapter is None and groups:
                chapter = groups[-1]['chapter_index']
            if not groups or groups[-1]['chapter_index'] != chapter:
                groups.append({'chapter_index': chapter, 'start': start, 'end': end,
                               'scene_prompt': scene.get('music_prompt')})
            else:
                groups[-1]['end'] = end
        groups[0]['start'] = 0.0
        for previous, following in zip(groups, groups[1:]):
            previous['end'] = following['start']
        groups[-1]['end'] = duration
    else:
        groups = [{'chapter_index': None, 'start': 0.0, 'end': duration}]
    styles = {'documentary': 'Warm restrained cinematic documentary, slow evolving instrumental',
              'science': 'Clean spacious science documentary, subtle electronic textures',
              'everyday': 'Gentle warm everyday storytelling, light acoustic instrumental'}
    chapters = {chapter.get('index', i + 1): chapter for i, chapter in enumerate(script.get('chapters', []))}
    base = cp.get('plan', {}).get('music_prompt', 'Quiet unobtrusive instrumental soundtrack')
    result = []
    for i, group in enumerate(groups):
        start, end = group['start'], group['end']
        if end <= start or start >= duration:
            continue
        chapter = chapters.get(group['chapter_index'], {})
        title = str(chapter.get('title', '')).strip()
        prompt = chapter.get('music_prompt') or group.get('scene_prompt') or base
        identity = f'music-section-{i:04}'
        result.append({'id': identity, 'asset_id': identity, 'chapter_index': group['chapter_index'],
                       'start': start, 'end': min(end, duration), 'duration': min(end, duration) - start,
                       'title': title or ('Soundtrack' if not has_chapters else f'Chapter {group["chapter_index"]}'),
                       'prompt': ('Instrumental only, no vocals. ' + styles.get(preset_id, styles['documentary']) +
                                  (f'. Chapter: {title}' if title else '') + '. ' + str(prompt)[:700])})
    return result


def _valid_cached_result(value):
    try:
        return bool(value.get('path')) and Path(value['path']).is_file() and all(
            Path(item['path']).is_file() and digest(item['path']) == item['sha256']
            for item in value.get('assets', []))
    except (KeyError, OSError, TypeError):
        return False


def generate_chapter_music(pipeline, job, check):
    """Generate/recover one durable Stable Audio receipt per semantic chapter.

    A completed legacy music checkpoint remains authoritative. The local summary
    also permits a retry after generation completed but before its DB checkpoint
    was written. Individual Comfy receipts retain the established recovery rules.
    """
    check()
    cp = job.get('checkpoints', {})
    existing = cp.get('music')
    if existing and _valid_cached_result(existing):
        return existing
    folder = Path(job['output'])
    folder.mkdir(parents=True, exist_ok=True)
    request = job.get('request', {})
    preset_id = request.get('edit_preset', 'documentary')
    duration = _measured_duration(job)
    ffmpeg, ffprobe = pipeline.ffmpeg, pipeline.ffprobe
    if request.get('music_enabled', True) is False:
        output = folder / 'music-intentionally-muted.wav'
        if not output.is_file():
            run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                 '-t', duration, '-c:a', 'pcm_s16le', output], check)
        return {'path': str(output), 'duration_seconds': duration, 'intentional_mute': True,
                'source': 'workflow-music-disabled', 'sections': [], 'full_decode_ok': True,
                'assets': [asset(output)]}
    sections = music_sections(job, preset_id)
    identity = _identity({'policy': 'chapter-music-v1', 'sections': sections})
    summary = folder / 'chapter-music.json'
    if summary.is_file():
        try:
            saved = json.loads(summary.read_text(encoding='utf8'))
            if saved.get('identity') == identity and _valid_cached_result(saved['result']):
                return saved['result']
        except (ValueError, KeyError, TypeError):
            pass
    from .providers import music_graph
    from .music import assemble_scene_soundtracks, extend_music, normalize_music_levels
    seed = int(hashlib.sha256(job['id'].encode()).hexdigest()[:8], 16)
    fade = min(1.5, min(section['duration'] for section in sections) * .3)
    assembled, assets, metadata = [], [], []
    for index, section in enumerate(sections):
        check()
        kind = section['id']
        raw = folder / (kind + '.mp3')
        graph = music_graph(section['prompt'], max(5.0, min(60.0, section['duration'] + fade)),
                            seed + index, 'videostudio/' + job['id'] + '-' + kind)
        generated = pipeline.comfy_asset(job, kind, graph, raw, check)
        run([ffmpeg, '-v', 'error', '-i', raw, '-f', 'null', '-'], check)
        normalized = normalize_music_levels(raw, folder, check, ffmpeg)
        tail = fade if index < len(sections) - 1 else 0.0
        target = section['duration'] + tail
        covered = folder / (kind + '-covered-' + _identity([digest(normalized['path']), target])[:12] + '.wav')
        if not covered.is_file():
            extend_music(normalized['path'], target, covered, check, ffmpeg, ffprobe)
        assets.extend(generated.get('assets', []))
        assets.extend(normalized['assets'])
        assets.append(asset(covered))
        assembled.append({'path': str(covered), 'duration': section['duration']})
        metadata.append({**section, 'path': str(covered), 'sha256': digest(covered),
                         'end': section['end'] + tail, 'section_end': section['end'],
                         'duration_seconds': target, 'source_start': 0, 'volume': .35,
                         'fade_in': fade if index else min(.4, section['duration'] / 4),
                         'fade_out': tail if tail else min(.5, section['duration'] / 4),
                         'source': 'stable-audio-chapter', 'recovery_kind': kind})
    output = folder / ('music-chapters-' + identity[:12] + '.wav')
    joined = assemble_scene_soundtracks(assembled, duration, output, check, ffmpeg, ffprobe)
    actual_fade = joined.get('crossfade_seconds', 0)
    for index, section in enumerate(metadata):
        if index < len(metadata) - 1:
            section['end'] = section['section_end'] + actual_fade
            section['fade_out'] = actual_fade
        if index:
            section['fade_in'] = actual_fade
    normalized = normalize_music_levels(output, folder, check, ffmpeg)
    assets.extend(joined['assets'] + normalized['assets'])
    result = {'path': normalized['path'], 'raw_path': str(output), 'duration_seconds': duration,
              'audio_quality': normalized['audio_quality'], 'raw_audio_quality': normalized['raw_audio_quality'],
              'full_decode_ok': True, 'license_reviewed': False, 'chapter_tracks': len(sections),
              'sections': metadata, 'crossfade_seconds': joined.get('crossfade_seconds', 0),
              'assets': list({item['path']: item for item in assets}.values())}
    _write_json(summary, {'identity': identity, 'result': result})
    return result


@lru_cache(maxsize=4)
def _sfx_bytes(name):
    """Versioned deterministic synthesis, no recordings or third-party samples."""
    rate = 48000
    duration = _SFX_DURATIONS[name]
    generator = random.Random('videostudio-sfx-v1-' + name)
    values = array.array('h')
    previous = 0.0
    for index in range(round(duration * rate)):
        t = index / rate
        phase = t / duration
        noise = generator.uniform(-1, 1)
        if name == 'whoosh':
            previous = previous * .88 + noise * .12
            value = .8 * previous * math.sin(math.pi * phase) ** 2
        elif name == 'impact':
            value = (.38 * math.sin(2 * math.pi * (80 * t - 30 * t * t)) + .12 * noise) * math.exp(-12 * t)
        elif name == 'chime':
            value = (.19 * math.sin(2 * math.pi * 880 * t) + .09 * math.sin(2 * math.pi * 1320 * t)) * math.exp(-5 * t)
        else:
            value = (.22 * noise + .13 * math.sin(2 * math.pi * 1800 * t)) * math.exp(-70 * t)
        value *= min(1.0, t / .004, (duration - t) / .012)
        values.append(round(max(-.8, min(.8, value)) * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        handle.writeframes(values.tobytes())
    return buffer.getvalue()


def ensure_sfx_library(folder):
    """Materialize four original CC0 procedural WAVs and an attested manifest."""
    # FastAPI serves parallel editor/asset requests. Serialize the very small
    # verification/write phase so Windows readers cannot race file replacement.
    with _SFX_LOCK:
        return _ensure_sfx_library(folder)


def _ensure_sfx_library(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, duration in _SFX_DURATIONS.items():
        payload = _sfx_bytes(name)
        expected = hashlib.sha256(payload).hexdigest()
        path = folder / (name + '.wav')
        if not path.is_file() or digest(path) != expected:
            partial = path.with_name(path.stem + '-' + uuid.uuid4().hex + '.part.wav')
            try:
                partial.write_bytes(payload)
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        identity = 'sfx-' + name
        result[identity] = {'id': identity, 'kind': 'audio', 'name': name.title(), 'path': str(path),
                            'duration': duration, 'sha256': expected,
                            'source': 'videostudio-procedural-synthesis-v1',
                            'license': 'CC0-1.0', 'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
                            'attribution': 'Original mathematical synthesis by VideoStudio; no sampled recordings.'}
    _write_json(folder / 'manifest.json', {'schema_version': 1, 'assets': list(result.values())})
    return result


def default_sfx_events(scenes, chapters, preset_id='documentary'):
    """Place restrained accents at the title and real chapter changes only."""
    timed = _scene_times(scenes)
    if not timed:
        return []
    duration = timed[-1][2]
    accents = [0.0]
    chapter = timed[0][0].get('chapter_index')
    for scene, start, _ in timed[1:]:
        current = scene.get('chapter_index', chapter)
        if current != chapter and start - accents[-1] >= 4:
            accents.append(start)
        chapter = current
    name = {'science': 'chime', 'everyday': 'click'}.get(preset_id, 'whoosh')
    return [{'id': f'sfx-accent-{i:04}', 'kind': 'audio', 'track_id': 'sfx', 'asset_id': 'sfx-' + name,
             'start': start, 'end': min(duration, start + _SFX_DURATIONS[name]), 'source_start': 0,
             'volume': .22 if name == 'chime' else .28, 'fade_in': .005, 'fade_out': .04,
             'enabled': True} for i, start in enumerate(accents) if start < duration]


def _cached_wave(path, identity):
    receipt = path.with_suffix('.json')
    try:
        saved = json.loads(receipt.read_text(encoding='utf8'))
        return path.is_file() and saved['identity'] == identity and saved['sha256'] == digest(path)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _render_wave(inputs, filters, output, duration, check, ffmpeg):
    output = Path(output)
    partial = output.with_name(output.stem + '-' + uuid.uuid4().hex + '.part.wav')
    try:
        run([ffmpeg, '-v', 'error', '-y', *inputs, '-filter_complex', filters,
             '-map', '[out]', '-t', duration, '-ar', '48000', '-ac', '2',
             '-c:a', 'pcm_s24le', '-rf64', 'auto', partial], check)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)


def _stem(clips, category, duration, folder, check, ffmpeg):
    """Cache independent stems; bounded batches support a long narration timeline."""
    identity = _identity([_MIX_POLICY, category, duration, clips])
    output = folder / (category + '-' + identity[:20] + '.wav')
    if _cached_wave(output, identity):
        return output
    if len(clips) > 24:
        children = [_stem(clips[i:i+24], category, duration, folder, check, ffmpeg)
                    for i in range(0, len(clips), 24)]
        # Merge recursively with the same bounded input count. Child stems are
        # already positioned and gain-adjusted on the global timeline.
        normalized = [{'path': str(path), 'sha256': digest(path), 'channels': 2, 'start': 0, 'end': duration,
                       'source_start': 0, 'volume': 1, 'fade_in': 0, 'fade_out': 0}
                      for path in children]
        merged = _stem(normalized, category + '-group', duration, folder, check, ffmpeg)
        # Avoid copying a potentially hours-long WAV for this outer cache layer.
        return merged
    inputs, chain = [], []
    for i, clip in enumerate(clips):
        inputs += ['-i', clip['path']]
        length = clip['end'] - clip['start']
        filt = (f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,'
                f'atrim=start={clip["source_start"]:.9f}:duration={length:.9f},'
                f'asetpts=N/SR/TB,apad=whole_dur={length:.9f},'
                f'atrim=duration={length:.9f},volume={clip["volume"]:.9f}')
        if clip['fade_in']:
            filt += f',afade=t=in:d={clip["fade_in"]:.9f}'
        if clip['fade_out']:
            filt += f',afade=t=out:st={max(0, length-clip["fade_out"]):.9f}:d={clip["fade_out"]:.9f}'
        # adelay can emit its initial silence with NOPTS on newer FFmpeg builds.
        # Assign sample-count timestamps before atrim/amix so the silence remains
        # real timeline audio rather than disappearing at the following trim.
        filt += (f',adelay={round(clip["start"] * 48000)}S:all=1,asetpts=N/SR/TB,'
                 f'apad=whole_dur={duration:.9f}[c{i}]')
        chain.append(filt)
    if len(clips) == 1:
        chain.append(f'[c0]atrim=duration={duration:.9f}[out]')
    elif clips:
        chain.append(''.join(f'[c{i}]' for i in range(len(clips))) +
                     f'amix=inputs={len(clips)}:duration=longest:normalize=0,atrim=duration={duration:.9f}[out]')
    else:
        inputs = ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        chain = [f'[0:a]atrim=duration={duration:.9f}[out]']
    _render_wave(inputs, ';'.join(chain), output, duration, check, ffmpeg)
    _write_json(output.with_suffix('.json'), {'identity': identity, 'sha256': digest(output)})
    return output


def mix_edit_audio(job, plan, resolved_assets, output, check, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Remix original scoped stems with clip trims/gains/fades and speech ducking.

    Returns a normal media checkpoint plus cache_key/reused. Silent output is
    intentional when every track is muted; it is never labeled generated music.
    """
    check()
    duration = _number(plan.get('duration'), 'duration', .001)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = output.parent / 'audio-stems'
    folder.mkdir(parents=True, exist_ok=True)
    tracks = {track['id']: track for track in plan.get('tracks', [])}
    categories = {'narration': [], 'music': [], 'sfx': [], 'audio': []}
    seen = set()
    source_hashes = {}
    source_info = {}
    for collection, default in (('clips', 'audio'), ('music', 'music'), ('sfx', 'sfx')):
        for clip in plan.get(collection, []):
            if collection == 'clips' and clip.get('kind') != 'audio':
                continue
            track = tracks.get(clip.get('track_id'), {})
            if (clip.get('enabled', True) is False or clip.get('muted') is True or clip.get('mute') is True
                    or track.get('muted') is True):
                continue
            clip_id = clip.get('id')
            if clip_id and clip_id in seen:
                continue
            if clip_id:
                seen.add(clip_id)
            category = track.get('kind', default)
            if category not in categories:
                category = default
            if clip.get('track_id') == 'narration':
                category = 'narration'
            narration = plan.get('narration', {}) if category == 'narration' else {}
            if narration.get('muted') is True:
                continue
            start = _number(clip.get('start', 0), 'clip start')
            end = _number(clip.get('end', duration), 'clip end')
            if end <= start:
                raise ValueError('Audio clip end must follow its start')
            source_start = _number(clip.get('source_start', 0), 'source trim')
            volume = _number(clip.get('volume', 1), 'volume', 0, 4) * _number(track.get('volume', 1), 'track volume', 0, 4)
            volume *= _number(narration.get('volume', 1), 'narration volume', 0, 4)
            fade_in = _number(clip.get('fade_in', 0), 'fade in')
            fade_out = _number(clip.get('fade_out', 0), 'fade out')
            if start >= duration or volume == 0:
                continue
            end = min(duration, end)
            identity = clip.get('asset_id')
            if identity not in resolved_assets:
                raise ValueError('Audio clip references an unavailable asset')
            source = resolved_assets[identity]
            path = Path(source['path'])
            if not path.is_file():
                raise ValueError('Audio source is missing')
            if str(path) not in source_hashes:
                source_hashes[str(path)] = digest(path)
            actual = source_hashes[str(path)]
            if source.get('sha256') and source['sha256'] != actual:
                raise ValueError('Attested original audio source changed')
            # A short legacy background source naturally loops; narration and
            # SFX always obey their finite source trim and are never repeated.
            if str(path) not in source_info:
                source_info[str(path)] = probe(path, ffprobe)
            info = source_info[str(path)]
            channels = next((stream.get('channels', 2) for stream in info.get('streams', [])
                             if stream.get('codec_type') == 'audio'), 2)
            if category == 'music':
                measured = float(info['format']['duration'])
                wanted = source_start + end - start
                if wanted > measured + .02:
                    from .music import extend_music
                    covered = folder / ('loop-' + _identity([actual, wanted])[:20] + '.wav')
                    if not covered.is_file():
                        extend_music(path, wanted, covered, check, ffmpeg, ffprobe)
                    path, actual = covered, digest(covered)
                    channels = 2
            categories[category].append({'path': str(path), 'sha256': actual, 'channels': channels,
                'start': start, 'end': end, 'source_start': source_start, 'volume': volume,
                'fade_in': min(fade_in, end-start), 'fade_out': min(fade_out, end-start)})
    identity = _identity([_MIX_POLICY, duration, categories])
    if _cached_wave(output, identity):
        return {'path': str(output), 'duration_seconds': duration, 'sha256': digest(output),
                'assets': [asset(output)], 'cache_key': identity, 'reused': True, 'full_decode_ok': True}
    stems = {category: _stem(clips, category, duration, folder, check, ffmpeg)
             for category, clips in categories.items() if clips}
    inputs, indexes = [], {}
    for category, path in stems.items():
        indexes[category] = len(indexes)
        inputs += ['-i', str(path)]
    chain, labels = [], []
    if 'narration' in indexes and 'music' in indexes:
        chain += [f'[{indexes["narration"]}:a]asplit=2[voice][side]',
                  f'[{indexes["music"]}:a][side]sidechaincompress=threshold=0.06:ratio=4:attack=25:release=300[duck]']
        labels += ['[voice]', '[duck]']
    else:
        labels += [f'[{indexes[name]}:a]' for name in ('narration', 'music') if name in indexes]
    labels += [f'[{indexes[name]}:a]' for name in ('sfx', 'audio') if name in indexes]
    if not labels:
        inputs = ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        labels = ['[0:a]']
    mix = f'amix=inputs={len(labels)}:duration=longest:normalize=0,' if len(labels) > 1 else ''
    chain.append(''.join(labels) + mix +
                 f'alimiter=limit=0.95:level=false:latency=true,apad=whole_dur={duration:.9f},'
                 f'atrim=duration={duration:.9f}[out]')
    _render_wave(inputs, ';'.join(chain), output, duration, check, ffmpeg)
    run([ffmpeg, '-v', 'error', '-i', output, '-f', 'null', '-'], check)
    actual_duration = float(probe(output, ffprobe)['format']['duration'])
    if abs(actual_duration - duration) > .03:
        raise RuntimeError('Edited soundtrack does not cover the measured timeline')
    _write_json(output.with_suffix('.json'), {'identity': identity, 'sha256': digest(output),
                                           'duration_seconds': actual_duration})
    return {'path': str(output), 'duration_seconds': actual_duration, 'sha256': digest(output),
            'assets': [asset(output)], 'cache_key': identity, 'reused': False, 'full_decode_ok': True}
