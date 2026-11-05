"""Stage handlers for workflow_mode == 'meme' (Panda meme videos).

The meme mode reuses the existing speech, subtitles and music stages unchanged; it replaces
plan/research/script (one catalog-constrained story call), images (asset resolution, no image
generation) and render/verify (the Pillow + FFmpeg meme renderer).
"""
from __future__ import annotations

import json
from pathlib import Path

from .core import PermanentError, digest

MODE = 'meme'
SCRIPT_ATTEMPTS = 3


def is_meme(job):
    return job.get('request', {}).get('workflow_mode') == MODE


def _log(pipeline, job, stage, text):
    store = getattr(pipeline, 'store', None)
    if store:
        store.log(job['id'], stage, text)


def _save(path, value):
    part = path.with_suffix(path.suffix + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    part.replace(path)


def plan(pipeline, job, check):
    from .meme_script import MUSIC_PROMPT
    _log(pipeline, job, 'plan', 'Chế độ video meme Gấu trúc: kiểm tra điều kiện chạy...')
    import os
    transport = os.getenv('VS_LLM_TRANSPORT', 'cdp')
    scope = pipeline.exchanges.for_job(job['id']) if transport in ('chrome', 'extension') and hasattr(pipeline, 'exchanges') else None
    status = pipeline.preflight(scope)
    if not status['ready']:
        raise PermanentError('Preflight blocked: ' + ', '.join(x['name'] for x in status['checks'] if not x['ok']))
    pipeline.voices.selected(job['request']['voice_id'])
    from .meme_catalog import load_catalog, refresh_library
    try:
        if refresh_library():
            _log(pipeline, job, 'plan', 'Đã nạp các asset mới vẽ trong thư mục new/ vào danh mục.')
    except Exception as error:  # a bad drawing must never block the video
        _log(pipeline, job, 'plan', 'Bỏ qua asset mới chưa nạp được: ' + (type(error).__name__ + ': ' + str(error))[:300])
    catalog = load_catalog()
    return {'title': job['request']['idea'][:80], 'music_prompt': MUSIC_PROMPT, 'visual_style': 'panda biaoqing meme',
            'meme': True, 'catalog': catalog.fingerprint(), 'backgrounds_available': len(catalog.backgrounds)}


def research(pipeline, job, check):
    check()
    return {'sources': [], 'assets': [], 'mode': 'meme_no_research', 'provenance': 'meme_story', 'context': {},
            'factual_claims_permitted': False}


def script(pipeline, job, check):
    from .media import asset
    from .meme_catalog import load_catalog
    from .meme_script import MemeScriptError, build_prompt, to_checkpoint, validate
    catalog = load_catalog()
    folder = Path(job['output'])
    folder.mkdir(parents=True, exist_ok=True)
    feedback = []
    last_path = None
    for attempt in range(SCRIPT_ATTEMPTS):
        check()
        path = folder / f'meme-script-attempt-{attempt:02}.json'
        rejected = path.with_suffix('.rejected.json')
        if path.is_file() and rejected.is_file():
            try:
                rejection = json.loads(rejected.read_text(encoding='utf8'))
                if rejection.get('sha256') == digest(path):
                    feedback = [rejection['error']]
                    last_path = path
                    continue  # Known bad reply: advance the repair budget without parsing it again.
            except (OSError, ValueError, KeyError, TypeError):
                pass
        _log(pipeline, job, 'script', f'Đang viết kịch bản meme và danh sách cảnh (lượt {attempt + 1}/{SCRIPT_ATTEMPTS})...')
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding='utf8'))
            except ValueError as error:
                feedback = ['Saved reply is not valid JSON: ' + str(error)[:300]]
                _save(rejected, {'sha256': digest(path), 'error': feedback[0]})
                continue
        else:
            try:
                raw = pipeline.llm_json(build_prompt(job['request'], catalog, feedback), check)
            except ValueError as error:
                feedback = [str(error)[:300]]
                continue
            _save(path, raw)
        last_path = path
        try:
            normalized = validate(raw, catalog, job['request'])
            break
        except MemeScriptError as error:
            feedback = [str(error)]
            _save(rejected, {'sha256': digest(path), 'error': feedback[0]})
            _log(pipeline, job, 'script', 'Kịch bản chưa đúng danh mục asset, nhờ viết lại: ' + str(error)[:300])
    else:
        if last_path is None:
            raise PermanentError('Không nhận được kịch bản meme hợp lệ: ' + '; '.join(feedback)[:500])
        # One final local coercion after the bounded repair attempts; preserve raw receipts.
        try:
            normalized = validate(json.loads(last_path.read_text(encoding='utf8')), catalog, job['request'], lenient=True)
        except (ValueError, TypeError) as error:
            raise PermanentError('Không có đủ nội dung meme để phục hồi: ' + str(error)[:500]) from error
        _log(pipeline, job, 'script', 'Dùng bản kịch bản cuối, tự thay các asset không có trong danh mục bằng mặc định.')
    result = to_checkpoint(normalized, catalog.fingerprint())
    final = folder / 'meme-script.json'
    _save(final, normalized)
    result['assets'] = [asset(final)]
    _log(pipeline, job, 'script', f"Kịch bản meme sẵn sàng: {len(normalized['beats'])} cảnh. Mở đầu: {normalized['hook']}")
    return result


