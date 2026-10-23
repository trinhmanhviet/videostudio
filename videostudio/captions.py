"""Captions from independently synthesized utterances and measured WAV durations.
No ASR transcription or fabricated word alignment: one cue per utterance.
"""
import re,unicodedata
from pathlib import Path

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

def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

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
    header='[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,130,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    def ass_stamp(value):
        cs=round(float(value)*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100);return f'{h}:{m:02}:{s:02}.{cs:02}'
    events=[]
    for u in utterances:
        caption=wrap_caption(u['narration']).replace('\n',r'\N')
        events.append(f"Dialogue: 0,{ass_stamp(u['start'])},{ass_stamp(u['end'])},Default,,0,0,0,,{caption}\n")
    ass.write_text(header+''.join(events),encoding='utf8')
    return {'cue_count':len(rows),'timing_policy':'measured_independent_utterance','max_columns':32,'max_lines':3,'ass_path':str(ass),'safe_margins_pixels':{'left':90,'right':90,'bottom':130},'font_size_pixels':52}
