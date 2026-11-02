"""Desktop client for the paired extension. Does not read browser cookies or launch Chrome."""
import time
import uuid
import hashlib
import secrets

import httpx


class FlowRequestFailure(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        self.request_id = receipt['id']
        super().__init__((receipt.get('result') or {}).get('message') or receipt['state'])


class FlowRequestClient:
    def __init__(self, base_url='http://localhost:8878', client_id=None):
        if base_url not in ('http://localhost:8878', 'http://127.0.0.1:8878', 'http://localhost:8877', 'http://127.0.0.1:8877'):
            raise ValueError('Flow request bridge must use a local VideoStudio endpoint')
        self.base_url = base_url + '/api/flow-request'
        self.client_id = client_id

    def _get(self, path):
        response = httpx.get(self.base_url + path, timeout=12, trust_env=False)
        response.raise_for_status()
        return response.json()

    def submit(self, operation, arguments, *, request_id=None, confirm_generation=False):
        """POST once. On any HTTP/network failure the exception retains the ID for GET reconciliation."""
        request_id = request_id or str(uuid.uuid4())
        client_id = self.client_id
        if client_id is None:
            candidates = [item for item in self._get('/status')['clients']
                          if item['connected'] and item.get('enabled') and item.get('session_ready')]
            if len(candidates) != 1:
                raise ValueError('Chọn client_id cụ thể khi chưa có hoặc có nhiều phiên Flow sẵn sàng')
            client_id = candidates[0]['client_id']
        try:
            response = httpx.post(self.base_url + '/commands', timeout=12, trust_env=False,
                                  json={'id': request_id, 'client_id': client_id, 'operation': operation,
                                        'arguments': arguments, 'confirm_generation': confirm_generation})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            if 400 <= error.response.status_code < 500:
                try:detail=error.response.json().get('detail')
                except ValueError:detail=None
                message=detail if isinstance(detail,str) else 'Bridge từ chối yêu cầu trước khi dispatch'
                code='verification_guarded' if message.startswith('verification_guarded:') else 'local_request_rejected'
                raise FlowRequestFailure({'id':request_id,'state':'failed','result':{'code':code,'message':message}}) from None
            raise FlowRequestFailure({'id':request_id,'state':'uncertain','result':{'code':'desktop_response_missing','message':'Chưa rõ bridge đã nhận yêu cầu; kiểm tra cùng request ID.'}}) from None
        except httpx.HTTPError as error:
            raise FlowRequestFailure({'id': request_id, 'state': 'uncertain', 'result': {
                'code': 'desktop_response_missing', 'message': 'Chưa nhận được biên nhận gửi. Dùng receipt(request_id) để kiểm tra; không tạo request mới.'}}) from error

    def receipt(self, request_id):
        return self._get('/commands/' + str(uuid.UUID(request_id)))

    def acquire_verification(self, context):
        """Consume one short-lived browser result in RAM; never return it to the UI."""
        key = secrets.token_urlsafe(32)
        identifier = str(uuid.uuid5(uuid.UUID(context['request_id']), 'desktop-verification'))
        self.submit('prepare_generation', {'project_id': context['project_id'],
                    'handoff_hash': hashlib.sha256(key.encode()).hexdigest()}, request_id=identifier)
        self.wait(identifier, timeout=75)
        response = httpx.post(self.base_url + '/commands/' + identifier + '/consume-verification',
                              json={'key': key}, timeout=12, trust_env=False)
        response.raise_for_status()
        value = response.json()
        if value.get('expires', 0) <= time.time():
            raise ValueError('Kết quả xác minh hết hạn')
        return value

    def wait(self, request_id, timeout=90):
        deadline = time.monotonic() + timeout
        while True:
            receipt = self.receipt(request_id)
            if receipt['state'] == 'completed':
                return receipt['result']
            if receipt['state'] in ('failed', 'blocked', 'uncertain'):
                raise FlowRequestFailure(receipt)
            if time.monotonic() >= deadline:
                raise FlowRequestFailure({'id': request_id, 'state': 'uncertain', 'result': {
                    'message': 'Hết thời gian chờ. Request vẫn được giữ; kiểm tra lại cùng ID.'}})
            time.sleep(1)
