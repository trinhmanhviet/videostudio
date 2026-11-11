"""Same-origin factory, queue and verified library routes."""
from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .content_factory import ContentFactory


def register_content_factory_routes(app, store, same_origin, public_job, submit_job,
                                    validate_submission=None, video_probe=None, retry_job=None):
    service = ContentFactory(store, submit_job, public_job, validate_submission, video_probe, retry_job)
    app.state.content_factory = service

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy mục hoặc video')
        except ValueError as error:
            message = str(error)
            conflict = any(part in message for part in ('already used', 'đã thay đổi', 'đang xử lý', 'đang được', 'checkpoint', 'Chỉ đổi'))
            raise HTTPException(409 if conflict else 422, message)

    @app.get('/api/factory/batches')
    def batches():
        return service.list_batches()

    @app.post('/api/factory/batches', status_code=201)
    def create_batch(data: dict, request: Request, idempotency_key: str | None = Header(default=None)):
        same_origin(request)
        return call(service.create_batch, data, idempotency_key, request.headers.get('x-connector-scope'))

    @app.get('/api/factory/batches/{batch_id}')
    def batch(batch_id: str):
        return call(service.get_batch, batch_id)

    @app.get('/api/factory/queue')
    def queue():
        return service.queue()

    @app.post('/api/factory/queue/pause')
    def pause(data: dict, request: Request):
        same_origin(request)
        return call(service.set_paused, data.get('paused'))

    @app.post('/api/factory/queue/reorder')
    def reorder(data: dict, request: Request):
        same_origin(request)
        return call(service.reorder, data.get('item_ids', data.get('ids')))

    @app.post('/api/factory/items/{item_id}/cancel')
    def cancel(item_id: str, request: Request):
        same_origin(request)
        return call(service.item_action, item_id, 'cancel')

    @app.post('/api/factory/items/{item_id}/skip')
    def skip(item_id: str, request: Request):
        same_origin(request)
        return call(service.item_action, item_id, 'skip')

    @app.post('/api/factory/items/{item_id}/retry')
    def retry(item_id: str, request: Request):
        same_origin(request)
        return call(service.item_action, item_id, 'retry', request.headers.get('x-connector-scope'))

    @app.get('/api/factory/videos')
    def videos(q: str = '', style: str = '', project: str = '', review_state: str = '',
               status: str = '', channel: str = '', page: int = 1, page_size: int = 20):
        return call(service.videos, q, style, project, review_state, status, channel, page, page_size)

    @app.get('/api/factory/videos/{job_id}/versions')
    def versions(job_id: str):
        job = call(store.get, job_id)
        return {'items': service._discover_versions(job), 'approved': service.approved_version(job_id)}

    @app.post('/api/factory/videos/{job_id}/approve')
    def approve(job_id: str, data: dict, request: Request):
        same_origin(request)
        record = call(service.approve, job_id, data.get('version_id'), data.get('sha256', data.get('hash')))
        return {'approved': record, **record}

    @app.get('/api/factory/videos/{job_id}/versions/{version_id}/file')
    def video_file(job_id: str, version_id: str):
        version = call(service.get_video_version, job_id, version_id)
        return FileResponse(version['path'], media_type='video/mp4', filename=version['name'])

    @app.get('/api/factory/videos/{job_id}/pack')
    def pack(job_id: str, version_id: str | None = None, include: str = 'video,captions,sidecar'):
        stream = call(service.pack, job_id, version_id, tuple(part.strip() for part in include.split(',') if part.strip()))
        def chunks():
            try:
                yield from iter(lambda: stream.read(1024 * 1024), b'')
            finally:
                stream.close()
        return StreamingResponse(chunks(), media_type='application/zip',
                                 headers={'Content-Disposition': f'attachment; filename="video-{job_id}.zip"'})

    return service
