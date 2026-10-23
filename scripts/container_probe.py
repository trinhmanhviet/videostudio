"""Run inside an isolated container, never infer host binaries are available."""
import json,os,subprocess,urllib.request,uuid
from pathlib import Path
report={'runtime':'Linux Docker container','checks':[]}
def add(name,ok,detail):report['checks'].append({'name':name,'ok':bool(ok),'detail':detail})
for tool in ['ffmpeg','ffprobe']:
    try:r=subprocess.run([tool,'-version'],capture_output=True,text=True,timeout=10);add(tool,r.returncode==0,r.stdout.splitlines()[0])
    except Exception as e:add(tool,False,type(e).__name__)
url='http://host.docker.internal:8188'
try:
    with urllib.request.urlopen(url+'/system_stats',timeout=8) as r:d=json.load(r)
    add('host_comfy',True,{'url':url,'os':d.get('system',{}).get('os')})
except Exception as e:add('host_comfy',False,type(e).__name__)
# Unique preserved file proves the actual mounted E: destination is writable.
try:
    folder=Path('/videos')/('videostudio-container-probe-'+uuid.uuid4().hex[:12]);folder.mkdir()
    file=folder/'probe.json';file.write_text(json.dumps({'purpose':'container write/read probe','no_generation':True}));add('video_volume',json.loads(file.read_text())['no_generation'],str(file))
except Exception as e:add('video_volume',False,type(e).__name__)
try:import vieneu;add('container_vieneu',True,'importable')
except ImportError:add('container_vieneu',False,'Native Windows VieNeu runtime is not a container HTTP service. Generation is not container-ready.')
report['all_generation_dependencies_ready']=all(c['ok'] for c in report['checks'])
print(json.dumps(report,indent=2))
