"""Stages of the "Kể truyện" (story narration) workflow: workflow_mode='story_narration'.

The worker, queue, checkpoints, retry and cancel are the existing ones; providers.Pipeline hands each stage here.
Stage meaning in this mode:
  plan       freeze the episode snapshot (chapters, voice settings, layout, gameplay playlist) into the job folder
  research   not applicable: the text is the user's own edited story
  script     split the text into reading units (sentence groups inside a paragraph), with pause targets
  speech     TTS through the existing engines (one model load per stage, batched); a WAV per unit + timing ledger
  images     gameplay: cut plan from the real narration length, then one master clip without text
  subtitles  cues from the unit timings (display split only, the spoken text is never rewritten); ASS + SRT
  music      not applicable
  render     compose the horizontal 1920x1080 and/or vertical 1080x1920 videos, MP3 and SRT
  verify     check every requested output, then publish beside each other in the book's folder
No ChatGPT, Flow, CDP or ComfyUI is used in any of these stages.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import wave
from pathlib import Path

from .media import asset, probe, run
from .story_library import StoryLibrary, slug

MODE = 'story_narration'
ALGORITHM = 'story-v1'
FPS = 30
# Layout contract (docs/ke-truyen-handoff.md §6). Boxes are x, y, w, h.
LAYOUTS = {
    # Game at 60% width (user, 2026-11-14: smaller than the first 70% so background, titles and captions show more).
    'ngang': {'size': (1920, 1080), 'game': (384, 178, 1152, 648), 'caption_bottom': 1080 - 975, 'caption_size': 46,
              'caption_margin': 200, 'line_chars': 56,
              'title': {'channel': (26, 30), 'book': (60, 58), 'chapter': (130, 36)}, 'title_margin': 120},
    'doc': {'size': (1080, 1920), 'game': (36, 650, 1008, 567), 'caption_bottom': 1920 - 1430, 'caption_size': 50,
            'caption_margin': 80, 'line_chars': 30,
            'title': {'channel': (215, 34), 'book': (262, 68), 'chapter': (430, 42)}, 'title_margin': 80},
}
PAUSE = {'title': 1.0, 'paragraph': .6, 'scene': 1.5, 'end': 1.2}
UNIT_CHARS = 220
SCENE_MARK = re.compile(r'^\s*(?:\*\s*){3,}$|^\s*([★☆◆◇■□●○#=~\-_·•])(?:\s*\1){2,}\s*$')
SENTENCE_END = re.compile(r'(?<=[.!?…])["”’»)]*\s+')


# Video encoding runs on the GPU (NVENC) by default; libx264 on the CPU is only the fallback when NVENC is unavailable.
NVENC = ['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '26', '-b:v', '0', '-maxrate', '8M', '-bufsize', '16M', '-profile:v', 'high']
X264 = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
_ENCODER = {}


def video_codec(ffmpeg):
    """NVENC when this FFmpeg and driver can actually encode with it (checked once per process)."""
    if ffmpeg not in _ENCODER:
        import subprocess
        try:
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:r=30:d=0.5', '-c:v', 'h264_nvenc', '-f', 'null', '-'],
                           check=True, timeout=30, capture_output=True)
            _ENCODER[ffmpeg] = NVENC
        except Exception:
            _ENCODER[ffmpeg] = X264
    return _ENCODER[ffmpeg]


def encode(pipeline, job, build, check, timeout, folder=None):
    """build(codec_args) -> FFmpeg argument list. Runs on NVENC; if that fails, retries once on the CPU and says so."""
    from .media import _run_in
    codec = video_codec(pipeline.ffmpeg)
    runner = (lambda args: _run_in(folder, args, check, timeout=timeout)) if folder else (lambda args: run(args, check, timeout=timeout))
    try:
        return runner(build(codec))
    except Exception as error:
        if codec is not NVENC or 'Cancelled' in type(error).__name__:
            raise
        _ENCODER[pipeline.ffmpeg] = X264
        if job:
            _log(pipeline, job, 'render', 'GPU (NVENC) không mã hoá được, chuyển sang CPU: ' + str(error)[-200:])
        return runner(build(X264))


def layout_for(orientation, user_layout=None):
    """The layout contract, with the game box the user dragged in the preview (if any). Captions follow the box:
    they sit just under the game, and on vertical video stay above the platforms' bottom overlay where possible."""
    layout = {**LAYOUTS[orientation]}
    box = ((user_layout or {}).get('game_box') or {}).get(orientation)
    if box:
        x, y, w = box
        h = int(round(w * 9 / 16 / 2) * 2)
        width, height = layout['size']
        layout['game'] = (x, y, w, h)
        lines = layout['caption_size'] * 2.5
        top = y + h + (24 if orientation == 'ngang' else 60)
        bottom = min(height - 20, top + lines)
        if orientation == 'doc' and bottom > 1440 and y + h + lines + 20 <= 1440:
            bottom = 1440
        layout['caption_bottom'] = int(max(20, height - bottom))
    return layout


def enabled(job):
    return (job.get('request') or {}).get('workflow_mode') == MODE


