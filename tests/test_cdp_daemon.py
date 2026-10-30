import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from aiohttp.test_utils import TestClient, TestServer
from videostudio.cdp_daemon import ChromeChatGPTBridge, create_app
from videostudio.cdp_requests import RequestJournal


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.launcher=MagicMock()
        self.bridge=ChromeChatGPTBridge(launcher=self.launcher,journal=RequestJournal(Path(self.tmp.name)/'db'))
        self.client=TestClient(TestServer(await create_app(self.bridge)))
        await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()
    async def test_status_poll_is_passive_and_never_launches_or_connects(self):
        for _ in range(3):
            r=await self.client.get('/api/status')
            d=await r.json();self.assertFalse(d['connected']);self.assertFalse(d['ready'])
        self.launcher.ensure_started.assert_not_called()
    async def test_cross_origin_and_missing_client_header_cannot_control_browser(self):
        for headers in ({},{'Origin':'https://evil.example','X-VS-Client':'videostudio'}):
            r=await self.client.post('/api/browser/start',json={},headers=headers)
            self.assertEqual(r.status,403)
        self.launcher.ensure_started.assert_not_called()
    async def test_cached_receipt_does_not_need_browser_or_resubmit(self):
        r=self.bridge.journal.prepare('job','prompt');self.bridge.journal.complete(r['id'],{'done':True})
        self.assertEqual(await self.bridge.ask_chatgpt('job','prompt'),{'done':True})
        self.launcher.ensure_started.assert_not_called()
    async def test_owned_tab_recreated_when_closed_does_not_take_foreign_tab(self):
        self.bridge.journal.set_conversation('job','https://chatgpt.com/c/owned','gone')
        self.bridge.cdp=MagicMock()
        self.bridge.cdp.close=AsyncMock()
        self.bridge.cdp.command=AsyncMock(side_effect=[{'targetInfos':[{'targetId':'foreign','url':'https://chatgpt.com/c/personal','type':'page'}]}, {'targetId':'new'}])
        tid=await self.bridge.ensure_tab('job')
        self.assertEqual(tid,'new')
        self.assertEqual(self.bridge.cdp.command.call_args_list[1].args[0],'Target.createTarget')
        self.assertEqual(self.bridge.cdp.command.call_args_list[1].args[1]['url'],'https://chatgpt.com/c/owned')
    async def test_reuses_only_owned_text_tab_and_preserves_other_tabs(self):
        self.bridge.journal.own_target('tab1','text')
        self.bridge.journal.set_conversation('prior','https://chatgpt.com/','tab1')
        self.bridge.cdp=MagicMock()
        self.bridge.cdp.close=AsyncMock()
        self.bridge.cdp.command=AsyncMock(side_effect=[
            {'targetInfos':[
                {'targetId':'tab1','url':'https://chatgpt.com/','type':'page'},
                {'targetId':'tab2','url':'https://chatgpt.com/c/old','type':'page'},
                {'targetId':'blank','url':'about:blank','type':'page'}
            ]},
            {},
            {}
        ])
        tid=await self.bridge.ensure_tab('new-job')
        self.assertEqual(tid,'tab1')
        closed=[c.args[1]['targetId'] for c in self.bridge.cdp.command.call_args_list if c.args[0]=='Target.closeTarget']
        self.assertEqual(closed,[])
        self.assertEqual(self.bridge.journal.conversation('new-job')['target'],'tab1')
    async def test_new_text_job_does_not_borrow_or_close_image_or_foreign_tab(self):
        self.bridge.journal.own_target('img','image');self.bridge.cdp=MagicMock();self.bridge.cdp.close=AsyncMock()
        self.bridge.cdp.command=AsyncMock(side_effect=[{'targetInfos':[{'targetId':'img','url':'https://chatgpt.com/c/image','type':'page'},{'targetId':'foreign','url':'https://chatgpt.com/c/human','type':'page'}]},{'targetId':'new-text'}])
        self.assertEqual(await self.bridge.ensure_tab('new'),'new-text')
        self.assertFalse(any(c.args[0]=='Target.closeTarget' for c in self.bridge.cdp.command.call_args_list))
        self.assertEqual(self.bridge.journal.target_purpose('new-text'),'text')
    async def test_image_route_needs_header_and_calls_image_adapter_only(self):
        import uuid
        identifier=str(uuid.uuid4());self.bridge.images.generate=AsyncMock(return_value={'task_id':identifier,'sha256':'fixture'})
        r=await self.client.post('/api/images/generate',json={'task_id':identifier,'prompt':'one image'})
        self.assertEqual(r.status,403);self.bridge.images.generate.assert_not_awaited()
        r=await self.client.post('/api/images/generate',json={'task_id':identifier,'prompt':'one image'},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(r.status,200);self.bridge.images.generate.assert_awaited_once_with(identifier,'one image')
    async def test_target_destroyed_invalidates_session(self):
        self.bridge.sessions['a']='session'
        self.bridge.on_event({'method':'Target.targetDestroyed','params':{'targetId':'a'}})
        self.assertNotIn('a',self.bridge.sessions)
    async def test_chat_requires_job_and_never_accepts_unscoped_old_api(self):
        r=await self.client.post('/api/chat',json={'prompt':'hello'},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(r.status,400)

    def page_state(self,mode='chat',draft=''):
        return {'url':'https://chatgpt.com/','composer':True,'login':False,'challenge':False,'mode':mode,'draft':draft}
    async def setup_page(self):
        self.bridge.ensure_tab=AsyncMock(return_value='own')
        self.bridge.session=AsyncMock(return_value='session')
        self.bridge.cdp=MagicMock()
        self.bridge.cdp.command=AsyncMock(return_value={})
        self.bridge.cdp.close=AsyncMock()
    async def test_work_is_switched_to_chat_with_native_click_before_ready(self):
        await self.setup_page()
        self.bridge.evaluate=AsyncMock(side_effect=[self.page_state('work'),{'x':10,'y':20},self.page_state('chat')])
        _,_,state=await self.bridge.page_ready('job')
        self.assertEqual(state['mode'],'chat')
        mouse=[c for c in self.bridge.cdp.command.call_args_list if c.args[0]=='Input.dispatchMouseEvent']
        self.assertEqual(len(mouse),2)
        self.assertTrue(self.bridge.authenticated)
    async def test_unknown_mode_fails_closed_without_typing(self):
        await self.setup_page();self.bridge.evaluate=AsyncMock(return_value=self.page_state('unknown'))
        with self.assertRaisesRegex(RuntimeError,'Chat mode'):
            await self.bridge.page_ready('job',timeout=.1)
        self.assertFalse(self.bridge.authenticated)
    async def test_existing_work_draft_is_not_discarded_by_mode_switch(self):
        await self.setup_page();self.bridge.evaluate=AsyncMock(return_value=self.page_state('work','unfinished work'))
        with self.assertRaisesRegex(RuntimeError,'draft'):
            await self.bridge.page_ready('job',timeout=.1)
        self.assertFalse(any(c.args[0]=='Input.dispatchMouseEvent' for c in self.bridge.cdp.command.call_args_list))
    async def test_already_chat_does_not_click_mode_again(self):
        await self.setup_page();self.bridge.evaluate=AsyncMock(return_value=self.page_state('chat'))
        await self.bridge.page_ready('job')
        self.assertFalse(any(c.args[0]=='Input.dispatchMouseEvent' for c in self.bridge.cdp.command.call_args_list))

    async def test_own_prepared_draft_can_resume_without_retyping(self):
        import json
        await self.setup_page();self.bridge.connect=AsyncMock()
        r=self.bridge.journal.prepare('job','prompt');identifier=r['id'];order=[]
        async def verified_high(session):
            self.assertEqual(self.bridge.journal.get(identifier)['state'],'prepared');order.append('high')
        self.bridge.ensure_high_effort=AsyncMock(side_effect=verified_high)
        async def record_input(method,*args,**kwargs):
            if method=='Input.dispatchMouseEvent':order.append('mouse')
            return {}
        self.bridge.cdp.command=AsyncMock(side_effect=record_input)
        marker='[VideoStudio request '+identifier+']'
        wrapped=(marker+'\n'+'prompt'+'\nReturn exactly one JSON object with this envelope: '+json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
        state=self.page_state('chat',wrapped.replace('\n','\n\n'))
        self.bridge.page_ready=AsyncMock(return_value=('own','session',state))
        response={'url':'https://chatgpt.com/c/own','mode':'chat','matched':True,'text':json.dumps({'request_id':identifier,'result':{'ok':True}}),'generating':False}
        self.bridge.evaluate=AsyncMock(side_effect=[{'x':1,'y':2},state,None,response,response])
        self.assertEqual(await self.bridge.ask_chatgpt('job','prompt'),{'ok':True})
        self.bridge.ensure_high_effort.assert_awaited_once_with('session')
        self.assertLess(order.index('high'),order.index('mouse'))
        self.assertFalse(any(c.args[0]=='Input.insertText' for c in self.bridge.cdp.command.call_args_list))
    async def test_foreign_prepared_draft_is_never_overwritten(self):
        await self.setup_page();self.bridge.connect=AsyncMock()
        self.bridge.page_ready=AsyncMock(return_value=('own','session',self.page_state('chat','user draft')))
        with self.assertRaisesRegex(RuntimeError,'draft'):
            await self.bridge.ask_chatgpt('job','prompt')
        self.assertFalse(any(c.args[0]=='Input.insertText' for c in self.bridge.cdp.command.call_args_list))

    async def test_transient_page_load_evaluation_timeout_is_read_only_retried(self):
        await self.setup_page()
        self.bridge.evaluate=AsyncMock(side_effect=[TimeoutError('page loading'),self.page_state('chat')])
        _,_,state=await self.bridge.page_ready('job',timeout=3)
        self.assertEqual(state['mode'],'chat')
        self.assertFalse(any(c.args[0].startswith('Input.') for c in self.bridge.cdp.command.call_args_list))

    async def test_navigation_replaces_cdp_session_and_recovery_never_types(self):
        from videostudio.cdp_protocol import CDPError
        await self.setup_page()
        self.bridge.ensure_tab=AsyncMock(side_effect=['old','new'])
        self.bridge.session=AsyncMock(side_effect=['session1','session2'])
        self.bridge.evaluate=AsyncMock(side_effect=[CDPError('Session with given id not found.'),self.page_state('chat')])
        target,session,state=await self.bridge.page_ready('job',timeout=3)
        self.assertEqual((target,session),('new','session2'))
        self.assertEqual(state['mode'],'chat')
        self.assertFalse(any(c.args[0].startswith('Input.') for c in self.bridge.cdp.command.call_args_list))

    async def test_work_change_after_claim_aborts_before_mouse_dispatch(self):
        import json
        from videostudio.cdp_requests import IndeterminateRequest
        await self.setup_page();self.bridge.connect=AsyncMock();self.bridge.ensure_high_effort=AsyncMock()
        r=self.bridge.journal.prepare('job','prompt');identifier=r['id']
        wrapped=('[VideoStudio request '+identifier+']\n'+'prompt'+'\nReturn exactly one JSON object with this envelope: '+json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
        state=self.page_state('chat',wrapped)
        response={'mode':'chat','matched':True,'text':json.dumps({'request_id':identifier,'result':{'ok':True}}),'generating':False}
        self.bridge.page_ready=AsyncMock(return_value=('own','session',state))
        self.bridge.evaluate=AsyncMock(side_effect=[{'x':1,'y':2},self.page_state('work',wrapped),response,response])
        with self.assertRaises(IndeterminateRequest):
            await self.bridge.ask_chatgpt('job','prompt')
        self.assertEqual(self.bridge.journal.get(identifier)['state'],'sending')
        self.assertFalse(any(c.args[0]=='Input.dispatchMouseEvent' for c in self.bridge.cdp.command.call_args_list))
    async def test_daemon_rejects_rebound_host_even_with_client_header(self):
        r=await self.client.post('/api/browser/start',json={},headers={'Host':'evil.example','X-VS-Client':'videostudio','Origin':'http://evil.example'})
        self.assertEqual(r.status,403);self.launcher.ensure_started.assert_not_called()

    async def test_crash_after_mouse_press_retains_sending_and_restart_never_resubmits(self):
        import json
        await self.setup_page();self.bridge.connect=AsyncMock();self.bridge.ensure_high_effort=AsyncMock()
        record=self.bridge.journal.prepare('job','prompt');identifier=record['id']
        wrapped=('[VideoStudio request '+identifier+']\n'+'prompt'+'\nReturn exactly one JSON object with this envelope: '+json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
        state=self.page_state('chat',wrapped)
        self.bridge.page_ready=AsyncMock(return_value=('own','session',state))
        self.bridge.evaluate=AsyncMock(side_effect=[{'x':1,'y':2},state])
        async def crash(method,*args,**kwargs):
            if method=='Input.dispatchMouseEvent':raise ConnectionError('lost after press')
            return {}
        self.bridge.cdp.command=AsyncMock(side_effect=crash)
        with self.assertRaises(ConnectionError):await self.bridge.ask_chatgpt('job','prompt')
        self.bridge.journal=RequestJournal(self.bridge.journal.path)
        self.assertEqual(self.bridge.journal.get(identifier)['state'],'sending')
        response={'mode':'chat','matched':True,'text':json.dumps({'request_id':identifier,'result':{'ok':True}}),'generating':False}
        self.bridge.evaluate=AsyncMock(side_effect=[response,response]);self.bridge.cdp.command=AsyncMock()
        result=await self.bridge.ask_chatgpt('job','prompt')
        self.assertEqual(result,{'ok':True})
        self.assertFalse(any(c.args[0].startswith('Input.') for c in self.bridge.cdp.command.call_args_list))

    async def test_flow_character_route_passes_native_name_and_prompt_to_visible_ui_adapter(self):
        import uuid
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());character_id='father'
        result={'task_id':task_id,'character_id':str(uuid.uuid4()),'name':character_id,'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}
        self.bridge.flow_images.create_character=AsyncMock(return_value=result)
        response=await self.client.post('/api/flow/characters/create',json={'task_id':task_id,'job_id':job_id,'character_id':character_id,'name':'father','prompt':'portrait'},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['data'],result)
        self.bridge.flow_images.create_character.assert_awaited_once_with(task_id,job_id,character_id,'father','portrait')

    async def test_flow_image_route_passes_native_character_mentions_to_visible_ui_adapter(self):
        import uuid
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());entity_id=str(uuid.uuid4())
        mentions=[{'character_id':entity_id,'name':'NguoiCha','project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}]
        self.bridge.flow_images.generate=AsyncMock(return_value={'task_id':task_id,'media_id':'result-media'})
        response=await self.client.post('/api/flow/images/generate',json={'task_id':task_id,'job_id':job_id,'prompt':'scene','character_mentions':mentions},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(response.status,200)
        self.bridge.flow_images.generate.assert_awaited_once_with(task_id,job_id,'scene',character_mentions=mentions)

    async def test_flow_batch_route_validates_and_passes_tasks_to_adapter(self):
        import uuid
        job_id=str(uuid.uuid4());tasks=[{'task_id':str(uuid.uuid4()),'prompt':'one','ordinal':0},{'task_id':str(uuid.uuid4()),'prompt':'two','ordinal':1}]
        expected=[{'task_id':tasks[0]['task_id'],'media_id':'media-1'},{'task_id':tasks[1]['task_id'],'media_id':'media-2'}]
        self.bridge.flow_images.generate_batch=AsyncMock(return_value=expected)
        response=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':tasks,'timeout':1800},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(response.status,200);self.assertEqual((await response.json())['data'],expected)
        self.bridge.flow_images.generate_batch.assert_awaited_once_with(job_id,tasks,timeout=1800.0,download_results=True)
        record_only=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':tasks,'timeout':1800,'download_results':False},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(record_only.status,200)
        self.bridge.flow_images.generate_batch.assert_awaited_with(job_id,tasks,timeout=1800.0,download_results=False)
        invalid=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':[]},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(invalid.status,400)
        invalid_flag=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':tasks,'download_results':'false'},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(invalid_flag.status,400)
        too_many=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':tasks*16},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(too_many.status,400)
        thirty=await self.client.post('/api/flow/images/generate-batch',json={'job_id':job_id,'tasks':tasks*15},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(thirty.status,200)
        self.assertEqual(self.bridge.flow_images.generate_batch.await_count,3)

if __name__=='__main__':unittest.main()
