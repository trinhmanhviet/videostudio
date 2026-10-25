"""Same-origin scene editor routes, bytes-only uploads and attested image serving."""
import io
from pathlib import Path
from fastapi import HTTPException,Request,Header
from fastapi.responses import FileResponse,Response
from PIL import Image
from .scene_editor import MAX_UPLOAD

def register_editor_routes(app,store,editor,same_origin,public_job,image_jobs):
    prefix='/api/jobs/{job_id}/scene-editor'
    def call(fn,*args):
        try:return fn(*args)
        except KeyError:raise HTTPException(404,'Job not found')
        except (ValueError,OSError) as e:raise HTTPException(409 if 'Stale' in str(e) or 'already used' in str(e) else 422,str(e))
    def public(v):
        return {**v,'scenes':[{k:x for k,x in r.items() if k not in ('image_path','original_path')} for r in v['scenes']]}
    @app.get(prefix)
    def view(job_id:str):return public(call(editor.view,job_id))
    @app.post(prefix+'/mode')
    def mode(job_id:str,data:dict,request:Request):
        same_origin(request);return public(call(editor.set_mode,job_id,data.get('mode'),data.get('version')))
    @app.post(prefix+'/scenes/{scene_id}/image')
    async def upload(job_id:str,scene_id:str,request:Request,version:int,fit:str='cover'):
        same_origin(request)
        length=request.headers.get('content-length')
        if length:
            try:
                if int(length)>MAX_UPLOAD:raise HTTPException(413,'Image exceeds 20 MB')
            except ValueError:raise HTTPException(422,'Invalid content length')
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>MAX_UPLOAD:raise HTTPException(413,'Image exceeds 20 MB')
            chunks.append(chunk)
        return public(call(editor.replace,job_id,scene_id,b''.join(chunks),fit,version))
    @app.get(prefix+'/scenes/{scene_id}/image')
    def image(job_id:str,scene_id:str,edit:str='original',thumb:bool=False):
        p=call(editor.image_file,job_id,scene_id,edit)
        if thumb:
            # Derived thumbnail only; never modify the checkpoint image.
            with Image.open(p) as im:
                im=im.convert('RGB');im.thumbnail((320,568));b=io.BytesIO();im.save(b,format='JPEG',quality=80)
            return Response(b.getvalue(),media_type='image/jpeg',headers={'Cache-Control':'private, max-age=3600'})
        return FileResponse(p,media_type='image/png')
    @app.get(prefix+'/scenes/{scene_id}/audio')
    def audio(job_id:str,scene_id:str):return FileResponse(call(editor.audio_file,job_id,scene_id),media_type='audio/wav')
    @app.post(prefix+'/scenes/{scene_id}/restore')
    def restore(job_id:str,scene_id:str,data:dict,request:Request):
        same_origin(request);return public(call(editor.restore,job_id,scene_id,data.get('edit_id','original'),data.get('version')))
    @app.post(prefix+'/scenes/{scene_id}/approve')
    def approve(job_id:str,scene_id:str,data:dict,request:Request):
        same_origin(request);return public(call(editor.approve,job_id,scene_id,data.get('image_sha256'),data.get('version')))
    @app.post(prefix+'/export')
    def export(job_id:str,data:dict,request:Request,idempotency_key:str|None=Header(default=None)):
        same_origin(request);child=call(editor.export,job_id,data.get('version'),idempotency_key,data.get('confirm_all',True));return public_job(child)

    generations=prefix+'/scenes/{scene_id}/generations'
    @app.get(generations)
    def image_generations(job_id:str,scene_id:str):
        return {'items':[image_jobs.public(t) for t in call(image_jobs.list,job_id,scene_id)],'providers':['chatgpt']}
    @app.post(generations,status_code=202)
    def generate_scene_image(job_id:str,scene_id:str,data:dict,request:Request,idempotency_key:str|None=Header(default=None)):
        same_origin(request)
        return image_jobs.public(call(image_jobs.start,job_id,scene_id,data.get('prompt'),data.get('provider','chatgpt'),idempotency_key,data.get('version')))
    @app.get(generations+'/{task_id}')
    def image_generation_status(job_id:str,scene_id:str,task_id:str):
        return image_jobs.public(call(image_jobs.scoped,job_id,scene_id,task_id))
    @app.get(generations+'/{task_id}/image')
    def image_generation_file(job_id:str,scene_id:str,task_id:str):
        p=call(image_jobs.candidate,job_id,scene_id,task_id)
        with Image.open(p) as im:kind=Image.MIME.get(im.format,'application/octet-stream')
        return FileResponse(p,media_type=kind)
    @app.post(generations+'/{task_id}/apply')
    def apply_image_generation(job_id:str,scene_id:str,task_id:str,data:dict,request:Request):
        same_origin(request)
        return public(call(image_jobs.apply,job_id,scene_id,task_id,data.get('version'),data.get('fit','cover')))
    @app.post(generations+'/{task_id}/resume')
    def resume_image_generation(job_id:str,scene_id:str,task_id:str,request:Request):
        same_origin(request);return image_jobs.public(call(image_jobs.resume,job_id,scene_id,task_id))
    @app.post(generations+'/{task_id}/cancel')
    def cancel_image_generation(job_id:str,scene_id:str,task_id:str,request:Request):
        same_origin(request);return image_jobs.public(call(image_jobs.cancel,job_id,scene_id,task_id))
