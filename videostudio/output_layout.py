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


def _base_video_path(job):
    output = Path(job['output'])
    if output.name == job['id'] and output.parent.name == 'data':
        return output.parent.parent / f"video-{job['id']}.mp4"
    return output / 'video.mp4'


def _matches_video_name(path, base):
    # Earlier exports sometimes accumulated suffixes such as -4-2.
    return re.fullmatch(re.escape(base.stem) + r'(?:-[0-9]+)*\.mp4', path.name) is not None


def final_video_path(job):
    base = _base_video_path(job)
    recorded = job.get('checkpoints', {}).get('render', {}).get('video')
    if recorded:
        path = Path(recorded)
        if path.resolve().parent == base.parent.resolve() and _matches_video_name(path, base):
            return path
    return base


def publish_video(job, result):
    from .media import asset
    source = Path(result['video'])
    if source.resolve() != final_video_path(job).resolve():
        base = destination = _base_video_path(job)
        index = 2
        while destination.exists():
            destination=base.with_name(base.stem+'-'+str(index)+base.suffix);index+=1
        source.replace(destination)
        result={**result,'video':str(destination),
                'assets':[a for a in result.get('assets',[]) if Path(a['path']).resolve()!=source.resolve()]+[asset(destination)]}
    return result


def job_video_files(job):
    final=final_video_path(job);output=Path(job['output'])
    if output.name!=job['id'] or output.parent.name!='data':return [final]
    base = _base_video_path(job)
    return [p for p in base.parent.glob(base.stem+'*.mp4') if _matches_video_name(p, base)] or [final]
