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
    render = job.get('checkpoints', {}).get('render', {})
    recorded = render.get('video')
    if recorded:
        path = Path(recorded)
        if path.resolve().parent == base.parent.resolve() and (_matches_video_name(path, base) or render.get('video_ngang')):
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


def _project_stem(job):
    from .core import output_slug
    project = job.get('request', {}).get('project') or ''
    if not project or project == 'Dự án mặc định':
        project = job.get('checkpoints', {}).get('plan', {}).get('title') or 'video'
    return output_slug(project)


def publish_pair(job, result):
    """Name the two deliverables <project>_doc.mp4 and <project>_ngang.mp4; a new render of this job replaces its own pair."""
    from .media import asset
    output = Path(job['output'])
    root = output.parent.parent if output.name == job['id'] and output.parent.name == 'data' else output
    record = output / 'video-name.txt'
    stem = record.read_text(encoding='utf8').strip() if record.is_file() else ''
    if not stem:
        base = stem = _project_stem(job)
        index = 2
        while (root / f'{stem}_doc.mp4').exists() or (root / f'{stem}_ngang.mp4').exists():
            stem = f'{base}-{index}'
            index += 1
        record.write_text(stem, encoding='utf8')
    sources = [Path(result['video']), Path(result['video_ngang'])]
    moved = {path.resolve() for path in sources}
    doc, landscape = root / f'{stem}_doc.mp4', root / f'{stem}_ngang.mp4'
    sources[0].replace(doc)
    sources[1].replace(landscape)
    kept = [a for a in result.get('assets', []) if Path(a['path']).resolve() not in moved]
    return {**result, 'video': str(doc), 'video_ngang': str(landscape), 'assets': kept + [asset(doc), asset(landscape)]}


def job_video_files(job):
    final=final_video_path(job);output=Path(job['output'])
    if output.name!=job['id'] or output.parent.name!='data':return [final]
    base = _base_video_path(job)
    found = [p for p in base.parent.glob(base.stem+'*.mp4') if _matches_video_name(p, base)]
    if job.get('checkpoints', {}).get('render', {}).get('video_ngang') and final not in found:
        found.insert(0, final)
    return found or [final]


def job_deliverables(job):
    """Every finished file of a job, for deletion: its video versions plus the landscape copy."""
    landscape = job.get('checkpoints', {}).get('render', {}).get('video_ngang')
    return job_video_files(job) + ([Path(landscape)] if landscape else [])
