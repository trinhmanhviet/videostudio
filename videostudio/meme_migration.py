"""One-time, lossless adaptation of saved meme jobs to the single HF pipeline.

No source media or old receipts are removed. Database changes are transactional;
the original job snapshot is durable before any checkpoint is changed.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .core import PermanentError, STAGES, digest
from .media import asset

VERSION = 'comedy-migration-v1'


def _read(path):
    return json.loads(path.read_text(encoding='utf8'))


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part.json')
    part.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    part.replace(path)


def _attested(path):
    receipt = path.with_suffix('.receipt.json')
    if not receipt.is_file() or _read(receipt).get('sha256') != digest(path):
        raise PermanentError(f'Saved animation receipt is missing or changed: {path.name}; restore its original receipt before continuing. Originals retained.')
    return _read(path)


def legacy_prefix(job, catalog):
    """Import only a contiguous, attested prefix; never regenerate saved text."""
    from .meme_animation_script import validate
    folder = Path(job['output'])/'animation-parts'
    if not folder.is_dir():
        return None
    outline_path = folder/'outline.json'
    if not outline_path.is_file():
        if any(folder.glob('*.json')):
            raise PermanentError('Saved animation parts have no validated outline; restore outline.json and its receipt before continuing. Originals retained.')
        return None
    outline = _attested(outline_path)
    descriptions = outline.get('parts')
    if not isinstance(descriptions,list) or not descriptions:
        raise PermanentError('Saved animation outline has no parts; restore its original outline. Originals retained.')
    meta = validate(outline,catalog,job['request'],metadata_only=True)
    parts = []; gap = False
    for i, description in enumerate(descriptions,1):
        path = folder/f'part-{i:02}.json'
        raw = None
        if not path.is_file():
            candidates = [p for p in sorted(folder.glob(f'part-{i:02}-*-attempt-*.json')) if not p.name.endswith('.rejected.json')]
            for candidate in candidates:
                rejection = candidate.with_suffix('.rejected.json')
                if rejection.is_file() and _read(rejection).get('sha256')==digest(candidate):continue
                try:
                    value = _read(candidate)
                    if value.get('part')!=i:continue
                    validate({**meta,'beats':value.get('beats')},catalog,job['request'],enforce_beat_count=False)
                    raw=value;break
                except (ValueError,TypeError,AttributeError):continue
            if raw is None:
                if candidates:
                    raise PermanentError(f'Saved animation part {i} contains no usable reply; repair its JSON before continuing. Originals retained.')
                gap = True;continue
        if gap:raise PermanentError('Saved animation parts are not contiguous; restore the missing part before continuing. Originals retained.')
        if raw is None:raw = _attested(path)
        if raw.get('part') != i:raise PermanentError('Saved animation part number changed; restore its original file. Originals retained.')
        clean = validate({**meta,'beats':raw.get('beats')},catalog,job['request'],enforce_beat_count=False)
        parts.append({'beats':clean['beats'],'summary':description['summary']})
    return {'meta':meta,'parts':parts,'outline_parts':descriptions,'total_parts':len(descriptions)}


def saved_script(job, catalog):
    from .meme_animation_script import validate, to_checkpoint
    folder = Path(job['output']); path = folder/'animation-script.json'
    if (folder/'comedy/inputs.json').is_file():
        return None  # Current writer restores complete quality metadata from its own receipts.
    if path.is_file():
        raw = _read(path)
    else:
        # Preserve replies saved just before the worker checkpoint transaction.
        raw = None
        for candidate in sorted(folder.glob('animation-script-attempt-*.json')):
            if candidate.name.endswith('.rejected.json'):continue
            try:
                raw = validate(_read(candidate),catalog,job['request'],enforce_beat_count=False)
                path = candidate;break
            except (ValueError,TypeError):continue
        if raw is None:return None
    script = validate(raw,catalog,job['request'],enforce_beat_count=False)
    result = to_checkpoint(script,catalog.fingerprint());result['assets']=[asset(path)]
    quality = folder/'comedy/quality.json'
    if quality.is_file():result['comedy']=_read(quality);result['assets'].append(asset(quality))
    return result


def _convert(job, script, catalog):
    from .meme_animation_script import validate, to_checkpoint
    lines = []
    for scene in script.get('scenes',[]):
        values = scene.get('narration_lines') or [scene.get('narration')]
        lines.extend(t for t in values if isinstance(t,str) and t.strip())
    if not lines:
        lines = [b.get('line') for b in script.get('beats',[]) if isinstance(b,dict) and b.get('line')]
    if len(lines)<2:
        raise PermanentError('Legacy script has fewer than two recoverable narration lines; restore script.json or create a new job. Originals retained.')
    meta = {'title':['TRUYỆN ĐÃ LƯU','TIẾP TỤC DỰNG'],'payoff':['CÂU CHUYỆN CŨ','GIỮ NGUYÊN LỜI'],
            'cast':{'toi':{'name':'Tôi','costume':sorted(catalog.costumes)[0],'acc':[],'face':sorted(catalog.faces)[0]}},
            'scenes':{'saved':{'bg':sorted(catalog.backgrounds)[0],'cast':['toi']}}}
    data = validate({**meta,'beats':[{'scene':'saved','who':'N','focus':'toi','text':t,'emo':{},'act':[],'punch':None} for t in lines]},catalog,job['request'],enforce_beat_count=False)
    result = to_checkpoint(data,catalog.fingerprint())
    # Existing speech recipes key on scene_id/text; retain that identity exactly.
    if len(script.get('scenes',[]))==len(lines):
        for old,new in zip(script['scenes'],result['scenes']):new['scene_id']=old['scene_id']
    result['migration']={'version':VERSION,'voice_id':job['request']['voice_id'],
                         'original_narration':script.get('narration',' '.join(lines))}
    cached = []; names = set(); output = Path(job['output'])
    # Pipeline.speech writes per-line receipts in this revision directory.
    # The root fallback covers older saved jobs; production cache takes priority.
    for revision in (output/'narration-attempt-00',output):
        for wav in sorted(revision.glob('speech-[0-9][0-9][0-9][0-9].wav')):
            if wav.name in names:continue
            receipt = wav.with_suffix('.json')
            if receipt.is_file():
                raw = _read(receipt)
                if raw.get('sha256') != digest(wav):
                    raise PermanentError('Legacy partial TTS asset changed; restore its original WAV before continuing. Originals retained.')
                cached.append({'audio':asset(wav),'receipt':asset(receipt)});names.add(wav.name)
    if cached:result['migration']['raw_utterances']=cached
    result['narration']=script.get('narration') or result['narration']
    if 'speech' in job['checkpoints']:
        speech = job['checkpoints']['speech']
        rows = speech.get('utterances',[])
        if len(rows)!=len(lines) or any((r.get('narration') or r.get('text')) != t or not Path(r.get('path','')).is_file() for r,t in zip(rows,lines)):
            raise PermanentError('Legacy TTS cannot be mapped 1:1 to saved narration; restore the original utterance files/mapping before continuing. Originals retained.')
        result['migration']['speech']=speech
    return result


def reuse_legacy_voice(job, revision):
    """Copy attested old utterance cache into the owned HF workspace once.

    The ordinary speech adapter validates the original text/voice identity before
    reusing each copied file, so changed voice requests synthesize only as needed.
    """
    cached = job['checkpoints']['script'].get('migration',{}).get('raw_utterances',[])
    revision.mkdir(parents=True,exist_ok=True)
    for item in cached:
        for key in ('audio','receipt'):
            original = item[key];source=Path(original['path']);destination=revision/source.name
            if not source.is_file() or digest(source)!=original['sha256']:
                raise PermanentError('Legacy partial TTS asset missing or changed; restore its original file before continuing.')
            if not destination.exists():shutil.copy2(source,destination)


def migrate_job(store, job_id, *, connection=None, lease_owner=None):
    """Adapt one idle job. Worker may pass its own lease while holding the DB lock."""
    if connection is None:
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return migrate_job(store,job_id,connection=c,lease_owner=lease_owner)
    c = connection
    row = c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise KeyError(job_id)
    job = dict(row);job.pop('idem');job['request']=json.loads(job['request'])
    job['checkpoints']={r['stage']:json.loads(r['value']) for r in c.execute('SELECT * FROM checkpoints WHERE job=?',(job_id,))}
    job['attempts']={r['stage']:r['count'] for r in c.execute('SELECT * FROM attempts WHERE job=?',(job_id,))}
    job['events']=[dict(r) for r in c.execute('SELECT * FROM events WHERE job=? ORDER BY seq',(job_id,))]
    if job['request'].get('workflow_mode')!='meme' or job['state']=='completed':return job
    script = job['checkpoints'].get('script')
    legacy_replies = [Path(job['output'])/'meme-script.json', *sorted(Path(job['output']).glob('meme-script-attempt-*.json'),reverse=True)]
    legacy_replies = [p for p in legacy_replies if p.is_file() and not p.name.endswith('.rejected.json')]
    if job['request'].get('meme_engine')=='hyperframes' and (script and script.get('animation_script') or not script and not legacy_replies):return job
    lease = c.execute('SELECT * FROM worker_lock WHERE expires>?',(time.time(),)).fetchone()
    owns_lease = lease is not None and lease_owner is not None and lease['owner']==lease_owner
    if (job['state']=='running' and not owns_lease) or (lease and not owns_lease):
        raise ValueError('Meme migration requires an idle job and no active worker lease')
    for cp in job['checkpoints'].values():
        for item in cp.get('assets',[]):
            if not Path(item['path']).is_file() or digest(item['path'])!=item['sha256']:
                raise PermanentError('Legacy checkpoint asset missing or changed; restore original media before migration. Originals retained.')
    if script is None and legacy_replies:
        for reply in legacy_replies:
            try:
                candidate = _read(reply)
                if isinstance(candidate,dict) and len(candidate.get('beats',[]))>=2 and all(isinstance(b,dict) and isinstance(b.get('line'),str) and b['line'].strip() for b in candidate['beats']):
                    script = candidate;break
            except (ValueError,OSError,TypeError):continue
        if script is None:
            raise PermanentError('Saved legacy replies contain no complete recoverable narration; repair meme-script.json before continuing. Originals retained.')
    from .meme_animation_script import AnimationCatalog
    converted = _convert(job,script,AnimationCatalog()) if script and not script.get('animation_script') else script
    folder = Path(job['output'])/VERSION;backup=folder/'original.json'
    if not backup.exists():_save(backup,{'version':VERSION,'job':job,'database_row':dict(row)})
    originals = {Path(job['output'])/(name+'.json') for name in STAGES}
    originals.update(Path(job['output'])/name for name in ('brief.json','video.mp4','speech.wav','subtitles.srt','subtitles.ass'))
    for cp in job['checkpoints'].values():
        originals.update(Path(a['path']) for a in cp.get('assets',[]))
        for key in ('video','path'):
            if cp.get(key):originals.add(Path(cp[key]))
    if converted is not None:
        for cached in converted.get('migration',{}).get('raw_utterances',[]):
            originals.update(Path(cached[key]['path']) for key in ('audio','receipt'))
    saved_files = []
    output = Path(job['output']).resolve()
    for source in sorted(originals):
        if not source.is_file() or not source.resolve().is_relative_to(output):continue
        destination = folder/'files'/source.resolve().relative_to(output)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.exists():shutil.copy2(source,destination)
        if digest(destination)!=digest(source):
            raise PermanentError('Migration backup differs from an original file; inspect comedy-migration-v1 before continuing. Originals retained.')
        saved_files.append({'original':str(source),'backup':str(destination),'sha256':digest(destination)})
    _save(folder/'files.json',saved_files)
    request = dict(job['request'],meme_engine='hyperframes')
    affected = []
    if converted is not script:
        # TTS files are reused; HF needs its own timing/processing checkpoint.
        affected = ['speech','images','subtitles','render','verify']
        _save(folder/'script.json',converted);converted['assets']=[asset(folder/'script.json')]
        c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(job_id,'script',json.dumps(converted,ensure_ascii=False)))
        for stage in affected:
            c.execute('DELETE FROM checkpoints WHERE job=? AND stage=?',(job_id,stage))
            c.execute('DELETE FROM attempts WHERE job=? AND stage=?',(job_id,stage))
    remaining = set(job['checkpoints'])-set(affected)
    if converted is not script:remaining.add('script')
    stage = next((s for s in STAGES if s not in remaining),None)
    state = 'queued' if job['state']=='running' and owns_lease else job['state']
    c.execute('UPDATE jobs SET request=?,state=?,stage=?,updated=? WHERE id=?',(json.dumps(request,ensure_ascii=False),state,stage,time.time(),job_id))
    store.event(c,job_id,stage,'comedy_migrated',f'Originals: {backup}; TTS/music retained; rebuilt stages: {affected}')
    _save(folder/'receipt.json',{'version':VERSION,'original_sha256':digest(backup),'invalidated':affected})
    # Read through the same transaction so callers see committed-intent state.
    job['request']=request;job['state']=state;job['stage']=stage
    for name in affected:job['checkpoints'].pop(name,None);job['attempts'].pop(name,None)
    if converted is not script:job['checkpoints']['script']=converted
    updated=c.execute('SELECT updated FROM jobs WHERE id=?',(job_id,)).fetchone();job['updated']=updated['updated']
    job['events']=[dict(r) for r in c.execute('SELECT * FROM events WHERE job=? ORDER BY seq',(job_id,))]
    return job
