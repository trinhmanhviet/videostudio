"""Restart only an absent Comfy service through its pre-authorized launcher.
Does not kill/restart a live process, unload models or submit generation work.
"""
import hashlib,json,os,socket,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
config=json.loads(Path('D:/Projects/storyforge/.runtime/comfyui-launcher.json').read_text())
launcher=Path(config['launcher'])
if hashlib.sha256(launcher.read_bytes()).hexdigest()!=config['sha256']:raise RuntimeError('Launcher changed; not executing')
if os.name!='nt':raise RuntimeError('This launcher is for Windows host only')
# A loopback connect timeout is not evidence of a dead service. Query the host
# socket table and processes; do not launch a second process while one boots.
probe=subprocess.run(['powershell','-NoProfile','-File',str(ROOT/'scripts/comfy_host_state.ps1')],capture_output=True,text=True,timeout=20,check=True)
state=json.loads(probe.stdout)
if state.get('listening') is not False or not isinstance(state.get('comfy_process_ids'),list) or state['comfy_process_ids']:
 raise RuntimeError('Comfy listener/process present or state unknown; refusing duplicate start')
logdir=ROOT/'data/comfy-recovery';logdir.mkdir(parents=True,exist_ok=True)
env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME='D:/Projects/storyforge/.runtime/media/model-cache')
CREATE_BREAKAWAY = getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0x01000000)
with (logdir/'startup.log').open('ab') as log:
 p=subprocess.Popen(['cmd.exe','/c',str(launcher)],cwd=launcher.parent,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|CREATE_BREAKAWAY)
print(json.dumps({'launcher_pid':p.pid,'generation_submitted':False}),flush=True)
end=time.monotonic()+180
while time.monotonic()<end:
 try:
  with urllib.request.urlopen(config['url']+'/system_stats',timeout=3) as response:d=json.load(response)
  record={'launcher_pid':p.pid,'launcher':str(launcher),'ready':True,'generation_submitted':False,'devices':[{'name':x['name'],'vram_free':x['vram_free']} for x in d['devices']]}
  (logdir/'service.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True);break
 except (OSError,ValueError):
  if p.poll() is not None:raise RuntimeError('Launcher exited; inspect data/comfy-recovery/startup.log')
  time.sleep(2)
else:raise TimeoutError('Comfy startup budget exhausted; generation not submitted')