def _log(pipeline, job, stage, text):
    store = getattr(pipeline, 'store', None)
    if store:
        store.log(job['id'], stage, text)


def _write(path, value):
    path = Path(path)
    part = path.with_name(path.name + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=1) if not isinstance(value, str) else value, encoding='utf-8')
    part.replace(path)
    return path


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def _snapshot(job):
    return _read(Path(job['output']) / 'story-snapshot.json')


def episode_title(snapshot):
    chapters = snapshot['chapters']
    first = chapters[0]
    label = lambda c: f'Chương {c["number"] or c["order"]}'
    if len(chapters) == 1:
        return f'{label(first)}: {first["title"]}' if first['title'] and first['title'] != label(first) else label(first)
    return f'{label(first)}–{chapters[-1]["number"] or chapters[-1]["order"]}'


def preflight_for_request(status, pipeline, request):
    """Story needs only FFmpeg, the speech engine and its own inputs; ChatGPT/Flow/Comfy/OAuth checks do not apply."""
    if request.get('workflow_mode') != MODE:
        return status
    keep = ('ffmpeg', 'speech', 'voice_inventory')
    checks = [c if c['name'] in keep else {**c, 'ok': True, 'detail': 'Không dùng cho Kể truyện (đọc truyện có sẵn + gameplay của bạn).'}
              for c in status['checks']]
    try:
        snapshot = StoryLibrary().snapshot(request.get('story_snapshot'))
        missing = [c['name'] for c in snapshot['gameplay'] if not Path(c['path']).is_file()]
        ok = bool(snapshot['gameplay']) and not missing
        detail = ('Có ' + str(len(snapshot['gameplay'])) + ' clip gameplay') if ok else (
            'Chưa có clip gameplay cho truyện này' if not snapshot['gameplay'] else 'Không thấy tệp gameplay: ' + ', '.join(missing))
        checks.append({'name': 'story_gameplay', 'ok': ok, 'detail': detail})
        free = shutil.disk_usage(pipeline.store.outputs if getattr(pipeline, 'store', None) else '.').free
        words = sum(len(c['text'].split()) for c in snapshot['chapters'])
        minutes = words / 4.2 / 60
        outputs = int(bool(snapshot['layout'].get('horizontal', True))) + int(bool(snapshot['layout'].get('vertical', True)))
        # Measured on a 1080p game recording: master about 45 MB/min, each output about 25 MB/min, plus working margin.
        need = int((300 + minutes * (45 + 25 * outputs + 5)) * 1024 * 1024)
        checks.append({'name': 'story_disk', 'ok': free > need, 'detail': f'Ổ lưu video còn trống {free / 2**30:.1f} GB, cần khoảng {need / 2**30:.1f} GB' + ('' if free > need else '. Giải phóng ổ hoặc đổi thư mục xuất trước khi chạy.')})
    except Exception as error:
        checks.append({'name': 'story_snapshot', 'ok': False, 'detail': 'Không đọc được nội dung truyện đã chốt: ' + str(error)[:200]})
    return {**status, 'checks': checks, 'ready': all(c['ok'] for c in checks)}


# --- plan / research / music ---------------------------------------------------------------------------------
def plan(pipeline, job, check):
    check()
    snapshot = StoryLibrary().snapshot(job['request']['story_snapshot'])
    path = _write(Path(job['output']) / 'story-snapshot.json', snapshot)
    title = episode_title(snapshot)
    _log(pipeline, job, 'plan', f'Đã chốt nội dung: {snapshot["book"]["title"]} · {title} ({len(snapshot["chapters"])} chương).')
    return {'title': f'{snapshot["book"]["title"]} · {title}', 'story': {'book': snapshot['book'], 'episode': title,
            'chapters': [{'id': c['id'], 'title': c['title'], 'revision': c['revision'], 'sha256': c['sha256']} for c in snapshot['chapters']]},
            'provided_text': True, 'assets': [asset(path)]}


def research(pipeline, job, check):
    check()
    return {'not_applicable': True, 'reason': 'Kể truyện đọc nguyên văn truyện bạn đã biên tập; không tìm nguồn hay kiểm chứng.', 'sources': [], 'assets': []}


def music(pipeline, job, check):
    check()
    return {'not_applicable': True, 'reason': 'Kể truyện v1 không thêm nhạc nền.', 'assets': []}


# --- script ----------------------------------------------------------------------------------------------------
def _spoken(line):
    """What the reader says: dialogue dashes and decoration go, words stay."""
    line = re.sub(r'^\s*[—–-]\s*', '', line)
    line = line.replace('***', ' ').strip()
    return re.sub(r'\s+', ' ', line)


def _groups(paragraph):
    sentences = [s.strip() for s in SENTENCE_END.split(paragraph) if s.strip()]
    pieces = []
    for sentence in sentences:
        if len(sentence) <= UNIT_CHARS + 80:
            pieces.append(sentence)
            continue
        # A very long sentence is read in clause-sized parts, never cut inside a word.
        part = ''
        for clause in re.split(r'(?<=[,;:])\s+', sentence):
            if part and len(part) + len(clause) + 1 > UNIT_CHARS:
                pieces.append(part)
                part = clause
            else:
                part = f'{part} {clause}'.strip()
        if part:
            pieces.append(part)
    units, current = [], ''
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > UNIT_CHARS:
            units.append(current)
            current = piece
        else:
            current = f'{current} {piece}'.strip()
    if current:
        units.append(current)
    return units


