"""Local channel setup and publishing calendar routes."""
from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from .publishing import Publishing, PublishBlocked, PublishUncertain


def register_publishing_routes(app, store, versions, same_origin, local_request):
    service = Publishing(store, versions)
    app.state.publishing = service
    from .publishing_plans import PostingPlans
    plans = PostingPlans(store, service, versions)
    service.plans = plans
    publish_tick = service.tick

    def tick():  # the publishing loop also runs the posting plans (every few minutes)
        try:
            plans.tick()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Posting plans will retry')
        return publish_tick()
    service.tick = tick

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

    @app.post('/api/publishing/channels/{channel_id}/remove')
    def remove_channel(channel_id: str, request: Request):
        local_request(request); same_origin(request)
        try:
            return service.remove_channel(channel_id)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy kênh')
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/publishing/facebook/reels')
    def facebook_reels(channel_id: str = '', refresh: bool = False):
        if not channel_id:
            channel_id = next((c['id'] for c in service.channels()['items'] if c['platform'] == 'facebook' and c['connected']), '')
        if not channel_id:
            raise HTTPException(422, 'Chưa kết nối Facebook Page')
        return call(service.facebook_reels, channel_id, refresh)

    @app.get('/api/publishing/youtube/videos')
    def youtube_videos(channel_id: str, refresh: bool = False):
        return call(service.youtube_videos, channel_id, refresh)

    @app.post('/api/publishing/facebook-check')
    def facebook_check(data: dict):
        from .facebook_safety import check
        text = data.get('text')
        if not isinstance(text, str) or len(text) > 5000:
            raise HTTPException(422, 'Lời đăng tối đa 5000 ký tự')
        return check(text)

    @app.put('/api/publishing/default-channels')
    def default_channels(data: dict, request: Request):
        local_request(request); same_origin(request)
        return call(service.set_default_channels, data)

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

    # --- Đăng tự động -----------------------------------------------------------------------------------
    def plan_call(function, *args):
        try:
            return function(*args)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy kế hoạch đăng')
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/publishing/plans')
    def list_plans():
        return {**plans.items(), 'projects': plans.projects()}

    @app.post('/api/publishing/plans')
    def create_plan(data: dict, request: Request):
        same_origin(request)
        return plan_call(plans.save, data)

    @app.put('/api/publishing/plans/{plan_id}')
    def update_plan(plan_id: str, data: dict, request: Request):
        same_origin(request)
        return plan_call(plans.save, data, plan_id)

    @app.delete('/api/publishing/plans/{plan_id}')
    def delete_plan(plan_id: str, request: Request):
        same_origin(request)
        return plan_call(plans.delete, plan_id)

    @app.post('/api/publishing/plans/run')
    def run_plans(request: Request):
        same_origin(request)
        return {'scheduled': plans.tick(force=True), **plans.items()}

    return service
