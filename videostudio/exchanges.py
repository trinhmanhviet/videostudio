"""Durable transport for the EXISTING Chrome connector protocol.
The extension owns trusted Start, delivery receipts and browser authorization.
This server owns immutable prompts, response correlation and idempotent imports.
"""
import hashlib,json,time,uuid
from .core import PermanentError

SMOKE_PROMPT='Engineering connection test only. Return exactly one JSON object: {"connection_test":"videostudio","ok":true}. Do not create media or use tools.'

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
            CREATE TABLE IF NOT EXISTS connector_status(scope TEXT PRIMARY KEY,status TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS connector_exchanges(id TEXT PRIMARY KEY,scope TEXT NOT NULL,request_key TEXT NOT NULL,prompt TEXT NOT NULL,response TEXT,version INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,UNIQUE(scope,request_key));
            CREATE TABLE IF NOT EXISTS connector_smokes(scope TEXT NOT NULL,exchange_id TEXT NOT NULL UNIQUE,created REAL NOT NULL);''')
    def accepted_extension(self,scope):
        """A fresh, scope-bound visible bridge and exact prior smoke reply are required."""
        with self.store.db() as c:
            parent=c.execute('SELECT bridge FROM connector_bridge_memberships WHERE scope=?',(scope,)).fetchone()
            if parent:scope=parent['bridge']
            status=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(scope,)).fetchone()
            smoke=c.execute('SELECT e.response FROM connector_smokes s JOIN connector_exchanges e ON e.id=s.exchange_id WHERE s.scope=? ORDER BY s.created DESC,s.rowid DESC LIMIT 1',(scope,)).fetchone()
        if not status or not smoke or not smoke['response'] or time.time()-status['updated']>30:return False
        try:
            s=json.loads(status['status']);answer=json.loads(smoke['response'])
        except (ValueError,TypeError):return False
        builds=('videostudio-extension-0.3.0',) if parent else ('videostudio-extension-0.2.0','videostudio-extension-0.2.1','videostudio-extension-0.2.2','videostudio-extension-0.3.0')
        return (s.get('build') in builds and s.get('stage')=='active'
                and s.get('connected') is True and s.get('enabled') is True
                and answer=={'connection_test':'videostudio','ok':True})
    def bridge_root(self,bridge):
        with self.store.db() as c:
            root=c.execute('SELECT id FROM connector_scopes WHERE id=? AND NOT EXISTS (SELECT 1 FROM connector_bridge_memberships WHERE scope=?)',(bridge,bridge)).fetchone()
        if not root:raise KeyError(bridge)
        return bridge
    def bridge_supports_sessions(self,bridge):
        self.bridge_root(bridge)
        with self.store.db() as c:
            row=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(bridge,)).fetchone()
        if not row or time.time()-row['updated']>30:return False
        status=json.loads(row['status'])
        return (status.get('build')=='videostudio-extension-0.3.0' and status.get('stage')=='active'
                and status.get('connected') is True and status.get('enabled') is True)
    def bridge_sessions(self,bridge):
        self.bridge_root(bridge)
        with self.store.db() as c:
            rows=c.execute('SELECT s.id AS scope,j.* FROM connector_scopes s JOIN jobs j ON j.id=s.job LEFT JOIN connector_bridge_memberships m ON m.scope=s.id WHERE s.id=? OR m.bridge=? ORDER BY j.created,j.id',(bridge,bridge)).fetchall()
            items=[]
            for row in rows:
                request=json.loads(row['request'])
                plan=c.execute("SELECT value FROM checkpoints WHERE job=? AND stage='plan'",(row['id'],)).fetchone()
                title=(json.loads(plan['value']).get('title') if plan else None) or request['idea'].splitlines()[0][:160]
                items.append({'scope':row['scope'],'job_id':row['id'],'title':title,'project':request.get('project','Dự án mặc định'),
                              'state':row['state'],'stage':row['stage'],'error':row['error'],'cancel_requested':bool(row['cancel']),'created':row['created']})
        return {'items':items}
    def bridge_pending(self,bridge):
        self.bridge_root(bridge)
        with self.store.db() as c:
            rows=c.execute('''SELECT e.*,s.job,EXISTS(SELECT 1 FROM connector_smokes smoke WHERE smoke.exchange_id=e.id) AS is_smoke FROM connector_exchanges e JOIN connector_scopes s ON s.id=e.scope
                LEFT JOIN connector_bridge_memberships m ON m.scope=s.id LEFT JOIN jobs j ON j.id=s.job
                WHERE (s.id=? OR m.bridge=?) AND e.response IS NULL AND
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
