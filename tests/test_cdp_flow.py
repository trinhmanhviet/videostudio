import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

from videostudio.cdp_flow import FlowImages, FlowTaskError


class FakeBridge:
    def __init__(self, targets):
        self.targets = targets
        self.cdp = type('Cdp', (), {})()
        self.cdp.command = AsyncMock(side_effect=self.command)
        self.job_lock = asyncio.Lock()
        self.sessions = {}
        self.images = type('Images', (), {'download_behavior_uncertain': False})()
        self.journal = type('Journal', (), {'own_target': lambda *_: None})()
        self.connected = False

    async def command(self, method, params=None, **kwargs):
        if method == 'Target.getTargets':
            return {'targetInfos': self.targets}
        if method == 'Target.createTarget':
            return {'targetId': 'new-flow-target'}
        if method == 'Target.attachToTarget':
            return {'sessionId': 'flow-session'}
        return {}

    async def connect(self):
        self.connected = True


class FlowSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_single_flow_tab_is_reused(self):
        bridge = FakeBridge([{'targetId': 'only-flow', 'type': 'page', 'url': 'https://flow.google.com/project/abc'}])
        flow = FlowImages(bridge, Path('unused'))
        self.assertEqual(await flow._target(), 'only-flow')
        bridge.cdp.command.assert_awaited_once_with('Target.getTargets')

    async def test_duplicate_flow_tabs_fail_closed_without_closing_either(self):
        bridge = FakeBridge([
            {'targetId': 'flow-a', 'type': 'page', 'url': 'https://flow.google.com/'},
            {'targetId': 'flow-b', 'type': 'page', 'url': 'https://flow.google.com/project/abc'},
        ])
        flow = FlowImages(bridge, Path('unused'))
        with self.assertRaisesRegex(FlowTaskError, 'More than one Flow tab'):
            await flow._target()
        self.assertEqual([c.args[0] for c in bridge.cdp.command.await_args_list], ['Target.getTargets'])

    async def test_no_tab_opens_exactly_one_flow_tab(self):
        bridge = FakeBridge([])
        flow = FlowImages(bridge, Path('unused'))
        self.assertEqual(await flow._target(), 'new-flow-target')
        self.assertEqual([c.args[0] for c in bridge.cdp.command.await_args_list], ['Target.getTargets', 'Target.createTarget'])
        self.assertEqual(bridge.cdp.command.await_args_list[1].args[1]['url'], 'https://flow.google.com/')

    async def test_agent_must_be_off_and_exact_zero_credit_text_required(self):
        bridge = FakeBridge([])
        flow = FlowImages(bridge, Path('unused'))
        base = {'agentOn': False, 'settingsOpen': True, 'settingsText': 'Nano Banana 2.1 crop_9_16 x1'}
        flow._snapshot = AsyncMock(side_effect=[{**base, 'creditLines':['Quá trình tạo sẽ tốn 1 tín dụng']},{**base, 'creditLines':['Quá trình tạo sẽ tốn 1 tín dụng']},{**base, 'creditLines':['Quá trình tạo sẽ tốn 1 tín dụng']}])
        flow._click_named = AsyncMock()
        flow._click_expr = AsyncMock()
        with self.assertRaises(FlowTaskError) as caught:
            await flow._ensure_agent_and_settings('session','fixture prompt')
        self.assertEqual(caught.exception.code,'needs_zero_credit')
        flow._click_named.assert_any_await('session','Hình ảnh',selector='button.mat-button-toggle-button')
        self.assertFalse(any('Bắt đầu tạo' in str(x) for x in flow._click_named.await_args_list))

    async def test_zero_credit_gate_accepts_only_exact_free_estimate_after_agent_off(self):
        bridge = FakeBridge([])
        flow = FlowImages(bridge, Path('unused'))
        state = {'agentOn':False,'settingsOpen':True,'settingsText':'Nano Banana 2.1 crop_9_16 x1','creditLines':['Quá trình tạo sẽ tốn 0 tín dụng']}
        flow._snapshot = AsyncMock(side_effect=[state,state,state])
        flow._click_named = AsyncMock()
        flow._click_expr = AsyncMock()
        result = await flow._ensure_agent_and_settings('session','fixture prompt')
        self.assertEqual(result['agentOn'],False)
        self.assertIn('0 tín dụng',result['creditLines'][0])
        self.assertEqual(flow._click_expr.await_count,0)

    async def test_zero_credit_failure_prevents_generate_button_click(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='free-only prompt'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp));receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':'https://flow.google.com/project/abc','target_id':'one','stage':'project_ready'}
            flow._write_receipt(task_id,receipt);flow._target=AsyncMock(return_value='one');flow._session=AsyncMock(return_value='session')
            flow._ensure_project=AsyncMock(return_value=(receipt,{'url':receipt['project_url']}));flow._prompt_box=AsyncMock(return_value={'x':1,'y':1,'text':prompt})
            flow._ensure_agent_and_settings=AsyncMock(side_effect=FlowTaskError('Flow did not confirm zero credits','needs_zero_credit'));flow._click_named=AsyncMock()
            with self.assertRaises(FlowTaskError) as caught:await flow.generate(task_id,job_id,prompt)
            self.assertEqual(caught.exception.code,'needs_zero_credit')
            self.assertNotIn('Bắt đầu tạo',[c.args[1] for c in flow._click_named.await_args_list])
            self.assertEqual(flow._read_receipt(task_id)['stage'],'project_ready')

    async def test_2k_download_is_correlated_to_flow_frame_and_saved_as_png(self):
        from PIL import Image
        task_id=str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([])
            async def cdp(method,params=None,**kwargs):
                if method=='Page.getFrameTree':return {'frameTree':{'frame':{'id':'flow-frame'}}}
                return {}
            bridge.cdp.command=AsyncMock(side_effect=cdp)
            flow=FlowImages(bridge,Path(tmp));flow._image=AsyncMock(return_value=[{'x':100,'y':200,'width':1080,'height':1920,'alt':'scene'}])
            async def click(session,name,**kwargs):
                if name=='2K':
                    folder=Path(tmp)/'downloads'/task_id;folder.mkdir(parents=True,exist_ok=True);guid=str(uuid.uuid4());file=folder/guid
                    Image.new('RGB',(1080,1920),'navy').save(file,format='JPEG',quality=90)
                    flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'foreign-frame','guid':str(uuid.uuid4())}})
                    flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'flow-frame','guid':guid,'suggestedFilename':'scene_2K.jpg'}})
                    flow.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed','receivedBytes':file.stat().st_size}})
            flow._click_named=AsyncMock(side_effect=click)
            receipt={'task_id':task_id,'project_url':'https://flow.google.com/project/abc','stage':'image_ready'}
            saved=await flow._download_2k(task_id,'flow-tab','session',receipt,'prompt')
            out=Path(saved['download_path']);self.assertTrue(out.is_file());self.assertEqual(saved['stage'],'downloaded');self.assertEqual(saved['format'],'JPEG')
            with Image.open(out) as im:self.assertEqual(im.format,'PNG');self.assertEqual(im.size,(1080,1920))
            self.assertEqual(saved['download_guid'],flow.download_guid)

    async def test_downloaded_receipt_recovers_same_candidate_without_browser_or_generation(self):
        from PIL import Image
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='already downloaded prompt'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp));output=Path(tmp)/(task_id+'.png');Image.new('RGB',(1080,1920),'olive').save(output,format='PNG')
            receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':'https://flow.google.com/project/abc','stage':'downloaded','download_path':str(output),'download_sha256':__import__('videostudio.core',fromlist=['digest']).digest(output),'width':1080,'height':1920,'download_guid':str(uuid.uuid4())}
            flow._write_receipt(task_id,receipt)
            result=await flow.generate(task_id,job_id,prompt)
            self.assertEqual(result['request_id'],'flow-'+task_id);self.assertEqual(result['sha256'],receipt['download_sha256'])
            bridge.connect=AsyncMock();bridge.cdp.command.assert_not_awaited()

    async def test_ambiguous_submitted_request_is_never_clicked_again(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='same request prompt'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp))
            project_url='https://flow.google.com/project/abc'
            receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':project_url,'target_id':'one','stage':'submitting'}
            flow._write_receipt(task_id,receipt)
            flow._target=AsyncMock(return_value='one');flow._session=AsyncMock(return_value='session')
            flow._ensure_project=AsyncMock(return_value=(receipt,{'url':project_url}))
            flow._snapshot=AsyncMock(return_value={'url':project_url,'login':False,'challenge':False})
            flow._image=AsyncMock(return_value=[])
            flow._click_named=AsyncMock()
            with self.assertRaises(FlowTaskError) as caught:
                await flow.generate(task_id,job_id,prompt)
            self.assertEqual(caught.exception.code,'uncertain')
            flow._click_named.assert_not_awaited()
            self.assertEqual(flow._read_receipt(task_id)['stage'],'submitting')


if __name__=='__main__':
    unittest.main()
