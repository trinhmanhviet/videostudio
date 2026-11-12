"""Local-only explicit posting confirmation and minimal durable post history."""
from fastapi import Header,HTTPException,Request
from .posted_cleanup import PostedCleanup


def register_posted_cleanup_routes(app,store,same_origin,local_request):
    service=PostedCleanup(store)
    app.state.posted_cleanup=service

    def call(function,*args):
        try:return function(*args)
        except KeyError:raise HTTPException(404,'Không tìm thấy video hoặc bản ghi')
        except ValueError as error:raise HTTPException(409,str(error))
        except OSError:raise HTTPException(409,'Tệp đang được sử dụng; chưa dọn được, hãy thử lại sau')

    @app.get('/api/publication-history')
    def history(q:str='',platform:str='',page:int=1,page_size:int=10):
        try:return service.history(q,platform,page,page_size)
        except ValueError as error:raise HTTPException(422,str(error))

    @app.post('/api/jobs/{job_id}/posted-cleanup')
    def posted_cleanup(job_id:str,data:dict,request:Request,idempotency_key:str|None=Header(default=None)):
        local_request(request);same_origin(request)
        if not idempotency_key or len(idempotency_key)>200:raise HTTPException(422,'Idempotency-Key required, tối đa 200 ký tự')
        try:service._body(data)
        except ValueError as error:raise HTTPException(422,str(error))
        from .meme_editor import _LIB_LOCK,_EDITOR_RENDERS
        with _LIB_LOCK:
            if job_id in _EDITOR_RENDERS:raise HTTPException(409,'Video đang xuất lại; chờ hoàn tất trước khi dọn')
            from . import social_copy
            with social_copy._lock:
                if job_id in social_copy._running:raise HTTPException(409,'Đang viết nội dung đăng cho video; chờ hoàn tất trước khi dọn')
            return call(service.posted_cleanup,job_id,data,idempotency_key,True)

    @app.get('/api/jobs/{job_id}/posted-cleanup')
    def cleanup_status(job_id:str,request:Request,idempotency_key:str|None=Header(default=None)):
        local_request(request)
        if not idempotency_key or len(idempotency_key)>200:raise HTTPException(422,'Idempotency-Key required, tối đa 200 ký tự')
        return call(service.status,job_id,idempotency_key)

    @app.post('/api/publication-history/{identifier}/cleanup')
    def retry_cleanup(identifier:str,data:dict,request:Request):
        local_request(request);same_origin(request)
        if data.get('confirm') is not True:raise HTTPException(422,'Cần xác nhận dọn tệp')
        return call(service.retry_cleanup,identifier)

    return service
