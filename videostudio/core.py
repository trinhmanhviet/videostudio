from __future__ import annotations
import hashlib, json, os, re, sqlite3, time, uuid, unicodedata
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

STAGES = ('plan','research','script','speech','images','subtitles','music','render','verify')
class Cancelled(Exception): pass
class PermanentError(Exception): pass

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def output_slug(text):
    """Readable ASCII slug for generated output folder names."""
    text=text.replace('đ','d').replace('Đ','D')
    text=''.join(ch for ch in unicodedata.normalize('NFD',text) if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')[:60].rstrip('-') or 'video'

def validate_request(data):
    required={'idea','voice_id','duration_seconds'}
    allowed={'idea','voice_id','duration_seconds','project','music_volume','pitch'}
    if not required.issubset(set(data)) or not set(data).issubset(allowed):
        raise ValueError('Exactly idea, voice_id, duration_seconds required')
    if not isinstance(data['idea'],str) or not 1<=len(data['idea'].strip())<=100000: raise ValueError('Invalid idea')
    if not isinstance(data['voice_id'],str) or not 1<=len(data['voice_id'])<=200: raise ValueError('Invalid voice')
    d=data['duration_seconds']
    if isinstance(d,bool) or not isinstance(d,(int,float)) or not 8<=d<=7200: raise ValueError('Duration must be 8–7200 seconds')
    res=dict(data,idea=data['idea'].strip())
    if 'project' in data:
        if not isinstance(data['project'],str) or not 1<=len(data['project'].strip())<=200:raise ValueError('Invalid project name')
        res['project']=data['project'].strip()
    if 'music_volume' in data:
        mv=data['music_volume']
        import math
        if isinstance(mv,bool) or not isinstance(mv,(int,float)) or not math.isfinite(mv) or not 0<=mv<=1:raise ValueError('Music volume must be finite 0–1')
        res['music_volume']=float(mv)
    if 'pitch' in data:
        p=data['pitch']
        import math
        if isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(p) or not -12<=p<=12:
            raise ValueError('Pitch must be finite number between -12 and 12 semitones')
        res['pitch']=round(float(p),1)
    return res

class Store:
    def __init__(self,path,outputs):
        self.path=Path(path); self.outputs=Path(outputs)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, stage TEXT, output TEXT NOT NULL, error TEXT, cancel INTEGER DEFAULT 0, next_at REAL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(job TEXT, stage TEXT, value TEXT NOT NULL, PRIMARY KEY(job,stage));
            CREATE TABLE IF NOT EXISTS attempts(job TEXT, stage TEXT, count INTEGER NOT NULL, PRIMARY KEY(job,stage));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, at REAL, stage TEXT, event TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS worker_lock(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS recovery_grants(job TEXT,stage TEXT,attempt_limit INTEGER NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(job,stage));
            CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY, created REAL NOT NULL);''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10); c.row_factory=sqlite3.Row
        try: yield c; c.commit()
        except: c.rollback(); raise
        finally: c.close()
    def event(self,c,j,s,e,detail=''):
        c.execute('INSERT INTO events(job,at,stage,event,detail) VALUES(?,?,?,?,?)',(j,time.time(),s,e,detail))
    def log(self,j,s,detail=''):
        with self.db() as c:
            self.event(c,j,s,'progress',detail)
            c.execute('UPDATE jobs SET updated=? WHERE id=?',(time.time(),j))
    def create(self,data,key,connector_scope=None):
        data=validate_request(data)
        if not key or len(key)>200: raise ValueError('Idempotency-Key required (max 200 characters)')
        raw=json.dumps(data,sort_keys=True,ensure_ascii=False)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE idem=?',(key,)).fetchone()
            if row:
                if row['request']!=raw: raise ValueError('Idempotency key already used for a different request')
                return self.get(row['id']),False
            j=str(uuid.uuid4()); self.outputs.mkdir(parents=True,exist_ok=True)
            slug=output_slug(data['idea'])
            name=slug+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')
            output=self.outputs/name
            try: output.mkdir()
            except FileExistsError:
                output=self.outputs/(name+'-'+j[:8]); output.mkdir()
            (output/'brief.json').write_text(json.dumps({'job_id':j,**data},ensure_ascii=False,indent=2),encoding='utf8')
            now=time.time()
            c.execute('INSERT OR IGNORE INTO projects VALUES(?,?)',(data.get('project','Dự án mặc định'),now))
            c.execute('INSERT INTO jobs(id,idem,request,state,output,created,updated) VALUES(?,?,?,?,?,?,?)',(j,key,raw,'queued',str(output),now,now))
            if connector_scope:
                bound=c.execute('UPDATE connector_scopes SET job=? WHERE id=? AND job IS NULL',(j,connector_scope))
                if bound.rowcount!=1:raise ValueError('Connector scope is unavailable')
            self.event(c,j,None,'created')
        return self.get(j),True
    def create_derived(self, parent_job_id, new_voice_id, key=None, pitch=0):
        parent=self.get(parent_job_id)
        if parent['state']!='completed':
            raise ValueError('Chỉ có thể đổi giọng cho video đã hoàn tất')
        data=dict(parent['request'], voice_id=new_voice_id, pitch=pitch)
        if not key:
            key=str(uuid.uuid4())
        data=validate_request(data)
        raw=json.dumps(data,sort_keys=True,ensure_ascii=False)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            j=str(uuid.uuid4())
            self.outputs.mkdir(parents=True,exist_ok=True)
            slug=output_slug(data['idea'])
            name=slug+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')
            output=self.outputs/name
            try: output.mkdir()
            except FileExistsError:
                output=self.outputs/(name+'-'+j[:8]); output.mkdir()
            (output/'brief.json').write_text(json.dumps({'job_id':j,**data,'parent_job':parent_job_id},ensure_ascii=False,indent=2),encoding='utf8')
            p_out=Path(parent['output'])
            if p_out.is_dir():
                import shutil
                for f in p_out.glob('images-*.*'):
                    shutil.copy2(f, output/f.name)
            now=time.time()
            c.execute('INSERT OR IGNORE INTO projects VALUES(?,?)',(data.get('project','Dự án mặc định'),now))
            for stage in ('plan', 'research', 'script', 'music'):
                if stage in parent['checkpoints']:
                    val=json.dumps(parent['checkpoints'][stage], ensure_ascii=False)
                    c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)', (j, stage, val))
            c.execute('INSERT INTO jobs(id,idem,request,state,stage,output,created,updated) VALUES(?,?,?,?,?,?,?,?)',(j,key,raw,'queued','speech',str(output),now,now))
            self.event(c, j, 'speech', 'voice_changed', f"Đổi giọng đọc từ video {parent_job_id} sang {new_voice_id}")
        return self.get(j)
    def get(self,j):
        with self.db() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(j,)).fetchone()
            if not r: raise KeyError(j)
            d=dict(r); d['request']=json.loads(d['request']); d.pop('idem')
            d['checkpoints']={r['stage']:json.loads(r['value']) for r in c.execute('SELECT * FROM checkpoints WHERE job=?',(j,))}
            d['attempts']={r['stage']:r['count'] for r in c.execute('SELECT * FROM attempts WHERE job=?',(j,))}
            d['events']=[dict(x) for x in c.execute('SELECT * FROM events WHERE job=? ORDER BY seq',(j,))]
            return d
    def list(self):
        with self.db() as c: ids=[r[0] for r in c.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT 200')]
        return [self.get(j) for j in ids]
    def cancel(self,j):
        self.get(j)
        with self.db() as c:
            c.execute("UPDATE jobs SET cancel=1,state=CASE WHEN state IN ('queued','retrying') THEN 'cancelled' ELSE state END,updated=? WHERE id=?",(time.time(),j));self.event(c,j,None,'cancel_requested')
        return self.get(j)
    def attempt_limit(self,j,stage,base=3):
        with self.db() as c:r=c.execute('SELECT attempt_limit FROM recovery_grants WHERE job=? AND stage=?',(j,stage)).fetchone()
        return r['attempt_limit'] if r else base
    def resume(self,j,scope,base=3,actor='owner'):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE id=?',(j,)).fetchone()
            if not row:raise KeyError(j)
            owner=c.execute('SELECT job FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if not owner or owner['job']!=j:raise ValueError('Connector scope does not own this job')
            if row['state'] not in ('failed','cancelled'):raise ValueError('Only failed/cancelled job may be continued')
            connector_failure='Chrome connector response unavailable' in (row['error'] or '')
            comfy_recovery=False
            if row['stage']=='music':
                from .comfy_recovery import resolve_music_kind
                comfy_recovery=resolve_music_kind(row['output'])!='music'
            if actor not in ('owner','service_recovery'):raise ValueError('Invalid resume actor')
            if actor=='service_recovery' and (not comfy_recovery or row['state']!='failed' or row['cancel']):raise ValueError('Service recovery requires a failed job and attested crash journal; never resume explicit cancellation')
            if row['state']=='failed' and not connector_failure and not comfy_recovery:raise ValueError('Failure needs targeted repair, not a generic retry')
            checkpoints={r['stage'] for r in c.execute('SELECT stage FROM checkpoints WHERE job=?',(j,))}
            stage=next((s for s in STAGES if s not in checkpoints),None)
            if stage is None:raise ValueError('Job already has all checkpoints')
            attempts=c.execute('SELECT count FROM attempts WHERE job=? AND stage=?',(j,stage)).fetchone();count=attempts['count'] if attempts else 0
            grant=c.execute('SELECT attempt_limit FROM recovery_grants WHERE job=? AND stage=?',(j,stage)).fetchone()
            limit=grant['attempt_limit'] if grant else base
            if count>=limit:
                if row['stage']=='music' and (Path(row['output'])/'music.mp3').is_file() and 'Silent or clipped audio' in (row['error'] or ''):
                    limit=count+1
                    c.execute('INSERT OR REPLACE INTO recovery_grants VALUES(?,?,?,?,?)',(j,stage,limit,'music normalization applied after MP3 peak overshoot',time.time()))
                elif grant:raise ValueError('One-time recovery allowance exhausted; attempts are preserved')
                elif count!=base:raise ValueError('Unexpected attempt history; no recovery budget granted')
                else:
                    limit=base+1
                    c.execute('INSERT INTO recovery_grants VALUES(?,?,?,?,?)',(j,stage,limit,'confirmed Comfy native-crash recovery' if comfy_recovery else 'explicit owner continuation after connector repair',time.time()))
            c.execute("UPDATE jobs SET state='queued',cancel=0,error=NULL,next_at=0,updated=? WHERE id=?",(time.time(),j))
            self.event(c,j,stage,'service_crash_resume' if actor=='service_recovery' else 'owner_resume',f'Keep checkpoints and {count} prior attempts; effective limit {limit}; old receipts preserved')
        return self.get(j)
    def active(self,j):
        if self.get(j)['cancel']: raise Cancelled()
    def lock(self,owner,ttl=30):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE'); r=c.execute('SELECT * FROM worker_lock WHERE id=1').fetchone()
            if r and r['owner']!=owner and r['expires']>time.time(): return False
            c.execute('INSERT OR REPLACE INTO worker_lock VALUES(1,?,?)',(owner,time.time()+ttl)); return True
    def release(self,owner):
        with self.db() as c: c.execute('DELETE FROM worker_lock WHERE owner=?',(owner,))

class Worker:
    """One local worker lease; heartbeated by service even during blocking stages."""
    def __init__(self,store,handlers,max_attempts=3,backoff=2):
        self.store=store;self.handlers=handlers;self.max_attempts=max_attempts;self.backoff=backoff;self.owner=str(uuid.uuid4())
    def step(self):
        s=self.store
        if not s.lock(self.owner): return False
        try:
            jobs=[j for j in s.list() if j['state'] in ('queued','running','retrying') and j['next_at']<=time.time()]
            if not jobs:return False
            j=jobs[-1]; jid=j['id']; stage=next((x for x in STAGES if x not in j['checkpoints']),None)
            if not stage: raise PermanentError('Missing verified completion transition')
            allowed_attempts=s.attempt_limit(jid,stage,self.max_attempts)
            try:
                s.active(jid)
                # A checkpoint is trusted only if every attested file still matches.
                for cp in j['checkpoints'].values():
                    for a in cp.get('assets',[]):
                        if not Path(a['path']).is_file() or digest(a['path'])!=a['sha256']: raise PermanentError('Checkpoint asset missing or changed')
                with s.db() as c:
                    row=c.execute('SELECT count FROM attempts WHERE job=? AND stage=?',(jid,stage)).fetchone(); count=(row[0] if row else 0)+1
                    if count>allowed_attempts: raise PermanentError('Retry budget exhausted after restart')
                    c.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(jid,stage,count))
                    c.execute("UPDATE jobs SET state='running',stage=?,updated=? WHERE id=?",(stage,time.time(),jid));s.event(c,jid,stage,'started')
                value=self.handlers[stage](j,lambda:s.active(jid))
                s.active(jid)
                if not isinstance(value,dict):raise PermanentError('Stage returned invalid checkpoint')
                if stage=='verify' and value.get('verified') is not True:raise PermanentError('Verification did not pass')
                mirror=Path(j['output'])/(stage+'.json');temporary=mirror.with_suffix('.part.json')
                temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(mirror)
                with s.db() as c:
                    c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(jid,stage,json.dumps(value)))
                    c.execute('UPDATE jobs SET state=?,error=NULL,next_at=0,updated=? WHERE id=?',('completed' if stage=='verify' else 'queued',time.time(),jid));s.event(c,jid,stage,'completed')
            except Cancelled:
                with s.db() as c:c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=?",(time.time(),jid));s.event(c,jid,stage,'cancelled')
            except Exception as e:
                attempts=s.get(jid)['attempts'].get(stage,0)
                terminal=isinstance(e,PermanentError) or attempts>=allowed_attempts
                with s.db() as c:
                    c.execute('UPDATE jobs SET state=?,error=?,next_at=?,updated=? WHERE id=?',('failed' if terminal else 'retrying',str(e)[:2000],time.time()+self.backoff*2**max(0,attempts-1),time.time(),jid));s.event(c,jid,stage,'failed' if terminal else 'retry',str(e)[:2000])
            return True
        finally:s.release(self.owner)
