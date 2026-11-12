"""Explicit post-and-clean receipts; only owned output is removed.

An on-disk move journal bridges SQLite commit and filesystem quarantine. Heavy
job content is removed, while tiny posting/idempotency/timing receipts survive.
"""
from __future__ import annotations
import hashlib,json,os,re,shutil,time,uuid,unicodedata,threading
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
from .project_lifecycle import OutputRemoval,has_table,image_tasks_active,LIVE_SCHEDULE_STATES,_alias,_strings
from .paths import DATA_ROOT


def encoded(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')
def fold(value):return ''.join(c for c in unicodedata.normalize('NFD',value.casefold().replace('đ','d')) if not unicodedata.combining(c))
def text(value,limit,label,optional=False):
    if not isinstance(value,str) or len(value)>limit or (not optional and not value.strip()):raise ValueError(label+' không hợp lệ')
    return value.strip()


class PostedCleanup:
    def __init__(self,store):
        self.store=store
        self.wake=threading.Event()
        self.journal_root=store.path.parent/'publication-cleanup'
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS publication_history(
                    id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL,idem TEXT UNIQUE NOT NULL,
                    fingerprint TEXT NOT NULL,source_idem TEXT UNIQUE NOT NULL,request_sha256 TEXT NOT NULL,
                    title TEXT NOT NULL,project TEXT NOT NULL,platform TEXT NOT NULL,channel_name TEXT NOT NULL,
                    post_url TEXT NOT NULL,published_at REAL NOT NULL,created REAL NOT NULL,posts TEXT NOT NULL,
                    cleanup_state TEXT NOT NULL DEFAULT 'pending',error TEXT,lease_until REAL NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS publication_cleanup_files(
                    entry_id TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(entry_id,path));
                CREATE TABLE IF NOT EXISTS publication_retired_batches(idem TEXT PRIMARY KEY,retired REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS voice_calibrations(
                    job_id TEXT PRIMARY KEY,voice_id TEXT NOT NULL,rate REAL NOT NULL,voice_sha256 TEXT,measured_at REAL NOT NULL);
            ''')
            if 'next_at' not in {row['name'] for row in db.execute('PRAGMA table_info(publication_history)')}:
                db.execute('ALTER TABLE publication_history ADD COLUMN next_at REAL NOT NULL DEFAULT 0')

    def _body(self,data):
        if not isinstance(data,dict) or data.get('confirm') is not True:raise ValueError('Cần xác nhận đã đăng và xóa job/tệp')
        if set(data)-{'confirm','title','platform','channel_name','post_url','published_at'}:raise ValueError('Trường dữ liệu không hợp lệ')
        if set(data)=={'confirm'}:return None
        platform=data.get('platform')
        if platform not in ('youtube','facebook','tiktok','other'):raise ValueError('Chọn nền tảng đã đăng')
        title=text(data.get('title'),300,'Tiêu đề')
        channel=text(data.get('channel_name',''),200,'Tên kênh',True)
        link=text(data.get('post_url',''),2000,'Link bài đăng',True)
        if link:
            parsed=urlparse(link)
            try:port=parsed.port
            except ValueError:raise ValueError('Link bài đăng không hợp lệ')
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<33 for c in link):raise ValueError('Link bài đăng phải là HTTPS, không kèm thông tin đăng nhập')
        raw=data.get('published_at')
        if not isinstance(raw,str):raise ValueError('Chọn ngày giờ đã đăng')
        at=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if at.tzinfo is None or at.timestamp()>time.time()+300:raise ValueError('Ngày giờ phải có múi giờ và không nằm trong tương lai')
        return {'title':title,'platform':platform,'channel_name':channel,'post_url':link,'published_at':at.timestamp()}

    def _automatic_metadata(self,db,raw):
        request=json.loads(raw['request']);title=''
        if has_table(db,'factory_items'):
            row=db.execute('SELECT title FROM factory_items WHERE job_id=? ORDER BY created DESC LIMIT 1',(raw['id'],)).fetchone()
            if row:title=row['title']
        if not title:
            for stage in ('script','plan'):
                row=db.execute('SELECT value FROM checkpoints WHERE job=? AND stage=?',(raw['id'],stage)).fetchone()
                if row:
                    value=json.loads(row['value']).get('title')
                    if isinstance(value,str) and value.strip():title=value;break
        if not title:title=request.get('project') or 'Video đã đăng'
        result={'title':str(title).strip()[:300],'platform':'other','channel_name':'','post_url':'','published_at':time.time()}
        if has_table(db,'publishing_schedules'):
            row=db.execute("SELECT * FROM publishing_schedules WHERE job_id=? AND state='published' ORDER BY rowid DESC LIMIT 1",(raw['id'],)).fetchone()
            if row:
                record=dict(row);result['platform']=record.get('platform') if record.get('platform') in ('youtube','facebook','tiktok','other') else 'other'
                result['channel_name']=str(record.get('channel_id') or '')[:200]
                if has_table(db,'publishing_channels'):
                    channel=db.execute('SELECT name FROM publishing_channels WHERE id=?',(record.get('channel_id'),)).fetchone()
                    if channel:result['channel_name']=channel['name'][:200]
                link=record.get('remote_url') or ''
                try:
                    parsed=urlparse(link)
                    if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password:result['post_url']=link[:2000]
                except ValueError:pass
                stamp=record.get('publish_at')
                if isinstance(stamp,(int,float)) and stamp==stamp and 0<stamp<result['published_at']:result['published_at']=stamp
        return result

    def _entry(self,row):
        value={k:row[k] for k in ('id','job_id','title','project','platform','channel_name','post_url','cleanup_state','error')}
        value['published_at']=iso(row['published_at']);value['created']=iso(row['created']);value['posts']=json.loads(row['posts'])
        return value

    def entry(self,identifier):
        with self.store.db() as db:row=db.execute('SELECT * FROM publication_history WHERE id=?',(identifier,)).fetchone()
        if row is None:raise KeyError(identifier)
        return self._entry(row)

    def history(self,q='',platform='',page=1,page_size=10):
        if type(page) is not int or page<1 or type(page_size) is not int or page_size not in (10,20,30):raise ValueError('Phân trang dùng 10, 20 hoặc 30 mục')
        if platform and platform not in ('youtube','facebook','tiktok','other'):raise ValueError('Nền tảng không hợp lệ')
        query=fold(text(q,500,'Tìm kiếm',True))
        with self.store.db() as db:rows=db.execute('SELECT * FROM publication_history ORDER BY published_at DESC,created DESC').fetchall()
        items=[self._entry(row) for row in rows if (not platform or row['platform']==platform) and (not query or query in fold(' '.join(str(row[k]) for k in ('title','project','channel_name','post_url'))))]
        total=len(items)
        return {'items':items[(page-1)*page_size:page*page_size],'total':total,'total_pages':max(1,(total+page_size-1)//page_size),'page':page,'page_size':page_size}

    def _write_journal(self,identifier,moves,job_id=None,task_ids=()):
        self.journal_root.mkdir(parents=True,exist_ok=True)
        target=self.journal_root/(identifier+'.json');temporary=target.with_suffix('.tmp')
        with temporary.open('w',encoding='utf8') as stream:
            stream.write(encoded({'entry_id':identifier,'job_id':job_id,'task_ids':list(task_ids),'moves':[[str(a),str(b)] for a,b in moves]}));stream.flush();os.fsync(stream.fileno())
        temporary.replace(target)
        return target

    def _external_targets(self,job_id,task_ids):
        # All ownership comes from database identifiers, never stored/client paths.
        if not isinstance(job_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',job_id):return {}
        data=self.store.path.parent.resolve();downloads=DATA_ROOT.resolve()/'chatgpt-images'
        targets={data/'editor-imports'/job_id:data}
        for task in task_ids:
            if not isinstance(task,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',task):raise ValueError('Invalid image task identity')
            targets[data/'scene-image-candidates'/(task+'.png')]=data
            targets[downloads/(task+'.png')]=DATA_ROOT.resolve()
            targets[downloads/'comfy-tasks'/task]=DATA_ROOT.resolve()
        return targets

    def _valid_move(self,target,quarantine,job_id=None,task_ids=()):
        root=self.store.outputs.resolve()
        allowed=self._external_targets(job_id,task_ids)
        destination=root if target.resolve().is_relative_to(root) and target.resolve()!=root else allowed.get(target)
        return (target.is_absolute() and destination is not None
                and quarantine.is_absolute() and quarantine.resolve().parent==destination
                and re.fullmatch(r'\.deleted-[a-f0-9]{32}',quarantine.name)
                and not any(_alias(p) for p in (target,quarantine,*target.parents,*quarantine.parents)))

    def _purge_path(self,path):
        roots={self.store.outputs.resolve(),self.store.path.parent.resolve(),DATA_ROOT.resolve()}
        if path.resolve().parent not in roots or not re.fullmatch(r'\.deleted-[a-f0-9]{32}',path.name) or any(_alias(p) for p in (path,*path.parents)):raise ValueError('Vị trí dọn không hợp lệ')
        if not path.exists():return
        if path.is_dir():
            if any(_alias(child) for child in path.rglob('*')):raise ValueError('Không dọn qua symlink/junction')
            shutil.rmtree(path)
        else:path.unlink()

    def _owned_targets(self,db,job,removal,task_ids):
        identifier=job['id'];targets={target:self.store.outputs.resolve() for target in removal.targets}
        targets.update(self._external_targets(identifier,task_ids))
        # A failed restore must be resolved before a replay can retire this job.
        for journal in self.journal_root.glob('*.json'):
            record=json.loads(journal.read_text(encoding='utf8'))
            if db.execute('SELECT 1 FROM publication_history WHERE id=?',(record['entry_id'],)).fetchone():continue
            if any(Path(original) in targets and Path(removed).exists() for original,removed in record['moves']):raise ValueError('Lần dọn trước chưa khôi phục xong; tệp vẫn được giữ an toàn')
        for target in targets:
            if any(_alias(p) for p in (target,*target.parents)) or (target.is_dir() and any(_alias(p) for p in target.rglob('*'))):raise ValueError('Không dọn qua symlink/junction')
        resolved_references={}
        def touches(value):
            try:
                path=Path(value)
                if not path.is_absolute():return False
                key=str(path)
                if key not in resolved_references:resolved_references[key]=path.resolve()
                resolved=resolved_references[key]
                return any(resolved==target or resolved.is_relative_to(target) for target in targets)
            except (OSError,ValueError):return False
        for table,column,key in (('checkpoints','value','job'),('edit_plan_heads','value','job'),('edit_plan_assets','value','job'),('scene_image_tasks','result','job'),('scene_image_edits','path','job')):
            if not has_table(db,table):continue
            for row in db.execute('SELECT '+key+' AS owner,'+column+' AS value FROM '+table):
                if row['owner']==identifier or not row['value']:continue
                try:values=[row['value']] if column=='path' else list(_strings(json.loads(row['value'])))
                except (TypeError,ValueError):raise ValueError('Không thể kiểm chứng tệp dùng chung')
                if any(touches(value) for value in values):raise ValueError('Tệp đang được job khác dùng chung; giữ lại tệp')
        for table in ('scene_exports','edit_plan_exports'):
            if has_table(db,table) and db.execute('SELECT 1 FROM '+table+' e JOIN jobs j ON j.id=e.child WHERE e.parent=? AND e.child<>?',(identifier,identifier)).fetchone():raise ValueError('Bản xuất khác còn phụ thuộc job này; giữ lại tệp')
        return targets

    def _purge_job(self,db,job):
        identifier=job['id']
        # Keep numeric calibration, not narration or any source/audio paths.
        from .voice_timing import _rate
        speech=job['checkpoints'].get('speech',{});rate=_rate(speech)
        if rate:
            db.execute('INSERT OR REPLACE INTO voice_calibrations VALUES(?,?,?,?,?)',(identifier,job['request']['voice_id'],rate,speech.get('voice_sha256'),time.time()))
            db.execute('DELETE FROM voice_calibrations WHERE voice_id=? AND job_id NOT IN (SELECT job_id FROM voice_calibrations WHERE voice_id=? ORDER BY measured_at DESC LIMIT 8)',(job['request']['voice_id'],job['request']['voice_id']))
        if has_table(db,'factory_items'):
            batches=[r[0] for r in db.execute('SELECT DISTINCT batch_id FROM factory_items WHERE job_id=?',(identifier,))]
            db.execute('DELETE FROM factory_items WHERE job_id=?',(identifier,))
            for batch in batches:
                if not db.execute('SELECT 1 FROM factory_items WHERE batch_id=?',(batch,)).fetchone():
                    receipt=db.execute('SELECT idem FROM factory_batches WHERE id=?',(batch,)).fetchone()
                    if receipt:db.execute('INSERT OR IGNORE INTO publication_retired_batches VALUES(?,?)',(receipt['idem'],time.time()))
                    db.execute('DELETE FROM factory_batches WHERE id=?',(batch,))
        if has_table(db,'scene_image_sources') and has_table(db,'scene_image_edits'):
            db.execute('DELETE FROM scene_image_sources WHERE edit IN (SELECT id FROM scene_image_edits WHERE job=?)',(identifier,))
        for table,column in (('edit_plan_heads','job'),('edit_plan_assets','job'),('scene_editor_heads','job'),
                             ('scene_active_edits','job'),('scene_user_approvals','job'),('scene_exports','child'),('edit_plan_exports','child'),
                             ('checkpoints','job'),('attempts','job'),('events','job'),('recovery_grants','job'),
                             ('flow_account_changes','job'),('scene_image_tasks','job'),('scene_image_edits','job'),
                             ('factory_video_versions','job_id'),('factory_video_approvals','job_id'),('factory_video_attestations','job_id'),
                             ('publishing_schedules','job_id'),('connector_dismissed_jobs','job')):
            if has_table(db,table) and column in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
                db.execute('DELETE FROM '+table+' WHERE '+column+'=?',(identifier,))
        if has_table(db,'connector_scopes'):
            scopes=[r[0] for r in db.execute('SELECT id FROM connector_scopes WHERE job=?',(identifier,))]
            for scope in scopes:
                member=has_table(db,'connector_bridge_memberships') and db.execute('SELECT 1 FROM connector_bridge_memberships WHERE scope=?',(scope,)).fetchone()
                if member:
                    for table,column in (('connector_exchanges','scope'),('connector_smokes','scope'),('connector_status','scope'),('connector_bridge_memberships','scope')):
                        if has_table(db,table):db.execute('DELETE FROM '+table+' WHERE '+column+'=?',(scope,))
                    db.execute('DELETE FROM connector_scopes WHERE id=?',(scope,))
                else:
                    # Shared bridge roots and their smoke receipts remain usable.
                    if has_table(db,'connector_exchanges'):
                        if has_table(db,'connector_smokes'):db.execute('DELETE FROM connector_exchanges WHERE scope=? AND NOT EXISTS (SELECT 1 FROM connector_smokes s WHERE s.exchange_id=connector_exchanges.id)',(scope,))
                        else:db.execute('DELETE FROM connector_exchanges WHERE scope=?',(scope,))
                    db.execute('UPDATE connector_scopes SET job=NULL WHERE id=?',(scope,))
        db.execute('DELETE FROM jobs WHERE id=?',(identifier,))
        # Hide an otherwise empty factory project, while allowing its name again.
        project=job['request'].get('project')
        if project and not db.execute("SELECT 1 FROM jobs WHERE json_extract(request,'$.project')=?",(project,)).fetchone():
            db.execute('DELETE FROM projects WHERE name=?',(project,))
            if has_table(db,'project_output_roots'):db.execute('DELETE FROM project_output_roots WHERE project=?',(project,))

    def posted_cleanup(self,job_id,data,key,defer_purge=False):
        normalized=self._body(data);key=text(key,200,'Idempotency-Key')
        fingerprint=hashlib.sha256(encoded({'job_id':job_id,**normalized} if normalized is not None else {'job_id':job_id,'confirm_only':True}).encode()).hexdigest()
        self.recover()
        moves=[];journal=None;identifier=str(uuid.uuid4());committed=False
        try:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                existing=db.execute('SELECT * FROM publication_history WHERE idem=? OR job_id=?',(key,job_id)).fetchone()
                if existing:
                    if existing['fingerprint']!=fingerprint:raise ValueError('Job hoặc khóa này đã được ghi nhận với thông tin khác')
                    return {'ok':True,'entry':self._entry(existing),'cleanup_pending':existing['cleanup_state']!='completed'}
                raw=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
                if raw is None:raise KeyError(job_id)
                if raw['state']!='completed':raise ValueError('Chỉ dọn video hoàn tất; tác vụ đang chạy/lỗi phải xử lý riêng')
                if normalized is None:normalized=self._automatic_metadata(db,raw)
                if has_table(db,'job_deletions') and db.execute('SELECT 1 FROM job_deletions WHERE job=?',(job_id,)).fetchone():raise ValueError('Video đã bị xóa')
                if image_tasks_active(db,[job_id]):raise ValueError('Video có ảnh cảnh đang chạy; chờ hoàn tất trước khi dọn')
                task_ids=[]
                if has_table(db,'scene_image_tasks'):
                    tasks=db.execute('SELECT id,state FROM scene_image_tasks WHERE job=?',(job_id,)).fetchall()
                    if any(task['state'] not in ('completed','applied','failed','cancelled') for task in tasks):raise ValueError('Ảnh cảnh chưa có kết quả chắc chắn; xử lý trước khi dọn')
                    task_ids=[task['id'] for task in tasks]
                posts=[{'platform':normalized['platform'],'channel_name':normalized['channel_name'],'post_url':normalized['post_url'],'published_at':iso(normalized['published_at'])}]
                if has_table(db,'publishing_schedules'):
                    if db.execute('SELECT 1 FROM publishing_schedules WHERE job_id=? AND state IN (%s)'%','.join('?'*len(LIVE_SCHEDULE_STATES)),(job_id,*LIVE_SCHEDULE_STATES)).fetchone():raise ValueError('Video còn lịch đăng chưa kết thúc; hủy/đối soát lịch trước khi dọn')
                    for row in db.execute("SELECT * FROM publishing_schedules WHERE job_id=? AND state='published'",(job_id,)):
                        record=dict(row);posts.append({'platform':record.get('platform','other'),'channel_name':record.get('channel_id',''),'post_url':record.get('remote_url') or '', 'published_at':iso(record.get('publish_at') or normalized['published_at'])})
                job=dict(raw);job['request']=json.loads(raw['request'])
                job['checkpoints']={r['stage']:json.loads(r['value']) for r in db.execute('SELECT stage,value FROM checkpoints WHERE job=?',(job_id,))}
                if job['checkpoints'].get('verify',{}).get('verified') is not True:raise ValueError('Video chưa được kiểm tra hoàn tất')
                removal=OutputRemoval(self.store,db,[job])
                targets=self._owned_targets(db,job,removal,task_ids)
                moves=[(target,root/('.deleted-'+uuid.uuid4().hex)) for target,root in targets.items() if target.exists()]
                journal=self._write_journal(identifier,moves,job_id,task_ids)
                for target,quarantine in moves:
                    if not self._valid_move(target,quarantine,job_id,task_ids):raise ValueError('Đường dẫn dọn tệp không hợp lệ')
                    target.rename(quarantine)
                db.execute('''INSERT INTO publication_history(id,job_id,idem,fingerprint,source_idem,request_sha256,title,project,platform,channel_name,post_url,published_at,created,posts)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(identifier,job_id,key,fingerprint,raw['idem'],hashlib.sha256(raw['request'].encode()).hexdigest(),normalized['title'],job['request'].get('project',''),normalized['platform'],normalized['channel_name'],normalized['post_url'],normalized['published_at'],time.time(),encoded(posts)))
                db.executemany('INSERT INTO publication_cleanup_files VALUES(?,?)',[(identifier,str(q)) for _,q in moves])
                self._purge_job(db,job)
            committed=True
        except Exception:
            if not committed:
                restored=True
                for target,quarantine in reversed(moves):
                    if quarantine.exists():
                        if target.exists():restored=False;continue
                        try:quarantine.rename(target)
                        except OSError:restored=False
                if journal and restored:journal.unlink(missing_ok=True)
            raise
        if defer_purge:
            self.wake.set()
            entry=self.entry(identifier)
            return {'ok':True,'entry':entry,'cleanup_pending':entry['cleanup_state']!='completed'}
        return self.retry_cleanup(identifier)

    def status(self,job_id,key):
        key=text(key,200,'Idempotency-Key')
        with self.store.db() as db:
            row=db.execute('SELECT * FROM publication_history WHERE job_id=? AND idem=?',(job_id,key)).fetchone()
        if row is None:return {'ok':False,'pending':True}
        return {'ok':True,'entry':self._entry(row),'cleanup_pending':row['cleanup_state']!='completed'}

    def retry_cleanup(self,identifier):
        now=time.time()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM publication_history WHERE id=?',(identifier,)).fetchone()
            if row is None:raise KeyError(identifier)
            if row['cleanup_state']=='completed' or row['lease_until']>now:return {'ok':True,'entry':self._entry(row),'cleanup_pending':row['cleanup_state']!='completed'}
            db.execute('UPDATE publication_history SET lease_until=? WHERE id=?',(now+300,identifier))
            paths=[Path(r[0]) for r in db.execute('SELECT path FROM publication_cleanup_files WHERE entry_id=?',(identifier,))]
        pending=False
        for path in paths:
            try:self._purge_path(path)
            except (OSError,ValueError):pending=True;continue
            with self.store.db() as db:db.execute('DELETE FROM publication_cleanup_files WHERE entry_id=? AND path=?',(identifier,str(path)))
        with self.store.db() as db:
            remains=db.execute('SELECT 1 FROM publication_cleanup_files WHERE entry_id=?',(identifier,)).fetchone()
            state='pending' if pending or remains else 'completed'
            db.execute('UPDATE publication_history SET cleanup_state=?,error=?,lease_until=0,next_at=? WHERE id=?',(state,'Tệp đang bận; hệ thống sẽ thử dọn lại' if state=='pending' else None,time.time()+60 if state=='pending' else 0,identifier))
        if state=='completed':
            journal=self.journal_root/(identifier+'.json')
            try:
                record=json.loads(journal.read_text(encoding='utf8'))
                root=self.store.outputs.resolve()
                for original,_ in record['moves']:
                    parent=Path(original).parent
                    while parent.resolve().is_relative_to(root) and parent.resolve()!=root:
                        if any(_alias(p) for p in (parent,*parent.parents)):break
                        try:parent.rmdir() # Empty directories only, never recurse here.
                        except FileNotFoundError:pass
                        except OSError:break
                        parent=parent.parent
            except (OSError,ValueError,KeyError,TypeError):pass
            journal.unlink(missing_ok=True)
        return {'ok':True,'entry':self.entry(identifier),'cleanup_pending':state!='completed'}

    def recover(self):
        if not self.journal_root.exists():return
        for journal in self.journal_root.glob('*.json'):
            try:
                # Match cleanup's write lock: never recover another live transaction.
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if not journal.exists():continue
                    record=json.loads(journal.read_text(encoding='utf8'));identifier=record['entry_id']
                    if db.execute('SELECT 1 FROM publication_history WHERE id=?',(identifier,)).fetchone():continue
                    moves=[(Path(original),Path(removed)) for original,removed in record['moves']]
                    if not all(self._valid_move(target,quarantine,record.get('job_id'),record.get('task_ids',())) for target,quarantine in moves):raise ValueError('Invalid cleanup recovery paths')
                    restored=True
                    for target,quarantine in reversed(moves):
                        if quarantine.exists():
                            if target.exists():restored=False;continue
                            target.parent.mkdir(parents=True,exist_ok=True);quarantine.rename(target)
                    if restored:journal.unlink(missing_ok=True)
            except (OSError,ValueError,KeyError,TypeError):
                import logging;logging.getLogger(__name__).exception('Could not recover publication cleanup journal')

    def tick(self):
        with self.store.db() as db:row=db.execute("SELECT id FROM publication_history WHERE cleanup_state='pending' AND lease_until<=? AND next_at<=? ORDER BY created LIMIT 1",(time.time(),time.time())).fetchone()
        if row:self.retry_cleanup(row['id']);return True
        return False