def build_units(snapshot):
    units = []

    def add(text, kind, chapter, pause):
        text = text.strip()
        if text:
            units.append({'id': f'u{len(units):05d}', 'text': text, 'kind': kind, 'chapter': chapter, 'pause': pause})

    for chapter_index, chapter in enumerate(snapshot['chapters']):
        if chapter['read_title']:
            label = f'Chương {chapter["number"] or chapter["order"]}'
            title = chapter['title'] if chapter['title'] and chapter['title'] != label else ''
            add(f'{label}. {title}.' if title else f'{label}.', 'title', chapter_index, PAUSE['title'])
        for line in chapter['text'].split('\n'):
            if SCENE_MARK.match(line):
                if units and units[-1]['chapter'] == chapter_index:
                    units[-1]['pause'] = max(units[-1]['pause'], PAUSE['scene'])
                continue
            spoken = _spoken(line)
            if not spoken:
                continue
            groups = _groups(spoken)
            for index, group in enumerate(groups):
                add(group, 'text', chapter_index, PAUSE['paragraph'] if index == len(groups) - 1 else 0.0)
        if units:
            units[-1]['pause'] = max(units[-1]['pause'], PAUSE['end'] if chapter_index < len(snapshot['chapters']) - 1 else .6)
    return units


def script(pipeline, job, check):
    check()
    snapshot = _snapshot(job)
    units = build_units(snapshot)
    if not units:
        from .core import PermanentError
        raise PermanentError('Chương không có chữ nào để đọc')
    path = _write(Path(job['output']) / 'story-units.json', units)
    _log(pipeline, job, 'script', f'Chia {len(units)} cụm đọc theo câu và đoạn (giữ nguyên chữ).')
    return {'narration': '\n'.join(u['text'] for u in units), 'units': len(units), 'provided_text': True,
            'scenes': [], 'assets': [asset(path)]}


# --- speech ----------------------------------------------------------------------------------------------------
def _wav_info(path):
    with wave.open(str(path), 'rb') as source:
        return source.getframerate(), source.getnframes(), source.getnchannels(), source.getsampwidth()


def speech(pipeline, job, check):
    from .core import PermanentError, digest
    from .speech_engine import create_speech_job, prepare_reference, speech_identity, _trailing_silence
    from .speech_worker import SpeechJob
    check()
    request = job['request']
    voice = pipeline.voices.selected(request['voice_id'])
    if request.get('speech_engine') == 'khanhtts':
        prepare_reference(pipeline, voice, request, check)
    units = _read(Path(job['output']) / 'story-units.json')
    folder = Path(job['output']) / 'story-speech'
    folder.mkdir(exist_ok=True)
    cache = StoryLibrary().root / 'tts-cache'
    cache.mkdir(exist_ok=True)
    rhythm = request.get('speech_rhythm', 'natural')
    for unit in units:
        unit['identity'] = speech_identity(unit['text'], voice, request, pipeline)
        unit['raw'] = str(folder / f'{unit["id"]}.raw.wav')
    # Reuse: this job's own receipts first, then the shared cache of earlier episodes (same text + voice + settings).
    missing = []
    for unit in units:
        raw, receipt = Path(unit['raw']), Path(unit['raw']).with_suffix('.json')
        if raw.is_file() and receipt.is_file() and _read(receipt).get('identity') == unit['identity'] and _read(receipt).get('sha256') == digest(raw):
            continue
        cached = cache / f'{unit["identity"]}.wav'
        if cached.is_file() and cached.stat().st_size > 1000:
            shutil.copyfile(cached, raw)
            _write(receipt, {'identity': unit['identity'], 'sha256': digest(raw)})
            continue
        missing.append(unit)
    if missing:
        _log(pipeline, job, 'speech', f'Tạo lời đọc: {len(missing)}/{len(units)} cụm cần đọc mới (còn lại dùng lại bản đã có).')
        with create_speech_job(pipeline, voice, request, check, worker_factory=SpeechJob) as worker:
            size = max(1, min(512, getattr(worker, 'batch_size', 1) or 1))
            done = 0
            for start in range(0, len(missing), size):
                check()
                group = missing[start:start + size]

                def completed(position, group=group):
                    unit = group[position]
                    raw = Path(unit['raw'])
                    _write(raw.with_suffix('.json'), {'identity': unit['identity'], 'sha256': digest(raw)})
                    target = cache / f'{unit["identity"]}.wav'
                    if not target.is_file():
                        part = target.with_name(target.name + '.part')
                        shutil.copyfile(raw, part)
                        part.replace(target)

                worker.write_lines([u['text'] for u in group], [Path(u['raw']) for u in group], on_complete=completed)
                done += len(group)
                _log(pipeline, job, 'speech', f'Đã đọc {done}/{len(missing)} cụm.')
    # Pauses: measure the silence the engine (and story rhythm) already left, then add only what is missing.
    ledger, cursor, rate = [], 0.0, None
    parts = []
    for unit in units:
        check()
        raw = Path(unit['raw'])
        if not raw.is_file():
            raise PermanentError(f'Thiếu âm thanh của cụm {unit["id"]}: {unit["text"][:60]}')
        sample_rate, frames, channels, width = _wav_info(raw)
        if width != 2:
            raise PermanentError('Âm thanh lời đọc cần PCM 16-bit')
        rate = rate or sample_rate
        if sample_rate != rate:
            raise PermanentError('Các cụm lời đọc có tần số mẫu khác nhau')
        duration = frames / sample_rate
        trailing = _trailing_silence(raw)
        base = 0.0
        if rhythm == 'story':
            from .speech_engine import boundary_pause
            base = boundary_pause(unit['text'])
        target = max(base, unit['pause'])
        pad = max(0.0, target - trailing)
        speech_end = cursor + max(0.05, duration - trailing)
        ledger.append({'id': unit['id'], 'text': unit['text'], 'kind': unit['kind'], 'chapter': unit['chapter'], 'path': str(raw),
                       'sha256': digest(raw), 'sample_rate': sample_rate, 'samples': frames, 'start': round(cursor, 4),
                       'speech_end': round(speech_end, 4), 'end': round(cursor + duration + pad, 4), 'pause_added': round(pad, 4),
                       'trailing_silence': round(trailing, 4), 'channels': channels})
        parts.append((raw, pad, channels))
        cursor += duration + pad
    # One PCM file: units back to back, with generated silence where a pause was missing.
    narration = Path(job['output']) / 'story-narration.wav'
    with wave.open(str(narration) + '.part', 'wb') as out:
        out.setnchannels(parts[0][2])
        out.setsampwidth(2)
        out.setframerate(rate)
        for raw, pad, channels in parts:
            with wave.open(str(raw), 'rb') as source:
                if source.getnchannels() != parts[0][2]:
                    raise PermanentError('Các cụm lời đọc có số kênh khác nhau')
                out.writeframes(source.readframes(source.getnframes()))
            if pad:
                out.writeframes(b'\x00\x00' * channels * int(round(pad * rate)))
    Path(str(narration) + '.part').replace(narration)
    ledger_path = _write(Path(job['output']) / 'story-ledger.json', ledger)
    total = cursor
    _log(pipeline, job, 'speech', f'Lời đọc dài {int(total // 60)} phút {int(total % 60)} giây.')
    return {'path': str(narration), 'duration_seconds': total, 'utterances': len(ledger), 'ledger': str(ledger_path),
            'voice_id': request['voice_id'], 'assets': [asset(narration), asset(ledger_path)]}


