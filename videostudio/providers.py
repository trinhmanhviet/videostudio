"""Verified local contracts only.
References (read-only): StoryForge apps/api/app/providers/images/comfy.py;
apps/web/src/features/video-creator/music-workflow.ts;
apps/worker-media/studio_media/speech.py; providers/llm/chatgpt2api.py.
No connector/browser implementation and no model downloads. LLM URL/model/key
must be explicitly configured; only loopback OpenAI-compatible endpoints allowed.
"""
import importlib.util, json, os, time, shutil
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .core import PermanentError, Cancelled
from .media import asset, probe, render, verify, run

def node(kind,**inputs):return {'class_type':kind,'inputs':inputs}

def image_graph(prompt,seed,prefix):
    return {'1':node('UNETLoader',unet_name='qwen_image_2.1_int8_convrot.safetensors',weight_dtype='default'),
    '2':node('CLIPLoader',clip_name='qwen3vl_8b_int8_convrot.safetensors',type='qwen_image',device='default'),
    '3':node('VAELoader',vae_name='qwen_image_2.1_vae_bf16.safetensors'),
    '4':node('TextEncodeQwenImage21',clip=['2',0],prompt=prompt,negative_prompt='blur, watermark, distorted anatomy, text',resolution=1024,vae=['3',0]),
    '5':node('EmptyLatentImage',width=768,height=1376,batch_size=1),
    '6':node('KSampler',model=['1',0],seed=seed,steps=25,cfg=1,sampler_name='euler',scheduler='simple',positive=['4',0],negative=['4',1],latent_image=['5',0],denoise=1),
    '7':node('VAEDecode',samples=['6',0],vae=['3',0]),'8':node('SaveImage',images=['7',0],filename_prefix=prefix)}

def music_graph(prompt,seconds,seed,prefix):
    return {'1':node('CheckpointLoaderSimple',ckpt_name='stable_audio_3_medium_base.safetensors'),
    '2':node('CLIPLoader',clip_name='t5gemma_b_b_ul2.safetensors',type='stable_audio',device='default'),
    '3':node('CLIPTextEncode',clip=['2',0],text=prompt),'4':node('CLIPTextEncode',clip=['2',0],text='speech, vocals, distorted audio, clipping'),
    '5':node('EmptyLatentAudio',seconds=min(60,seconds),batch_size=1),
    '6':node('KSampler',model=['1',0],seed=seed,steps=50,cfg=7,sampler_name='lcm',scheduler='simple',positive=['3',0],negative=['4',0],latent_image=['5',0],denoise=1),
    '7':node('VAEDecodeAudio',samples=['6',0],vae=['1',2]),'8':node('SaveAudioMP3',audio=['7',0],filename_prefix=prefix,quality='V0')}

