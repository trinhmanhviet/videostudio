"""Same-origin editing APIs with bounded raw uploads and attested file access."""
import io
from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from .edit_plan import EditPlanService, MAX_UPLOAD
from .editing_presets import editing_presets


def register_edit_plan_routes(app, store, same_origin, public_job=None, *, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    service = EditPlanService(store,ffmpeg=ffmpeg,ffprobe=ffprobe)
    prefix = '/api/jobs/{job_id}/edit-plan'

    def call(fn, *args):
        try: return fn(*args)
        except KeyError as error: raise HTTPException(404, 'Job not found') from error
        except (ValueError, OSError, RuntimeError) as error:
            status = 409 if 'Stale' in str(error) or 'already used' in str(error) else 422
            raise HTTPException(status, str(error)) from error

    @app.get('/api/edit-presets')
    def presets(): return {'items': editing_presets()}

    @app.get(prefix)
    def view(job_id: str): return call(service.view, job_id)

    @app.put(prefix)
    def save(job_id: str, data: dict, request: Request):
        same_origin(request)
        return call(service.save, job_id, data.get('revision'), data.get('plan'))

    @app.post(prefix + '/preset')
    def preset(job_id: str, data: dict, request: Request):
        same_origin(request)
        return call(service.preset, job_id, data.get('revision'), data.get('preset_id'))

    @app.post(prefix + '/assets')
    async def upload(job_id: str, request: Request, name: str):
        same_origin(request)
        length = request.headers.get('content-length')
        if length:
            try:
                if int(length) > MAX_UPLOAD: raise HTTPException(413, 'Media exceeds 150 MB')
            except ValueError as error: raise HTTPException(422, 'Invalid content length') from error
        chunks = []; size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD: raise HTTPException(413, 'Media exceeds 150 MB')
            chunks.append(chunk)
        return call(service.import_asset, job_id, b''.join(chunks), name)

    @app.get(prefix + '/assets/{asset_id}')
    def media(job_id: str, asset_id: str, thumb: bool = False):
        path = call(service.asset_file, job_id, asset_id, thumb)
        if thumb:
            try:
                with Image.open(path) as im:
                    im = im.convert('RGB'); im.thumbnail((320, 568)); output = io.BytesIO(); im.save(output, format='JPEG', quality=80)
                return Response(output.getvalue(), media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=3600'})
            except OSError as error: raise HTTPException(422, 'Thumbnail requires a visual asset') from error
        return FileResponse(path, headers={'Cache-Control': 'private, max-age=3600'})

    @app.get(prefix + '/waveform')
    def waveform(job_id: str, asset_id: str): return call(service.waveform, job_id, asset_id)

    @app.post(prefix + '/export')
    def export(job_id: str, data: dict, request: Request, idempotency_key: str | None = Header(default=None)):
        same_origin(request)
        child = call(service.export, job_id, data.get('revision'), idempotency_key)
        if public_job: return public_job(child)
        return {k: child[k] for k in ('id', 'state', 'stage', 'error', 'created', 'updated')}

    return service