# --- subtitles -------------------------------------------------------------------------------------------------
def _wrap(text, width, lines=2):
    """Display cues: at most `lines` lines of about `width` characters. Words are never split or changed."""
    words = text.split()
    cues, rows, row = [], [], ''
    for word in words:
        if row and len(row) + 1 + len(word) > width:
            rows.append(row)
            row = word
            if len(rows) == lines:
                cues.append(rows)
                rows = []
        else:
            row = f'{row} {word}'.strip()
    if row:
        rows.append(row)
    if rows:
        cues.append(rows)
    return cues


def caption_cues(ledger, width):
    cues = []
    for unit in ledger:
        if unit['kind'] == 'title':
            continue
        groups = _wrap(unit['text'], width)
        total = sum(len(' '.join(g)) for g in groups) or 1
        start, span = unit['start'], max(.3, unit['speech_end'] - unit['start'])
        for group in groups:
            share = span * len(' '.join(group)) / total
            cues.append({'start': start, 'end': start + share, 'lines': group})
            start += share
        cues[-1]['end'] = min(unit['end'], cues[-1]['end'] + min(.4, unit['end'] - unit['speech_end']))
    return cues


def _srt_time(value):
    value = max(0.0, value)
    ms = int(round(value * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def _ass_time(value):
    cs = int(round(max(0.0, value) * 100))
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def _ass_text(text):
    return str(text).replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', ' ')


def write_srt(cues, path):
    rows = [f'{index}\n{_srt_time(c["start"])} --> {_srt_time(c["end"])}\n' + '\n'.join(c['lines']) + '\n' for index, c in enumerate(cues, 1)]
    Path(path).write_text('\n'.join(rows), encoding='utf-8')
    return Path(path)


def subtitles(pipeline, job, check):
    check()
    ledger = _read(Path(job['output']) / 'story-ledger.json')
    result, assets = {'cues': {}}, []
    for orientation, layout in LAYOUTS.items():
        cues = caption_cues(ledger, layout['line_chars'])
        _write(Path(job['output']) / f'story-cues-{orientation}.json', cues)
        srt = write_srt(cues, Path(job['output']) / f'story-{orientation}.srt')
        result['cues'][orientation] = len(cues)
        result[f'srt_{orientation}'] = str(srt)
        assets.append(asset(srt))
    result['srt_path'] = result['srt_ngang']
    result['timing_policy'] = 'measured_utterance_split_by_characters'
    result['assets'] = assets
    return result


# --- gameplay (the "images" stage) -------------------------------------------------------------------------------
def cut_plan(clips, cursor, seconds):
    """Deterministic: walk the playlist from the cursor, take whole usable spans, loop when the pool ends."""
    usable = [c for c in clips if c['end'] - c['start'] >= 1]
    if not usable:
        raise ValueError('Chưa có đoạn gameplay dùng được')
    index = min(int(cursor.get('clip', 0)), len(usable) - 1)
    position = usable[index]['start'] + max(0.0, float(cursor.get('offset', 0.0)))
    if position >= usable[index]['end'] - .5:
        index, position = (index + 1) % len(usable), None
    segments, remaining, guard, loops = [], seconds, 0, 0
    while remaining > .01:
        clip = usable[index]
        start = clip['start'] if position is None else position
        length = min(remaining, clip['end'] - start)
        if length >= .2:
            segments.append({'clip': index, 'id': clip['id'], 'sha256': clip['sha256'], 'path': clip['path'], 'name': clip['name'],
                             'start': round(start, 3), 'length': round(length, 3), 'has_audio': clip.get('has_audio', False)})
            remaining -= length
        end_offset = start + length
        if remaining > .01 or end_offset >= clip['end'] - .5:
            index, position = (index + 1) % len(usable), None
            loops += index == 0
        else:
            position = end_offset
        guard += 1
        if guard > 10000:
            raise ValueError('Kế hoạch gameplay không hội tụ')
    next_cursor = {'clip': index, 'offset': 0.0 if position is None else round(position - usable[index]['start'], 3)}
    return segments, next_cursor, loops


def images(pipeline, job, check):
    from .core import PermanentError
    check()
    snapshot = _snapshot(job)
    speech_seconds = float(job['checkpoints']['speech']['duration_seconds'])
    seconds = speech_seconds + .5
    folder = Path(job['output']) / 'story-gameplay'
    folder.mkdir(exist_ok=True)
    plan_path = folder / 'plan.json'
    library = StoryLibrary()
    book_id = snapshot['book']['id']
    layout = snapshot['layout']
    if plan_path.is_file():
        plan_data = _read(plan_path)  # frozen on retry: never consumes the cursor twice
    else:
        missing = [c['name'] for c in snapshot['gameplay'] if not Path(c['path']).is_file()]
        if missing:
            raise PermanentError('Không thấy tệp gameplay: ' + ', '.join(missing) + '. Nạp lại clip trong Kể truyện → Gameplay rồi thử lại; lời đọc đã có được giữ nguyên.')
        cursor = library.cursor(book_id) if layout.get('continue_gameplay', True) else {'clip': 0, 'offset': 0.0}
        try:
            segments, next_cursor, loops = cut_plan(snapshot['gameplay'], cursor, seconds)
        except ValueError as error:
            raise PermanentError(str(error) + '. Thêm clip gameplay cho truyện rồi thử lại.')
        plan_data = {'algorithm': ALGORITHM, 'seconds': seconds, 'cursor_before': cursor, 'cursor_after': next_cursor,
                     'loops': loops, 'segments': segments, 'game_audio': bool(layout.get('game_audio'))}
        _write(plan_path, plan_data)
        if layout.get('continue_gameplay', True):
            library.advance_cursor(book_id, next_cursor['clip'], next_cursor['offset'], job['id'])
    master = build_master(pipeline, job, plan_path, check)
    _log(pipeline, job, 'images', f'Gameplay: {len(plan_data["segments"])} đoạn, {int(seconds // 60)} phút {int(seconds % 60)} giây'
         + (f', lặp lại danh sách {plan_data["loops"]} lần.' if plan_data['loops'] else '.'))
    # The master is a rebuildable cache (from the frozen plan), so it is not an attested asset: it may be removed to
    # save disk after the videos are published, and render rebuilds it if a later re-render needs it.
    return {'gameplay_plan': str(plan_path), 'master': str(master), 'segments': len(plan_data['segments']), 'seconds': seconds,
            'scenes': [], 'assets': [asset(plan_path)]}


def build_master(pipeline, job, plan_path, check):
    """One gameplay clip without text for the whole narration, from the frozen plan. Segment files are deleted as soon
    as they are joined, so the job folder never holds the same footage twice."""
    from .core import PermanentError
    plan_data = _read(plan_path)
    folder = Path(plan_path).parent
    master, receipt = folder / 'master.mp4', folder / 'master.json'
    identity = _identity({'algorithm': ALGORITHM, 'plan': plan_data, 'fps': FPS})
    if master.is_file() and receipt.is_file() and _read(receipt).get('identity') == identity:
        return master
    game_audio = plan_data['game_audio']
    parts = []
    for index, segment in enumerate(plan_data['segments']):
        check()
        part_identity = _identity({'algorithm': ALGORITHM, 'segment': segment, 'fps': FPS, 'audio': game_audio})
        target = folder / f'seg-{index:03d}.mp4'
        part_receipt = target.with_suffix('.json')
        if not (target.is_file() and part_receipt.is_file() and _read(part_receipt).get('identity') == part_identity):
            if not Path(segment['path']).is_file():
                raise PermanentError(f'Không thấy tệp gameplay {segment["name"]}. Nạp lại clip rồi thử lại; lời đọc đã có được giữ nguyên.')
            _log(pipeline, job, 'images', f'Chuẩn bị gameplay: đoạn {index + 1}/{len(plan_data["segments"])} ({segment["name"]}).')
            args = [pipeline.ffmpeg, '-v', 'error', '-y', '-ss', f'{segment["start"]:.3f}', '-t', f'{segment["length"]:.3f}', '-i', segment['path']]
            video = (f'fps={FPS},scale=1920:1080:force_original_aspect_ratio=decrease,'
                     'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x101827,setsar=1,format=yuv420p')
            if game_audio:
                if not segment['has_audio']:
                    args += ['-f', 'lavfi', '-t', f'{segment["length"]:.3f}', '-i', 'anullsrc=r=48000:cl=stereo']
                args += ['-filter_complex', f'[0:v]{video}[v]', '-map', '[v]', '-map', '0:a:0' if segment['has_audio'] else '1:a:0',
                         '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-b:a', '128k']
            else:
                args += ['-vf', video, '-an']
            args += ['-t', f'{segment["length"]:.3f}', '-r', str(FPS)]
            encode(pipeline, job, lambda codec, args=args: args + codec + ['-pix_fmt', 'yuv420p', str(target)], check, timeout=max(600, segment['length'] * 3))
            _write(part_receipt, {'identity': part_identity})
        parts.append(target)
    listing = folder / 'concat.txt'
    listing.write_text('\n'.join(f"file '{p.name}'" for p in parts), encoding='utf-8')
    run([pipeline.ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(master)], check,
        timeout=max(600, float(plan_data['seconds'])))
    _write(receipt, {'identity': identity})
    for part in parts:
        part.unlink(missing_ok=True)
        part.with_suffix('.json').unlink(missing_ok=True)
    return master


# --- render ----------------------------------------------------------------------------------------------------
def _ass_header(width, height, styles):
    head = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n'
            '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
            'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n')
    return head + ''.join('Style: ' + s + '\n' for s in styles) + '\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'


def _fit(text, size, room):
    """Shrink a title that would not fit on its line(s); never cut letters."""
    length = max(1, len(text))
    return max(int(size * .55), min(size, int(size * room / length))) if length > room else size


def write_ass(path, orientation, snapshot, cues, burn):
    layout = layout_for(orientation, snapshot.get('layout'))
    width, height = layout['size']
    margin = layout['title_margin']
    room = {'ngang': 52, 'doc': 22}[orientation]
    channel = (snapshot['layout'].get('channel') or '').upper()
    book = snapshot['book']['title'].upper()
    chapter = episode_title(snapshot)
    t = layout['title']
    styles = [
        f'Channel,Arial,{t["channel"][1]},&H00EFC979,&H00EFC979,&H00101010,&H00000000,1,0,0,0,100,100,2,0,1,2,0,8,{margin},{margin},0,1',
        f'Book,Arial,{_fit(book, t["book"][1], room * (2 if orientation == "doc" else 1))},&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,1,0,0,0,100,100,0,0,1,3,1,8,{margin},{margin},0,1',
        f'Chapter,Arial,{_fit(chapter, t["chapter"][1], int(room * 1.4))},&H00F0E8E0,&H00F0E8E0,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,{margin},{margin},0,1',
        f'Caption,Arial,{layout["caption_size"]},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,'
        f'{layout["caption_margin"]},{layout["caption_margin"]},{layout["caption_bottom"]},1',
    ]
    end = _ass_time(max(c['end'] for c in cues) + 2 if cues else 36000)
    x = width // 2
    events = []
    if channel:
        events.append(f'Dialogue: 1,0:00:00.00,{end},Channel,,0,0,0,,{{\\pos({x},{t["channel"][0]})}}{_ass_text(channel)}')
    events.append(f'Dialogue: 1,0:00:00.00,{end},Book,,0,0,0,,{{\\pos({x},{t["book"][0]})}}{_ass_text(book)}')
    events.append(f'Dialogue: 1,0:00:00.00,{end},Chapter,,0,0,0,,{{\\pos({x},{t["chapter"][0]})}}{_ass_text(chapter)}')
    if burn:
        for cue in cues:
            events.append(f'Dialogue: 0,{_ass_time(cue["start"])},{_ass_time(cue["end"])},Caption,,0,0,0,,' + '\\N'.join(_ass_text(l) for l in cue['lines']))
    Path(path).write_text(_ass_header(width, height, styles) + '\n'.join(events) + '\n', encoding='utf-8')
    return Path(path)


def _background_input(snapshot, width, height, seconds, folder=None, ffmpeg='ffmpeg'):
    """The background is prepared once (one frame) and repeated by the loop filter, not decoded/converted per frame."""
    tail = f'format=yuv420p,loop=loop=-1:size=1:start=0,fps={FPS},setsar=1[bg]'
    image = snapshot.get('background')
    if image and Path(image).is_file():
        return ['-i', image], f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},{tail}'
    preset = snapshot.get('background_preset') or {'top': '0x0b1a33', 'bottom': '0x1d3b63'}
    folder = Path(folder or StoryLibrary().root / 'previews')
    still = folder / f'bg-{preset["top"][2:]}-{preset["bottom"][2:]}-{width}x{height}.png'
    if not still.is_file():
        run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
             f'gradients=s={width}x{height}:c0={preset["top"]}:c1={preset["bottom"]}:x0=0:y0=0:x1=0:y1={height}:d=0.04:speed=0.0001',
             '-frames:v', '1', str(still)], lambda: None, timeout=60)
    return ['-i', str(still)], f'[0:v]{tail}'


