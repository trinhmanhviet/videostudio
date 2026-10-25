"""Immutable visual edits, user decisions, and frozen export revisions.
No LLM, TTS or image-generation calls are made by the editor.
"""
import copy,io,json,shutil,time,uuid,warnings
from pathlib import Path
from PIL import Image,ImageOps,UnidentifiedImageError
from .core import AwaitingVisualReview,digest,validate_request,output_slug,STAGES
from .media import asset
from .visual_quality import bind_scene_ids,text_hash,fingerprint,atomic_json

MAX_UPLOAD=20*1024*1024
MAX_PIXELS=20_000_000

class SceneEditor:
    def __init__(self,store):
        self.store=store
        with store.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS scene_editor_heads(job TEXT PRIMARY KEY,mode TEXT NOT NULL,version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS scene_image_edits(id TEXT PRIMARY KEY,job TEXT NOT NULL,scene TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,fit TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS scene_active_edits(job TEXT,scene TEXT,edit_id TEXT,PRIMARY KEY(job,scene));
            CREATE TABLE IF NOT EXISTS scene_user_approvals(job TEXT,scene TEXT,image_sha256 TEXT,timeline_sha256 TEXT,created REAL,PRIMARY KEY(job,scene));
            CREATE TABLE IF NOT EXISTS scene_exports(child TEXT PRIMARY KEY,parent TEXT,version INTEGER,confirm_all INTEGER,snapshot_sha256 TEXT);
            CREATE TABLE IF NOT EXISTS scene_image_sources(edit TEXT PRIMARY KEY,provider TEXT NOT NULL,task_id TEXT NOT NULL,request_id TEXT NOT NULL);
            ''')
    def mode(self,j):
        with self.store.db() as c:r=c.execute('SELECT mode FROM scene_editor_heads WHERE job=?',(j['id'],)).fetchone()
        return r['mode'] if r else j['request'].get('quality_mode','quick')
    def _head(self,j):
        with self.store.db() as c:
            c.execute('INSERT OR IGNORE INTO scene_editor_heads VALUES(?,?,0)',(j['id'],j['request'].get('quality_mode','quick')))
    def _layout(self,j):
        cp=j['checkpoints']
        if 'speech' not in cp or 'images' not in cp:raise ValueError('Scenes are available after narration and images have completed')
        utterances=bind_scene_ids(cp['speech']['utterances']);images=cp['images']['scenes']
        if not utterances or len(utterances)!=len(images):raise ValueError('Narration/image scene count mismatch')
        attested={str(Path(a['path']).resolve()):a['sha256'] for a in cp['images'].get('assets',[])}
        layout=[]
        for i,(u,img) in enumerate(zip(utterances,images)):
            p=Path(img['path']).resolve();sha=attested.get(str(p))
            if not sha:raise ValueError('Original image is not checkpoint-attested')
            layout.append({'scene_id':u['scene_id'],'index':i,'narration':u['narration'],'visual_prompt':u.get('visual_prompt',''),'start':u['start'],'end':u['end'],'duration':img['duration'],'original_path':str(p),'original_sha256':sha})
        timeline=fingerprint({'scene_timing':[{k:r[k] for k in ('scene_id','narration','start','end','duration')} for r in layout], 'speech':cp['speech'].get('assets',[]),'subtitles':cp.get('subtitles',{}).get('assets',[]),'music':cp.get('music',{}).get('assets',[])})
        return layout,timeline
    def view(self,jid):
        j=self.store.get(jid);self._head(j);layout,timeline=self._layout(j)
        with self.store.db() as c:
            head=dict(c.execute('SELECT * FROM scene_editor_heads WHERE job=?',(jid,)).fetchone())
            edits={r['scene']:dict(r) for r in c.execute('SELECT a.scene,e.* FROM scene_active_edits a JOIN scene_image_edits e ON a.edit_id=e.id WHERE a.job=?',(jid,))}
            approvals={r['scene']:dict(r) for r in c.execute('SELECT * FROM scene_user_approvals WHERE job=?',(jid,))}
            history={}
            for r in c.execute('SELECT e.id,e.scene,e.sha256,e.fit,e.created,COALESCE(s.provider,"upload") AS provider FROM scene_image_edits e LEFT JOIN scene_image_sources s ON s.edit=e.id WHERE e.job=? ORDER BY e.created DESC',(jid,)):history.setdefault(r['scene'],[]).append(dict(r))
        for row in layout:
            sid=row['scene_id'];edit=edits.get(sid);row.update(image_path=edit['path'] if edit else row['original_path'],image_sha256=edit['sha256'] if edit else row['original_sha256'],edit_id=edit['id'] if edit else 'original',fit=edit['fit'] if edit else 'original',history=history.get(sid,[]))
            approved=approvals.get(sid)
            row['review_status']='user_approved' if approved and approved['image_sha256']==row['image_sha256'] and approved['timeline_sha256']==timeline else 'needs_review'
            row['image_url']=f'/api/jobs/{jid}/scene-editor/scenes/{sid}/image?edit={row["edit_id"]}'
            row['audio_url']=f'/api/jobs/{jid}/scene-editor/scenes/{sid}/audio'
        return {'job_id':jid,'version':head['version'],'mode':head['mode'],'state':j['state'],'timeline_sha256':timeline,'scenes':layout,'editable':j['state'] in ('completed','failed','awaiting_visual_review'),'reviewer':'manual_user_selection','automatic_visual_review_available':False}
    def _mutable(self,c,jid,version):
        if type(version) is not int or version<0:raise ValueError('An editor version is required')
        row=c.execute('SELECT h.*,j.state FROM scene_editor_heads h JOIN jobs j ON h.job=j.id WHERE h.job=?',(jid,)).fetchone()
        if not row or row['version']!=version:raise ValueError('Stale editor version; refresh before editing/exporting')
        if row['state'] not in ('completed','failed','awaiting_visual_review'):raise ValueError('Job is active; wait for generation to settle before editing')
        return row
    def _bump(self,c,jid):c.execute('UPDATE scene_editor_heads SET version=version+1 WHERE job=?',(jid,))
    def set_mode(self,jid,mode,version):
        if mode not in ('quick','careful'):raise ValueError('Mode must be quick or careful')
        self.view(jid)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');self._mutable(c,jid,version)
            c.execute('UPDATE scene_editor_heads SET mode=?,version=version+1 WHERE job=?',(mode,jid));self.store.event(c,jid,None,'editor_mode_changed',mode)
        return self.view(jid)
    def _scene(self,view,sid):
        for row in view['scenes']:
            if row['scene_id']==sid:return row
        raise ValueError('Scene not found')
    def replace(self,jid,sid,raw,fit,version,generated_task=None):
        if fit not in ('cover','contain'):raise ValueError('Framing must be cover or contain')
        if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_UPLOAD:raise ValueError('Image upload must be between 1 byte and 20 MB')
        v=self.view(jid);self._scene(v,sid)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as im:
                    if im.format not in ('PNG','JPEG','WEBP') or getattr(im,'n_frames',1)!=1:raise ValueError('Only still PNG, JPEG, WebP images are supported')
                    if min(im.size)<32 or max(im.size)>8192 or im.width*im.height>MAX_PIXELS:raise ValueError('Image dimensions outside safe limits')
                    im.load();im=ImageOps.exif_transpose(im).convert('RGBA');background=Image.new('RGBA',im.size,'black');background.alpha_composite(im);im=background.convert('RGB')
                    if fit=='cover':prepared=ImageOps.fit(im,(1080,1920),method=Image.Resampling.LANCZOS)
                    else:
                        prepared=Image.new('RGB',(1080,1920),'black');resized=ImageOps.contain(im,(1080,1920),method=Image.Resampling.LANCZOS);prepared.paste(resized,((1080-resized.width)//2,(1920-resized.height)//2))
        except (OSError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning) as e:raise ValueError('Invalid or unsafe image bytes') from e
        edit=uuid.uuid4().hex;folder=self.store.path.parent/'scene-edits'/jid;folder.mkdir(parents=True,exist_ok=True);path=folder/(edit+'.png')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');self._mutable(c,jid,version)
            if generated_task:
                task=c.execute("SELECT * FROM scene_image_tasks WHERE id=? AND job=? AND scene=? AND state='completed'",(generated_task,jid,sid)).fetchone()
                if not task or task['timeline_sha256']!=v['timeline_sha256']:raise ValueError('Generated image candidate is stale or already applied')
            prepared.save(path,format='PNG');sha=digest(path)
            c.execute('INSERT INTO scene_image_edits VALUES(?,?,?,?,?,?,?)',(edit,jid,sid,str(path.resolve()),sha,fit,time.time()))
            c.execute('INSERT OR REPLACE INTO scene_active_edits VALUES(?,?,?)',(jid,sid,edit))
            # Upload is an explicit user selection, NOT model certification.
            c.execute('INSERT OR REPLACE INTO scene_user_approvals VALUES(?,?,?,?,?)',(jid,sid,sha,v['timeline_sha256'],time.time()))
            if generated_task:
                receipt=json.loads(task['result'])['request_id']
                c.execute('INSERT INTO scene_image_sources VALUES(?,?,?,?)',(edit,task['provider'],generated_task,receipt))
                c.execute("UPDATE scene_image_tasks SET state='applied',applied_edit_id=?,updated=? WHERE id=?",(edit,time.time(),generated_task))
            self._bump(c,jid);self.store.event(c,jid,'images','user_image_selected',sid)
        return self.view(jid)
    def restore(self,jid,sid,edit,version):
        self._scene(self.view(jid),sid)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');self._mutable(c,jid,version)
            if edit!='original':
                found=c.execute('SELECT * FROM scene_image_edits WHERE id=? AND job=? AND scene=?',(edit,jid,sid)).fetchone()
                if not found or not Path(found['path']).is_file() or digest(found['path'])!=found['sha256']:raise ValueError('Historical edit missing or changed')
            c.execute('INSERT OR REPLACE INTO scene_active_edits VALUES(?,?,?)',(jid,sid,None if edit=='original' else edit));self._bump(c,jid);self.store.event(c,jid,'images','user_image_restored',sid)
        return self.view(jid)
    def approve(self,jid,sid,expected_hash,version):
        v=self.view(jid);row=self._scene(v,sid)
        if expected_hash!=row['image_sha256'] or digest(row['image_path'])!=expected_hash:raise ValueError('Image changed; refresh before approval')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');self._mutable(c,jid,version)
            c.execute('INSERT OR REPLACE INTO scene_user_approvals VALUES(?,?,?,?,?)',(jid,sid,expected_hash,v['timeline_sha256'],time.time()));self._bump(c,jid);self.store.event(c,jid,'images','user_image_approved',sid)
        return self.view(jid)
    def image_file(self,jid,sid,edit='original'):
        v=self.view(jid);row=self._scene(v,sid)
        if edit=='original':path=Path(row['original_path']);sha=row['original_sha256']
        else:
            with self.store.db() as c:r=c.execute('SELECT * FROM scene_image_edits WHERE id=? AND job=? AND scene=?',(edit,jid,sid)).fetchone()
            if not r:raise ValueError('Image version not found')
            path=Path(r['path']);sha=r['sha256']
        if not path.is_file() or digest(path)!=sha:raise ValueError('Image artifact changed')
        return path
    def audio_file(self,jid,sid):
        j=self.store.get(jid);v=self.view(jid);row=self._scene(v,sid);cp=j['checkpoints']['speech'];p=Path(cp['utterances'][row['index']]['path'])
        hashes={a['path']:a['sha256'] for a in cp['assets']}
        if str(p) not in hashes or not p.is_file() or digest(p)!=hashes[str(p)]:raise ValueError('Audio artifact changed')
        return p
    def export(self,jid,version,key,confirm_all=False):
        if not isinstance(key,str) or not 1<=len(key)<=150:raise ValueError('Idempotency-Key required (max 150)')
        if type(confirm_all) is not bool:raise ValueError('confirm_all must be boolean')
        idem='scene-export:'+key
        v=self.view(jid);parent=self.store.get(jid)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT j.id,e.* FROM jobs j LEFT JOIN scene_exports e ON e.child=j.id WHERE j.idem=?',(idem,)).fetchone()
            if old:
                if old['parent']!=jid or old['version']!=version or old['confirm_all']!=int(confirm_all):raise ValueError('Idempotency key already used for another editor snapshot')
                child=old['id']
            else:
                head=self._mutable(c,jid,version)
                for stage in ('plan','research','script','speech','images','subtitles','music'):
                    if stage not in parent['checkpoints']:raise ValueError('Required source checkpoint missing: '+stage)
                    for a in parent['checkpoints'][stage].get('assets',[]):
                        if not Path(a['path']).is_file() or digest(a['path'])!=a['sha256']:raise ValueError('Source checkpoint changed')
                for r in v['scenes']:
                    if digest(r['image_path'])!=r['image_sha256']:raise ValueError('Selected image changed')
                child=str(uuid.uuid4());output=self.store.outputs/(output_slug(parent['request']['idea'])+'-edit-'+child[:12]);output.mkdir(parents=True,exist_ok=False)
                req=validate_request(dict(parent['request'],quality_mode=head['mode']));now=time.time()
                snap={'schema_version':1,'parent_job':jid,'editor_version':version,'mode':head['mode'],'actor':'user_selection','confirmed_all':confirm_all,'timeline_sha256':v['timeline_sha256'],'scenes':[{k:r[k] for k in ('scene_id','index','narration','start','end','duration','image_path','image_sha256','edit_id')} for r in v['scenes']]}
                manifest=output/'visual-edit-snapshot.json';atomic_json(manifest,snap)
                cps={s:copy.deepcopy(parent['checkpoints'][s]) for s in ('plan','research','script','speech','subtitles','music')}
                images=[{'path':r['image_path'],'duration':r['duration'],'scene_id':r['scene_id']} for r in v['scenes']]
                cps['images']={'scenes':images,'assets':[asset(r['path']) for r in images]+[asset(manifest)],'editor_snapshot':str(manifest),'visual_qa_status':'not_checked','visual_qa_required':False,'review_source':'quick','automatic_visual_review':False}
                if parent['state']=='completed' and parent['checkpoints'].get('verify',{}).get('verified') is True:
                    video=Path(parent['checkpoints']['render']['video'])
                    video_asset=next((a for a in parent['checkpoints']['render'].get('assets',[]) if Path(a['path']).resolve()==video.resolve()),None)
                    if not video_asset or digest(video)!=video_asset['sha256']:raise ValueError('Original verified video changed')
                    cps['images']['reuse_audio']=dict(video_asset)
                    cps['images']['assets'].append(dict(video_asset))
                # Only copy valid, unchanged visual clip caches. No TTS/LLM or GPU generation.
                for i,r in enumerate(v['scenes']):
                    clip=Path(parent['output'])/f'visual-{i:04}.mp4';receipt=clip.with_suffix('.json')
                    if clip.is_file() and receipt.is_file():
                        import hashlib
                        expected=hashlib.sha256((r['image_sha256']+str(r['duration'])+'1080x1920-30-pan-v1').encode()).hexdigest()
                        try:cache=json.loads(receipt.read_text())
                        except (OSError,ValueError):cache={}
                        if cache.get('identity')==expected and cache.get('sha256')==digest(clip):
                            shutil.copy2(clip,output/clip.name);shutil.copy2(receipt,output/receipt.name)
                # Renderer resolves subtitle filter filenames against the new output cwd.
                # Copy bytes only; keep source checkpoint/audio/timing unchanged.
                for a in parent['checkpoints']['subtitles'].get('assets',[]):
                    source=Path(a['path'])
                    if source.suffix.lower() in ('.ass','.srt'):shutil.copy2(source,output/source.name)
                if (Path(parent['output'])/'final-script.json').is_file():shutil.copy2(Path(parent['output'])/'final-script.json',output/'final-script.json')
                atomic_json(output/'brief.json',dict(req,job_id=child,parent_job=jid,revision_type='image_edit'))
                c.execute('INSERT INTO jobs(id,idem,request,state,stage,output,created,updated) VALUES(?,?,?,?,?,?,?,?)',(child,idem,json.dumps(req,ensure_ascii=False,sort_keys=True),'queued','render',str(output),now,now))
                for stage,cp in cps.items():
                    c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(child,stage,json.dumps(cp,ensure_ascii=False)));atomic_json(output/(stage+'.json'),cp)
                c.execute('INSERT INTO scene_exports VALUES(?,?,?,?,?)',(child,jid,version,int(confirm_all),fingerprint(snap)))
                self.store.event(c,child,'render','image_revision_created','Frozen visual edit from '+jid)
        return self.store.get(child)
    def require_user_review(self,j):
        cp=j['checkpoints'].get('images',{})
        if cp.get('editor_snapshot'):
            path=Path(cp['editor_snapshot']);snap=json.loads(path.read_text(encoding='utf8'))
            with self.store.db() as c:record=c.execute('SELECT snapshot_sha256 FROM scene_exports WHERE child=?',(j['id'],)).fetchone()
            if not record or fingerprint(snap)!=record['snapshot_sha256'] or snap.get('actor')!='user_selection' or snap.get('mode')!=j['request'].get('quality_mode','quick'):raise ValueError('Export approval provenance changed')
            if self._layout(j)[1]!=snap['timeline_sha256']:raise ValueError('Export narration/timeline changed')
            # Verify frozen paths/order/timeline against the exact checkpoint being rendered.
            if len(snap['scenes'])!=len(cp['scenes']):raise ValueError('Export snapshot scene count changed')
            for row,img in zip(snap['scenes'],cp['scenes']):
                if row['scene_id']!=img['scene_id'] or row['image_path']!=img['path'] or row['duration']!=img['duration'] or digest(img['path'])!=row['image_sha256']:raise ValueError('Export image snapshot changed')
            return {'status':'user_approved' if snap['mode']=='careful' else 'not_checked','source':'user_selection' if snap['mode']=='careful' else 'quick','model_certification':False}
        return {'status':'not_checked','source':'quick','model_certification':False}
