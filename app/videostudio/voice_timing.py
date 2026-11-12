"""Read-only per-voice speaking rates from completed speech or paired previews.

No synthesis, model loading or remote calls are performed for an estimate. Rates
are Vietnamese whitespace-separated syllables at 1x playback, not word alignment.
"""
from __future__ import annotations

import json
import math
import statistics
import wave
from pathlib import Path

DEFAULT_RATE=4.2


def _object(value):
    if isinstance(value,dict):return value
    try:
        result=json.loads(value)
        return result if isinstance(result,dict) else {}
    except (ValueError,TypeError):return {}


def _positive(value):
    if isinstance(value,bool):return None
    try:number=float(value)
    except (TypeError,ValueError,OverflowError):return None
    return number if math.isfinite(number) and number>0 else None


def _reference_hash(record):
    direct=record.get('voice_sha256') or record.get('reference_sha256')
    if direct:return direct
    for field in ('voice','reference','voice_reference'):
        nested=record.get(field)
        if isinstance(nested,dict) and nested.get('sha256'):return nested['sha256']
    return None


def _same_voice(record,voice):
    # Imported clone IDs survive retirement, but an old job is not evidence for
    # a replacement reference with the same ID. Unknown clone histories fall
    # back to a preview with known matching text/reference instead.
    if record.get('voice_id') is not None and record['voice_id']!=voice['id']:return False
    reference=_reference_hash(record)
    if voice.get('kind')=='clone' or str(voice['id']).startswith('clone:'):
        return bool(voice.get('sha256') and reference==voice['sha256'])
    return not reference or not voice.get('sha256') or reference==voice['sha256']


def _rate(speech):
    utterances=speech.get('utterances')
    speed=_positive(speech.get('speed',1))
    if not isinstance(utterances,list) or not utterances or speed is None:return None
    if not .25<=speed<=4:return None
    words=seconds=0
    for utterance in utterances:
        if not isinstance(utterance,dict):return None
        text=utterance.get('narration')
        duration=_positive(utterance.get('duration'))
        if not isinstance(text,str) or not text.strip() or duration is None:return None
        words+=len(text.split());seconds+=duration
    rate=words/seconds/speed
    return rate if words>=5 and seconds>=1 and .5<=rate<=12 else None


def _preview_rate(voice):
    sample=voice.get('sample_path')
    if not isinstance(sample,str) or not sample:return None
    path=Path(sample)
    request=path.parent/'request.json'
    try:
        record=_object(request.read_text(encoding='utf-8-sig'))
        if voice.get('kind')=='clone' or str(voice['id']).startswith('clone:'):
            if not _same_voice(record,voice):return None
        elif record.get('voice_id')!=voice['id']:return None
        text=record.get('text')
        if not isinstance(text,str) or not text.strip():return None
        with wave.open(str(path),'rb') as wav:
            seconds=wav.getnframes()/wav.getframerate()
        return _rate({'utterances':[{'narration':text,'duration':seconds}],'speed':record.get('speed',1)})
    except (OSError,ValueError,ZeroDivisionError,wave.Error,EOFError):return None


def reading_profiles(store,voices):
    """Return {voice_id: profile}; inspect at most eight verified jobs per voice."""
    catalog={voice['id']:voice for voice in voices if isinstance(voice,dict) and isinstance(voice.get('id'),str)}
    rates={identifier:[] for identifier in catalog}
    if catalog:
        placeholders=','.join('?' for _ in catalog)
        # One bounded query for the whole catalog. CASE guards legacy malformed
        # JSON before SQLite evaluates json_extract; profile failures stay local.
        with store.db() as connection:
            retained=''
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_calibrations'").fetchone():
                retained=' UNION ALL SELECT voice_id,NULL AS speech,measured_at AS updated,rate AS measured_rate,voice_sha256 FROM voice_calibrations '
            rows=connection.execute(f'''
                WITH eligible AS (
                    SELECT CASE WHEN json_valid(j.request) THEN json_extract(j.request,'$.voice_id') END voice_id,
                           s.value speech,j.updated,NULL AS measured_rate,NULL AS voice_sha256
                    FROM jobs j JOIN checkpoints s ON s.job=j.id AND s.stage='speech'
                    JOIN checkpoints v ON v.job=j.id AND v.stage='verify'
                    WHERE j.state='completed' AND
                        CASE WHEN json_valid(v.value) THEN json_extract(v.value,'$.verified') ELSE 0 END=1
                    {retained}
                ), ranked AS (
                    SELECT voice_id,speech,measured_rate,voice_sha256,ROW_NUMBER() OVER(PARTITION BY voice_id ORDER BY updated DESC) AS n
                    FROM eligible WHERE voice_id IN ({placeholders})
                ) SELECT voice_id,speech,measured_rate,voice_sha256 FROM ranked WHERE n<=8
            ''',tuple(catalog)).fetchall()
        for row in rows:
            identifier=row['voice_id'];speech=_object(row['speech']) if row['measured_rate'] is None else {'voice_id':identifier,'voice_sha256':row['voice_sha256']}
            if not _same_voice(speech,catalog[identifier]):continue
            value=_rate(speech) if row['measured_rate'] is None else _positive(row['measured_rate'])
            if value is not None and not .5<=value<=12:value=None
            if value is not None:rates[identifier].append(value)
    profiles={}
    for identifier,voice in catalog.items():
        measured=rates[identifier]
        source='verified_jobs' if measured else 'default'
        if not measured:
            preview=_preview_rate(voice)
            if preview is not None:measured=[preview];source='preview'
        profiles[identifier]={'syllables_per_second':round(statistics.median(measured),3) if measured else DEFAULT_RATE,
                              'samples':len(measured),'source':source,'speed':1}
    return profiles