def compose(pipeline, job, orientation, snapshot, master, audio, cues, seconds, check, game_audio=False):
    layout = layout_for(orientation, snapshot.get('layout'))
    width, height = layout['size']
    gx, gy, gw, gh = layout['game']
    folder = Path(job['output'])
    ass = write_ass(folder / f'story-{orientation}.ass', orientation, snapshot, cues, snapshot['layout'].get('burn_subtitles', True))
    target = folder / f'story-out-{orientation}.mp4'
    identity = _identity({'algorithm': ALGORITHM, 'orientation': orientation, 'layout': layout, 'master': _file_id(master),
                          'audio': _file_id(audio), 'ass': hashlib.sha256(ass.read_bytes()).hexdigest(), 'game_audio': game_audio,
                          'background': snapshot.get('background') and _file_id(snapshot['background']), 'preset': snapshot.get('background_preset')})
    receipt = target.with_suffix('.json')
    if target.is_file() and receipt.is_file() and _read(receipt).get('identity') == identity:
        return target
    background, bg_filter = _background_input(snapshot, width, height, seconds, folder, pipeline.ffmpeg)
    inputs = background + ['-i', str(master), '-i', str(audio)]
    graph = (f'{bg_filter};[1:v]scale={gw}:{gh}:force_original_aspect_ratio=decrease:flags=bilinear,setsar=1,format=yuv420p[g];'
             f'[bg][g]overlay=x={gx}+({gw}-w)/2:y={gy}+({gh}-h)/2:eof_action=repeat:format=yuv420,ass={ass.name}[v]')
    audio_args = ['-map', '2:a:0', '-c:a', 'copy']
    if game_audio:
        graph += ';[1:a]volume=0.15[game];[2:a][game]amix=inputs=2:duration=first:dropout_transition=0[a]'
        audio_args = ['-map', '[a]', '-c:a', 'aac', '-b:a', '192k']
    head = [pipeline.ffmpeg, '-v', 'error', '-y', *inputs, '-filter_complex', graph, '-map', '[v]', *audio_args, '-t', f'{seconds:.3f}', '-r', str(FPS)]
    _log(pipeline, job, 'render', f'Dựng bản {"ngang 1920×1080" if orientation == "ngang" else "dọc 1080×1920"} bằng GPU…')
    encode(pipeline, job, lambda codec: head + codec + ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', target.name], check,
           timeout=max(900, seconds * 4), folder=folder)
    _write(receipt, {'identity': identity})
    return target


