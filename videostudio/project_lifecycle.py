"""Project visibility and explicitly requested, output-only file removal.

Database receipts and checkpoints remain immutable. File removal first moves every
validated directory to quarantine; a staging/transaction failure restores them all.
"""
import json
import shutil
import time
import uuid
from pathlib import Path

DEFAULT_PROJECT='Dự án mặc định'
TERMINAL_STATES=('completed','failed','cancelled')


def project_name(raw):
    try:return json.loads(raw).get('project') or DEFAULT_PROJECT
    except (ValueError,TypeError):return DEFAULT_PROJECT


def has_table(c,name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None


def reject_deleted_project(c,name):
    if has_table(c,'project_lifecycle') and c.execute('SELECT 1 FROM project_lifecycle WHERE name=? AND deleted=1',(name,)).fetchone():
        raise ValueError('Dự án đã bị xóa; vui lòng chọn tên dự án khác')


def reject_retired_job(c,identifier):
    row=c.execute('SELECT request FROM jobs WHERE id=?',(identifier,)).fetchone()
    if row:reject_deleted_project(c,project_name(row['request']))
    if has_table(c,'job_file_deletions') and c.execute('SELECT 1 FROM job_file_deletions WHERE job=?',(identifier,)).fetchone():
        raise ValueError('Các tệp đã bị xóa; hãy tạo job mới')


def _alias(path):
    return path.is_symlink() or (getattr(path,'is_junction',lambda:False)())


def image_tasks_active(c,ids):
    if not has_table(c,'scene_image_tasks'):return False
    return any(c.execute("SELECT 1 FROM scene_image_tasks WHERE job=? AND state IN ('queued','running')",(identifier,)).fetchone() for identifier in ids)


def _strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for child in value.values():yield from _strings(child)
    elif isinstance(value,list):
        for child in value:yield from _strings(child)


class OutputRemoval:
    def __init__(self,store,c,jobs):
        self.moves=[];self.root=store.outputs.resolve();self.targets=[]
        selected={j['id'] for j in jobs}
        for job in jobs:
            raw=Path(job['output']);target=raw.resolve()
            if not raw.is_absolute() or not target.is_relative_to(self.root) or target==self.root:
                raise ValueError('Không thể xóa: thư mục output phải nằm riêng bên trong thư mục xuất video')
            # Refuse aliases, including junctions and symlinks within the tree.
            chain=[raw,*raw.parents]
            if any(_alias(p) for p in chain if p!=store.outputs.parent):
                raise ValueError('Không thể xóa output qua symlink/junction')
            if target.exists() and not target.is_dir():raise ValueError('Output không phải thư mục')
            if target.exists() and any(_alias(p) for p in target.rglob('*')):
                raise ValueError('Output chứa symlink/junction; giữ lại tệp để an toàn')
            self.targets.append(target)
        if len(set(self.targets))!=len(self.targets) or any(a!=b and a.is_relative_to(b) for a in self.targets for b in self.targets):
            raise ValueError('Output dùng chung hoặc lồng nhau; hãy giữ lại tệp')
        def touches(value):
            try:
                p=Path(value)
                if not p.is_absolute():return False
                p=p.resolve()
                return any(p==target or p.is_relative_to(target) for target in self.targets)
            except (ValueError,OSError):return False
        for other in c.execute('SELECT id,output,request FROM jobs'):
            if other['id'] in selected:continue
            p=Path(other['output']).resolve()
            if touches(other['output']) or any(target.is_relative_to(p) for target in self.targets):
                raise ValueError('Output dùng chung với job khác; hãy chọn giữ lại tệp')
            for cp in c.execute('SELECT value FROM checkpoints WHERE job=?',(other['id'],)):
                try:values=_strings(json.loads(cp['value']))
                except (ValueError,TypeError):raise ValueError('Không thể kiểm chứng checkpoint dùng chung; hãy giữ lại tệp')
                if any(touches(value) for value in values):
                    raise ValueError('Tệp đang được checkpoint của job khác dùng chung; hãy giữ lại tệp')
        for table,column in (('scene_image_edits','path'),('scene_image_tasks','result')):
            if not has_table(c,table):continue
            for row in c.execute(f'SELECT job,{column} AS value FROM {table}'):
                if row['job'] in selected or not row['value']:continue
                values=[row['value']]
                if column=='result':
                    try:values=list(_strings(json.loads(row['value'])))
                    except (ValueError,TypeError):raise ValueError('Không thể kiểm chứng scene image; hãy giữ lại tệp')
                if any(touches(value) for value in values):raise ValueError('Tệp đang được scene image khác dùng chung; hãy giữ lại tệp')
        if has_table(c,'scene_exports'):
            for export in c.execute('SELECT child,parent FROM scene_exports'):
                if export['parent'] in selected and export['child'] not in selected:
                    raise ValueError('Scene export khác còn phụ thuộc job này; hãy giữ lại tệp')
    def stage(self):
        try:
            for target in self.targets:
                if not target.exists():continue
                quarantine=self.root/('.deleted-'+uuid.uuid4().hex)
                target.rename(quarantine);self.moves.append((target,quarantine))
        except OSError as error:
            self.rollback()
            raise ValueError('Không thể di chuyển toàn bộ output để xóa; các thư mục đã được khôi phục') from error
    def rollback(self):
        for target,quarantine in reversed(self.moves):quarantine.rename(target)
        self.moves=[]
    def purge(self):
        pending=False
        for _,quarantine in self.moves:
            try:shutil.rmtree(quarantine)
            except OSError:pending=True
        return pending


class ProjectLifecycle:
    def __init__(self,store):
        self.store=store
        with store.db() as c:c.execute('''CREATE TABLE IF NOT EXISTS project_lifecycle(
            name TEXT PRIMARY KEY,archived INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,
            files_deleted INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL)''')
    def metadata(self):
        with self.store.db() as c:return {r['name']:dict(r) for r in c.execute('SELECT * FROM project_lifecycle')}
    def _jobs(self,c,name):
        return [dict(row) for row in c.execute('SELECT * FROM jobs') if project_name(row['request'])==name]
    def _require(self,c,name,jobs):
        if name==DEFAULT_PROJECT or jobs or c.execute('SELECT 1 FROM projects WHERE name=?',(name,)).fetchone():return
        raise KeyError(name)
    def archive(self,name,archived):
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');reject_deleted_project(c,name);self._require(c,name,self._jobs(c,name))
            c.execute('''INSERT INTO project_lifecycle(name,archived,updated) VALUES(?,?,?)
                ON CONFLICT(name) DO UPDATE SET archived=excluded.archived,updated=excluded.updated''',(name,int(archived),time.time()))
        return {'ok':True,'name':name,'archived':archived}
    def delete(self,name,delete_files):
        removal=None
        try:
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE');jobs=self._jobs(c,name);self._require(c,name,jobs)
                if any(job['state'] not in TERMINAL_STATES for job in jobs):raise ValueError('Dự án có job đang hoạt động; dừng job trước khi xóa')
                if image_tasks_active(c,[j['id'] for j in jobs]):raise ValueError('Dự án có scene image đang chạy hoặc chờ; dừng trước khi xóa')
                old=c.execute('SELECT files_deleted FROM project_lifecycle WHERE name=?',(name,)).fetchone()
                files_deleted=bool(old and old['files_deleted']) or delete_files
                if delete_files:
                    removal=OutputRemoval(self.store,c,jobs);removal.stage()
                for job in jobs:
                    c.execute('UPDATE jobs SET cancel=1,updated=? WHERE id=?',(time.time(),job['id']))
                    if has_table(c,'connector_scopes'):
                        owner=c.execute('''SELECT COALESCE(m.bridge,s.id) AS bridge FROM connector_scopes s
                            LEFT JOIN connector_bridge_memberships m ON m.scope=s.id WHERE s.job=?''',(job['id'],)).fetchone()
                        if owner:c.execute('INSERT OR IGNORE INTO connector_dismissed_jobs VALUES(?,?,?)',(job['id'],owner['bridge'],time.time()))
                    self.store.event(c,job['id'],None,'project_deleted','delete_files='+str(delete_files).lower())
                c.execute('''INSERT INTO project_lifecycle(name,deleted,files_deleted,updated) VALUES(?,1,?,?)
                    ON CONFLICT(name) DO UPDATE SET deleted=1,files_deleted=excluded.files_deleted,updated=excluded.updated''',(name,int(files_deleted),time.time()))
        except Exception:
            if removal:removal.rollback()
            raise
        pending=removal.purge() if removal else False
        return {'ok':True,'name':name,'deleted':True,'files_deleted':files_deleted,'files_preserved':not files_deleted,'cleanup_pending':pending}
