"""Additive offline speech selection; absent options retain VieNeu audio identity."""
import hashlib,json,math,os,wave,re
from pathlib import Path
from .speech_worker import SpeechJob
from .paths import RUNTIME_ROOT,DATA_ROOT
from .core import digest

SPEECH_FIELDS={'speech_engine','khanh_steps','speech_rhythm','speech_speed','speech_reference_text'}
KHANH_REVISION='20d056b8ea5d8d578b4cbaf1f703012fa3798a84'
PRESET_REFERENCE_TEXT='Xin chào, hôm nay chúng ta cùng lắng nghe một câu chuyện. Mỗi lời kể mở ra một khung cảnh mới, đưa người nghe đến gần hơn với những điều bình dị trong cuộc sống.'

def speech_options(request):
    engine=request.get('speech_engine','vieneu');steps=request.get('khanh_steps',32)
    rhythm=request.get('speech_rhythm','natural');speed=request.get('speech_speed',1.0)
    if not isinstance(engine,str) or engine not in ('vieneu','khanhtts'):raise ValueError('speech_engine must be vieneu or khanhtts')
    if type(steps) is not int or steps not in (16,32):raise ValueError('khanh_steps must be 16 or 32')
    if not isinstance(rhythm,str) or rhythm not in ('natural','story'):raise ValueError('speech_rhythm must be natural or story')
    if isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or not .5<=speed<=2:raise ValueError('speech_speed must be a finite number from 0.5 to 2.0')
    if 'speech_reference_text' in request:
        text=request['speech_reference_text']
        if not isinstance(text,str) or not 1<=len(text.strip())<=10000:raise ValueError('speech_reference_text must contain 1–10000 characters of exact reference transcript')
    return {'speech_engine':engine,'khanh_steps':steps,'speech_rhythm':rhythm,'speech_speed':float(speed)}

def _json(path):
    try:
        result=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return result if isinstance(result,dict) else {}
    except (OSError,ValueError):return {}

def _reference_cache(pipeline,voice):
    identity={'voice_id':voice['id'],'source':'vieneu_preset','version':1,'text':PRESET_REFERENCE_TEXT}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    root=Path(getattr(pipeline,'speech_reference_cache',None) or DATA_ROOT/'voice-reference-cache')/key
    return root,identity

def _cached_reference(pipeline,voice):
    if voice.get('kind')!='preset' or voice.get('reference_path'):return None
    root,identity=_reference_cache(pipeline,voice);path=root/'reference.wav';record=_json(root/'reference.json')
    if record.get('identity')!=identity or not path.is_file() or record.get('sha256')!=digest(path):return None
    return {'path':str(path.resolve()),'sha256':record['sha256'],'text':PRESET_REFERENCE_TEXT,
            'text_sha256':hashlib.sha256(PRESET_REFERENCE_TEXT.encode()).hexdigest(),'source':'prepared_vieneu_preset'}

def _can_prepare(pipeline,voice):
    python=getattr(pipeline,'speech_python','');cache=getattr(pipeline,'speech_cache','')
    return voice.get('kind')=='preset' and not voice.get('reference_path') and bool(python) and Path(python).is_file() and bool(cache) and Path(cache).is_dir()

def prepare_reference(pipeline,voice,request,check):
    """Deliberate synthesis only: close VieNeu before starting KhanhTTS."""
    check()
    try:return resolve_reference(pipeline,voice,request)
    except ValueError:
        if not _can_prepare(pipeline,voice):raise
    import uuid
    root,identity=_reference_cache(pipeline,voice);root.mkdir(parents=True,exist_ok=True)
    pending=root/f'.{uuid.uuid4().hex}.wav';receipt=root/f'.{uuid.uuid4().hex}.json'
    try:
        # The transcript is exactly what this synthetic reference reads. Existing
        # clone recordings never take this fallback and are never transcribed.
        with SpeechJob(pipeline.speech_python,pipeline.speech_cache,voice,check,1) as worker:
            worker.write_line(PRESET_REFERENCE_TEXT,pending,timeout=900)
        check()
        with wave.open(str(pending),'rb') as source:
            duration=source.getnframes()/source.getframerate()
            if source.getsampwidth()!=2 or not 1<=duration<=40:raise ValueError('Prepared preset reference has invalid WAV format/duration')
        sha=digest(pending);receipt.write_text(json.dumps({'identity':identity,'sha256':sha}),encoding='utf8')
        pending.replace(root/'reference.wav');receipt.replace(root/'reference.json')
        result=_cached_reference(pipeline,voice)
        if result is None:raise ValueError('Prepared voice reference changed before verification')
        return result
    finally:pending.unlink(missing_ok=True);receipt.unlink(missing_ok=True)