def _file_id(path):
    stat = Path(path).stat()
    return f'{Path(path).name}:{stat.st_size}:{stat.st_mtime_ns}'


def _stem(job, snapshot):
    record = Path(job['output']) / 'story-video-name.txt'
    if record.is_file() and record.read_text(encoding='utf-8').strip():
        return record.read_text(encoding='utf-8').strip()
    chapters = snapshot['chapters']
    first, last = chapters[0], chapters[-1]
    number = lambda c: int(c['number'] or c['order'])
    base = f'chuong-{number(first):03d}' + (f'-{number(last):03d}' if len(chapters) > 1 else '')
    if len(chapters) == 1 and first['title']:
        base += '-' + slug(first['title'], 40)
    root = _root(job)
    version = 1
    while any(root.glob(f'{base}-v{version}[._]*')):
        version += 1
    stem = f'{base}-v{version}'
    record.write_text(stem, encoding='utf-8')
    return stem


def _root(job):
    output = Path(job['output'])
    return output.parent.parent if output.name == job['id'] and output.parent.name == 'data' else output


def render(pipeline, job, check):
    from .core import PermanentError
    check()
    snapshot = _snapshot(job)
    layout = snapshot['layout']
    wanted = [o for o, flag in (('ngang', layout.get('horizontal', True)), ('doc', layout.get('vertical', True))) if flag]
    if not wanted:
        raise PermanentError('Chưa chọn định dạng xuất (ngang hoặc dọc)')
    folder = Path(job['output'])
    narration = Path(job['checkpoints']['speech']['path'])
    seconds = float(job['checkpoints']['speech']['duration_seconds'])
    master = Path(job['checkpoints']['images']['master'])
    if not master.is_file():
        master = build_master(pipeline, job, Path(job['checkpoints']['images']['gameplay_plan']), check)
    # Narration is levelled once (speech loudness about -16 LUFS) and encoded once; both videos copy it.
    levelled = folder / 'story-narration.m4a'
    if not levelled.is_file() or levelled.stat().st_mtime < narration.stat().st_mtime:
        run([pipeline.ffmpeg, '-v', 'error', '-y', '-i', str(narration), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000',
             '-c:a', 'aac', '-b:a', '192k', str(levelled)], check, timeout=max(600, seconds))
    # One after the other: measured on a 1080p chapter, running both at once was not faster (the CPU-side overlay is the limit).
    outputs = {}
    for orientation in wanted:
        cues_path = folder / f'story-cues-{orientation}.json'
        if not cues_path.is_file():  # removed by tidy(); rebuilt from the timing ledger
            _write(cues_path, caption_cues(_read(folder / 'story-ledger.json'), LAYOUTS[orientation]['line_chars']))
        cues = _read(cues_path)
        outputs[orientation] = compose(pipeline, job, orientation, snapshot, master, levelled, cues, seconds, check,
                                       game_audio=bool(layout.get('game_audio')))
    # Publish beside each other in the book's folder: <stem>_ngang.mp4, <stem>_doc.mp4, <stem>.mp3, <stem>_<o>.srt
    root, stem = _root(job), _stem(job, snapshot)
    published, files = {}, []
    for orientation, source in outputs.items():
        target = root / f'{stem}_{orientation}.mp4'
        # Same drive: a move, never a second copy of a long video.
        source.replace(target)
        source.with_suffix('.json').unlink(missing_ok=True)
        published[orientation] = str(target)
        files.append(target)
        if layout.get('export_srt', True):
            srt = root / f'{stem}_{orientation}.srt'
            shutil.copyfile(job['checkpoints']['subtitles'][f'srt_{orientation}'], srt)
            published[f'srt_{orientation}'] = str(srt)
            files.append(srt)
    if layout.get('export_mp3', True):
        mp3 = root / f'{stem}.mp3'
        run([pipeline.ffmpeg, '-v', 'error', '-y', '-i', str(narration), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
             '-ar', '44100', '-c:a', 'libmp3lame', '-q:a', '2', str(mp3)], check, timeout=max(600, seconds))
        published['mp3'] = str(mp3)
        files.append(mp3)
    primary = published.get('doc') or published['ngang']
    result = {'video': primary, 'story_outputs': published, 'story_files': [str(f) for f in files],
              'orientation': 'both' if len(wanted) == 2 else wanted[0], 'duration_seconds': seconds, 'renderer': 'story-v1',
              'assets': [asset(f) for f in files]}
    if 'ngang' in published:
        result['video_ngang'] = published['ngang']
    return result


