"""One real local Stable Audio3 smoke; reruns reattach using persisted receipt."""
import json,uuid,sys
from datetime import datetime
from pathlib import Path
from videostudio.providers import Pipeline,music_graph
from videostudio.voices import Voices
from videostudio.media import probe,run,asset
ROOT=Path(__file__).resolve().parents[1]
folder=Path(sys.argv[1]) if len(sys.argv)>1 else Path('E:/Videos')/('videostudio-music-test-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(exist_ok=True)
identity=folder/'job.json'
if identity.is_file():j=json.loads(identity.read_text())
else:
    j={'id':str(uuid.uuid4()),'output':str(folder)};identity.write_text(json.dumps(j))
prompt='Instrumental only, no vocals, gentle acoustic piano with warm ambient pads, calm hopeful mood, soft percussion, 80 BPM, eight seconds.'
graph=music_graph(prompt,8,482619,'videostudio/'+j['id']+'-music')
(folder/'workflow.json').write_text(json.dumps(graph,indent=2))
print('PROJECT '+str(folder),flush=True)
p=Pipeline(Voices('D:/Projects/storyforge',ROOT/'data/voices-export.json'))
result=p.comfy_asset(j,'music',graph,folder/'music.mp3',lambda:None)
d=probe(folder/'music.mp3');run(['ffmpeg','-v','error','-i',str(folder/'music.mp3'),'-f','null','-'],lambda:None)
result.update(duration_seconds=float(d['format']['duration']),full_decode_ok=True,engine='Stable Audio3 local ComfyUI',semantic_or_license_acceptance=False)
(folder/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
