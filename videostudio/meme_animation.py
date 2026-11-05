"""Durable adapter for the existing MemeStudio HyperFrames episode engine.

All generated files belong to this job; approved developer episodes are read only.
Speech is generated once in the speech stage, never by the renderer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path

from .core import PermanentError, digest
from .media import asset, run, audio_report, verify as verify_media
from .meme_pipeline import _log, _save

ROOT = Path(__file__).resolve().parents[1]
MS = ROOT / 'memestudio'
VERSION = 'meme-hyperframes-v1'


def enabled(job):
    r = job.get('request', {})
    return r.get('workflow_mode') == 'meme' and r.get('meme_engine') == 'hyperframes'


def preflight_for_request(status, request):
    if not enabled({'request': request}):
        return status
    checks = [{**c, 'ok': True, 'detail': 'Không dùng trong hoạt hình HyperFrames (asset và SFX cục bộ).'}
              if c['name'].startswith(('comfy_', 'model:', 'stable_audio')) else c for c in status['checks']]
    return {**status, 'checks': checks, 'ready': all(c['ok'] for c in checks)}


def episode(job):
    path = Path(job['output']) / 'episode'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _identity(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}


def _valid_assets(items):
    return bool(items) and all(Path(a['path']).is_file() and digest(a['path']) == a['sha256'] for a in items)


def command(args, check, log, timeout=900, progress=None):
    """Run only owned local engine children; cancel the whole owned process tree."""
    check()
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY='1', DO_NOT_TRACK='1', PYTHONIOENCODING='utf-8')
    with Path(log).open('wb') as output:
        p = subprocess.Popen([str(a) for a in args], cwd=MS, env=env, stdout=output, stderr=subprocess.STDOUT, **options)
        start = last = time.monotonic()
        try:
            while p.poll() is None:
                check()
                now = time.monotonic()
                if now - start > timeout:
                    raise TimeoutError('Animation engine timed out; source checkpoints are preserved')
                if progress and now - last > 15:
                    progress(); last = now
                time.sleep(.2)
            if p.returncode:
                raise RuntimeError(Path(log).read_text(encoding='utf8', errors='replace')[-2500:])
        finally:
            if p.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=20)


def plan(pipeline, job, check):
    from .meme_animation_script import AnimationCatalog
    check()
    scope = pipeline.exchanges.for_job(job['id']) if os.getenv('VS_LLM_TRANSPORT', 'cdp') in ('extension', 'chrome') and hasattr(pipeline, 'exchanges') else None
    status = preflight_for_request(pipeline.preflight(scope), job['request'])
    # This engine uses local sprites and SFX, not image/music generation models.
    failures = [c['name'] for c in status['checks'] if not c['ok']]
    if failures:
        raise PermanentError('Preflight blocked: ' + ', '.join(failures))
    pipeline.voices.selected(job['request']['voice_id'])
    if not shutil.which('node') or not (MS / 'node_modules/hyperframes/bin/hyperframes.mjs').is_file():
        raise PermanentError('HyperFrames unavailable: run npm ci in memestudio first')
    catalog = AnimationCatalog()
    _log(pipeline, job, 'plan', 'Hoạt hình HyperFrames: dùng tủ đồ, biểu cảm, chuyển động và SFX có sẵn.')
    return {'title': job['request']['idea'][:80], 'meme': True, 'meme_engine': 'hyperframes',
            'catalog': catalog.fingerprint(), 'speed': 1.15, 'music_prompt': ''}


def script(pipeline, job, check):
    from .meme_animation_script import AnimationCatalog, MemeScriptError, build_prompt, validate, to_checkpoint
    catalog = AnimationCatalog(); folder = Path(job['output']); folder.mkdir(parents=True, exist_ok=True)
    from .meme_animation_long import needs_parts, write_parts
    if needs_parts(job['request']):
        return write_parts(pipeline, job, check, catalog)
    feedback = []; last = None
    for attempt in range(3):
        check(); path = folder / f'animation-script-attempt-{attempt:02}.json'
        rejected = path.with_suffix('.rejected.json')
        rejection = _load(rejected)
        if path.is_file() and rejection.get('sha256') == digest(path):
            last = path; feedback = [rejection['error']]; continue
        _log(pipeline, job, 'script', f'Viết hoạt hình theo tủ đồ, giọng đã chọn và biểu cảm (lượt {attempt+1}/3)...')
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding='utf8'))
            else:
                raw = pipeline.llm_json(build_prompt(job['request'], catalog, feedback), check)
                _save(path, raw)
            last = path
            normalized = validate(raw, catalog, job['request']); break
        except (MemeScriptError, ValueError) as error:
            feedback = [str(error)[:1000]]
            if path.is_file():
                _save(rejected, {'sha256': digest(path), 'error': feedback[0]})
    else:
        try:
            normalized = validate(json.loads(last.read_text(encoding='utf8')), catalog, job['request'], lenient=True)
        except (AttributeError, OSError, ValueError, TypeError) as error:
            raise PermanentError('Không đủ nội dung để dựng hoạt hình: ' + str(error)[:500]) from error
    result = to_checkpoint(normalized, catalog.fingerprint())
    final = folder / 'animation-script.json'; _save(final, normalized)
    result['assets'] = [asset(final)]
    _log(pipeline, job, 'script', f"Sẵn sàng {len(normalized['beats'])} lượt thoại, {len(normalized['cast'])} nhân vật có tạo hình riêng.")
    return result


def _silence(writer, frames):
    chunk = bytes(48000 * 4)
    while frames > 0:
        n = min(frames, 48000); writer.writeframesraw(chunk[:n*4]); frames -= n


def speech(pipeline, job, check):
    ep = episode(job); data = copy.deepcopy(job['checkpoints']['script']['animation_script'])
    # A derived "change voice" job reuses the story checkpoint, not its voice.
    data['narrator_voice'] = job['request']['voice_id']
    for character in data['cast'].values():
        character['voice'] = job['request']['voice_id']
    for flag in ('captions_enabled', 'sfx_enabled'):
        data[flag] = job['request'].get(flag, True)
    _save(ep / 'script.json', data)
    rawjob = copy.deepcopy(job); rawjob['request']['pitch'] = 0
    revision = ep / 'raw-voice'; revision.mkdir(exist_ok=True)
    raw = pipeline._speech_attempt(rawjob, check, revision)
    if len(raw['utterances']) != len(data['beats']):
        raise PermanentError('Animation voice count differs from script')
    voice = pipeline.voices.selected(job['request']['voice_id'])
    speed = float(data['speed']); pitch = float(job['request'].get('pitch', 0)); rows = []
    for n, (beat, source) in enumerate(zip(data['beats'], raw['utterances'])):
        check(); who = beat['who']; wav = ep / f'assets/voice/{n:02}_{who}.wav'; wav.parent.mkdir(parents=True, exist_ok=True)
        recipe = _identity({'raw': digest(source['path']), 'speed': speed, 'pitch': pitch, 'version': VERSION})
        receipt = wav.with_suffix('.processing.json'); saved = _load(receipt)
        if not (wav.is_file() and saved.get('recipe') == recipe and saved.get('sha256') == digest(wav)):
            part = wav.with_suffix('.part.wav'); filters = [f'atempo={speed}']
            if pitch:
                filters.append(f'rubberband=pitch={2**(pitch/12):.10f}:formant=preserved')
            filters.append('alimiter=limit=0.89:level=false')
            run([pipeline.ffmpeg, '-v', 'error', '-y', '-i', source['path'], '-af', ','.join(filters),
                 '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', part], check)
            part.replace(wav); _save(receipt, {'recipe': recipe, 'sha256': digest(wav)})
        with wave.open(str(wav), 'rb') as w:
            duration = w.getnframes() / w.getframerate()
        ident = _identity({'t': beat['text'], 'v': voice, **({'s': speed} if speed != 1 else {})})
        wav.with_suffix('.id').write_text(ident, encoding='utf8')
        rows.append({'n': n, 'who': who, 'voice': voice['id'], 'file': f'assets/voice/{n:02}_{who}.wav',
                     'duration': round(duration, 3), 'text': beat['text'], 'resolved_voice': voice,
                     'source_id': ident, 'wav_sha256': digest(wav)})
    _save(ep / 'voice.json', rows)
    command([sys.executable, '-I', MS / 'engine/make_episode.py', ep], check, ep / 'build.log')
    staging = _load(ep / 'staging.json'); seconds = float(staging['duration']); utterances = []
    path = Path(job['output']) / 'speech.wav'; part = path.with_suffix('.part.wav')
    with wave.open(str(part), 'wb') as output:
        output.setparams((2, 2, 48000, 0, 'NONE', 'not compressed')); cursor = 0
        for n, (timing, row) in enumerate(zip(staging['beats'], rows)):
            check(); start = round(timing['start'] * 48000)
            _silence(output, max(0, start-cursor)); cursor = max(cursor, start)
            with wave.open(str(ep / row['file']), 'rb') as w:
                frames = w.getnframes(); output.writeframesraw(w.readframes(frames)); cursor += frames
            utterances.append({**job['checkpoints']['script']['scenes'][n], 'scene_index': n, 'line_index': 0,
                               'path': str(ep / row['file']), 'start': timing['start'], 'end': timing['end'],
                               'duration': row['duration'], 'who': row['who']})
        _silence(output, max(0, round(seconds*48000)-cursor))
    part.replace(path)
    files = [p for p in ep.rglob('*') if p.name not in ('render-receipt.json', 'sfx.wav')]
    assets = raw.get('assets', []) + [asset(p) for p in files if p.is_file() and p.suffix not in ('.log', '.part')] + [asset(path)]
    return {'path': str(path), 'duration_seconds': seconds, 'utterances': utterances, 'scenes': utterances,
            'final_narration': job['checkpoints']['script']['narration'], 'duration_attempts': 1,
            'meme_engine': 'hyperframes', 'speed': speed, 'pitch': pitch, 'assets': assets}


def images(pipeline, job, check):
    check(); ep = episode(job)
    files = [p for p in (ep / 'assets').rglob('*') if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.ttf', '.js')]
    if not files or not (ep / 'index.html').is_file():
        raise PermanentError('Animation composition missing; resume from speech')
    _log(pipeline, job, 'images', 'Đã chuẩn bị tạo hình, trang phục và nền riêng cho video; không gọi Flow.')
    return {'image_provider': 'meme_assets', 'scenes': [], 'meme_engine': 'hyperframes',
            'visual_qa_required': False, 'visual_qa_status': 'not_applicable', 'assets': [asset(p) for p in files]}


def music(pipeline, job, check):
    check(); seconds = float(job['checkpoints']['speech']['duration_seconds']); path = Path(job['output']) / 'music-muted.wav'
    with wave.open(str(path), 'wb') as w:
        w.setparams((2, 2, 48000, 0, 'NONE', 'not compressed')); _silence(w, round(seconds*48000))
    return {'path': str(path), 'duration_seconds': seconds, 'intentional_mute': True,
            'reason': 'HyperFrames episode mixes voice and procedural SFX', 'assets': [asset(path)]}


def render(pipeline, job, check):
    from .meme_render import ensure_clean_audio
    from .output_layout import publish_video
    ep = episode(job); seconds = float(job['checkpoints']['speech']['duration_seconds'])
    sources = [a for name in ('script', 'speech', 'images', 'music') for a in job['checkpoints'][name].get('assets', [])]
    if not _valid_assets(sources):
        raise PermanentError('Animation source checkpoint changed; retry from the affected stage')
    engine = [MS / 'engine/make_sfx.py', MS / 'package-lock.json']
    sfx = sorted((MS / 'assets/sfx').glob('*'))
    identity = _identity({'version': VERSION, 'sources': sources, 'engine': [asset(p) for p in engine+sfx if p.is_file()]})
    receipt = ep / 'render-receipt.json'; saved = _load(receipt)
    if saved.get('identity') == identity and _valid_assets(saved.get('result', {}).get('assets', [])):
        return saved['result']
    _log(pipeline, job, 'render', f'Dựng hoạt hình HyperFrames {seconds:.1f} giây: chuyển động, nhép miệng, camera và SFX...')
    if job['request'].get('sfx_enabled', True):
        command([sys.executable, '-I', MS / 'engine/make_sfx.py', ep], check, ep / 'sfx.log')
    target = Path(job['output']) / 'video.part.mp4'
    command([shutil.which('node') or 'node', MS / 'node_modules/hyperframes/bin/hyperframes.mjs',
             'render', ep, '--quiet', '--fps', '30', '-o', target], check, ep / 'render.log',
            timeout=max(180, seconds*12+120), progress=lambda: _log(pipeline, job, 'render', 'HyperFrames đang dựng; không gửi lại kịch bản hoặc tạo lại lời đọc.'))
    audio = ensure_clean_audio(str(target), check, pipeline.ffmpeg)
    verify_media(str(target), seconds, pipeline.ffprobe)
    result = publish_video(job, {'video': str(target), 'assets': [asset(target)], 'renderer': VERSION,
                                'beats': len(job['checkpoints']['speech']['utterances']), 'duration_seconds': seconds,
                                'audio_quality': audio})
    _save(receipt, {'identity': identity, 'result': result})
    return result


def verify(pipeline, job, check):
    path = job['checkpoints']['render']['video']; seconds = job['checkpoints']['speech']['duration_seconds']
    check(); result = verify_media(path, seconds, pipeline.ffprobe)
    run([pipeline.ffmpeg, '-v', 'error', '-i', path, '-f', 'null', '-'], check, timeout=max(900, seconds*3))
    result.update(audio_quality=audio_report(path, check, pipeline.ffmpeg), full_video_decode_ok=True,
                  semantic_viewing_performed=False, renderer=VERSION,
                  visual_quality={'status': 'not_applicable', 'reason': 'pre-approved animation rig assets'})
    return result
