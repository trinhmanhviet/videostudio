import asyncio
import json
import unittest
import websockets
from videostudio.cdp_protocol import CDPConnection, CDPError


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received=[]
        async def handler(ws):
            async for raw in ws:
                m=json.loads(raw);self.received.append(m)
                await ws.send(json.dumps({'method':'Target.targetDestroyed','params':{'targetId':'old'}}))
                if m['method']=='error':
                    await ws.send(json.dumps({'id':m['id'],'error':{'code':-1,'message':'expected failure'}}))
                elif m['method']=='disconnect':
                    await ws.close()
                elif m['method']=='hold':
                    continue
                else:
                    await ws.send(json.dumps({'id':m['id'],'result':{'method':m['method']}}))
        self.server=await websockets.serve(handler,'127.0.0.1',0)
        self.url='ws://127.0.0.1:'+str(self.server.sockets[0].getsockname()[1])
        self.events=[]
        self.cdp=CDPConnection(on_event=self.events.append)
        await self.cdp.connect(self.url)

    async def asyncTearDown(self):
        await self.cdp.close();self.server.close();await self.server.wait_closed()

    async def test_events_do_not_consume_command_response_and_concurrent_ids_match(self):
        a,b=await asyncio.gather(self.cdp.command('first'),self.cdp.command('second'))
        self.assertEqual(a['method'],'first');self.assertEqual(b['method'],'second')
        self.assertEqual(len(self.events),2)

    async def test_protocol_error_is_not_silently_empty_result(self):
        with self.assertRaisesRegex(CDPError,'expected failure'):
            await self.cdp.command('error')

    async def test_disconnect_fails_pending_without_waiting_for_timeout(self):
        with self.assertRaises(ConnectionError):
            await asyncio.wait_for(self.cdp.command('disconnect'),1)
        self.assertFalse(self.cdp.connected)

    async def test_command_timeout_cleans_pending(self):
        with self.assertRaises(TimeoutError):
            await self.cdp.command('hold',timeout=.05)
        self.assertEqual(self.cdp.pending,{})

    async def test_health_is_passive_and_reconnect_does_not_add_second_reader(self):
        self.assertTrue(self.cdp.connected)
        reader=self.cdp.reader
        await self.cdp.connect(self.url)
        self.assertIs(reader,self.cdp.reader)
        self.assertEqual(self.received,[])

if __name__=='__main__':unittest.main()
