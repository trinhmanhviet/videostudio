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
    async def test_job_project_registry_reuses_one_flow_project_across_scenes(self):
        job_id=str(uuid.uuid4());task_id=str(uuid.uuid4());project_url='https://flow.google.com/project/abc'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp));flow._save_project_registry(job_id,project_url)
            flow._snapshot=AsyncMock(return_value={'url':'https://flow.google.com/project/demo','draftEmpty':True,'generateDisabled':True,'login':False,'challenge':False})
            flow._wait_page=AsyncMock(return_value={'url':project_url,'draftEmpty':True,'generateDisabled':True,'composerAvailable':True})
            flow._click_named=AsyncMock()
            receipt,state=await flow._ensure_project(task_id,job_id,'prompt','only-flow','session',None)
            self.assertEqual(receipt['project_url'],project_url);self.assertEqual(receipt['stage'],'project_ready')
            self.assertFalse(any(c.args[1]=='Dự án mới' for c in flow._click_named.await_args_list))
            self.assertEqual(flow._load_project_registry(job_id)['project_url'],project_url)

    async def test_first_scene_creates_flow_project_and_later_scenes_reuse_it(self):
        job_id=str(uuid.uuid4());first_task=str(uuid.uuid4());second_task=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp))
            home={'url':'https://flow.google.com/','draftEmpty':True,'draftLength':0,'generateDisabled':True,'composerAvailable':False,'login':False,'challenge':False,'largeImages':[]}
            demo={'url':'https://flow.google.com/project/demo','draftEmpty':True,'draftLength':0,'generateDisabled':True,'composerAvailable':True,'login':False,'challenge':False,'largeImages':[]}
            created={'url':project,'draftEmpty':True,'draftLength':0,'generateDisabled':True,'composerAvailable':True,'login':False,'challenge':False,'largeImages':[]}
            flow._snapshot=AsyncMock(return_value=demo);flow._wait_page=AsyncMock(side_effect=[home,created]);flow._click_named=AsyncMock()
            first,_=await flow._ensure_project(first_task,job_id,'scene one','only-flow','session',None)
            self.assertEqual(first['project_url'],project);self.assertEqual(flow._load_project_registry(job_id)['project_url'],project)
            self.assertTrue(any(call.args[1]=='Dự án mới' for call in flow._click_named.await_args_list))
            flow._snapshot=AsyncMock(return_value=created);flow._wait_page=AsyncMock();flow._click_named.reset_mock()
            second,_=await flow._ensure_project(second_task,job_id,'scene two','only-flow','session',None)
            self.assertEqual(second['project_url'],project);self.assertEqual(second['baseline_media_ids'],[])
            self.assertFalse(any(call.args[1]=='Dự án mới' for call in flow._click_named.await_args_list))
            self.assertEqual(len(list((Path(tmp)/'projects').glob('*.json'))),1)

    def test_task_correlation_requires_exactly_one_new_flow_media_id(self):
        before={'media-a','media-b'};now=[{'media_id':'media-a'},{'media_id':'media-b'},{'media_id':'media-c'}]
        self.assertEqual(FlowImages._new_media(before,now)['media_id'],'media-c')
        with self.assertRaises(FlowTaskError):FlowImages._new_media(before,now+[{'media_id':'media-d'}])
        self.assertIsNone(FlowImages._new_media(before,now[:2]))

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
            self.assertEqual(flow._read_receipt(task_id)['stage'],'references_attached')
            self.assertEqual(flow._read_receipt(task_id)['reference_media_ids'],[])

    async def test_2k_download_is_correlated_to_flow_frame_and_saved_as_png(self):
        from PIL import Image
        task_id=str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([])
            async def cdp(method,params=None,**kwargs):
                if method=='Page.getFrameTree':return {'frameTree':{'frame':{'id':'flow-frame'}}}
                return {}
            bridge.cdp.command=AsyncMock(side_effect=cdp)
            flow=FlowImages(bridge,Path(tmp));flow._image=AsyncMock(return_value=[{'media_id':'media-2k','x':100,'y':200,'width':1080,'height':1920,'alt':'scene'}]);flow._click_media_control=AsyncMock()
            async def click(session,name,**kwargs):
                if name=='2K':
                    folder=Path(tmp)/'downloads'/task_id;folder.mkdir(parents=True,exist_ok=True);guid=str(uuid.uuid4());file=folder/guid
                    Image.new('RGB',(1080,1920),'navy').save(file,format='JPEG',quality=90)
                    flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'foreign-frame','guid':str(uuid.uuid4())}})
                    flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'flow-frame','guid':guid,'suggestedFilename':'scene_2K.jpg'}})
                    flow.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed','receivedBytes':file.stat().st_size}})
            flow._click_named=AsyncMock(side_effect=click)
            receipt={'task_id':task_id,'project_url':'https://flow.google.com/project/abc','stage':'image_ready'}
            saved=await flow._download_2k(task_id,'flow-tab','session',receipt,'prompt',media_id='media-2k')
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


    async def test_reference_attachment_requires_visible_exact_media_id(self):
        media_id=str(uuid.uuid4());flow=FlowImages(FakeBridge([]),Path('unused'))
        flow._image=AsyncMock(return_value=[{'media_id':media_id,'x':100,'y':200}])
        flow._click_media_control=AsyncMock();flow._click_named=AsyncMock()
        flow._wait_page=AsyncMock(return_value={'attachedMediaIds':[media_id]})
        state=await flow._attach_reference('session',media_id,'scene prompt')
        flow._click_media_control.assert_awaited_once_with('session',media_id,'Tuỳ chọn khác')
        flow._click_named.assert_awaited_once_with('session','Thêm vào câu lệnh',exact=True)
        self.assertEqual(state['attachedMediaIds'],[media_id])

    async def test_reference_attachment_fails_closed_if_media_id_is_not_exposed(self):
        media_id=str(uuid.uuid4());flow=FlowImages(FakeBridge([]),Path('unused'))
        flow._image=AsyncMock(return_value=[{'media_id':media_id,'x':100,'y':200}])
        flow._click_media_control=AsyncMock();flow._click_named=AsyncMock()
        flow._wait_page=AsyncMock(return_value={'attachedMediaIds':[]})
        with self.assertRaisesRegex(FlowTaskError,'did not expose exactly one attached reference'):
            await flow._attach_reference('session',media_id,'scene prompt')

    async def test_reference_not_in_job_project_blocks_before_attachment_or_generate(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());media_id=str(uuid.uuid4());prompt='scene prompt'
        flow=FlowImages(FakeBridge([]),Path('unused'));flow._target=AsyncMock(return_value='target');flow._session=AsyncMock(return_value='session')
        receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':'https://flow.google.com/project/abc','target_id':'target','stage':'project_ready','baseline_media_ids':[]}
        state={'url':receipt['project_url'],'largeImages':[],'attachedMediaIds':[],'draftEmpty':True,'generateDisabled':True}
        flow._ensure_project=AsyncMock(return_value=(receipt,state));flow._attach_reference=AsyncMock();flow._click_named=AsyncMock()
        identity=[{'character_id':'father','media_id':media_id,'sha256':'a'*64,'project_url':receipt['project_url']}]
        with self.assertRaises(FlowTaskError) as caught:
            await flow.generate(task_id,job_id,prompt,reference_media_ids=[media_id],reference_identity=identity)
        self.assertEqual(caught.exception.code,'needs_flow_check')
        flow._attach_reference.assert_not_awaited();flow._click_named.assert_not_awaited()

    async def test_reference_change_on_existing_receipt_is_never_resubmitted(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());old=str(uuid.uuid4());new=str(uuid.uuid4());prompt='same scene prompt'
        with tempfile.TemporaryDirectory() as tmp:
            flow=FlowImages(FakeBridge([]),Path(tmp));flow._write_receipt(task_id,{'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'reference_media_ids':[old],'stage':'project_ready'})
            identity=[{'character_id':'father','media_id':new,'sha256':'b'*64,'project_url':'https://flow.google.com/project/abc'}]
            with self.assertRaisesRegex(FlowTaskError,'reference media set differs'):
                await flow.generate(task_id,job_id,prompt,reference_media_ids=[new],reference_identity=identity)
            flow.bridge.cdp.command.assert_not_awaited()

    async def test_reference_content_hash_change_fails_before_cached_result(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());media_id=str(uuid.uuid4());prompt='same prompt';project='https://flow.google.com/project/abc'
        old=[{'character_id':'father','media_id':media_id,'sha256':'a'*64,'project_url':project}]
        changed=[{'character_id':'father','media_id':media_id,'sha256':'b'*64,'project_url':project}]
        with tempfile.TemporaryDirectory() as tmp:
            flow=FlowImages(FakeBridge([]),Path(tmp));flow._write_receipt(task_id,{'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'reference_media_ids':[media_id],'reference_identity':old,'stage':'project_ready'})
            with self.assertRaisesRegex(FlowTaskError,'reference content/character identity differs'):
                await flow.generate(task_id,job_id,prompt,reference_media_ids=[media_id],reference_identity=changed)
            flow.bridge.cdp.command.assert_not_awaited()

if __name__=='__main__':
    unittest.main()
