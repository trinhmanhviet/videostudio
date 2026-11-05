"""Write a long episode as resumable, bounded JSON replies with a fixed cast.

Only the writing is split. Speech/render still receive one ordinary episode.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .core import PermanentError, digest
from .media import asset
from .meme_animation_script import MemeScriptError, beat_range, build_prompt, to_checkpoint, validate
from .meme_pipeline import _log, _save

PART_BEATS = 20
SINGLE_BEATS = 36


def needs_parts(request):
    return beat_range(request.get('duration_seconds', 60))[2] > SINGLE_BEATS


def part_sizes(request):
    target = beat_range(request['duration_seconds'])[2]
    count = math.ceil(target / PART_BEATS)
    return [target // count + (i < target % count) for i in range(count)]


def _read(path):
    return json.loads(path.read_text(encoding='utf8'))


def _reply(pipeline, job, check, folder, name, prompt, normalize):
    """Keep raw/rejected replies and a validated receipt for every individual part."""
    final = folder / (name + '.json'); receipt = final.with_suffix('.receipt.json')
    import hashlib
    identity = hashlib.sha256(prompt.encode('utf8')).hexdigest()
    if final.is_file() and receipt.is_file():
        saved = _read(receipt)
        if saved.get('identity') == identity and saved.get('sha256') == digest(final):
            return _read(final)
    feedback = []; last = None
    for attempt in range(3):
        check(); raw_path = folder / f'{name}-{identity[:16]}-attempt-{attempt:02}.json'
        rejected = raw_path.with_suffix('.rejected.json')
        if raw_path.is_file() and rejected.is_file():
            saved = _read(rejected)
            if saved.get('sha256') == digest(raw_path):
                feedback = [saved['error']]; last = raw_path; continue
        try:
            if raw_path.is_file():
                raw = _read(raw_path)
            else:
                raw = pipeline.llm_json(prompt + ('\nSửa lỗi phần này: ' + '; '.join(feedback) if feedback else ''), check)
                _save(raw_path, raw)
            last = raw_path
            result = normalize(raw, False); break
        except (ValueError, MemeScriptError) as error:
            feedback = [str(error)[:1500]]
            if raw_path.is_file():
                _save(rejected, {'sha256': digest(raw_path), 'error': feedback[0]})
            _log(pipeline, job, 'script', f'Sửa cấu trúc {name}, giữ các phần đã xong (lượt {attempt+1}/3).')
    else:
        try:
            result = normalize(_read(last), True) if last else None
            if result is None:
                raise MemeScriptError('Không nhận được JSON')
        except (ValueError, OSError, TypeError) as error:
            raise PermanentError(f'Chưa hoàn tất {name}; đã giữ các phần trước để tiếp tục: {error}') from error
    _save(final, result); _save(receipt, {'identity': identity, 'sha256': digest(final)})
    return result


def write_parts(pipeline, job, check, catalog):
    request = job['request']; sizes = part_sizes(request); count = len(sizes)
    folder = Path(job['output']) / 'animation-parts'; folder.mkdir(parents=True, exist_ok=True)
    # A fully written script can survive a crash before the stage checkpoint commits.
    completed = Path(job['output']) / 'animation-script.json'
    if completed.is_file():
        normalized = validate(_read(completed), catalog, request)
        result = to_checkpoint(normalized, catalog.fingerprint())
        result['assets'] = [asset(completed)]
        return result
    outline_prompt = f'''[MEME_OUTLINE]
Lập dàn ý cho MỘT video meme dài {request['duration_seconds']} giây, chia {count} phần viết.
Đây chỉ là DÀN Ý NGẮN, không viết beats hoặc toàn bộ JSON kịch bản trong lượt này.
Giữ đầy đủ mạch truyện, các tình tiết quan trọng và câu chốt; không tự rút thành video ngắn.
Yêu cầu gốc: {json.dumps(request['idea'], ensure_ascii=False)}
Danh mục thật: {catalog.describe_for_prompt()}
Chỉ trả một object JSON: title/payoff mỗi trường là 2 dòng giật tít ngắn kiểu meme (mỗi dòng tối đa 4-5 từ hoặc 16 ký tự, IN HOA, ví dụ title: ["NGHỀ LÀM BỐ","HỌP PHỤ HUYNH THUÊ"], payoff: ["CON THUÊ BỐ GIẢ","TĂNG GIÁ GÓI VIP"], KHÔNG viết đoạn văn tóm tắt);
cast map ID -> {{name,costume,acc:[],face,voice}}; scenes map ID -> {{bg,cast:[1-3 ID vai]}};
parts là mảng ĐÚNG {count} object {{summary,ending}} theo diễn biến từ mở đầu đến kết,
mỗi summary nêu cụ thể tình tiết cần kể trong phần đó, ending nêu điểm nối hoặc câu chốt.
Dùng ID chữ ASCII/số/gạch dưới, bắt đầu bằng chữ hoặc gạch dưới. Không dùng N làm ID vai.
Trang phục/phụ kiện phân biệt các vai và cố định cả video. Giọng mọi vai: {json.dumps(request['voice_id'])}.
Phần cuối phải kể và kết thúc trọn câu chuyện. Không cần viết bất kỳ beat/thoại nào lúc lập dàn ý.'''

    def normalize_outline(raw, lenient):
        meta = validate(raw, catalog, request, lenient=lenient, metadata_only=True)
        parts = raw.get('parts')
        if not isinstance(parts, list) or len(parts) != count:
            raise MemeScriptError(f'parts cần đúng {count} phần dàn ý')
        clean = []
        for p in parts:
            if not isinstance(p, dict) or any(not isinstance(p.get(k), str) or not p[k].strip() for k in ('summary', 'ending')):
                raise MemeScriptError('Mỗi phần cần summary và ending không rỗng')
            clean.append({k: p[k].strip() for k in ('summary', 'ending')})
        return {**meta, 'parts': clean}

    _log(pipeline, job, 'script', f'Lập dàn ý chung cho {count} phần, giữ nguyên độ dài video.')
    outline = _reply(pipeline, job, check, folder, 'outline', outline_prompt, normalize_outline)
    meta = {k: v for k, v in outline.items() if k != 'parts'}; beats = []
    for index, target in enumerate(sizes):
        check(); number = index+1
        # Reuse engine rules without asking for the full episode or repeated cast JSON.
        part_request = {**request, 'duration_seconds': target*2.5}
        rules = build_prompt(part_request, catalog).split('Chỉ trả JSON, không markdown. Cấu trúc:')[0]
        prompt = f'''[MEME_PART {number}/{count}; target={target}]
{rules}
Dàn ý và tạo hình chung, KHÔNG thay đổi cast/scenes/title/payoff:
{json.dumps(outline, ensure_ascii=False)}
CHỈ VIẾT PHẦN {number}/{count}: {json.dumps(outline['parts'][index], ensure_ascii=False)}
Hai câu trước để nối mạch, không kể lại: {json.dumps([b['text'] for b in beats[-2:]], ensure_ascii=False)}
Viết {target-2}–{target+2} beats, mục tiêu {target}; không viết các phần khác.
{'Đây là phần cuối, phải có kết và câu chốt.' if number == count else 'Tiếp diễn mạch truyện, chưa kể trước kết của các phần sau.'}
Chỉ trả JSON {{"part":{number},"beats":[{{"scene":"ID cảnh đã có","who":"N hoặc ID vai",
"focus":"ID vai trong cảnh","text":"Câu ngắn tiếng Việt","emo":{{"ID vai":"ID mặt"}},"act":[],"punch":null}}]}}.
Không lặp lại cast/scenes, không tóm tắt hoặc từ chối vì độ dài toàn video: lượt này chỉ viết phần nhỏ hiện tại.'''

        def normalize_part(raw, lenient):
            if not isinstance(raw, dict) or type(raw.get('part')) is not int or raw['part'] != number:
                raise MemeScriptError(f'part phải là {number}')
            rows = raw.get('beats')
            if not isinstance(rows, list) or not target-2 <= len(rows) <= target+2:
                raise MemeScriptError(f'Phần {number} cần {target-2}–{target+2} beats')
            normalized = validate({**meta, 'beats': rows}, catalog, part_request, lenient=lenient)
            if len(normalized['beats']) < target-2:
                raise MemeScriptError('Phần còn thiếu lời kể, không thể tự bịa để bù')
            return {'part': number, 'beats': normalized['beats']}

        _log(pipeline, job, 'script', f'Viết kịch bản phần {number}/{count} ({target} câu); các phần xong đã được lưu.')
        part = _reply(pipeline, job, check, folder, f'part-{number:02}', prompt, normalize_part)
        beats.extend(part['beats'])
    normalized = validate({**meta, 'beats': beats}, catalog, request)
    _save(completed, normalized)
    result = to_checkpoint(normalized, catalog.fingerprint()); result['assets'] = [asset(completed)]
    _log(pipeline, job, 'script', f'Đã ghép {count} phần thành kịch bản {len(beats)} câu cho một video.')
    return result
