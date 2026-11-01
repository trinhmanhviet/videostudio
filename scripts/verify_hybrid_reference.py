"""Explicit, isolated local GPU acceptance; never changes a VideoStudio job."""
import argparse,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
import httpx
from videostudio.providers import Pipeline
from videostudio.comfy_references import upload_references,reference_graph
from videostudio.core import digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live-generation',action='store_true');args=parser.parse_args()
    if not args.live_generation:parser.error('Use --live-generation explicitly; this runs one isolated local GPU image')
    root=Path(__file__).resolve().parents[1];job_id=str(uuid.uuid4());folder=root/'data/hybrid-reference-acceptance'/job_id;folder.mkdir(parents=True)
    with httpx.Client(base_url='http://127.0.0.1:8188/',trust_env=False,timeout=5) as client:
        queue=client.get('queue');queue.raise_for_status()
        if any(queue.json().get(k) for k in ('queue_running','queue_pending')):raise RuntimeError('Comfy is busy; no work submitted')
    image=Image.new('RGB',(768,1376),'white');draw=ImageDraw.Draw(image);draw.rectangle((190,450,570,850),fill='red');draw.rectangle((240,520,290,780),fill='cyan')
    source=folder/'reference.png';image.save(source)
    refs=[{'portrait_path':str(source),'portrait_sha256':digest(source),'character_id':'fixture-prop'}]
    inputs,identity=upload_references('http://127.0.0.1:8188',job_id,refs,folder/'prepared',lambda:None)
    graph=reference_graph('Keep the reference object: a red block with one cyan vertical stripe. Place this same object on a wooden table in a simple room. One object, vertical photograph, no text.',12345,'videostudio/'+job_id+'-images-acceptance',inputs)
    pipeline=Pipeline.__new__(Pipeline);pipeline.comfy='http://127.0.0.1:8188';pipeline.gpu_ownership=root/'data/gpu-ownership.json'
    result=pipeline.comfy_asset({'id':job_id,'output':str(folder)},'images-acceptance',graph,folder/'output.png',lambda:None)
    with Image.open(folder/'output.png') as output:
        output.load();embedded=json.loads(output.info.get('prompt','{}'))
        if embedded.get('4',{}).get('inputs',{}).get('images.image_1')!=['10',0]:raise RuntimeError('Generated PNG lacks the expected reference graph')
        dimensions=list(output.size)
    report={'passed':True,'scope':'local_reference_graph_execution','job_id':job_id,'output':str(folder/'output.png'),'dimensions':dimensions,'reference_images':identity,'prompt_id':result['prompt_id'],'semantic_identity_review':'pending'}
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
