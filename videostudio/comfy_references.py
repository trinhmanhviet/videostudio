"""Real image conditioning for the installed Qwen Image 2.1 node."""
import hashlib,uuid,io
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image,ImageOps
from .core import digest,PermanentError


def reference_graph(prompt,seed,prefix,inputs):
    from .providers import image_graph,node
    if not 1<=len(inputs)<=16:raise PermanentError('Qwen 2.1 requires 1..16 reference images')
    graph=image_graph(prompt,seed,prefix)
    graph['4']['inputs']['resolution']=0
    graph['6']['inputs']['latent_image']=['4',2]
    for index,name in enumerate(inputs,1):
        key=str(9+index);graph[key]=node('LoadImage',image=name)
        graph['4']['inputs'][f'images.image_{index}']=[key,0]
    return graph


def upload_references(base,job_id,references,folder,check):
    parsed=urlparse(base)
    uuid.UUID(job_id)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1','::1'):raise PermanentError('Reference upload requires local ComfyUI')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);names=[];identities=[]
    with httpx.Client(base_url=base.rstrip('/')+'/',timeout=30,trust_env=False) as client:
        try:response=client.get('object_info/TextEncodeQwenImage21')
        except (httpx.ConnectError,httpx.ConnectTimeout):
            from .gpu import recover_comfy
            recover_comfy(base,check);response=client.get('object_info/TextEncodeQwenImage21')
        response.raise_for_status()
        schema=response.json().get('TextEncodeQwenImage21',{}).get('input',{}).get('required',{}).get('images',[])
        if not schema or schema[0]!='COMFY_AUTOGROW_V3':raise PermanentError('Installed Qwen node lacks verified reference-image conditioning')
        for reference in references:
            check();source=Path(reference['portrait_path'])
            if not source.is_file() or digest(source)!=reference['portrait_sha256']:raise PermanentError('Reference image changed')
            identity=reference['portrait_sha256'];prepared=folder/(identity+'-canvas.png')
            with Image.open(source) as image:
                image.load();image=ImageOps.contain(image.convert('RGB'),(768,1376))
                canvas=Image.new('RGB',(768,1376),(127,127,127));canvas.paste(image,((768-image.width)//2,(1376-image.height)//2))
                encoded=io.BytesIO();canvas.save(encoded,format='PNG');expected_hash=hashlib.sha256(encoded.getvalue()).hexdigest()
            if prepared.is_file() and digest(prepared)!=expected_hash:raise PermanentError('Prepared reference canvas changed')
            if not prepared.is_file():
                temporary=prepared.with_suffix('.part');temporary.write_bytes(encoded.getvalue());temporary.replace(prepared)
            sha=digest(prepared);name=sha+'.png';subfolder='videostudio/references/'+job_id
            existing=client.get('view',params={'filename':name,'subfolder':subfolder,'type':'input'})
            if existing.status_code!=200 or hashlib.sha256(existing.content).hexdigest()!=sha:
                with prepared.open('rb') as stream:
                    uploaded=client.post('upload/image',data={'type':'input','subfolder':subfolder,'overwrite':'false'},files={'image':(name,stream,'image/png')})
                uploaded.raise_for_status();result=uploaded.json()
                if result.get('name')!=name or result.get('subfolder')!=subfolder or result.get('type')!='input':raise PermanentError('Comfy reference upload identity differs')
                verified=client.get('view',params={'filename':name,'subfolder':subfolder,'type':'input'});verified.raise_for_status()
                if hashlib.sha256(verified.content).hexdigest()!=sha:raise PermanentError('Uploaded reference hash differs')
            names.append(subfolder+'/'+name);identities.append({'character_id':reference['character_id'],'sha256':identity,'input_sha256':sha})
    return names,identities
