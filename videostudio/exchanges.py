"""Durable transport for the EXISTING Chrome connector protocol.
The extension owns trusted Start, delivery receipts and browser authorization.
This server owns immutable prompts, response correlation and idempotent imports.
"""
import hashlib,json,time,uuid
from .core import PermanentError

SMOKE_PROMPT='Engineering connection test only. Return exactly one JSON object: {"connection_test":"videostudio","ok":true}. Do not create media or use tools.'
EXTENSION_HEARTBEAT_SECONDS=90

def parse_reply(text):
    if not isinstance(text,str) or len(text.encode('utf8'))>700000:raise ValueError('Response too large')
    raw=text.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):raw=raw[8:-4]
    elif raw.startswith('```\n') and raw.endswith('\n```'):raw=raw[4:-4]
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise ValueError('Duplicate JSON key')
            d[k]=v
        return d
    def invalid(value):raise ValueError('Nonfinite JSON number')
    d=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    if not isinstance(d,dict):raise ValueError('JSON object required')
    return d

class Exchanges:
    def __init__(self,store):
        self.store=store
        with store.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS connector_scopes(id TEXT PRIMARY KEY,job TEXT UNIQUE,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS connector_bridge_memberships(scope TEXT PRIMARY KEY,bridge TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS connector_bridge_memberships_bridge ON connector_bridge_memberships(bridge);
            CREATE TABLE IF NOT EXISTS connector_dismissed_jobs(job TEXT PRIMARY KEY,bridge TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS job_file_deletions(job TEXT PRIMARY KEY,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS connector_status(scope TEXT PRIMARY KEY,status TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS connector_exchanges(id TEXT PRIMARY KEY,scope TEXT NOT NULL,request_key TEXT NOT NULL,prompt TEXT NOT NULL,response TEXT,version INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,UNIQUE(scope,request_key));
            CREATE TABLE IF NOT EXISTS connector_smokes(scope TEXT NOT NULL,exchange_id TEXT NOT NULL UNIQUE,created REAL NOT NULL);''')
    def accepted_extension(self,scope):
        """Require a live bridge and its exact latest correlated smoke reply."""
        try:return self.extension_status(scope)['ready']
        except KeyError:return False
    def extension_status(self,scope):
        """Read transport liveness and latest smoke independently for this scope's root."""
        with self.store.db() as c:
            known=c.execute('SELECT id FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if not known:raise KeyError(scope)
            parent=c.execute('SELECT bridge FROM connector_bridge_memberships WHERE scope=?',(scope,)).fetchone()
            bridge=parent['bridge'] if parent else scope
            status=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(bridge,)).fetchone()
            smoke=c.execute('SELECT e.id,e.response FROM connector_smokes s JOIN connector_exchanges e ON e.id=s.exchange_id AND e.scope=s.scope WHERE s.scope=? ORDER BY s.created DESC,s.rowid DESC LIMIT 1',(bridge,)).fetchone()
        try:s=json.loads(status['status']) if status else {}
        except (ValueError,TypeError):s={}
        if not isinstance(s,dict):s={}
        age=max(0,time.time()-status['updated']) if status else None
        builds=('videostudio-extension-0.3.0',) if parent else ('videostudio-extension-0.2.0','videostudio-extension-0.2.1','videostudio-extension-0.2.2','videostudio-extension-0.3.0')
        heartbeat={'present':bool(status),'updated':status['updated'] if status else None,'age_seconds':age,
                   'freshness_seconds':EXTENSION_HEARTBEAT_SECONDS,'fresh':age is not None and age<=EXTENSION_HEARTBEAT_SECONDS,
                   'build':s.get('build'),'runtime_version':s.get('runtime_version'),'supported_build':s.get('build') in builds,'active':s.get('stage')=='active',
                   'connected':s.get('connected') is True,'enabled':s.get('enabled') is True,'error':s.get('error')}
        problems=[]
        if not heartbeat['present']:problems.append('Chưa nhận heartbeat từ extension; bấm Start trên tab Studio này.')
        else:
            if not heartbeat['fresh']:problems.append(f'Heartbeat đã cũ ({age:.0f} giây; tối đa {EXTENSION_HEARTBEAT_SECONDS} giây); kiểm tra bridge đang chạy.')
            if not heartbeat['supported_build']:problems.append('Phiên bản extension chưa được hỗ trợ; tải lại extension VideoStudio 0.3.0.')
            if not heartbeat['active']:problems.append('Bridge chưa ở trạng thái active; bấm Start trên tab Studio.')
            if not heartbeat['connected']:problems.append('Extension chưa kết nối với tab ChatGPT.')
            if not heartbeat['enabled']:problems.append('Bridge chưa được bật; bấm Start trên tab Studio.')
        heartbeat['ready']=not problems
        heartbeat['reason']=' '.join(problems) if problems else f'Bridge đang kết nối; heartbeat {age:.0f} giây trước (tối đa {EXTENSION_HEARTBEAT_SECONDS} giây).'
        smoke_status='missing';smoke_reason='Chưa có bài kiểm tra kết nối; bấm Kiểm tra kết nối.'
        if smoke:
            if smoke['response'] is None:
                smoke_status='pending';smoke_reason='Bài kiểm tra kết nối mới nhất đang chờ phản hồi ChatGPT khớp request ID.'
                error=s.get('error')
                if isinstance(error,dict):
                    detail=error.get('reason') or error.get('message')
                    if isinstance(detail,str) and detail:smoke_reason+=' Lỗi extension: '+detail
            else:
                try:answer=json.loads(smoke['response'])
                except (ValueError,TypeError):answer=None
                valid=isinstance(answer,dict) and set(answer)=={'connection_test','ok'} and answer.get('connection_test')=='videostudio' and answer.get('ok') is True
                smoke_status='accepted' if valid else 'invalid'
                smoke_reason='Bài kiểm tra kết nối mới nhất đã có phản hồi JSON hợp lệ, khớp request ID.' if valid else 'Phản hồi bài kiểm tra kết nối mới nhất không đúng JSON yêu cầu; cần kiểm tra kết nối lại.'
        return {'scope':scope,'bridge':bridge,'heartbeat':heartbeat,
                'smoke':{'status':smoke_status,'exchange_id':smoke['id'] if smoke else None,'reason':smoke_reason},
                'ready':heartbeat['ready'] and smoke_status=='accepted'}
    def bridge_root(self,bridge):
        with self.store.db() as c:
            root=c.execute('SELECT id FROM connector_scopes WHERE id=? AND NOT EXISTS (SELECT 1 FROM connector_bridge_memberships WHERE scope=?)',(bridge,bridge)).fetchone()
        if not root:raise KeyError(bridge)
        return bridge
    def bridge_supports_sessions(self,bridge):
        self.bridge_root(bridge)
        heartbeat=self.extension_status(bridge)['heartbeat']
        return heartbeat['ready'] and heartbeat['build']=='videostudio-extension-0.3.0'
    def bridge_sessions(self,bridge):
        self.bridge_root(bridge)
        with self.store.db() as c:
            rows=c.execute('SELECT s.id AS scope,j.* FROM connector_scopes s JOIN jobs j ON j.id=s.job LEFT JOIN connector_bridge_memberships m ON m.scope=s.id WHERE (s.id=? OR m.bridge=?) AND NOT EXISTS(SELECT 1 FROM connector_dismissed_jobs d WHERE d.job=j.id) ORDER BY j.created,j.id',(bridge,bridge)).fetchall()
            items=[]
            for row in rows:
                request=json.loads(row['request'])
                plan=c.execute("SELECT value FROM checkpoints WHERE job=? AND stage='plan'",(row['id'],)).fetchone()
                title=(json.loads(plan['value']).get('title') if plan else None) or request['idea'].splitlines()[0][:160]
                items.append({'scope':row['scope'],'job_id':row['id'],'title':title,'project':request.get('project','Dự án mặc định'),
                              'state':row['state'],'stage':row['stage'],'error':row['error'],'cancel_requested':bool(row['cancel']),'created':row['created'],'image_provider':request.get('image_provider','comfy')})
        return {'items':items}
    def bridge_job(self,bridge,job):
        self.bridge_root(bridge)
        with self.store.db() as c:
            row=c.execute('SELECT s.id AS scope,j.*,EXISTS(SELECT 1 FROM connector_dismissed_jobs d WHERE d.job=j.id AND d.bridge=?) AS dismissed FROM jobs j JOIN connector_scopes s ON s.job=j.id LEFT JOIN connector_bridge_memberships m ON m.scope=s.id WHERE j.id=? AND (s.id=? OR m.bridge=?)',(bridge,job,bridge,bridge)).fetchone()
        if not row:raise KeyError(job)
        return {'scope':row['scope'],'job_id':row['id'],'state':row['state'],'dismissed':bool(row['dismissed'])}
    def dismiss_job(self,bridge,job,delete_files=False):
        from .project_lifecycle import OutputRemoval, image_tasks_active
        self.bridge_job(bridge,job)
        removal=None
        try:
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
                if row['state'] not in ('completed','failed','cancelled'):raise ValueError('Chỉ xóa phiên đã hoàn tất, lỗi hoặc đã hủy')
                if delete_files:
                    if image_tasks_active(c,[job]):raise ValueError('Scene image đang chạy hoặc chờ; dừng trước khi xóa tệp')
                    removal=OutputRemoval(self.store,c,[dict(row)]);removal.stage()
                    c.execute('INSERT OR IGNORE INTO job_file_deletions VALUES(?,?)',(job,time.time()))
                c.execute('UPDATE jobs SET cancel=1,updated=? WHERE id=?',(time.time(),job))
                c.execute('INSERT OR IGNORE INTO connector_dismissed_jobs VALUES(?,?,?)',(job,bridge,time.time()))
                c.execute("UPDATE scene_image_tasks SET state='cancelled',updated=? WHERE job=? AND state IN ('queued','running')",(time.time(),job))
                self.store.event(c,job,None,'session_dismissed','delete_files='+str(delete_files).lower())
        except Exception:
            if removal:removal.rollback()
            raise
        pending=removal.purge() if removal else False
        with self.store.db() as c:files_deleted=bool(c.execute('SELECT 1 FROM job_file_deletions WHERE job=?',(job,)).fetchone())
        return {**self.bridge_job(bridge,job),'files_deleted':files_deleted,'files_preserved':not files_deleted,'cleanup_pending':pending}
    def bridge_pending(self,bridge):
        self.bridge_root(bridge)
        with self.store.db() as c:
            rows=c.execute('''SELECT e.*,s.job,EXISTS(SELECT 1 FROM connector_smokes smoke WHERE smoke.exchange_id=e.id) AS is_smoke FROM connector_exchanges e JOIN connector_scopes s ON s.id=e.scope
                LEFT JOIN connector_bridge_memberships m ON m.scope=s.id LEFT JOIN jobs j ON j.id=s.job
                WHERE (s.id=? OR m.bridge=?) AND e.response IS NULL AND
                (NOT EXISTS(SELECT 1 FROM connector_dismissed_jobs d WHERE d.job=j.id) OR EXISTS(SELECT 1 FROM connector_smokes sm WHERE sm.exchange_id=e.id)) AND
                ((j.state IN ('queued','running','retrying') AND j.cancel=0) OR
                 (s.id=? AND EXISTS (SELECT 1 FROM connector_smokes smoke WHERE smoke.exchange_id=e.id)))
                ORDER BY e.created,e.rowid''',(bridge,bridge,bridge)).fetchall()
        seen=set();items=[]
        for row in rows:
            if row['scope'] in seen:continue
            seen.add(row['scope'])
            items.append({'scope':row['scope'],'job_id':None if row['is_smoke'] else row['job'],'is_smoke':bool(row['is_smoke']),'id':row['id'],'version':row['version'],'prompt':row['prompt'],'attachments':[]})
        return {'items':items}
    def enqueue_smoke(self,scope):
        """Create a distinct synthetic exchange after any preceding pending item has settled."""
        pending=self.pending(scope)['items']
        with self.store.db() as c:
            terminal=c.execute("SELECT j.id FROM connector_scopes s JOIN jobs j ON j.id=s.job WHERE s.id=? AND (j.state NOT IN ('queued','running','retrying') OR j.cancel=1)",(scope,)).fetchone()
            smoke_pending=c.execute('SELECT e.id FROM connector_smokes s JOIN connector_exchanges e ON e.id=s.exchange_id WHERE s.scope=? AND e.response IS NULL',(scope,)).fetchone()
        # A retained failed-job receipt must not prevent testing its parent bridge.
        if (pending and not terminal) or smoke_pending:
            raise PermanentError('Previous connector exchange is still pending; do not send a duplicate')
        nonce=str(uuid.uuid4())
        identifier=self.enqueue(scope,SMOKE_PROMPT+'\nRequest nonce: '+nonce)
        with self.store.db() as c:
            c.execute('INSERT INTO connector_smokes(scope,exchange_id,created) VALUES(?,?,?)',(scope,identifier,time.time()))
        return identifier
    def scope(self):
        identifier=str(uuid.uuid4())
        with self.store.db() as c:c.execute('INSERT INTO connector_scopes(id,created) VALUES(?,?)',(identifier,time.time()))
        return identifier
    def bind(self,scope,job):
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT job FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if row is None or row['job'] not in (None,job):raise ValueError('Connector scope already bound or unknown')
            c.execute('UPDATE connector_scopes SET job=? WHERE id=?',(job,scope))
    def for_job(self,job):
        with self.store.db() as c:r=c.execute('SELECT id FROM connector_scopes WHERE job=?',(job,)).fetchone()
        if not r:raise PermanentError('Job lacks real-click connector scope')
        return r['id']
    def pending(self,scope):
        with self.store.db() as c:
            known=c.execute('SELECT id FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if not known:raise KeyError(scope)
            rows=c.execute('SELECT * FROM connector_exchanges WHERE scope=? AND response IS NULL ORDER BY created LIMIT 1',(scope,)).fetchall()
        return {'items':[{'id':r['id'],'version':r['version'],'prompt':r['prompt'],'attachments':[]} for r in rows]}
    def get(self,scope,identifier):
        with self.store.db() as c:r=c.execute('SELECT * FROM connector_exchanges WHERE scope=? AND id=?',(scope,identifier)).fetchone()
        if not r:raise KeyError(identifier)
        return dict(r)
    def receive(self,scope,identifier,version,text):
        if isinstance(text,(dict,list)):
            text=json.dumps(text,ensure_ascii=False)
        value=parse_reply(text);serialized=json.dumps(value,ensure_ascii=False,sort_keys=True)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM connector_exchanges WHERE scope=? AND id=?',(scope,identifier)).fetchone()
            if not r:raise KeyError(identifier)
            if version!=r['version']:raise ValueError('Exchange version mismatch')
            if r['response'] is not None and r['response']!=serialized:raise ValueError('Immutable response conflict')
            c.execute('UPDATE connector_exchanges SET response=? WHERE id=?',(serialized,identifier))
        return {'accepted':True,'id':identifier,'version':version}
    def enqueue(self,scope,prompt):
        self.pending(scope)
        key=hashlib.sha256(prompt.encode()).hexdigest()
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT id FROM connector_exchanges WHERE scope=? AND request_key=?',(scope,key)).fetchone()
            identifier=row['id'] if row else str(uuid.uuid4())
            if not row:
                immutable=f'YÊU CẦU STUDIO {identifier}\n'+prompt
                if len(immutable.encode())>700000:raise PermanentError('Connector request exceeds size budget')
                c.execute('INSERT INTO connector_exchanges(id,scope,request_key,prompt,created) VALUES(?,?,?,?,?)',(identifier,scope,key,immutable,time.time()))
        return identifier
    def request(self,job,prompt,check,timeout=180):
        scope=self.for_job(job)
        identifier=self.enqueue(scope,prompt)
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            check();r=self.get(scope,identifier)
            if r['response'] is not None:return json.loads(r['response'])
            time.sleep(.5)
        raise TimeoutError('Chrome connector response unavailable; request retained for correlated recovery, not resubmitted')