def verify(pipeline, job, check):
    from .core import PermanentError
    from .media import verify as verify_video
    check()
    render_cp = job['checkpoints']['render']
    seconds = float(job['checkpoints']['speech']['duration_seconds'])
    assets = []
    for orientation, size in (('ngang', (1920, 1080)), ('doc', (1080, 1920))):
        path = render_cp['story_outputs'].get(orientation)
        if not path:
            continue
        try:
            assets += verify_video(path, seconds, pipeline.ffprobe, size=size)['assets']
        except Exception as error:
            raise PermanentError(f'Bản {orientation} chưa đạt: {error}')
    for key in ('mp3', 'srt_ngang', 'srt_doc'):
        path = render_cp['story_outputs'].get(key)
        if path:
            if not Path(path).is_file() or Path(path).stat().st_size == 0:
                raise PermanentError(f'Thiếu tệp {Path(path).name}')
            assets.append(asset(path))
    freed = tidy(job)
    _log(pipeline, job, 'verify', 'Đã kiểm tra: ' + ', '.join(Path(p).name for p in render_cp['story_files'])
         + (f'. Dọn {freed / 2**20:.0f} MB tệp tạm.' if freed else ''))
    return {'verified': True, 'duration_seconds': seconds, 'orientation': render_cp.get('orientation'), 'assets': assets}


