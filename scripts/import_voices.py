"""Read-only authoritative voice import from the already-running local StoryForge DB.
No DB writes, no service start, no secret output. Keeps preset IDs and clone identities.
"""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STORY=Path('D:/Projects/storyforge')
sql="BEGIN READ ONLY; SELECT json_agg(t) FROM (SELECT id,status,sha256,metadata_json FROM assets WHERE metadata_json->>'purpose'='voice_sample')t; COMMIT;"
container='multigen-story-video-postgres-1'
def variable(name):
    return subprocess.check_output(['docker','exec',container,'printenv',name],text=True).strip()
r=subprocess.run(['docker','exec','-i',container,'psql','-U',variable('POSTGRES_USER'),'-d',variable('POSTGRES_DB'),'-Atq'],input=sql,text=True,capture_output=True,encoding='utf-8',check=True)
records=json.loads(r.stdout.strip()) or []
metadata=json.loads((STORY/'apps/api/app/data/voice-presets.json').read_text(encoding='utf-8'))
rows=[dict(p,kind='preset') for p in metadata['presets']]
missing=[]
for a in records:
    ref=STORY/'Voices/Samples'/f"{a['id']}.wav"
    valid=ref.is_file() and hashlib.sha256(ref.read_bytes()).hexdigest()==a['sha256']
    row={'id':'clone:'+a['id'],'name':a['metadata_json'].get('name',a['id']),'kind':'clone','status':a['status'],'reference_path':str(ref),'sha256':a['sha256'],'selectable':a['status']=='locked' and valid}
    if a['status']=='locked' and not valid:missing.append(a['id'])
    preview=[]
    for p in (STORY/'Voices/Work/Previews').glob('*/request.json'):
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            if d.get('voice_id')==row['id'] and (p.parent/'preview.wav').is_file():preview.append(p.parent/'preview.wav')
        except (ValueError,OSError):pass
    if preview:row['sample_path']=str(preview[-1])
    rows.append(row)
# Recover preset audition references, preserving authoritative names and IDs.
for p in (STORY/'Voices/Work/Previews').glob('*/request.json'):
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
        for row in rows:
            if row['id']==d.get('voice_id') and (p.parent/'preview.wav').is_file():row.setdefault('sample_path',str(p.parent/'preview.wav'))
    except (ValueError,OSError):pass
out=ROOT/'data/voices-export.json';out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({'complete':not missing,'source':'read-only PostgreSQL assets and canonical preset metadata','voices':rows,'missing_locked_references':missing},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'presets':len(metadata['presets']),'locked_clones':sum(a['status']=='locked' for a in records),'archived_clones':sum(a['status']!='locked' for a in records),'missing_locked_references':missing,'export':str(out)}))
