"""Local channel setup and publishing calendar routes."""
from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from .publishing import Publishing, PublishBlocked, PublishUncertain


def register_publishing_routes(app, store, versions, same_origin, local_request):
    service = Publishing(store, versions)
    app.state.publishing = service

    def call(function, *args):
        try:
            return function(*args)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy lịch đăng')
        except (ValueError, PublishBlocked, PublishUncertain) as error:
            raise HTTPException(422, str(error))
        except Exception:
            raise HTTPException(502, 'Không kết nối được nền tảng. Kiểm tra mạng rồi thử lại; thông tin bí mật không được ghi ra phản hồi.')

    def callback(request):
        return str(request.base_url).rstrip('/')+'/api/publishing/youtube/callback'

    @app.get('/api/publishing/channels')
    def channels(request: Request):
        local_request(request)
        return {**service.channels(), 'callback_url': callback(request)}

    @app.post('/api/publishing/youtube/config')
    def configure_youtube(data: dict, request: Request):
        local_request(request); same_origin(request)
        return call(service.configure_youtube, data.get('client_json'))

    @app.post('/api/publishing/youtube/connect')
    def connect_youtube(request: Request):
        local_request(request); same_origin(request)
        return call(service.oauth_start, callback(request))

    @app.get('/api/publishing/youtube/callback', response_class=HTMLResponse)
    def youtube_callback(request: Request, state: str = '', code: str = '', error: str = ''):
        local_request(request)
        if error or not state or not code:
            return HTMLResponse('<meta charset="utf-8"><p>Chưa cấp quyền. Trở lại VideoStudio → Cài đặt để kết nối lại.</p>', status_code=400)
        call(service.oauth_finish, state, code)
        return HTMLResponse('<meta charset="utf-8"><p>Đã kết nối YouTube. <a href="/?view=settings">Trở lại VideoStudio</a>.</p>',
                            headers={'Referrer-Policy':'no-referrer','Cache-Control':'no-store'})

    @app.post('/api/publishing/facebook/connect')
    def connect_facebook(data: dict, request: Request):
        local_request(request); same_origin(request)
        return call(service.connect_facebook, data)

    @app.delete('/api/publishing/channels/{channel_id}')
    def disconnect(channel_id: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.disconnect, channel_id)

    @app.get('/api/publishing/schedules')
    def schedules():
        return service.schedules()

    @app.post('/api/publishing/schedules', status_code=201)
    def create_schedule(data: dict, request: Request, idempotency_key: str | None = Header(default=None)):
        local_request(request); same_origin(request)
        return call(service.create_schedule, data, idempotency_key)

    @app.delete('/api/publishing/schedules/{identifier}')
    def cancel_schedule(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.cancel, identifier)

    @app.post('/api/publishing/schedules/{identifier}/retry')
    def retry_schedule(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.retry, identifier)

    @app.post('/api/publishing/schedules/{identifier}/reconcile')
    def reconcile_schedule(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.reconcile, identifier)

    return service