def resolve_reference(pipeline,voice,request=None):
    """Use only this voice's attested audio/transcript; never infer or transcribe."""
    request=request or {};speech_options(request)
    cached=_cached_reference(pipeline,voice)
    explicit=voice.get('reference_path')
    path=Path(explicit or voice.get('sample_path') or '__missing_reference__')
    # This one locally attested trial is a proven paired reference for Thiện Minh.
    # Never substitute it for another voice or for a user-selected reference.
    if not explicit and voice.get('id')=='Thiện Minh' and not path.is_file():
        record=_json(DATA_ROOT/'story-narration-demo-20261113/receipt.json')
        units=record.get('units',[])
        if record.get('voice')==voice['id'] and units and isinstance(units[0],dict):
            known=units[0]
            if Path(known.get('path','__missing__')).is_file() and isinstance(known.get('text'),str):
                voice={**voice,'sample_path':known['path'],'reference_text':known['text']};path=Path(known['path'])
    if not path.is_file():
        if cached:return cached
        raise ValueError('KhanhTTS requires an available reference audio for this voice')
    sha=digest(path)
    if explicit and voice.get('sha256')!=sha:raise ValueError('Voice reference changed or checksum is unverified')
    text=request.get('speech_reference_text') or voice.get('reference_text') or voice.get('reference_transcript')
    source='user_transcript' if request.get('speech_reference_text') else 'voice_metadata'
    if not text:
        record=_json(path.parent/'request.json')
        # A preview text describes preview.wav, never its input clone recording.
        if path.name=='preview.wav' and record.get('voice_id')==voice['id']:
            text=record.get('text');source='preview_request'
        reference=record.get('voice_reference',{})
        if not text and isinstance(reference,dict) and reference.get('sha256')==sha:
            text=reference.get('reference_text') or reference.get('transcript');source='reference_metadata'
    if not isinstance(text,str) or not 1<=len(text.strip())<=10000:
        if cached:return cached
        raise ValueError('KhanhTTS needs the exact reference transcript; supply speech_reference_text or use a voice with a verified preview transcript')
    text=text.strip()
    return {'path':str(path.resolve()),'sha256':sha,'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'source':source}

def _khanh_paths(pipeline):
    python=Path(getattr(pipeline,'khanh_python',None) or os.getenv('VS_KHANH_PYTHON',str(RUNTIME_ROOT/'khanhtts/.venv/Scripts/python.exe')))
    cache=Path(getattr(pipeline,'speech_cache',None) or RUNTIME_ROOT/'media/model-cache')
    snapshot=Path(getattr(pipeline,'khanh_snapshot',None) or os.getenv('VS_KHANH_SNAPSHOT',str(cache/'hub/models--kjanh--KhanhTTS-OmniVoice/snapshots'/KHANH_REVISION)))
    return python,cache,snapshot

def khanh_snapshot_ready(snapshot):
    return all((Path(snapshot)/name).is_file() for name in ('config.json','model.safetensors','tokenizer.json','audio_tokenizer/config.json','audio_tokenizer/model.safetensors'))

def engine_status(pipeline,voice=None,request=None):
    options=speech_options(request or {});engine=options['speech_engine']
    reference_ready=True;reason='';needs_prepare=False
    if engine=='khanhtts':
        python,cache,snapshot=_khanh_paths(pipeline)
        runtime_ready=python.is_file() and khanh_snapshot_ready(snapshot)
        if not runtime_ready:reason='Existing offline KhanhTTS runtime/model snapshot is unavailable'
        if voice is not None:
            try:resolve_reference(pipeline,voice,request)
            except ValueError as error:
                needs_prepare=_can_prepare(pipeline,voice)
                reference_ready=bool(needs_prepare);reason='The first KhanhTTS read prepares a paired voice sample with existing offline VieNeu' if needs_prepare else str(error)
    else:
        python=getattr(pipeline,'speech_python','');cache=getattr(pipeline,'speech_cache','')
        runtime_ready=bool(python) and Path(python).is_file() and bool(cache) and Path(cache).is_dir()
        if not runtime_ready:reason='Existing offline VieNeu runtime/cache is unavailable'
    supported={'rhythms':['natural','story'],'speed':{'min':.5,'max':2.0,'default':1.0},'reference_transcript_required':engine=='khanhtts','emotion_style':False}
    if engine=='khanhtts':supported['steps']=[16,32];supported['default_steps']=32
    if engine=='khanhtts' and not runtime_ready:reason='Existing offline KhanhTTS runtime/model snapshot is unavailable'
    return {'engine':engine,'ready':bool(runtime_ready and reference_ready),'runtime_ready':bool(runtime_ready),'reference_ready':reference_ready,'needs_reference_prepare':needs_prepare,'reason':reason,'options':supported}

def legacy_sound_request(request):
    options=speech_options(request)
    return options['speech_engine']=='vieneu' and options['speech_rhythm']=='natural' and options['speech_speed']==1

def preflight_for_request(result,pipeline,request):
    """Replace the legacy speech gate only when engine selection needs it."""
    if speech_options(request)['speech_engine']=='vieneu':return result
    try:
        voice=pipeline.voices.selected(request['voice_id'])
        status=engine_status(pipeline,voice,request)
    except (ValueError,KeyError) as error:status={'ready':False,'reason':str(error)}
    checks=[{**row,'ok':status['ready'],'detail':status.get('reason') or 'Existing offline KhanhTTS runtime, model and paired voice reference available; synthesis is checked separately'} if row['name']=='speech' else dict(row) for row in result['checks']]
    if not any(row['name']=='speech' for row in checks):checks.append({'name':'speech','ok':status['ready'],'detail':status.get('reason','')})
    return {**result,'checks':checks,'ready':all(row['ok'] for row in checks)}

def speech_identity(text,voice,request,pipeline=None):
    options=speech_options(request);identity={'narration':text,'voice':voice}
    # Keep byte-for-byte old VieNeu receipts, including explicit equivalent defaults.
    if options['speech_engine']=='khanhtts':
        ref=resolve_reference(pipeline,voice,request)
        identity['engine']={'name':'khanhtts','revision':str(_khanh_paths(pipeline)[2].resolve()),'steps':options['khanh_steps'],'reference_sha256':ref['sha256'],'text_sha256':ref['text_sha256']}
    if options['speech_rhythm']!='natural' or options['speech_speed']!=1:
        identity['processing']={'version':1,'rhythm':options['speech_rhythm'],'speed':options['speech_speed']}
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

def boundary_pause(text):
    text=text.rstrip().rstrip('\"\'”’)]}')
    return .45 if text.endswith(('!','?','…')) else .35 if text.endswith('.') else .22 if text.endswith((',',':',';')) else .18

def speech_units(text):
    """Preview sentence units; keep each supplied video utterance unchanged."""
    if not isinstance(text,str) or not text.strip():raise ValueError('Provide non-empty speech text')
    return [part.strip() for part in re.split(r'(?<=[.!?…])\s+|\n+',text.strip()) if part.strip()]

def _trailing_silence(path):
    import array
    with wave.open(str(path),'rb') as source:
        if source.getsampwidth()!=2:raise ValueError('Speech processing requires PCM16 WAV')
        channels=source.getnchannels();rate=source.getframerate();samples=array.array('h',source.readframes(source.getnframes()))
    frames=0
    for offset in range(len(samples)-channels,-1,-channels):
        if any(abs(sample)>100 for sample in samples[offset:offset+channels]):break
        frames+=1
    return frames/rate

class ProcessedSpeechJob:
    """Apply tempo and minimum boundary pauses before each output/receipt is published."""
    def __init__(self,worker,pipeline,options,check):
        self.worker=worker;self.pipeline=pipeline;self.options=options;self.check=check;self.batch_size=worker.batch_size;self.pending=set()
    def __enter__(self):self.worker.__enter__();return self
    def __exit__(self,*args):
        try:return self.worker.__exit__(*args)
        finally:
            for path in self.pending:path.unlink(missing_ok=True);path.with_suffix('.part.wav').unlink(missing_ok=True)
    def _finish(self,text,raw,output):
        from .media import run
        self.check();speed=self.options['speech_speed'];filters=[]
        if speed!=1:filters.append(f'atempo={speed:.8f}')
        if self.options['speech_rhythm']=='story':
            silence=max(0,boundary_pause(text)-_trailing_silence(raw)/speed)
            if silence:filters.append(f'apad=pad_dur={silence:.8f}')
        partial=Path(output).with_suffix('.processed.part.wav');self.pending.add(partial)
        if filters:
            run([self.pipeline.ffmpeg,'-v','error','-y','-i',str(raw),'-af',','.join(filters),'-c:a','pcm_s16le',str(partial)],self.check)
            self.check();partial.replace(output)
        else:raw.replace(output)
        raw.unlink(missing_ok=True);self.pending.discard(raw);self.pending.discard(partial)
    def write_line(self,text,output,timeout=900):self.write_lines([text],[output],timeout)
    def write_lines(self,texts,outputs,timeout=900,on_complete=None):
        import uuid
        if len(texts)!=len(outputs) or not texts:raise ValueError('One output required per utterance')
        if len(set(map(str,outputs)))!=len(outputs):raise ValueError('Utterance outputs must be unique')
        raw=[Path(path).with_name(f'.{Path(path).stem}.{uuid.uuid4().hex}.raw.wav') for path in outputs];self.pending.update(raw)
        def completed(index):
            self._finish(texts[index],raw[index],Path(outputs[index]))
            if on_complete:on_complete(index)
        self.worker.write_lines(texts,raw,timeout=timeout,on_complete=completed)

def create_speech_job(pipeline,voice,request,check,*,worker_factory=None):
    options=speech_options(request)
    if options['speech_engine']=='khanhtts':
        from .khanh_speech_worker import KhanhSpeechJob
        python,cache,snapshot=_khanh_paths(pipeline)
        status=engine_status(pipeline,voice,request)
        if not status['ready']:raise ValueError(status['reason'])
        reference=prepare_reference(pipeline,voice,request,check)
        worker=KhanhSpeechJob(str(python),cache,reference,check,request.get('speech_batch_size'),snapshot,options['khanh_steps'])
    else:worker=(worker_factory or SpeechJob)(pipeline.speech_python,pipeline.speech_cache,voice,check,request.get('speech_batch_size'))
    if options['speech_rhythm']=='natural' and options['speech_speed']==1:return worker
    return ProcessedSpeechJob(worker,pipeline,options,check)
