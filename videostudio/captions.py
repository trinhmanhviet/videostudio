"""Captions from independently synthesized utterances and measured WAV durations.
No ASR transcription or fabricated word alignment: one cue per utterance.
"""
import re,unicodedata
from pathlib import Path

# Bottom-aligned text stays above the lower 30% used by Shorts/Reels overlays.
SUBTITLE_BOTTOM_MARGIN = 576

def wrap_caption(text,max_columns=32,max_lines=3):
    text=unicodedata.normalize('NFC',text).strip()
    if not text or '-->' in text or '<' in text or '{' in text or '}' in text or '\\' in text:raise ValueError('Unsafe/empty caption')
    words=text.split();lines=[];line=''
    for word in words:
        if len(word)>max_columns:raise ValueError('Caption token exceeds safe width')
        if line and len(line)+1+len(word)>max_columns:lines.append(line);line=word
        else:line=(line+' '+word).strip()
    if line:lines.append(line)
    if len(lines)>max_lines:raise ValueError('Utterance exceeds safe caption area; split narration upstream')
    return '\n'.join(lines)

# Each chunk becomes one separately voiced utterance, so a break is also an audible pause.
# Never cut greedily mid-phrase ("... đầy nghi" | "vấn."): prefer punctuation, then a connector word,
# then the most balanced split, and never leave a fragment under MIN_CHUNK_WORDS words.
_BREAK_AFTER = (',', ';', ':', '—', '–', '…')
_CONNECTORS = {'và', 'nhưng', 'bởi', 'vì', 'khi', 'rồi', 'mà', 'thì', 'để', 'nên', 'hoặc', 'nếu', 'rằng',
               'song', 'còn', 'tuy', 'dù', 'mặc', 'trong', 'sau', 'trước', 'cho', 'tại', 'do', 'với'}
# Words that usually open a phrase and are rarely the second syllable of a compound word.
_PHRASE_START = {'đã', 'đang', 'sẽ', 'bị', 'được', 'không', 'chưa', 'cũng', 'vẫn', 'đều', 'những', 'các', 'khiến',
                 'theo', 'từ', 'ở', 'về', 'như', 'chỉ', 'lại', 'liền', 'bỗng', 'ngay', 'luôn'}
MIN_CHUNK_WORDS = 4


def _fits(words):
    try:
        wrap_caption(' '.join(words))
        return True
    except ValueError as error:
        if str(error) != 'Utterance exceeds safe caption area; split narration upstream':
            raise
        return False


def split_caption_text(text):
    """Split one oversized sentence into caption-safe chunks at natural breaks (order-preserving)."""
    words = unicodedata.normalize('NFC', text or '').split()
    if not words:
        return []
    if _fits(words):
        return [' '.join(words)]
    total = len(' '.join(words))
    best = None
    for i in range(1, len(words)):
        left, right = words[:i], words[i:]
        if not _fits(left):
            break                                   # the left part only grows from here
        left_len = len(' '.join(left))
        score = abs(left_len - (total - left_len - 1)) / total
        head = right[0].lower().strip('"“‘(')
        if left[-1].endswith(_BREAK_AFTER):
            score += 0.0
        elif head in _CONNECTORS:
            score += 0.1
        elif head in _PHRASE_START:
            score += 0.15
        else:
            score += 0.6                            # plain break may split a compound word: last resort
        if len(left) < MIN_CHUNK_WORDS or len(right) < MIN_CHUNK_WORDS:
            score += 1.0
        if best is None or score < best[0]:
            best = (score, i)
    if best is None:                                # even the first word is too wide
        wrap_caption(words[0])
        raise ValueError('Utterance exceeds safe caption area; split narration upstream')
    i = best[1]
    return [' '.join(words[:i])] + split_caption_text(' '.join(words[i:]))


def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def split_caption_scenes(scenes):
    """Split oversized narration locally, preserving words and visual metadata."""
    result=[]
    for scene in scenes:
        chunks=split_caption_text(scene.get('narration',''))
        if not chunks:wrap_caption('')
        for index,text in enumerate(chunks):
            item={**scene,'narration':text}
            if len(chunks)>1 and 'scene_id' in item:item['scene_id']=f"{item['scene_id']}-part-{index+1}"
            result.append(item)
    return result

def write_captions(utterances,path):
    rows=[];end=0
    for i,u in enumerate(utterances,1):
        start=float(u['start']);stop=float(u['end'])
        if start<end-.0001 or stop<=start:raise ValueError('Overlapping/empty caption cue')
        wrapped=wrap_caption(u['narration'])
        if re.sub(r'\s+',' ',wrapped)!=re.sub(r'\s+',' ',unicodedata.normalize('NFC',u['narration']).strip()):raise ValueError('Caption text mismatch')
        rows.append(f'{i}\n{stamp(start)} --> {stamp(stop)}\n{wrapped}\n');end=stop
    if not rows:raise ValueError('No captions')
    Path(path).write_text('\n'.join(rows),encoding='utf-8')
    ass=Path(path).with_suffix('.ass')
    header=f'[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,{SUBTITLE_BOTTOM_MARGIN},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    def ass_stamp(value):
        cs=round(float(value)*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100);return f'{h}:{m:02}:{s:02}.{cs:02}'
    events=[]
    for u in utterances:
        caption=wrap_caption(u['narration']).replace('\n',r'\N')
        events.append(f"Dialogue: 0,{ass_stamp(u['start'])},{ass_stamp(u['end'])},Default,,0,0,0,,{caption}\n")
    ass.write_text(header+''.join(events),encoding='utf8')
    return {'cue_count':len(rows),'timing_policy':'measured_independent_utterance','max_columns':32,'max_lines':3,'ass_path':str(ass),'safe_margins_pixels':{'left':90,'right':90,'bottom':SUBTITLE_BOTTOM_MARGIN},'font_size_pixels':52}
