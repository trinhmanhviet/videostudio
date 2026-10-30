import asyncio
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

from PIL import Image

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
    def test_native_character_mentions_validate_entity_name_and_project(self):
        job_id=str(uuid.uuid4());entity_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
        mentions=[{'character_id':entity_id,'name':'NguoiCha','project_url':project}]
        self.assertEqual(FlowImages._validate_character_mentions(job_id,mentions),mentions)
        with self.assertRaisesRegex(FlowTaskError,'Duplicate native Character'):
            FlowImages._validate_character_mentions(job_id,mentions*2)
        second={'character_id':str(uuid.uuid4()),'name':'Mother','project_url':'https://flow.google.com/project/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}
        with self.assertRaisesRegex(FlowTaskError,'same Flow project'):
            FlowImages._validate_character_mentions(job_id,mentions+[second])

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

    async def test_named_control_waits_for_menu_and_hits_visible_target_before_click(self):
        bridge=FakeBridge([]);flow=FlowImages(bridge,Path('unused'))
        point={'x':45,'y':72,'hitIsControl':True}
        flow._eval=AsyncMock(side_effect=[None,point,point,None])
        await flow._click_named('session','Tải xuống',timeout=1)
        self.assertEqual(flow._eval.await_count,4)
        moved=[call for call in bridge.cdp.command.call_args_list if call.args[0]=='Input.dispatchMouseEvent' and call.args[1]['type']=='mouseMoved']
        clicks=[call for call in bridge.cdp.command.call_args_list if call.args[0]=='Input.dispatchMouseEvent' and call.args[1]['type'] in ('mousePressed','mouseReleased')]
        self.assertEqual(len(moved),1);self.assertEqual(len(clicks),2)

    async def test_media_control_scrolls_then_hovers_before_menu_lookup(self):
        bridge=FakeBridge([]);flow=FlowImages(bridge,Path('unused'));sequence=[]
        async def evaluate(session,expression,timeout=8):
            if 'flow-info-panel' in expression:sequence.append('popup-check');return 0
            if 'scrollIntoView' in expression:sequence.append('scroll');return {'x':100,'y':200}
            sequence.append('lookup');return {'x':120,'y':180,'hitIsControl':True}
        async def command(method,params=None,**kwargs):
            if method=='Input.dispatchMouseEvent' and params['type']=='mouseMoved':sequence.append('hover')
            elif method=='Input.dispatchMouseEvent' and params['type']=='mousePressed':sequence.append('click')
            return {}
        flow._eval=AsyncMock(side_effect=evaluate);bridge.cdp.command=AsyncMock(side_effect=command)
        await flow._click_media_control('session','media-one','Tuỳ chọn khác')
        self.assertEqual(sequence[:4],['popup-check','scroll','hover','lookup'])
        self.assertIn('click',sequence)

    async def test_dismiss_flow_popups_clicks_outside_until_overlays_close(self):
        bridge=FakeBridge([]);flow=FlowImages(bridge,Path('unused'));checks=iter([2,1,0])
        async def evaluate(session,expression,timeout=8):
            if 'innerWidth' in expression:return {'x':1908,'y':899}
            return next(checks)
        flow._eval=AsyncMock(side_effect=evaluate)
        await flow._dismiss_flow_popups('session')
        clicks=[call for call in bridge.cdp.command.call_args_list if call.args[0]=='Input.dispatchMouseEvent' and call.args[1]['type']=='mousePressed']
        self.assertEqual(len(clicks),2)
        self.assertTrue(all(call.args[1]['x']==1908 and call.args[1]['y']==899 for call in clicks))

    async def test_thumbnail_discovery_accepts_loaded_286px_flow_cards(self):
        flow=FlowImages(FakeBridge([]),Path('unused'))
        expressions=[]
        async def capture(session,expression,timeout=8):
            expressions.append(expression)
            return []
        flow._eval=AsyncMock(side_effect=capture)
        await flow._snapshot('session','')
        await flow._image('session')
        self.assertEqual(len(expressions),2)
        snapshot_expr,image_expr=expressions
        self.assertIn('complete:!!i&&i.complete&&i.naturalWidth>0&&i.naturalHeight>0',snapshot_expr)
        self.assertIn('i.complete&&i.naturalWidth>=256&&i.naturalHeight>=256',snapshot_expr)
        self.assertIn('i.complete&&i.naturalWidth>=256&&i.naturalHeight>=256',image_expr)
        self.assertNotIn('i.naturalWidth>=512',image_expr)

    async def test_download_still_rejects_thumbnail_sized_file(self):
        with tempfile.TemporaryDirectory() as td:
            task_id=str(uuid.uuid4());bridge=FakeBridge([])
            async def command(method,params=None,session=None,**kwargs):
                if method=='Page.getFrameTree':return {'frameTree':{'frame':{'id':'frame'}}}
                return {}
            bridge.cdp.command=AsyncMock(side_effect=command)
            flow=FlowImages(bridge,Path(td))
            flow._image=AsyncMock(return_value=[{'media_id':'media-1','x':60,'y':60}])
            flow._click_media_control=AsyncMock()
            async def click_named(session,name,**kwargs):
                if name=='2K':
                    folder=Path(td)/'downloads'/task_id;folder.mkdir(parents=True,exist_ok=True)
                    Image.effect_noise((400,600),100).convert('RGB').save(folder/'probe',format='PNG')
                    flow.download_guid='probe';flow.downloads={'probe':{'state':'completed'}};flow.download_complete=True;flow.download_changed.set()
            flow._click_named=AsyncMock(side_effect=click_named)
            with self.assertRaisesRegex(FlowTaskError,'dimensions failed validation'):
                await flow._download_2k(task_id,'target','session',{'stage':'image_ready'},'prompt',media_id='media-1')

    def test_batch_full_prompt_mapping_ignores_completion_order_and_clipped_titles(self):
        job_id=str(uuid.uuid4())
        tasks=[
            {'task_id':str(uuid.uuid4()),'job_id':job_id,'ordinal':0,'prompt':'Cobalt-blue lighthouse on rocky coast at sunrise, no text.','character_mentions':[]},
            {'task_id':str(uuid.uuid4()),'job_id':job_id,'ordinal':1,'prompt':'Yellow tram crossing a snowy bridge at dawn, no text.','character_mentions':[]},
        ]
        media=[
            {'media_id':'media-tram','prompt':tasks[1]['prompt'],'mention_entity_ids':[],'title':'Yellow tram crossing a snowy …'},
            {'media_id':'media-lighthouse','prompt':tasks[0]['prompt'],'mention_entity_ids':[],'title':'Cobalt-blue lighthouse on rocky …'},
        ]
        mapping=FlowImages._batch_prompt_mapping(tasks,media)
        self.assertEqual(mapping[tasks[0]['task_id']],'media-lighthouse')
        self.assertEqual(mapping[tasks[1]['task_id']],'media-tram')

    def test_batch_full_prompt_mapping_rejects_clipped_prompt_and_duplicate_fingerprints(self):
        job_id=str(uuid.uuid4());prompt='Cobalt-blue lighthouse on a rocky coast at sunrise.'
        one={'task_id':str(uuid.uuid4()),'job_id':job_id,'ordinal':0,'prompt':prompt,'character_mentions':[]}
        with self.assertRaises(FlowTaskError):
            FlowImages._batch_prompt_mapping([one],[{'media_id':'media-1','prompt':'Cobalt-blue lighthouse on rocky …','mention_entity_ids':[]}])
        same=[dict(one,ordinal=0),dict(one,task_id=str(uuid.uuid4()),ordinal=1)]
        with self.assertRaises(FlowTaskError):
            FlowImages._batch_prompt_mapping(same,[{'media_id':'media-b','prompt':prompt,'mention_entity_ids':[]},{'media_id':'media-a','prompt':prompt,'mention_entity_ids':[]}])

    def test_top_row_mapping_requires_ten_complete_prompt_identified_tiles(self):
        tasks=[{'task_id':str(uuid.uuid4()),'ordinal':i,'prompt':f'Unique subject {i} under amber light','character_mentions':[]} for i in range(10)]
        tiles=[{'media_id':f'media-{i}','complete':True,'text':tasks[i]['prompt'],'x':(9-i)*100,'y':120,'tile_height':180} for i in range(10)]
        mapping=FlowImages._batch_row_mapping(tasks,tiles,[])
        self.assertEqual([mapping[t['task_id']] for t in tasks],[f'media-{i}' for i in range(10)])
        with self.assertRaisesRegex(FlowTaskError,'conflicts with the visual row order'):
            FlowImages._batch_row_mapping(tasks,[{**tiles[4],'text':'wrong'} if i==4 else tile for i,tile in enumerate(tiles)],[])
        detail_prompts=[{'media_id':f'media-{i}','prompt':tasks[i]['prompt']} for i in range(10)]
        self.assertEqual([FlowImages._batch_row_mapping(tasks,tiles,[],media_prompts=detail_prompts)[t['task_id']] for t in tasks],[f'media-{i}' for i in range(10)])
        wrong_detail=[{'media_id':f'media-{i}','prompt':'mismatch' if i==3 else tasks[i]['prompt']} for i in range(10)]
        with self.assertRaisesRegex(FlowTaskError,'did not match exactly one cohort task'):
            FlowImages._batch_row_mapping(tasks,tiles,[],media_prompts=wrong_detail)
        with self.assertRaisesRegex(FlowTaskError,'different number'):
            FlowImages._batch_row_mapping(tasks,tiles[:-1],[])

    def test_batch_download_order_is_right_to_left_and_oldest_rows_first(self):
        tasks=[{'task_id':f'task-{i}','ordinal':i,'prompt':f'p{i}','character_mentions':[]} for i in range(10)]
        mapping={task['task_id']:f'media-{i}' for i,task in enumerate(tasks)}
        tiles=[{'media_id':f'media-{i}','complete':True,'x':(10-i)*100,'y':100,'tile_height':180} for i in range(10)]
        order,_=FlowImages._batch_download_order(tasks,tiles,mapping)
        self.assertEqual(order,[task['task_id'] for task in tasks])
        twenty=[{'task_id':f'task-{i}','ordinal':i,'prompt':f'p{i}','character_mentions':[]} for i in range(20)]
        mapping20={task['task_id']:f'media-{i}' for i,task in enumerate(twenty)}
        tiles20=[]
        for i in range(10):tiles20.append({'media_id':f'media-{i}','complete':True,'x':(10-i)*100,'y':400,'tile_height':180})
        for i in range(10,20):tiles20.append({'media_id':f'media-{i}','complete':True,'x':(20-i)*100,'y':100,'tile_height':180})
        order20,_=FlowImages._batch_download_order(twenty,tiles20,mapping20)
        self.assertEqual(order20,[task['task_id'] for task in twenty])
        wrapped=[{**tile,'x':(index%7)*100,'y':100 if index<7 else 400} for index,tile in enumerate(tiles)]
        order_wrapped,_=FlowImages._batch_download_order(tasks,wrapped,mapping)
        self.assertEqual(order_wrapped,['task-9','task-8','task-7','task-6','task-5','task-4','task-3','task-2','task-1','task-0'])

    async def test_generate_batch_rejects_duplicate_fingerprints_before_any_submission(self):
        with tempfile.TemporaryDirectory() as td:
            job_id=str(uuid.uuid4());prompt='identical prompt';flow=FlowImages(FakeBridge([]),Path(td))
            flow._generate_unreserved=AsyncMock()
            tasks=[{'task_id':str(uuid.uuid4()),'ordinal':i,'prompt':prompt,'character_mentions':[]} for i in range(2)]
            with self.assertRaisesRegex(FlowTaskError,'Duplicate prompt/entity fingerprints'):
                await flow.generate_batch(job_id,tasks)
            flow._generate_unreserved.assert_not_awaited()
            self.assertFalse(flow.batches.exists())

    async def test_indeterminate_batch_receipt_never_resubmits_on_replay(self):
        with tempfile.TemporaryDirectory() as td:
            flow=FlowImages(FakeBridge([]),Path(td));job_id=str(uuid.uuid4());task_id=str(uuid.uuid4());prompt='Unique test scene prompt'
            flow._generate_unreserved=AsyncMock(side_effect=FlowTaskError('click ambiguous','uncertain'))
            tasks=[{'task_id':task_id,'ordinal':0,'prompt':prompt,'character_mentions':[]}]
            with self.assertRaises(FlowTaskError):await flow.generate_batch(job_id,tasks,timeout=1)
            receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                     'character_mentions':[],'stage':'submitting'}
            flow._write_receipt(task_id,receipt)
            with self.assertRaisesRegex(FlowTaskError,'indeterminate submitting'):
                await flow.generate_batch(job_id,tasks,timeout=1)
            self.assertEqual(flow._generate_unreserved.await_count,1)

    async def test_enter_submission_focuses_editor_and_uses_preheld_browser_lock(self):
        with tempfile.TemporaryDirectory() as td:
            job_id=str(uuid.uuid4());task_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc';prompt='Distinct focused scene'
            bridge=FakeBridge([{'targetId':'only-flow','type':'page','url':project}]);flow=FlowImages(bridge,Path(td))
            ready={'url':project,'composerAvailable':True,'draftEmpty':True,'generateDisabled':True,'largeImages':[]}
            focused={'url':project,'draftMatches':True,'mentionEntityIds':[],'attachedMediaIds':[],'agentOn':False,
                     'creditLines':['Quá trình tạo sẽ tốn 0 tín dụng'],'settingsText':'Nano Banana 2.1 crop_9_16 x1'}
            flow._ensure_project=AsyncMock(return_value=({'task_id':task_id,'job_id':job_id,'project_url':project,'stage':'project_ready','baseline_media_ids':[]},ready))
            flow._attach_character_mentions=AsyncMock(return_value={'mentionEntityIds':[]})
            flow._ensure_agent_and_settings=AsyncMock(return_value={**focused,'settingsOpen':True})
            flow._prompt_box=AsyncMock(return_value={'x':50,'y':60,'text':prompt})
            flow._click_point=AsyncMock();flow._click_expr=AsyncMock();flow._eval=AsyncMock(return_value=True)
            flow._snapshot=AsyncMock(return_value={**focused,'creditLines':[],'settingsOpen':False})
            flow._wait_page=AsyncMock(side_effect=[{'url':project,'settingsOpen':False},{'draftEmpty':True,'generateDisabled':True}])
            async with bridge.job_lock:
                result=await asyncio.wait_for(flow._generate_unreserved(task_id,job_id,prompt,submit_only=True,require_zero_credit=True,submit_with_enter=True,bridge_lock_held=True),timeout=2)
            self.assertEqual(result['stage'],'waiting_result')
            flow._click_point.assert_awaited_once_with('flow-session',{'x':50,'y':60,'text':prompt})
            keys=[c for c in bridge.cdp.command.call_args_list if c.args[0]=='Input.dispatchKeyEvent']
            self.assertEqual([c.args[1]['type'] for c in keys],['keyDown','keyUp'])
            self.assertEqual(flow._read_receipt(task_id)['stage'],'waiting_result')
            self.assertIn('0 tín dụng',flow._read_receipt(task_id)['credit_estimate'])
            flow._click_expr.assert_awaited_once()

    async def test_enter_rejects_changed_draft_after_cost_panel_closes(self):
        with tempfile.TemporaryDirectory() as td:
            job_id=str(uuid.uuid4());task_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc';prompt='Distinct safe prompt'
            bridge=FakeBridge([{'targetId':'only-flow','type':'page','url':project}]);flow=FlowImages(bridge,Path(td))
            flow._ensure_project=AsyncMock(return_value=({'task_id':task_id,'job_id':job_id,'project_url':project,'stage':'project_ready','baseline_media_ids':[]},{'url':project}))
            flow._attach_character_mentions=AsyncMock(return_value={'mentionEntityIds':[]})
            verified={'url':project,'draftMatches':True,'mentionEntityIds':[],'attachedMediaIds':[],'agentOn':False,'settingsOpen':True,
                      'settingsText':'Nano Banana 2.1 crop_9_16 x1','creditLines':['Quá trình tạo sẽ tốn 0 tín dụng']}
            flow._ensure_agent_and_settings=AsyncMock(return_value=verified)
            flow._click_expr=AsyncMock();flow._prompt_box=AsyncMock(return_value={'x':50,'y':60});flow._click_point=AsyncMock();flow._eval=AsyncMock(return_value=True)
            flow._wait_page=AsyncMock(return_value={'url':project,'settingsOpen':False})
            flow._snapshot=AsyncMock(return_value={**verified,'draftMatches':False,'settingsOpen':False,'creditLines':[]})
            with self.assertRaisesRegex(FlowTaskError,'changed at Enter boundary'):
                await flow._generate_unreserved(task_id,job_id,prompt,submit_only=True,require_zero_credit=True,submit_with_enter=True)
            self.assertFalse(any(c.args[0]=='Input.dispatchKeyEvent' for c in bridge.cdp.command.call_args_list))
            self.assertNotEqual(flow._read_receipt(task_id)['stage'],'submitting')

    async def test_batch_reservation_blocks_single_generate_interleaving(self):
        flow=FlowImages(FakeBridge([]),Path('unused'));batch_started=asyncio.Event();release_batch=asyncio.Event();single_called=[]
        async def batch_impl(job_id,tasks,timeout=1200,bridge_lock_held=False,download_results=True,require_zero_credit=True):
            batch_started.set();await release_batch.wait();return ['batch']
        async def single_impl(*args,**kwargs):single_called.append(True);return {'task_id':'single'}
        flow._generate_batch_unreserved=AsyncMock(side_effect=batch_impl)
        flow._generate_unreserved=AsyncMock(side_effect=single_impl)
        batch=asyncio.create_task(flow.generate_batch('job',[],timeout=1))
        await batch_started.wait()
        single=asyncio.create_task(flow.generate('task','job','prompt'))
        await asyncio.sleep(0)
        self.assertEqual(single_called,[])
        release_batch.set()
        self.assertEqual(await batch,['batch']);self.assertEqual((await single)['task_id'],'single')
        self.assertEqual(single_called,[True])

    async def test_batch_submits_before_wait_maps_exact_prompts_and_downloads_in_manifest_order(self):
        with tempfile.TemporaryDirectory() as td:
            job_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
            tasks=[
                {'task_id':str(uuid.uuid4()),'ordinal':0,'prompt':'Cobalt-blue lighthouse on rocky coast at sunrise, no text.','character_mentions':[]},
                {'task_id':str(uuid.uuid4()),'ordinal':1,'prompt':'Yellow tram crossing a snowy bridge at dawn, no text.','character_mentions':[]},
            ]
            bridge=FakeBridge([{'targetId':'only-flow','type':'page','url':project}]);flow=FlowImages(bridge,Path(td));submit_calls=[];download_calls=[]
            async def fake_generate(task_id,current_job,prompt,**kwargs):
                submit_calls.append((task_id,kwargs.get('submit_only'),kwargs.get('require_zero_credit')))
                receipt={'task_id':task_id,'job_id':current_job,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'character_mentions':[],
                         'project_url':project,'stage':'waiting_result','baseline_media_ids':[],'credit_estimate':'Quá trình tạo sẽ tốn 0 tín dụng','credit_verified_at':1.0,'submitted_at':1.0}
                flow._write_receipt(task_id,receipt)
                return {'task_id':task_id,'stage':'waiting_result','project_url':project,'credit_estimate':'Quá trình tạo sẽ tốn 0 tín dụng','credit_verified_at':1.0}
            flow._generate_unreserved=AsyncMock(side_effect=fake_generate)
            flow._target=AsyncMock(return_value='only-flow');flow._session=AsyncMock(return_value='flow-session')
            flow._snapshot=AsyncMock(return_value={'url':project,'composerAvailable':True,'draftEmpty':True,'assetTiles':[
                {'media_id':'media-2','complete':True,'aria_label':'Yellow tram crossing a snowy …','text':tasks[1]['prompt'],'x':300,'y':200,'tile_height':200},
                {'media_id':'media-1','complete':True,'aria_label':'Cobalt-blue lighthouse on rocky …','text':tasks[0]['prompt'],'x':100,'y':200,'tile_height':200}],'largeImages':[]})
            flow._read_detail_prompt_for_media=AsyncMock(side_effect=[
                {'media_id':'media-2','prompt':tasks[1]['prompt'],'mention_entity_ids':[]},
                {'media_id':'media-1','prompt':tasks[0]['prompt'],'mention_entity_ids':[]},
            ])
            flow._read_prompt_for_media=flow._read_detail_prompt_for_media
            flow._wait_page=AsyncMock(return_value={'url':project,'composerAvailable':True,'draftEmpty':True})
            interrupted=[False]
            async def fake_download(task_id,target,session,receipt,prompt,media_id=None):
                if download_calls:
                    self.assertEqual(receipt.get('download_resolution_requested'),'1K','after a failed 2K download, reuse 1K for the rest of this cohort')
                    if not interrupted[0]:
                        interrupted[0]=True
                        raise FlowTaskError('fixture interrupted download','uncertain')
                else:
                    receipt.update(download_resolution_requested='1K',download_fallback_reason='2K unavailable')
                download_calls.append(task_id)
                path=Path(td)/(task_id+'.png');Image.new('RGB',(600,600),(30,80,120)).save(path,format='PNG')
                from videostudio.core import digest
                receipt.update({'stage':'downloaded','media_id':media_id,'download_path':str(path),'download_sha256':digest(path),'width':600,'height':600,'format':'PNG','download_guid':'guid-'+media_id})
                flow._write_receipt(task_id,receipt);return receipt
            flow._download_2k=AsyncMock(side_effect=fake_download)
            record_only=await flow.generate_batch(job_id,tasks,timeout=2,download_results=False)
            self.assertEqual([x['stage'] for x in record_only],['image_ready','image_ready'])
            self.assertEqual(flow._download_2k.await_count,0,'recording run stops after generation/mapping')
            self.assertEqual(flow._read_batch_manifest(next(flow.batches.glob('*.json')).stem)['stage'],'images_ready')
            with self.assertRaisesRegex(FlowTaskError,'fixture interrupted download'):
                await flow.generate_batch(job_id,tasks,timeout=2)
            # A restart/reflow must retain task/media ownership and the saved order.
            for tile in flow._snapshot.return_value['assetTiles']:tile['x']=500-tile['x']
            results=await flow.generate_batch(job_id,tasks,timeout=2)
            self.assertEqual([x['task_id'] for x in results],[x['task_id'] for x in tasks])
            self.assertEqual([x['media_id'] for x in results],['media-1','media-2'])
            self.assertEqual(download_calls,[tasks[1]['task_id'],tasks[0]['task_id']], 'download order must follow visible row right-to-left, not task ordinal')
            self.assertEqual([x[0] for x in submit_calls],[x['task_id'] for x in tasks])
            self.assertTrue(all(only and zero for _,only,zero in submit_calls))
            self.assertEqual([c.kwargs['batch_settings_verified'] for c in flow._generate_unreserved.await_args_list],[False,True])
            self.assertTrue(all(c.kwargs['submit_with_enter'] is False for c in flow._generate_unreserved.await_args_list))
            self.assertEqual(flow._download_2k.await_count,3)
            self.assertEqual(flow._read_batch_manifest(next(flow.batches.glob('*.json')).stem)['mapping'],{tasks[0]['task_id']:'media-1',tasks[1]['task_id']:'media-2'})
            replay=await flow.generate_batch(job_id,tasks,timeout=2)
            self.assertEqual([item['media_id'] for item in replay],['media-1','media-2'])
            self.assertEqual(len(submit_calls),2,'replay must not submit a second time')
            self.assertEqual(flow._download_2k.await_count,3,'replay must reuse saved downloads')

    async def test_submit_only_returns_after_receipt_and_requires_explicit_zero_cost_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            job_id=str(uuid.uuid4());task_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
            bridge=FakeBridge([{'targetId':'only-flow','type':'page','url':project}]);flow=FlowImages(bridge,Path(td))
            state={'url':project,'composerAvailable':True,'draftEmpty':True,'generateDisabled':True,'largeImages':[]}
            flow._ensure_project=AsyncMock(return_value=({'task_id':task_id,'job_id':job_id,'project_url':project,'stage':'project_ready','baseline_media_ids':[]},state))
            flow._attach_character_mentions=AsyncMock(return_value={'mentionEntityIds':[]})
            flow._ensure_agent_and_settings=AsyncMock(return_value={'draftMatches':True,'mentionEntityIds':[],'attachedMediaIds':[],'agentOn':False,'creditLines':['Quá trình tạo sẽ tốn 0 tín dụng'],'settingsText':'🍌 Nano Banana 2.1\ncrop_9_16\nx1'})
            flow._click_named=AsyncMock()
            flow._wait_page=AsyncMock(return_value={'draftEmpty':True})
            result=await flow.generate(task_id,job_id,'Cobalt-blue lighthouse prompt.',submit_only=True,require_zero_credit=True)
            self.assertEqual(result['stage'],'waiting_result')
            self.assertEqual(flow._read_receipt(task_id)['stage'],'waiting_result')
            flow._click_named.assert_awaited_once_with('flow-session','Bắt đầu tạo',exact=True,native_only=True)
            self.assertTrue(flow._wait_page.await_args.args[1]({'draftEmpty':True}))
            self.assertFalse(flow._wait_page.await_args.args[1]({'draftEmpty':False,'largeImages':[{'media_id':'unrelated'}]}))
            task2=str(uuid.uuid4());flow2=FlowImages(bridge,Path(td)/'second')
            flow2._ensure_project=AsyncMock(return_value=({'task_id':task2,'job_id':job_id,'project_url':project,'stage':'project_ready','baseline_media_ids':[]},state))
            flow2._attach_character_mentions=AsyncMock(return_value={'mentionEntityIds':[]})
            flow2._ensure_agent_and_settings=AsyncMock(return_value={'draftMatches':True,'mentionEntityIds':[],'attachedMediaIds':[],'agentOn':False,'creditLines':['Quá trình tạo sẽ tốn 3 tín dụng'],'settingsText':'🍌 Nano Banana 2.1\ncrop_9_16\nx1'})
            flow2._click_named=AsyncMock()
            with self.assertRaisesRegex(FlowTaskError,'not explicitly 0'):
                await flow2.generate(task2,job_id,'Yellow tram prompt.',submit_only=True,require_zero_credit=True)
            flow2._click_named.assert_not_awaited()

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

    async def test_native_character_creation_can_save_when_paid_generation_is_authorized(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());character_id='father';name='father';prompt='neutral portrait prompt';project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc';entity_id=str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmp:
            flow=FlowImages(FakeBridge([]),Path(tmp));receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':project,'stage':'project_ready'}
            state={'url':project,'composerAvailable':True,'draftEmpty':True,'generateDisabled':True}
            form={'url':project+'/character','composerAvailable':True}
            detail={'url':project+'/character/'+entity_id,'composerAvailable':True}
            fields=[{'value':'Character not named','rect':{'x':10,'y':10}},{'value':'Character not named','rect':{'x':20,'y':20}}]
            named={'values':[name,name],'done':1,'disabled':[False],'point':{'x':30,'y':30}}
            flow._target=AsyncMock(return_value='flow-tab');flow._session=AsyncMock(return_value='session');flow._ensure_project=AsyncMock(return_value=(receipt,state))
            flow._click_named=AsyncMock();flow._wait_page=AsyncMock(side_effect=[form,detail])
            flow._eval=AsyncMock(side_effect=[{'x':10,'y':10,'text':''},{'prompt':prompt,'models':1,'generate':[{'disabled':False,'rect':{'x':5,'y':5}}],'credits':[]},fields,named,True])
            flow._click_point=AsyncMock();flow._return_to_project_root=AsyncMock()
            result=await flow.create_character(task_id,job_id,character_id,name,prompt)
            self.assertEqual(result,{'task_id':task_id,'character_id':entity_id,'name':name,'project_url':project})
            self.assertEqual(flow._read_receipt(task_id)['stage'],'character_saved')
            self.assertEqual(flow._read_receipt(task_id)['credit_estimate'],None)
            self.assertEqual(flow._click_point.await_count,4)

    async def test_agent_off_and_image_settings_are_required_but_credit_estimate_is_not(self):
        bridge = FakeBridge([])
        flow = FlowImages(bridge, Path('unused'))
        state = {'agentOn':False,'settingsOpen':True,'settingsText':'Nano Banana 2.1 crop_9_16 x1','creditLines':['Quá trình tạo sẽ tốn 3 tín dụng']}
        flow._snapshot = AsyncMock(side_effect=[state,state,state])
        flow._click_named = AsyncMock();flow._click_expr = AsyncMock()
        result=await flow._ensure_agent_and_settings('session','fixture prompt')
        self.assertIs(result['agentOn'],False)
        self.assertEqual(result['settingsText'],state['settingsText'])
        self.assertIn('3 tín dụng',result['creditLines'][0])

    async def test_flow_submit_still_requires_agent_off_and_settings(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='free-only prompt'
        with tempfile.TemporaryDirectory() as tmp:
            bridge=FakeBridge([]);flow=FlowImages(bridge,Path(tmp));receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':'https://flow.google.com/project/abc','target_id':'one','stage':'project_ready'}
            flow._write_receipt(task_id,receipt);flow._target=AsyncMock(return_value='one');flow._session=AsyncMock(return_value='session')
            flow._ensure_project=AsyncMock(return_value=(receipt,{'url':receipt['project_url']}));flow._attach_character_mentions=AsyncMock(return_value={'draftMatches':True,'mentionEntityIds':[],'attachedMediaIds':[]})
            flow._ensure_agent_and_settings=AsyncMock(side_effect=FlowTaskError('Tác nhân is not confirmed off','needs_flow_check'));flow._click_named=AsyncMock()
            with self.assertRaises(FlowTaskError) as caught:await flow.generate(task_id,job_id,prompt)
            self.assertEqual(caught.exception.code,'needs_flow_check')
            self.assertNotIn('Bắt đầu tạo',[c.args[1] for c in flow._click_named.await_args_list])
            self.assertEqual(flow._read_receipt(task_id)['stage'],'characters_attached')
            self.assertEqual(flow._read_receipt(task_id)['character_mentions'],[])

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
                    flow.active_frame=kwargs.get('download_frame')
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


    async def test_native_character_mentions_insert_and_verify_exact_entity_chip(self):
        entity_id=str(uuid.uuid4());project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
        mention={'character_id':entity_id,'name':'father','project_url':project}
        flow=FlowImages(FakeBridge([]),Path('unused'))
        flow._snapshot=AsyncMock(return_value={'draftMatches':False,'mentionEntityIds':[],'attachedMediaIds':[]})
        flow._prompt_box=AsyncMock(return_value={'x':10,'y':10,'text':''})
        flow._eval=AsyncMock(return_value=[{'name':'father','active':True,'selected':False}])
        flow._wait_page=AsyncMock(side_effect=[{'mentionEntityIds':[entity_id],'attachedMediaIds':[]},{'draftMatches':True,'mentionEntityIds':[entity_id],'attachedMediaIds':[]}])
        result=await flow._attach_character_mentions('session','A man looks across a field.',[mention])
        self.assertEqual(result['mentionEntityIds'],[entity_id])
        inserted=[c.args[1].get('text') for c in flow.bridge.cdp.command.await_args_list if c.args[0]=='Input.insertText']
        self.assertEqual(inserted,['@',' ','A man looks across a field.'])
        self.assertTrue(any(c.args[1].get('key')=='Enter' for c in flow.bridge.cdp.command.await_args_list if c.args[0]=='Input.dispatchKeyEvent'))

    async def test_native_character_from_another_job_project_blocks_before_prompt_or_generate(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='scene prompt';other='https://flow.google.com/project/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        mention={'character_id':str(uuid.uuid4()),'name':'father','project_url':other}
        flow=FlowImages(FakeBridge([]),Path('unused'));flow._target=AsyncMock(return_value='target');flow._session=AsyncMock(return_value='session')
        receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc','target_id':'target','stage':'project_ready','baseline_media_ids':[]}
        state={'url':receipt['project_url'],'largeImages':[],'attachedMediaIds':[],'draftEmpty':True,'generateDisabled':True}
        flow._ensure_project=AsyncMock(return_value=(receipt,state));flow._attach_character_mentions=AsyncMock();flow._click_named=AsyncMock()
        with self.assertRaises(FlowTaskError) as caught:await flow.generate(task_id,job_id,prompt,character_mentions=[mention])
        self.assertEqual(caught.exception.code,'needs_flow_check')
        flow._attach_character_mentions.assert_not_awaited();flow._click_named.assert_not_awaited()

    async def test_changed_native_character_mentions_are_never_resubmitted(self):
        task_id=str(uuid.uuid4());job_id=str(uuid.uuid4());prompt='same scene prompt';project='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc';entity=str(uuid.uuid4())
        old=[{'character_id':entity,'name':'father','project_url':project}]
        changed=[{'character_id':entity,'name':'dad','project_url':project}]
        with tempfile.TemporaryDirectory() as tmp:
            flow=FlowImages(FakeBridge([]),Path(tmp));flow._write_receipt(task_id,{'task_id':task_id,'job_id':job_id,'prompt_sha256':__import__('hashlib').sha256(prompt.encode()).hexdigest(),'character_mentions':old,'stage':'project_ready'})
            with self.assertRaisesRegex(FlowTaskError,'mention set differs'):
                await flow.generate(task_id,job_id,prompt,character_mentions=changed)
            flow.bridge.cdp.command.assert_not_awaited()

if __name__=='__main__':
    unittest.main()