def tidy(job):
    """After every requested output is verified, keep only what is small and useful: the frozen snapshot, reading
    units, timing ledger, narration WAV, gameplay plan, subtitles and stage records. Per-sentence WAVs (also kept in
    the shared TTS cache), the gameplay master, encoded audio and render scratch are removed. Attested checkpoint
    files are never touched. Returns the number of bytes freed."""
    folder = Path(job['output'])
    attested = {str(Path(a['path']).resolve()) for cp in job.get('checkpoints', {}).values() if isinstance(cp, dict)
                for a in cp.get('assets', []) if isinstance(a, dict) and a.get('path')}
    victims = [*(folder / 'story-speech').glob('*'), *(folder / 'story-gameplay').glob('seg-*'), folder / 'story-gameplay' / 'master.mp4',
               folder / 'story-gameplay' / 'master.json', folder / 'story-gameplay' / 'concat.txt', folder / 'story-narration.m4a',
               *folder.glob('story-*.ass'), *folder.glob('story-cues-*.json'), *folder.glob('story-out-*'), *folder.glob('*.part')]
    freed = 0
    for path in victims:
        try:
            if path.is_file() and str(path.resolve()) not in attested:
                size = path.stat().st_size
                path.unlink()
                freed += size
        except OSError:
            continue
    try:
        (folder / 'story-speech').rmdir()
    except OSError:
        pass
    return freed
