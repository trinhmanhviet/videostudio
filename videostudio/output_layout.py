"""Project-level deliverables, isolated per-job working files."""
import hashlib
import re
from pathlib import Path


def allocate_output(store, connection, request, job_id):
    from .core import output_slug
    project=request.get('project') or 'Dự án mặc định'
    connection.execute('CREATE TABLE IF NOT EXISTS project_output_roots(project TEXT PRIMARY KEY,path TEXT UNIQUE COLLATE NOCASE NOT NULL)')
    saved=connection.execute('SELECT path FROM project_output_roots WHERE project=?',(project,)).fetchone()
    if saved:
        root=Path(saved['path'])
        if root.resolve().parent!=store.outputs.resolve():raise ValueError('Project output root is outside output directory')
    else:
        slug=output_slug(project)
        if slug.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:slug='project-'+slug
        root=store.outputs/slug
        suffix=hashlib.sha256(project.encode('utf8')).hexdigest()[:10]
        if root.exists() or connection.execute('SELECT 1 FROM project_output_roots WHERE path=?',(str(root),)).fetchone():
            root=store.outputs/(slug+'-'+suffix)
        if root.exists():raise ValueError('Project output folder already exists without a registered owner')
        connection.execute('INSERT INTO project_output_roots VALUES(?,?)',(project,str(root)))
    output=root/'data'/job_id
    output.mkdir(parents=True,exist_ok=False)
    return output


def final_video_path(job):
    output=Path(job['output'])
    if output.name==job['id'] and output.parent.name=='data':
        root=output.parent.parent
        recorded=job.get('checkpoints',{}).get('render',{}).get('video')
        if recorded:
            path=Path(recorded)
            if path.resolve().parent==root.resolve() and re.fullmatch('video-'+re.escape(job['id'])+r'(?:-\d+)?\.mp4',path.name):return path
        return root/('video-'+job['id']+'.mp4')
    return output/'video.mp4'


def publish_video(job, result):
    from .media import asset
    source=Path(result['video']);destination=final_video_path(job)
    if source.resolve()!=destination.resolve():
        base=destination;index=2
        while destination.exists():
            destination=base.with_name(base.stem+'-'+str(index)+base.suffix);index+=1
        source.replace(destination)
        result={**result,'video':str(destination),
                'assets':[a for a in result.get('assets',[]) if Path(a['path']).resolve()!=source.resolve()]+[asset(destination)]}
    return result


def job_video_files(job):
    final=final_video_path(job);output=Path(job['output'])
    if output.name!=job['id'] or output.parent.name!='data':return [final]
    pattern='video-'+re.escape(job['id'])+r'(?:-\d+)?\.mp4'
    return [p for p in final.parent.glob('video-'+job['id']+'*.mp4') if re.fullmatch(pattern,p.name)] or [final]
