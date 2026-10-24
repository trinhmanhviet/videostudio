"""One WebSocket reader dispatches CDP replies by ID and forwards lifecycle events."""
import asyncio
import json
import websockets


class CDPError(RuntimeError):
    pass


class CDPConnection:
    def __init__(self, on_event=None):
        self.ws = None
        self.reader = None
        self.pending = {}
        self.counter = 0
        self.on_event = on_event
        self.connect_lock = asyncio.Lock()

    @property
    def connected(self):
        return bool(self.ws and not self.ws.closed and self.reader and not self.reader.done())

    async def connect(self, url):
        async with self.connect_lock:
            if self.connected:
                return
            await self.close()
            self.ws = await websockets.connect(url, open_timeout=5, ping_interval=20, ping_timeout=20,
                                               max_size=8*1024*1024)
            self.reader = asyncio.create_task(self._read(self.ws))

    async def _read(self, ws):
        try:
            async for raw in ws:
                data = json.loads(raw)
                future = self.pending.get(data.get('id'))
                if future and not future.done():
                    if 'error' in data:
                        future.set_exception(CDPError(data['error'].get('message', 'CDP error')))
                    else:
                        future.set_result(data.get('result', {}))
                elif data.get('method') and self.on_event:
                    self.on_event(data)
        except (websockets.ConnectionClosed, OSError):
            pass
        finally:
            for f in tuple(self.pending.values()):
                if not f.done():
                    f.set_exception(ConnectionError('Chrome CDP disconnected'))

    async def command(self, method, params=None, session=None, timeout=10):
        if not self.connected:
            raise ConnectionError('Chrome CDP is not connected')
        self.counter += 1
        identifier = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        message = {'id':identifier, 'method':method, 'params':params or {}}
        if session:
            message['sessionId'] = session
        try:
            await self.ws.send(json.dumps(message))
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(identifier, None)

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
        self.ws = None
        self.reader = None