class Pipeline:
    def __init__(self,voices):
        self.voices=voices
        self.comfy=os.getenv('VS_COMFY_URL','http://127.0.0.1:8188').rstrip('/')
        self.llm=os.getenv('VS_LLM_URL','').rstrip('/');self.model=os.getenv('VS_LLM_MODEL','');self.key=os.getenv('VS_LLM_KEY','')
        self.speech_cache=os.getenv('VS_SPEECH_CACHE','')
        self.knowledge=Path(os.environ['VS_KNOWLEDGE_DIR']) if os.getenv('VS_KNOWLEDGE_DIR') else None
        self.ffmpeg=os.getenv('VS_FFMPEG','ffmpeg');self.ffprobe=os.getenv('VS_FFPROBE','ffprobe')
    def preflight(self):
        checks=[]
        def add(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':detail})
        local=lambda u:urlparse(u).hostname in ('127.0.0.1','localhost','::1')
        add('llm',self.llm and self.model and self.key and local(self.llm),'Explicit loopback VS_LLM_URL (including /v1), VS_LLM_MODEL and VS_LLM_KEY required; no automatic credential import')
        add('speech',importlib.util.find_spec('vieneu') and self.speech_cache and Path(self.speech_cache).is_dir(),'VieNeu and pre-existing offline VS_SPEECH_CACHE required')
        add('research',self.knowledge and self.knowledge.is_dir() and any(self.knowledge.glob('*.txt')),'VS_KNOWLEDGE_DIR must contain real .txt research sources; no fabricated internet research')
        add('ffmpeg',shutil.which(self.ffmpeg) and shutil.which(self.ffprobe),'FFmpeg and FFprobe required')
        info={}
        if local(self.comfy):
            try:
                r=httpx.get(self.comfy+'/object_info',timeout=4);r.raise_for_status();info=r.json()
            except Exception:pass
        required=image_graph('',0,'x')|{}
        classes={v['class_type'] for v in required.values()}|{v['class_type'] for v in music_graph('',8,0,'x').values()}
        add('comfy_nodes',all(c in info for c in classes),'Source-derived Qwen2.1/Stable Audio3 blueprint node availability only; not live workflow validation. Flux2Klein unavailable (no verified graph)')
        add('stable_audio3_integration',False,'Stable Audio3 source blueprint is not an attested working integration. Model filenames/node presence do not prove model compatibility; generation adapter unavailable pending verified workflow/output evidence. No GPU test performed.')
        for cls,param,expected in [('UNETLoader','unet_name','qwen_image_2.1_int8_convrot.safetensors'),('CLIPLoader','clip_name','qwen3vl_8b_int8_convrot.safetensors'),('VAELoader','vae_name','qwen_image_2.1_vae_bf16.safetensors'),('CheckpointLoaderSimple','ckpt_name','stable_audio_3_medium_base.safetensors'),('CLIPLoader','clip_name','t5gemma_b_b_ul2.safetensors')]:
            choices=info.get(cls,{}).get('input',{}).get('required',{}).get(param,[[]])[0]
            add('model:'+expected,isinstance(choices,list) and expected in choices,'Must already exist in Comfy; no download')
        catalog=self.voices.catalog();add('voice_inventory',catalog['complete'],'Complete preset and all-project clone DB export required; stopped DB is never started')
        add('production_acceptance',False,'Implementation incomplete: multi-scene timed storyboard, measured narration rewrite, aligned safe-area subtitles, GPU ownership coordination and live AI end-to-end acceptance remain unverified. Production jobs disabled; no fake completion.')
        return {'ready':all(x['ok'] for x in checks),'checks':checks,'voice_warnings':catalog['warnings']}
    def llm_json(self,prompt,check):
        check()
        if not self.llm or not self.key or not self.model:raise PermanentError('LLM unconfigured')
        if urlparse(self.llm).hostname not in ('localhost','127.0.0.1','::1'):raise PermanentError('Only explicit local LLM service permitted')
        r=httpx.post(self.llm+'/chat/completions',headers={'Authorization':'Bearer '+self.key},json={'model':self.model,'messages':[{'role':'user','content':prompt}],'response_format':{'type':'json_object'},'stream':False,'max_tokens':6000},timeout=180)
        r.raise_for_status();check();choice=r.json()['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError('Incomplete/refused LLM response')
        d=json.loads(choice['message']['content'])
        if not isinstance(d,dict):raise ValueError('LLM JSON object required')
        return d
    def comfy_asset(self,j,kind,graph,path,check):
        """Persist prompt ID before polling; restart reattaches, never blindly resubmits.
        An indeterminate POST is failed closed and requires a new job, because Comfy
        does not provide a server-side idempotency key. No global /interrupt calls.
        """
        receipt=Path(j['output'])/(kind+'-receipt.json')
        with httpx.Client(base_url=self.comfy+'/',timeout=30) as c:
            if receipt.exists():
                saved=json.loads(receipt.read_text());pid=saved.get('prompt_id')
                if not pid:raise PermanentError('Indeterminate Comfy submission; refusing duplicate GPU work')
            else:
                check();receipt.write_text(json.dumps({'state':'submitting'}))
                r=c.post('prompt',json={'prompt':graph,'client_id':'videostudio-'+j['id']});r.raise_for_status();pid=r.json().get('prompt_id')
                if not pid:raise PermanentError('Comfy rejected workflow')
                receipt.write_text(json.dumps({'prompt_id':pid}))
            deadline=time.monotonic()+900
            while time.monotonic()<deadline:
                check();r=c.get('history/'+pid);r.raise_for_status();h=r.json().get(pid)
                if h:
                    if h.get('status',{}).get('status_str')=='error':raise PermanentError('Comfy generation failed')
                    outputs=h.get('outputs',{}).get('8',{});items=outputs.get('images' if kind=='images' else 'audio',[])
                    if items:
                        a=items[0];prefix=graph['8']['inputs']['filename_prefix'];folder,name=prefix.rsplit('/',1)
                        if a.get('type')!='output' or a.get('subfolder')!=folder or not a.get('filename','').startswith(name+'_') or '/' in a['filename'] or '\\' in a['filename']:raise PermanentError('Unsafe Comfy output')
                        content=c.get('view',params=a);content.raise_for_status()
                        if len(content.content)>64*1024*1024:raise PermanentError('Comfy asset too large')
                        Path(path).write_bytes(content.content);return {'path':str(path),'prompt_id':pid,'assets':[asset(path)]}
                time.sleep(.5)
            raise TimeoutError('Comfy history timeout; persisted prompt will be reattached')
    def handlers(self):return {s:getattr(self,s) for s in ('plan','research','script','speech','images','subtitles','music','render','verify')}
    def plan(self,j,check):
        pf=self.preflight()
        if not pf['ready']:raise PermanentError('Preflight blocked: '+', '.join(x['name'] for x in pf['checks'] if not x['ok']))
        self.voices.selected(j['request']['voice_id'])
        d=self.llm_json('Create a concise video plan as JSON {"title":str,"research_query":str,"visual_prompt":str,"music_prompt":str}. Video request: '+json.dumps(j['request']),check)
        if not all(isinstance(d.get(k),str) and d[k].strip() for k in ('title','research_query','visual_prompt','music_prompt')):raise ValueError('Invalid video plan')
        return d
    def research(self,j,check):
        check();query=j['checkpoints']['plan']['research_query'].casefold().split();sources=[]
        for p in self.knowledge.glob('*.txt'):
            text=p.read_text(encoding='utf-8')[:50000]
            score=sum(w in text.casefold() for w in query)
            if score:sources.append((score,{'path':str(p),'text':text,'sha256':asset(p)['sha256']}))
        sources=[s for _,s in sorted(sources,key=lambda x:-x[0])[:5]]
        if not sources:raise PermanentError('No relevant verified local research sources')
        return {'sources':sources,'assets':[{'path':s['path'],'sha256':s['sha256']} for s in sources],'mode':'local_corpus'}
    def script(self,j,check):
        d=self.llm_json('Write Vietnamese narration for requested duration. Return JSON {"narration":str,"source_paths":[str]}. Only supported facts from supplied sources; do not invent quotes. Target ~3 spoken words per second. '+json.dumps({'request':j['request'],'plan':j['checkpoints']['plan'],'research':j['checkpoints']['research']},ensure_ascii=False),check)
        allowed={s['path'] for s in j['checkpoints']['research']['sources']}
        if not isinstance(d.get('narration'),str) or not d['narration'].strip() or not d.get('source_paths') or not set(d['source_paths'])<=allowed:raise ValueError('Unattributed or empty script')
        return d
    def speech(self,j,check):
        check();v=self.voices.selected(j['request']['voice_id']);out=Path(j['output'])/'speech.wav'
        # Separate process allows cooperative cancel and avoids loading GPU in API process.
        args=[os.sys.executable,'-m','videostudio.speech_worker',json.dumps({'text':j['checkpoints']['script']['narration'],'voice':v,'cache':self.speech_cache,'output':str(out)},ensure_ascii=False)]
        run(args,check,timeout=900)
        seconds=float(probe(out,self.ffprobe)['format']['duration'])
        if seconds<=0:raise ValueError('Empty speech')
        return {'path':str(out),'duration_seconds':seconds,'assets':[asset(out)]}
    def images(self,j,check):
        prefix='videostudio/'+j['id']+'-image';graph=image_graph(j['checkpoints']['plan']['visual_prompt'],int(j['id'].replace('-','')[:8],16),prefix)
        return self.comfy_asset(j,'images',graph,Path(j['output'])/'image.png',check)
    def subtitles(self,j,check):
        # Honest scene-level caption: full utterance cue, not fabricated word alignment.
        check();p=Path(j['output'])/'subtitles.srt';secs=j['request']['duration_seconds']
        def stamp(s):
            ms=round(s*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000);return f'{h:02}:{m:02}:{s:02},{ms:03}'
        text=j['checkpoints']['script']['narration'].replace('-->','→')
        p.write_text('1\n00:00:00,000 --> '+stamp(secs)+'\n'+text+'\n',encoding='utf-8')
        return {'path':str(p),'timing_policy':'single_utterance_measured_speech_paced_to_target','assets':[asset(p)]}
    def music(self,j,check):
        check()
        raise PermanentError('Stable Audio3 unavailable: source blueprint has not been attested against installed model/node compatibility and actual output. Refusing speculative GPU submission.')
    def render(self,j,check):
        cp=j['checkpoints'];return render(cp['images']['path'],cp['speech']['path'],cp['music']['path'],cp['subtitles']['path'],Path(j['output'])/'video.mp4',j['request']['duration_seconds'],check,self.ffmpeg,self.ffprobe)
    def verify(self,j,check):
        p=j['checkpoints']['render']['video'];v=verify(p,j['request']['duration_seconds'],self.ffprobe)
        run([self.ffmpeg,'-v','error','-i',p,'-f','null','-'],check,timeout=900)
        return v
