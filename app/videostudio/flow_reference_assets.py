"""Fetch existing Flow portraits and bind immutable local references to a job."""
from .paths import DATA_ROOT
import json,shutil,uuid,re
from pathlib import Path
from PIL import Image
from .core import digest,PermanentError
from .media import asset


def ensure_portrait(pipeline,job,reference,check):
    from .providers import ROOT
    folder=Path(job['output'])/'flow-character-references';folder.mkdir(parents=True,exist_ok=True)
    task=reference['task_id'];name=reference['name'];path=folder/(name+'.png');sidecar=folder/(name+'.portrait.json')
    uuid.UUID(task);uuid.UUID(reference['character_id'])
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name):raise PermanentError('Invalid reference name')
    if sidecar.is_file():
        record=json.loads(sidecar.read_text(encoding='utf8'))
        if record.get('task_id')!=task or record.get('character_id')!=reference['character_id'] or not path.is_file() or digest(path)!=record.get('sha256'):
            raise PermanentError('Saved Flow portrait identity changed: '+name)
    else:
        import os
        base=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/')
        response=pipeline._flow_post(base+'/api/flow/characters/reference',{'task_id':task,'job_id':job['id'],'character_id':reference['character_id']},check,120)
        if response.status_code!=200:
            from .providers import UncertainDeliveryError
            raise UncertainDeliveryError('Flow reference download: '+response.json().get('error',str(response.status_code)))
        data=response.json().get('data',{})
        source=Path(data.get('file_path','')).resolve();expected=(DATA_ROOT/'flow-images/references'/(task+'.png')).resolve()
        if data.get('task_id')!=task or data.get('character_id')!=reference['character_id'] or source!=expected or not source.is_file() or digest(source)!=data.get('sha256'):
            raise PermanentError('Flow portrait download receipt differs: '+name)
        with Image.open(source) as picture:
            picture.load()
            if min(picture.size)<256:raise PermanentError('Flow portrait is too small')
        temporary=path.with_suffix('.part');shutil.copyfile(source,temporary);temporary.replace(path)
        record={'task_id':task,'character_id':reference['character_id'],'sha256':digest(path),'project_url':reference['project_url']}
        temporary=sidecar.with_suffix('.part.json');temporary.write_text(json.dumps(record,ensure_ascii=False),encoding='utf8');temporary.replace(sidecar)
    return {**reference,'portrait_path':str(path),'portrait_sha256':record['sha256']},[asset(path),asset(sidecar)]
