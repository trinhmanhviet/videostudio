"""Project-level deliverables, isolated per-job working files."""
import hashlib
import re
import shutil
import uuid
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
    return publish_subtitles(job,result)


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
    return publish_subtitles(job,{**result, 'video': str(doc), 'video_ngang': str(landscape), 'assets': kept + [asset(doc), asset(landscape)]})


def publish_subtitles(job,result,overwrite=True):
    """Copy genuine generated subtitle files beside the current MP4(s).

    Originals/checkpoints remain in data/. Historical MP4s must never be
    backfilled using a newer script. No transcription or translation occurs.
    """
    from .media import asset
    folder=Path(job['output'])
    subtitles=job.get('checkpoints',{}).get('subtitles',{})
    sources={}
    if result.get('edit_plan_sha256'):
        # Editor captions use its own timing/emphasis. Never export the old
        # checkpoint when the editor disabled/replaced the caption overlay.
        overlays=folder/'edit-overlays.ass'
        if overlays.is_file():
            lines=overlays.read_text(encoding='utf8').splitlines()
            if any(line.startswith('Dialogue:') and len(line.split(',',9))==10 and line.split(',',9)[3]=='Caption' for line in lines):sources['.ass']=overlays
    elif not str(result.get('renderer','')).endswith('-rerender'):
        for key in ('srt_path','path','ass_path','vtt_path'):
            source=Path(subtitles[key]) if isinstance(subtitles.get(key),str) else None
            if source and source.suffix.lower() in ('.srt','.ass','.vtt') and source.is_file():sources[source.suffix.lower()]=source
    files=[]
    for key in ('video','video_ngang'):
        if not isinstance(result.get(key),str):continue
        video=Path(result[key])
        if not video.is_file():continue
        actual=dict(sources)
        if key=='video' and result.get('video_ngang') and (folder/'subtitles-doc.ass').is_file():actual['.ass']=folder/'subtitles-doc.ass'
        for suffix,source in actual.items():
            target=video.with_suffix(suffix)
            if source.resolve()!=target.resolve() and (overwrite or not target.exists()):
                temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                try:shutil.copy2(source,temporary);temporary.replace(target)
                finally:temporary.unlink(missing_ok=True)
            if target.is_file():files.append(target)
    if not files:return result
    records={str(Path(item['path']).resolve()):item for item in result.get('assets',[])}
    for path in files:records[str(path.resolve())]=asset(path)
    return {**result,'subtitle_files':[str(path) for path in files],'assets':list(records.values())}


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
    videos=list(dict.fromkeys(job_video_files(job) + ([Path(landscape)] if landscape else [])))
    return videos+[video.with_suffix(suffix) for video in videos for suffix in ('.srt','.ass','.vtt') if video.with_suffix(suffix).is_file()]
