"""Standalone, durable speech auditions on the existing serial GPU worker.

The browser owns an opaque local history scope. Files are resolved exclusively
from server-generated task/reference IDs, never a caller-supplied path.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import math
import re
import shutil
import time
import uuid
import wave
from pathlib import Path
from .core import Cancelled, digest


VOLUMES = (50, 75, 100, 125, 150, 200)
TARGET_LUFS = -16

def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label}: cần 1–{maximum} ký tự')
    return value.strip()


def _owner(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', value):
        raise ValueError('Thiếu mã thư viện của trình duyệt')
    return value


class VoiceStudio:
    def __init__(self, store, pipeline, voices, root=None, render=None):
        self.store, self.pipeline, self.voices = store, pipeline, voices
        self.root = Path(root or store.path.parent / 'voice-studio').resolve()
        self.render = render or self._render
        self.stop_event = None  # Parent serial worker supplies its shutdown Event.
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS voice_studio_tasks(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, idem TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, request TEXT NOT NULL, title TEXT NOT NULL,
                    state TEXT NOT NULL, message TEXT, version INTEGER NOT NULL DEFAULT 1,
                    saved INTEGER NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0,
                    result TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(owner,idem));
                CREATE INDEX IF NOT EXISTS voice_studio_queue ON voice_studio_tasks(state,created);
                CREATE TABLE IF NOT EXISTS voice_studio_references(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    transcript TEXT NOT NULL, sha256 TEXT NOT NULL, duration REAL NOT NULL,
                    created REAL NOT NULL);
            ''')

    def _path(self, *parts):
        path = self.root.joinpath(*parts)
        # resolve also guards a task directory replaced with a symlink/junction.
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Đường dẫn âm thanh không thuộc Phòng thử giọng')
        return path

    def _request(self, owner, body):
        if not isinstance(body, dict): raise ValueError('Yêu cầu phải là đối tượng')
        voice_id = _text(body.get('voice_id'), 200, 'Giọng đọc')
        self.voices.selected(voice_id)
        engine = body.get('speech_engine', 'vieneu')
        rhythm = body.get('speech_rhythm', 'natural')
        speed = body.get('speech_speed', 1)
        steps = body.get('khanh_steps', 32)
        if engine not in ('vieneu', 'khanhtts'): raise ValueError('Bộ đọc không hợp lệ')
        if rhythm not in ('natural', 'story'): raise ValueError('Nhịp đọc không hợp lệ')
        if type(speed) not in (float, int) or not math.isfinite(speed) or not .5 <= speed <= 2:
            raise ValueError('Tốc độ cần từ 0.5 đến 2')
        if type(steps) is not int or steps not in (16, 32): raise ValueError('KhanhTTS chỉ hỗ trợ 16 hoặc 32 bước')
        request = dict(text=_text(body.get('text'), 20000, 'Nội dung'), voice_id=voice_id,
                       speech_engine=engine, speech_rhythm=rhythm, speech_speed=float(speed))
        if engine == 'khanhtts': request['khanh_steps'] = steps
        if 'speech_volume' in body:
            # Output loudness only: 100% is speech loudness -16 LUFS. Old tasks without the field keep their raw level.
            if type(body['speech_volume']) not in (int, float) or body['speech_volume'] not in VOLUMES: raise ValueError('Âm lượng không hợp lệ')
            request['speech_volume'] = int(body['speech_volume'])
        if body.get('speech_reference_id'):
            reference = self.reference(owner, body['speech_reference_id'])
            request['speech_reference_id'] = reference['id']
        if engine=='khanhtts' and not request.get('speech_reference_id') and body.get('speech_reference_text'):
            request['speech_reference_text'] = _text(body['speech_reference_text'], 10000, 'Lời mẫu')
        return request

    def create(self, owner, body, idem):
        owner = _owner(owner); idem = _text(idem, 200, 'Idempotency-Key')
        request = self._request(owner, body)
        title = _text(body.get('title') or request['text'][:70], 160, 'Tên bản đọc')
        fingerprint = hashlib.sha256(_json({'request':request, 'title':title}).encode()).hexdigest()
        now = time.time(); identifier = uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM voice_studio_tasks WHERE owner=? AND idem=?', (owner, idem)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint: raise ValueError('Khóa gửi lại đã dùng cho nội dung khác')
                if old['state'] == 'deleted': raise ValueError('Bản đọc của yêu cầu này đã được xóa; hãy tạo yêu cầu mới')
                return self._public(old)
            db.execute('''INSERT INTO voice_studio_tasks
                (id,owner,idem,fingerprint,request,title,state,message,created,updated)
                VALUES(?,?,?,?,?,?,'queued',?,?,?)''',
                (identifier,owner,idem,fingerprint,_json(request),title,'Chờ GPU rảnh sau các tác vụ video và ảnh',now,now))
        return self.get(owner, identifier)

    def _row(self, db, owner, identifier):
        row = db.execute("SELECT * FROM voice_studio_tasks WHERE id=? AND owner=? AND state!='deleted'", (identifier,_owner(owner))).fetchone()
        if row is None: raise KeyError(identifier)
        return row

    def _public(self, row):
        result = json.loads(row['result']) if row['result'] else None
        return {key: row[key] for key in ('id','title','state','message','version','created','updated')} | {
            'saved':bool(row['saved']), 'request':json.loads(row['request']), 'result':result}

    def get(self, owner, identifier):
        with self.store.db() as db: return self._public(self._row(db,owner,identifier))

    def history(self, owner, page=1, page_size=10, saved=False):
        _owner(owner)
        if type(page) is not int or page < 1 or page_size not in (10,20,30): raise ValueError('Phân trang không hợp lệ')
        where = "owner=? AND state!='deleted'" + (' AND saved=1' if saved else '')
        with self.store.db() as db:
            total = db.execute('SELECT COUNT(*) FROM voice_studio_tasks WHERE '+where,(owner,)).fetchone()[0]
            rows = db.execute('SELECT * FROM voice_studio_tasks WHERE '+where+' ORDER BY created DESC LIMIT ? OFFSET ?', (owner,page_size,(page-1)*page_size)).fetchall()
        return {'items':[self._public(row) for row in rows], 'total':total, 'page':page, 'page_size':page_size}

    def shared_history(self, viewer='', page=1, page_size=10, saved=False):
        """Single-user library: share existing recordings, retain write ownership."""
        if type(page) is not int or page<1 or page_size not in (10,20,30):
            raise ValueError('Phân trang không hợp lệ')
        where="state!='deleted'"+(' AND saved=1' if saved else '')
        with self.store.db() as db:
            total=db.execute('SELECT COUNT(*) FROM voice_studio_tasks WHERE '+where).fetchone()[0]
            rows=db.execute('SELECT * FROM voice_studio_tasks WHERE '+where+' ORDER BY created DESC LIMIT ? OFFSET ?',
                            (page_size,(page-1)*page_size)).fetchall()
        return {'items':[{**self._public(row),'can_manage':row['owner']==viewer} for row in rows],
                'total':total,'page':page,'page_size':page_size}

    def shared_get(self, viewer, identifier):
        with self.store.db() as db:
            row=db.execute("SELECT * FROM voice_studio_tasks WHERE id=? AND state!='deleted'",(identifier,)).fetchone()
        if row is None:raise KeyError(identifier)
        return {**self._public(row),'can_manage':row['owner']==viewer}

    def shared_file(self, identifier, extension):
        if extension not in ('wav','mp3'):raise ValueError('Định dạng không hợp lệ')
        task=self.shared_get('',identifier)
        if task['state']!='completed':raise KeyError(identifier)
        path=self._path('tasks',task['id'],str(task['version']),'audio.'+extension)
        expected=(task['result'] or {}).get('sha256',{}).get(extension)
        if not path.is_file() or not expected or digest(path)!=expected:raise KeyError(identifier)
        return path

    def _version(self, row, version):
        if type(version) is not int or row['version'] != version:
            raise ValueError('Bản đọc đã thay đổi; hãy tải lại trước khi thao tác')

    def update(self, owner, identifier, data, version):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE'); row=self._row(db,owner,identifier);self._version(row,version)
            title = _text(data.get('title',row['title']),160,'Tên bản đọc')
            saved = data.get('saved',bool(row['saved']))
            if not isinstance(saved,bool): raise ValueError('Lựa chọn lưu không hợp lệ')
            if saved and row['state']!='completed': raise ValueError('Chỉ lưu bản đọc đã hoàn tất')
            db.execute('UPDATE voice_studio_tasks SET title=?,saved=?,updated=? WHERE id=?', (title,int(saved),time.time(),identifier))
        return self.get(owner,identifier)

    def retry(self, owner, identifier, version):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,owner,identifier)
            # An acknowledged retry can be repeated after a lost HTTP response.
            if row['version']==version+1 and row['state'] in ('queued','running','completed'):
                return self._public(row)
            self._version(row,version)
            if row['state'] not in ('failed','cancelled'): raise ValueError('Bản đọc này không cần thử lại')
            db.execute("UPDATE voice_studio_tasks SET state='queued',cancel=0,version=version+1,result=NULL,message=?,updated=? WHERE id=?", ('Chờ GPU rảnh để thử lại đúng yêu cầu',time.time(),identifier))
        return self.get(owner,identifier)

    def cancel(self, owner, identifier, version):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,owner,identifier);self._version(row,version)
            if row['state'] in ('queued','running'):
                db.execute("UPDATE voice_studio_tasks SET cancel=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,message='Đã yêu cầu dừng',updated=? WHERE id=?", (time.time(),identifier))
        return self.get(owner,identifier)

    def delete(self, owner, identifier, version):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,owner,identifier);self._version(row,version)
            if row['state'] in ('queued','running'): raise ValueError('Dừng bản đọc trước khi xóa')
            folder=self._path('tasks',identifier)
            if folder.exists(): shutil.rmtree(folder)
            # Keep the idempotency receipt, but forget text and all public content.
            db.execute("UPDATE voice_studio_tasks SET state='deleted',request='{}',result=NULL,title='',message=NULL,updated=? WHERE id=?", (time.time(),identifier))
        return {'ok':True}

    def file(self, owner, identifier, extension):
        if extension not in ('wav','mp3'): raise ValueError('Định dạng không hợp lệ')
        task=self.get(owner,identifier)
        if task['state']!='completed': raise KeyError(identifier)
        path=self._path('tasks',task['id'],str(task['version']),'audio.'+extension)
        expected=(task['result'] or {}).get('sha256',{}).get(extension)
        if not path.is_file() or not expected or digest(path)!=expected: raise KeyError(identifier)
        return path

    def references(self, owner):
        with self.store.db() as db:
            rows=db.execute('SELECT id,name,transcript,duration,created FROM voice_studio_references WHERE owner=? ORDER BY created DESC',(_owner(owner),)).fetchall()
        return {'items':[dict(row) for row in rows]}

    def reference(self, owner, identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier): raise ValueError('Mẫu tham chiếu không hợp lệ')
        with self.store.db() as db:
            row=db.execute('SELECT * FROM voice_studio_references WHERE id=? AND owner=?',(identifier,_owner(owner))).fetchone()
        if not row: raise KeyError(identifier)
        return dict(row)

    def reference_file(self, owner, identifier):
        ref=self.reference(owner,identifier);path=self._path('references',identifier,'reference.wav')
        if not path.is_file() or digest(path)!=ref['sha256']: raise KeyError(identifier)
        return path

    def add_reference(self, owner, data):
        _owner(owner);name=_text(data.get('name'),100,'Tên mẫu')
        transcript=data.get('transcript')
        _text(transcript,10000,'Lời chính xác trong mẫu')  # Preserve the exact supplied transcript.
        encoded=data.get('audio_base64')
        if not isinstance(encoded,str) or len(encoded)>17_000_000: raise ValueError('Mẫu WAV tối đa 12 MB')
        try:
            raw=base64.b64decode(encoded.split('base64,')[-1],validate=True)
            with wave.open(io.BytesIO(raw),'rb') as w:
                duration=w.getnframes()/w.getframerate()
                if w.getnchannels() not in (1,2) or w.getsampwidth()!=2 or not 8000<=w.getframerate()<=96000 or not 1<=duration<=60 or len(w.readframes(w.getnframes()))!=w.getnframes()*w.getnchannels()*2:
                    raise ValueError('Dùng mẫu WAV PCM 16-bit, mono/stereo, dài 1–60 giây')
        except (wave.Error,EOFError,ZeroDivisionError,ValueError) as error: raise ValueError('Mẫu cần là WAV PCM 16-bit hợp lệ, dài 1–60 giây') from error
        if len(raw)>12_000_000: raise ValueError('Mẫu WAV tối đa 12 MB')
        identifier=uuid.uuid4().hex;path=self._path('references',identifier,'reference.wav');path.parent.mkdir(parents=True,exist_ok=False);path.write_bytes(raw)
        try:
            with self.store.db() as db:
                db.execute('INSERT INTO voice_studio_references VALUES(?,?,?,?,?,?,?)',(identifier,owner,name,transcript,digest(path),duration,time.time()))
        except BaseException:
            path.unlink(missing_ok=True);path.parent.rmdir();raise
        return {k:v for k,v in self.reference(owner,identifier).items() if k not in ('sha256','owner')}

    def delete_reference(self, owner, identifier):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');ref=self.reference(owner,identifier)
            rows=db.execute("SELECT request FROM voice_studio_tasks WHERE owner=? AND state!='deleted'",(owner,)).fetchall()
            if any(json.loads(row['request']).get('speech_reference_id')==identifier for row in rows):
                raise ValueError('Mẫu đang được bản đọc sử dụng; xóa bản đọc đó trước để giữ khả năng dùng lại thiết lập')
            folder=self._path('references',ref['id'])
            if folder.exists():shutil.rmtree(folder)
            db.execute('DELETE FROM voice_studio_references WHERE id=? AND owner=?',(identifier,owner))
        return {'ok':True}

    def _voice(self, owner, request):
        voice=dict(self.voices.selected(request['voice_id']))
        if request.get('speech_reference_id'):
            ref=self.reference(owner,request['speech_reference_id']);path=self.reference_file(owner,ref['id'])
            voice.update(kind='clone',reference_path=str(path),sha256=ref['sha256'],reference_text=ref['transcript'])
        return voice

    def status(self, owner, body):
        from .speech_engine import engine_status
        request=self._request(owner,{**body,'text':body.get('text') or 'Kiểm tra cấu hình'})
        return engine_status(self.pipeline,self._voice(owner,request),request)

    def _busy(self, db):
        if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','retrying') LIMIT 1").fetchone():return True
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
            if db.execute("SELECT 1 FROM scene_image_tasks WHERE state IN ('queued','running') LIMIT 1").fetchone():return True
        return False

    def recover(self):
        owner='voice-recover-'+uuid.uuid4().hex
        if not self.store.lock(owner):return 0
        try:
            with self.store.db() as db:
                count=db.execute("UPDATE voice_studio_tasks SET state=CASE WHEN cancel=1 THEN 'cancelled' ELSE 'queued' END,message='Khôi phục sau khi khởi động; chờ GPU rảnh',updated=? WHERE state='running'",(time.time(),)).rowcount
            return count
        finally:self.store.release(owner)

    def step(self, owner):
        # Called only by the SAME serial loop as scene_image_tasks and Worker.step.
        if not self.store.lock(owner):return False
        task=None
        try:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if self._busy(db):return False
                # Owning the common worker lease makes stale running rows recoverable.
                db.execute("UPDATE voice_studio_tasks SET state=CASE WHEN cancel=1 THEN 'cancelled' ELSE 'queued' END WHERE state='running'")
                row=db.execute("SELECT * FROM voice_studio_tasks WHERE state='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
                if not row:return False
                db.execute("UPDATE voice_studio_tasks SET state='running',message='Đang tạo bản đọc riêng',updated=? WHERE id=?",(time.time(),row['id']))
                task=self._public(row);task['owner']=row['owner']
            def check():
                if self.stop_event is not None and self.stop_event.is_set():
                    raise InterruptedError('Đã ngắt khi tắt backend; sẽ tiếp tục sau khi khởi động')
                with self.store.db() as db:
                    row=self._row(db,task['owner'],task['id'])
                    if row['cancel'] or row['version']!=task['version']:raise Cancelled()
                if not self.store.lock(owner):raise Cancelled()
            output=self._path('tasks',task['id'],str(task['version']));output.mkdir(parents=True,exist_ok=True)
            result=self.render(task,output,check);check()
            hashes={ext:digest(output/('audio.'+ext)) for ext in ('wav','mp3')}
            result={**result,'sha256':hashes}
            with self.store.db() as db:
                db.execute("UPDATE voice_studio_tasks SET state='completed',message='Bản đọc đã sẵn sàng',result=?,updated=? WHERE id=? AND version=?",(_json(result),time.time(),task['id'],task['version']))
            return True
        except Exception as error:
            if not task:raise
            with self.store.db() as db:
                state='cancelled' if isinstance(error,Cancelled) else 'queued' if isinstance(error,InterruptedError) else 'failed'
                db.execute('UPDATE voice_studio_tasks SET state=?,message=?,updated=? WHERE id=? AND version=?',(state, 'Đã dừng bản đọc' if isinstance(error,Cancelled) else str(error)[-2000:],time.time(),task['id'],task['version']))
            return True
        finally:self.store.release(owner)

    def _render(self, task, output, check):
        from .speech_engine import create_speech_job, speech_units
        from .media import run, audio_report
        request=task['request'];voice=self._voice(task['owner'],request)
        # The engine adapter owns rhythm, speed and reference conditioning.
        target=output/'audio.wav';units=speech_units(request['text'])
        if not units:raise ValueError('Nội dung đọc trống')
        parts=[output/f'utterance-{index:04}.wav' for index in range(len(units))]
        with create_speech_job(self.pipeline,voice,request,check) as speech:
            size=max(1,min(512,getattr(speech,'batch_size',1)))
            for start in range(0,len(units),size):
                check();speech.write_lines(units[start:start+size],parts[start:start+size])
        # Generated paths contain only server IDs and fixed filenames.
        listing=output/'concat.txt'
        listing.write_text('\n'.join("file '"+part.name+"'" for part in parts),encoding='utf-8')
        run([getattr(self.pipeline,'ffmpeg','ffmpeg'),'-v','error','-y','-f','concat','-safe','1','-i',listing,'-c:a','pcm_s16le',target],check)
        if 'speech_volume' in request:
            with wave.open(str(target),'rb') as w:rate=w.getframerate()
            leveled=output/'audio.level.wav'
            gain=request['speech_volume']/100
            run([getattr(self.pipeline,'ffmpeg','ffmpeg'),'-v','error','-y','-i',target,'-af',
                 f'loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11,volume={gain:.4f},alimiter=limit=0.89:level=false','-ar',str(rate),'-c:a','pcm_s16le',leveled],check)
            leveled.replace(target)
        quality=audio_report(target,check,getattr(self.pipeline,'ffmpeg','ffmpeg'))
        with wave.open(str(target),'rb') as w:duration=w.getnframes()/w.getframerate()
        if not math.isfinite(duration) or duration<=0:raise ValueError('Bản đọc không có âm thanh hợp lệ')
        run([getattr(self.pipeline,'ffmpeg','ffmpeg'),'-v','error','-y','-i',target,'-codec:a','libmp3lame','-q:a','2',output/'audio.mp3'],check)
        return {'duration_seconds':duration,'quality':quality}
