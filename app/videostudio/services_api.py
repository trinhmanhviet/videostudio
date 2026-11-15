"""Dịch vụ nền in Cài đặt: status of ComfyUI and the dedicated Chrome, and stop / start / restart for each.

A restart can take minutes (an old ComfyUI may need time to give its GPU memory back), so actions run in a background
thread and the page polls GET /api/system/services. Owner only (the machine, or the owner through Cloudflare Access).
"""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request

from . import comfy_control

ACTIONS = ('restart', 'stop', 'start')


def register_service_routes(app, owner_request, same_origin, browser_manager, control=comfy_control):
    tasks = {'comfy': {'busy': None, 'message': '', 'at': 0.0}, 'chrome': {'busy': None, 'message': '', 'at': 0.0}}
    lock = threading.Lock()

    def run(service, action, work):
        def body():
            try:
                result = work()
                message = result.get('message') if isinstance(result, dict) else ''
                tasks[service].update(message=message or 'Xong.')
            except Exception as error:
                tasks[service].update(message=str(error)[:300])
            finally:
                tasks[service].update(busy=None, at=time.time())
        with lock:
            if tasks[service]['busy']:
                raise HTTPException(409, 'Đang ' + LABELS[tasks[service]['busy']] + ', chờ xong rồi bấm lại.')
            tasks[service].update(busy=action, message='', at=time.time())
        threading.Thread(target=body, name=f'service-{service}-{action}', daemon=True).start()

    def chrome_status():
        try:
            state = browser_manager.status()
            label = 'Đang chạy (debug)' if state.get('mode') == 'debug' else 'Đang chạy (chế độ sạch)' if state.get('running') else 'Đã tắt'
            return {'running': bool(state.get('running')), 'mode': state.get('mode'), 'label': label}
        except Exception as error:
            return {'running': None, 'label': 'Không đọc được: ' + str(error)[:120]}

    @app.get('/api/system/services')
    def services(request: Request):
        owner_request(request)
        try:
            comfy = control.status()
        except Exception as error:
            comfy = {'running': None, 'label': 'Không đọc được: ' + str(error)[:120]}
        return {'comfy': {**comfy, 'task': dict(tasks['comfy'])}, 'chrome': {**chrome_status(), 'task': dict(tasks['chrome'])}}

    @app.post('/api/system/services/{service}/{action}')
    def act(service: str, action: str, request: Request, data: dict | None = None):
        owner_request(request)
        same_origin(request)
        if service not in tasks or action not in ACTIONS:
            raise HTTPException(404, 'Không có thao tác này')
        force = (data or {}).get('force', False)
        if type(force) is not bool:
            raise HTTPException(422, 'force phải là bật/tắt')
        if service == 'comfy':
            if action != 'start' and not force and control.active_jobs():
                raise HTTPException(409, 'Đang có video hoặc ảnh chạy, ComfyUI có thể đang làm cho nó. Chờ xong, hoặc chọn vẫn làm.')
            work = {'restart': lambda: control.restart(force=True), 'stop': lambda: control.stop(force=True), 'start': control.start}[action]
        else:
            work = {'restart': browser_manager.restart, 'stop': browser_manager.stop, 'start': lambda: browser_manager.open('debug')}[action]
        run(service, action, work)
        return services(request)


LABELS = {'restart': 'khởi động lại', 'stop': 'tắt', 'start': 'bật'}
