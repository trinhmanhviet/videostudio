"""Captions from independently synthesized utterances and measured WAV durations.
No ASR transcription or fabricated word alignment: one cue per utterance.
"""
import re,unicodedata
from pathlib import Path

def wrap_caption(text,max_columns=32,max_lines=3):
    text=unicodedata.normalize('NFC',text).strip()
    if not text or '-->' in text or '<' in text or '{' in text:raise ValueError('Unsafe/empty caption')
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
    return {'cue_count':len(rows),'timing_policy':'measured_independent_utterance','max_columns':32,'max_lines':3}