def images(pipeline, job, check):
    """No image generation: confirm every asset the script uses still exists and record what is used."""
    from .meme_catalog import load_catalog
    check()
    catalog = load_catalog()
    beats = [scene['meme'] for scene in job['checkpoints']['script']['scenes']]
    used = {'backgrounds': sorted({b['bg'] for b in beats}), 'sprites': sorted({x for b in beats for x in [b.get('pose'), b.get('face'), b.get('prop'), b.get('partner'), *b.get('fx', [])] if x})}
    missing = [x for x in used['sprites'] if x not in catalog.items] + [x for x in used['backgrounds'] if x not in catalog.backgrounds]
    if missing:
        raise PermanentError('Asset meme không còn trong danh mục: ' + ', '.join(missing))
    _log(pipeline, job, 'images', f"Dùng {len(used['sprites'])} sprite và {len(used['backgrounds'])} nền có sẵn; không cần tạo ảnh.")
    return {'image_provider': 'meme_assets', 'scenes': [], 'meme_assets': used, 'catalog': catalog.fingerprint(),
            'visual_qa_required': False, 'visual_qa_status': 'not_applicable', 'assets': []}


def music_job(job):
    """The music stage reads plan.music_prompt; use the story's own music description."""
    import copy
    prompt = job['checkpoints'].get('script', {}).get('meme', {}).get('music_prompt')
    if not prompt:
        return job
    edited = copy.deepcopy(job)
    edited['checkpoints']['plan']['music_prompt'] = prompt
    return edited


def render(pipeline, job, check):
    from .meme_catalog import load_catalog
    from .meme_render import render_meme
    from .output_layout import publish_video
    _log(pipeline, job, 'render', 'Đang dựng video meme (ghép nhân vật, hiệu ứng, phụ đề, nhạc và âm thanh)...')
    result = render_meme(job, check, load_catalog(), pipeline.ffmpeg, pipeline.ffprobe)
    _log(pipeline, job, 'render', f"Dựng xong {result['beats']} cảnh trong {result.get('render_seconds', 0)} giây.")
    return publish_video(job, result)


def verify(pipeline, job, check):
    from .media import run, verify as verify_media
    from .meme_render import ensure_clean_audio
    _log(pipeline, job, 'verify', 'Đang kiểm tra video meme thành phẩm...')
    path = job['checkpoints']['render']['video']
    seconds = float(job['checkpoints']['speech']['duration_seconds'])
    # Videos from the first renderer could peak too hot; this re-encodes only the audio when needed.
    audio = ensure_clean_audio(path, check, pipeline.ffmpeg)
    result = verify_media(path, seconds, pipeline.ffprobe)
    run([pipeline.ffmpeg, '-v', 'error', '-i', path, '-f', 'null', '-'], check, timeout=900)
    result['audio_quality'] = audio
    result.update(full_video_decode_ok=True, semantic_viewing_performed=False,
                  visual_quality={'status': 'not_applicable', 'reason': 'meme assets are pre-approved sprites'})
    return result
