"""One real Qwen Image2.1 smoke; receipt makes retry attach, not duplicate."""
import json,uuid,sys
from pathlib import Path
from datetime import datetime
from PIL import Image,ImageStat
from videostudio.providers import Pipeline,image_graph
from videostudio.voices import Voices
ROOT=Path(__file__).resolve().parents[1]
folder=Path(sys.argv[1]) if len(sys.argv)>1 else Path('E:/Videos')/('videostudio-image-test-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(exist_ok=True);identity=folder/'job.json'
if identity.is_file():j=json.loads(identity.read_text())
else:j={'id':str(uuid.uuid4()),'output':str(folder)};identity.write_text(json.dumps(j))
prompt='A quiet Vietnamese home garden at sunrise, dew on green leaves, terracotta plant pots beside a wooden window, warm natural light, realistic cinematic photography, vertical composition, no text, no watermark, no people.'
graph=image_graph(prompt,482619,'videostudio/'+j['id']+'-image');(folder/'workflow.json').write_text(json.dumps(graph,indent=2))
print('PROJECT '+str(folder),flush=True)
p=Pipeline(Voices('D:/Projects/storyforge',ROOT/'data/voices-export.json'));r=p.comfy_asset(j,'images',graph,folder/'image.png',lambda:None)
with Image.open(folder/'image.png') as im:
 im.load();r.update(width=im.width,height=im.height,stddev=ImageStat.Stat(im.convert('RGB')).stddev,decode_ok=True,engine='Qwen Image 2.1 local ComfyUI')
(folder/'verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True)
