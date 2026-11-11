"""Opt-in request lab: python -m FlowAPI.server. No production jobs or Chrome restarts."""
from pathlib import Path
import re

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .bridge import FlowRequestBridge

ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = frozenset(('localhost:8877', '127.0.0.1:8877', 'localhost:8878', '127.0.0.1:8878'))


def local_page(request):
    host = request.headers.get('host', '')
    if host not in ALLOWED_HOSTS:
        raise HTTPException(403, 'Chỉ cho phép truy cập hệ thống qua loopback')
    origin = request.headers.get('origin')
    if origin and origin != 'http://' + host:
        raise HTTPException(403, 'Không cho phép website khác điều khiển Flow')


def extension_origin(request):
    if request.headers.get('host', '') not in ALLOWED_HOSTS:
        raise HTTPException(403, 'Invalid local host')
    origin = request.headers.get('origin', '')
    if not re.fullmatch(r'chrome-extension://[a-p]{32}', origin):
        raise HTTPException(403, 'Cần kết nối từ extension Flow')
    return origin


def create_router(database):
    router = APIRouter()
    bridge = FlowRequestBridge(database)

    def worker(request):
        origin = extension_origin(request)
        auth = request.headers.get('authorization', '')
        client = request.headers.get('x-flow-client', '')
        if not auth.startswith('Bearer '):
            raise PermissionError('Thiếu khóa kết nối extension')
        bridge.authenticate(client, auth[7:], origin)
        return client

    def translate(action):
        try:
            return action()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, 'Request không tồn tại') from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.get('/flow-request')
    def page(request: Request):
        local_page(request)
        return FileResponse(ROOT / 'request.html', headers={'Cache-Control': 'no-store'})

    @router.get('/flow-request.js')
    def script(request: Request):
        local_page(request)
        return FileResponse(ROOT / 'request.js', media_type='application/javascript')

    @router.get('/api/flow-request/status')
    def status(request: Request):
        local_page(request)
        return bridge.status()

    @router.post('/api/flow-request/invitation')
    def invitation(request: Request):
        local_page(request)
        return bridge.invitation()

    @router.post('/api/flow-request/pair')
    def pair(data: dict, request: Request):
        origin = extension_origin(request)
        return translate(lambda: bridge.pair(data.get('code'), origin))

    @router.post('/api/flow-request/poll')
    def poll(data: dict, request: Request):
        return translate(lambda: bridge.poll(worker(request), data))

    @router.post('/api/flow-request/commands/{request_id}/result')
    def complete(request_id: str, data: dict, request: Request):
        result = data.get('result')
        if not isinstance(result, dict):
            raise HTTPException(422, 'Thiếu kết quả request')
        return translate(lambda: bridge.complete(worker(request), request_id, data.get('dispatch'), result))

    @router.post('/api/flow-request/commands')
    def enqueue(data: dict, request: Request):
        local_page(request)
        return translate(lambda: bridge.enqueue(data.get('client_id'), data.get('operation'),
                                                data.get('arguments'), data.get('id'), data.get('confirm_generation')))

    @router.get('/api/flow-request/commands/{request_id}')
    def receipt(request_id: str, request: Request):
        local_page(request)
        return translate(lambda: bridge.get(request_id))

    @router.post('/api/flow-request/commands/{request_id}/consume-verification')
    def consume(request_id: str, data: dict, request: Request):
        local_page(request)
        value = translate(lambda: bridge.consume_verification(request_id, data.get('key')))
        return JSONResponse(value, headers={'Cache-Control': 'no-store'})

    return router


def create_app(database=None):
    app = FastAPI(title='VideoStudio Flow request lab')
    app.include_router(create_router(database or ROOT.parents[1] / 'data' / 'flow-request.sqlite3'))

    @app.get('/')
    def home(request: Request):
        local_page(request)
        return FileResponse(ROOT / 'request.html', headers={'Cache-Control': 'no-store'})

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(), host='127.0.0.1', port=8878, access_log=False)
