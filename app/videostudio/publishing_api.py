"""Local channel setup and publishing calendar routes."""
from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from .publishing import Publishing, PublishBlocked, PublishUncertain


def register_publishing_routes(app, store, versions, same_origin, local_request):
    service = Publishing(store, versions)
    app.state.publishing = service
    from .publishing_plans import PostingPlans
    from .shorts import ShortMaker, load as load_short
    shorts = ShortMaker(store, service, versions)
    plans = PostingPlans(store, service, versions, shorts=shorts)
    service.plans = plans
    service.shorts = shorts
    publish_tick = service.tick

    def shorts_loop(stop):  # its own thread: a short asks ChatGPT and cuts a video, which must not hold up the posting
        import logging
        while not stop.is_set():
            try:
                did = shorts.tick()
            except Exception:
                logging.getLogger(__name__).exception('Shorts will retry')
                did = False
            stop.wait(5 if did else 30)
    app.state.shorts_loop = shorts_loop  # started with the other background threads (create_app)

    # Truyện trên YouTube: ChatGPT titles, chapter thumbnails, one playlist per book (story_promo.py)
    from .story_promo import StoryPromo, set_branding
    promo = StoryPromo(store, service)
    service.promo = promo

    def promo_loop(stop):
        import logging
        while not stop.is_set():
            try:
                did = promo.tick()
            except Exception:
                logging.getLogger(__name__).exception('Story promo will retry')
                did = False
            stop.wait(20 if did else 120)
    app.state.promo_loop = promo_loop

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

    @app.post('/api/publishing/schedules/{identifier}/publish-now')
    def publish_schedule_now(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.publish_now, identifier)

    @app.post('/api/publishing/schedules/{identifier}/retry')
    def retry_schedule(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.retry, identifier)

    @app.post('/api/publishing/schedules/{identifier}/reconcile')
    def reconcile_schedule(identifier: str, request: Request):
        local_request(request); same_origin(request)
        return call(service.reconcile, identifier)

    # --- Bản ngắn ----------------------------------------------------------------------------------------
    def short_state(job_id):
        record = load_short(job_id)
        waiting = [r for r in shorts.requests(job_id) if r['state'] == 'waiting']
        failed = next((r for r in shorts.requests(job_id) if r['state'] == 'failed'), None)
        return {'short': {k: v for k, v in record.items() if k != 'path'} if record else None,
                'file_url': f'/api/shorts/{job_id}/file' if record else None,
                'waiting': len(waiting), 'error': failed['note'] if failed and not record else None}

    @app.get('/api/shorts/flags')
    def short_flags():
        return {'items': shorts.flags()}

    @app.get('/api/shorts/{job_id}')
    def short_get(job_id: str):
        try:
            return short_state(job_id)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/shorts/{job_id}/file')
    def short_file(job_id: str):
        from fastapi.responses import FileResponse
        try:
            record = load_short(job_id)
        except ValueError as error:
            raise HTTPException(422, str(error))
        if not record:
            raise HTTPException(404, 'Chưa có bản ngắn')
        return FileResponse(record['path'], media_type='video/mp4', filename='ban-ngan.mp4')

    @app.post('/api/shorts/{job_id}/post')
    def short_post(job_id: str, data: dict, request: Request):
        """Make (when needed) and schedule the short on the ticked channels; the work runs in the background."""
        local_request(request); same_origin(request)
        from datetime import datetime
        channels = data.get('channels')
        known = {c['id'] for c in service.channels()['items'] if c.get('connected')}
        if not isinstance(channels, list) or not channels or any(c not in known for c in channels):
            raise HTTPException(422, 'Tick ít nhất một kênh đã kết nối')
        try:
            at = datetime.fromisoformat(str(data.get('publish_at')).replace('Z', '+00:00')).timestamp()
            load_short(job_id)  # checks the id
        except ValueError:
            raise HTTPException(422, 'Giờ đăng hoặc mã video không hợp lệ')
        if at < service.clock() + 600:
            raise HTTPException(422, 'Chọn giờ đăng ít nhất 10 phút từ bây giờ (tool cần thời gian cắt và tải lên)')
        shorts.request(job_id, channels, at)
        return short_state(job_id)

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

    # --- Truyện trên YouTube: tiêu đề, ảnh bìa, danh sách phát, mô tả kênh ----------------------------------------
    @app.get('/api/story-promo')
    def promo_status():
        return promo.status()

    @app.post('/api/story-promo/backfill')
    def promo_backfill(data: dict, request: Request):
        """The owner's yes for story videos uploaded before the feature: which parts may be changed on them."""
        local_request(request); same_origin(request)
        parts = data.get('parts')
        if not isinstance(parts, list) or not data.get('channel_id'):
            raise HTTPException(422, 'Chọn kênh và phần được sửa (title, category, thumbnail, playlist)')
        return promo.approve_backfill(data['channel_id'], parts)

    @app.get('/api/story-promo/books')
    def promo_books(page: int = 1, page_size: int = 12):
        """Kho video → Kể truyện: the books, small cards."""
        try:
            return promo.books(page, page_size)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/story-promo/books/{book_id}/cast')
    def promo_cast(book_id: str):
        try:
            return promo.cast(book_id)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/story-promo/books/{book_id}/cast/{cast_id}')
    def promo_portrait(book_id: str, cast_id: str):
        from fastapi.responses import FileResponse
        try:
            return FileResponse(promo.portrait_file(book_id, cast_id), media_type='image/png', headers={'Cache-Control': 'no-cache'})
        except (KeyError, ValueError):
            raise HTTPException(404, 'Chưa có chân dung')

    @app.get('/api/story-promo/thumb/{job_id}')
    def promo_thumb(job_id: str):
        from fastapi.responses import FileResponse
        try:
            return FileResponse(promo.thumb_file(job_id), media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
        except (KeyError, ValueError):
            raise HTTPException(404, 'Chưa có ảnh bìa')

    @app.post('/api/story-promo/{job_id}/repaint')
    def promo_repaint(job_id: str, request: Request):
        """Vẽ lại ảnh bìa: a new picture for the episode (title kept), drawn when the GPU is free."""
        local_request(request); same_origin(request)
        try:
            return promo.repaint(job_id)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.post('/api/story-promo/{job_id}/redo')
    def promo_redo(job_id: str, request: Request):
        local_request(request); same_origin(request)
        try:
            return promo.redo(job_id)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.put('/api/publishing/youtube/{channel_id}/branding')
    def youtube_branding(channel_id: str, data: dict, request: Request):
        local_request(request); same_origin(request)
        description, words = data.get('description'), data.get('keywords') or []
        if not isinstance(description, str) or not description.strip() or not isinstance(words, list):
            raise HTTPException(422, 'Nhập mô tả kênh và danh sách từ khoá')
        return call(set_branding, service, channel_id, description.strip(), words, data.get('country') or 'VN')

    return service
