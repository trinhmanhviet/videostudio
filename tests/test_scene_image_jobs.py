import copy,importlib,importlib.util,io,json,tempfile,unittest,uuid
from PIL import Image
from pathlib import Path
from unittest.mock import Mock,patch
from test_scene_editor import ready_job,picture
from videostudio.core import digest

class ImageParserTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.cdp_images'),'Image transport missing')
        return importlib.import_module('videostudio.cdp_images')
    def state(self):return {'mode':'chat','login':False,'challenge':False,'image_turns':[{'user':'[image-marker] prompt','state':'complete','images':[{'src':'blob:https://chatgpt.com/owned','width':941,'height':1672,'loaded':True}]}]}
    def test_only_exact_matching_turn_can_supply_image(self):
        q=self.module();s=self.state();s['image_turns'].insert(0,{'user':'older prompt','state':'complete','images':[{'src':'https://old','width':1024,'height':1024,'loaded':True}]})
        self.assertEqual(q.match_image(s,'[image-marker]')['src'],'blob:https://chatgpt.com/owned')
    def test_duplicate_marker_or_many_images_is_not_guessed(self):
        q=self.module();s=self.state();s['image_turns'].append(copy.deepcopy(s['image_turns'][0]))
        with self.assertRaises(ValueError):q.match_image(s,'[image-marker]')
        s=self.state();s['image_turns'][0]['images']*=2
        with self.assertRaises(ValueError):q.match_image(s,'[image-marker]')
    def test_incomplete_thumbnail_or_missing_image_cannot_pass(self):
        q=self.module()
        for change in ({'state':'running'},{'images':[]},{'images':[{'src':'blob:https://chatgpt.com/x','width':100,'height':100,'loaded':True}]}):
            s=self.state();s['image_turns'][0].update(change);self.assertIsNone(q.match_image(s,'[image-marker]'))
    def test_image_download_requires_owned_frame_and_guid(self):
        q=self.module();events=[{'method':'Browser.downloadWillBegin','params':{'frameId':'other','guid':str(uuid.uuid4())}}]
        self.assertIsNone(q.correlated_download(events,'owned'))
        guid=str(uuid.uuid4());events.extend([{'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':guid}},{'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed'}}])
        self.assertEqual(q.correlated_download(events,'owned'),guid)
    def test_image_download_deduplicates_identical_start_events_and_rejects_conflicting_guids(self):
        q=self.module();guid=str(uuid.uuid4())
        # Duplicate start events for the same frameId and GUID should succeed
        dup_events=[
            {'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':guid}},
            {'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':guid}},
            {'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed'}}
        ]
        self.assertEqual(q.correlated_download(dup_events,'owned'),guid)
        # Conflicting GUIDs for the same frameId must be rejected
        other_guid=str(uuid.uuid4())
        conflicting=[
            {'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':guid}},
            {'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':other_guid}},
            {'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed'}}
        ]
        self.assertIsNone(q.correlated_download(conflicting,'owned'))
        # Incomplete download must be rejected
        incomplete=[
            {'method':'Browser.downloadWillBegin','params':{'frameId':'owned','guid':guid}},
            {'method':'Browser.downloadProgress','params':{'guid':guid,'state':'inProgress'}}
        ]
        self.assertIsNone(q.correlated_download(incomplete,'owned'))
    def test_recovery_can_read_matching_image_under_open_viewer_without_known_mode(self):
        q=self.module();s=self.state();s['mode']='unknown';self.assertIsNotNone(q.match_image(s,'[image-marker]'))
        s['mode']='work';self.assertIsNone(q.match_image(s,'[image-marker]'))
        s['mode']='unknown';s['login']=True;self.assertIsNone(q.match_image(s,'[image-marker]'))
    def test_download_control_must_be_stable_after_reflow(self):
        q=self.module();p1={'control':'viewer-download','x':100,'y':200,'width':44,'height':40};p2={'control':'viewer-download','x':120,'y':200,'width':44,'height':40}
        self.assertFalse(q.stable_control_point(p1,p2));self.assertTrue(q.stable_control_point(p2,dict(p2)))
    def test_download_events_record_rejected_frame_without_sensitive_url_or_filename(self):
        q=self.module().ChatGPTImages(Mock(),Path('.'));q.active_frame='owned-frame';q.attempt={'steps':[],'events':[]};q.attempt_started=__import__('time').monotonic();guid=str(uuid.uuid4())
        q.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'foreign-frame','guid':str(uuid.uuid4()),'url':'https://signed.invalid/x','suggestedFilename':'private.png'}})
        q.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'owned-frame','guid':guid,'url':'https://signed.invalid/x','suggestedFilename':'private.png'}})
        q.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed','receivedBytes':2048,'totalBytes':2048}})
        self.assertEqual([e['accepted'] for e in q.attempt['events']],[False,True,True])
        self.assertEqual(len(q.events),2)
        self.assertTrue(all('url' not in e and 'suggestedFilename' not in e for e in q.attempt['events']))
    def test_download_attempt_diagnostics_are_unique_and_preserve_prior_failure(self):
        q=self.module().ChatGPTImages(Mock(),Path('.'))
        with tempfile.TemporaryDirectory() as t:
            for ident,label in [('a'*32,'first failed'),('b'*32,'resume succeeded')]:
                q.attempt={'attempt_id':ident,'steps':[{'phase':label}],'events':[]};q._save_attempt(Path(t))
            files=sorted(Path(t).glob('download-attempt-*.json'))
            self.assertEqual(len(files),2)
            self.assertIn('first failed',json.loads(files[0].read_text())['steps'][0]['phase'])
            self.assertIn('resume succeeded',json.loads(files[1].read_text())['steps'][0]['phase'])
    def test_wrapper_requests_image_not_json(self):
        q=self.module();wrapped=q.image_prompt('draw an apple','f'*64)
        self.assertIn('draw an apple',wrapped);self.assertIn('[VideoStudio image request '+('f'*64)+']',wrapped);self.assertNotIn('Return exactly one JSON',wrapped)

class DownloadControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_viewer_reflow_is_resampled_until_bounds_stabilize(self):
        from videostudio.cdp_images import ChatGPTImages
        class Bridge:
            def __init__(self):
                self.points=iter([
                    {'x':100,'y':200,'width':44,'height':40},
                    {'x':120,'y':200,'width':44,'height':40},
                    {'x':120,'y':200,'width':44,'height':40}
                ])
                self.calls=0
            async def evaluate(self,session,expression):
                self.calls+=1;return next(self.points)
        bridge=Bridge();image=ChatGPTImages(bridge,Path('.'));image.attempt={'attempt_id':'test','steps':[],'events':[]};image.attempt_started=__import__('time').monotonic()
        point=await image._stable_control_point('session','download-control',1,'viewer-download')
        self.assertEqual(bridge.calls,3);self.assertEqual((point['x'],point['y']),(120,200))
        self.assertEqual(image.attempt['steps'][-1]['phase'],'control_stable')
    async def test_disappearing_control_never_returns_stale_coordinates(self):
        from videostudio.cdp_images import ChatGPTImages
        class Bridge:
            async def evaluate(self,session,expression):return None
        image=ChatGPTImages(Bridge(),Path('.'));self.assertIsNone(await image._stable_control_point('session','download-control',.01,'viewer-download'))
    async def test_restore_failure_does_not_mask_primary_error_and_is_logged(self):
        from videostudio.cdp_images import ChatGPTImages,IndeterminateRequest
        class CDP:
            async def command(self,*args,**kwargs):raise OSError('restore failed')
        class Bridge:cdp=CDP()
        image=ChatGPTImages(Bridge(),Path('.'));image.active_frame='owned';image.attempt_started=__import__('time').monotonic()
        with tempfile.TemporaryDirectory() as t:
            image.attempt={'attempt_id':'after-success','steps':[],'events':[]}
            await image._finish_download_attempt(Path(t),None)
            self.assertTrue(image.download_behavior_uncertain)
            self.assertTrue((Path(t)/'download-attempt-after-success.json').is_file())
            image.attempt={'attempt_id':'after-error','steps':[],'events':[]};image.attempt_started=__import__('time').monotonic()
            with self.assertRaisesRegex(ValueError,'original download failure'):
                try:raise ValueError('original download failure')
                finally:await image._finish_download_attempt(Path(t),__import__('sys').exc_info()[1])
            self.assertTrue(image.download_behavior_uncertain)
            traces=sorted(Path(t).glob('download-attempt-*.json'));self.assertEqual(len(traces),2)
            self.assertEqual(traces[1].read_text(encoding='utf8').count('download_behavior_restore_failed'),1)

class QueueTests(unittest.TestCase):
    def queue(self,s):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.scene_images'),'Scene image queue missing')
        q=importlib.import_module('videostudio.scene_images').SceneImageJobs(s)
        q.download_root=s.path.parent/'downloads';q.download_root.mkdir(exist_ok=True)
        def runner(task):
            p=q.download_root/(task['id']+'.png');Image.new('RGB',(512,912),'green').save(p,format='PNG')
            return {'task_id':task['id'],'file_path':str(p),'sha256':digest(p),'request_id':'fixture-receipt','conversation_url':'https://chatgpt.com/c/fixture','width':512,'height':912}
        q.runner=Mock(side_effect=runner);return q
    def start(self,q,j,key='image-key'):
        v=q.editor.view(j['id']);return q.start(j['id'],v['scenes'][0]['scene_id'],'redraw this scene','chatgpt',key,v['version'])
    def test_submit_is_idempotent_and_does_not_change_selected_scene(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);v=q.editor.view(j['id']);a=self.start(q,j);b=self.start(q,j)
            self.assertEqual(a['id'],b['id']);self.assertEqual(a['state'],'queued');self.assertEqual(q.editor.view(j['id'])['version'],v['version']);self.assertEqual(s.get(j['id'])['checkpoints'],j['checkpoints']);q.runner.assert_not_called()
    def test_candidate_is_not_applied_until_user_selects_it(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);v=q.editor.view(j['id']);a=self.start(q,j);q.step('test-worker');a=q.get(a['id']);self.assertEqual(a['state'],'completed');self.assertEqual(q.editor.view(j['id'])['scenes'][0]['edit_id'],'original')
            # Queue fixture uses real image bytes; application must not touch narration/timeline.
            result=q.apply(j['id'],v['scenes'][0]['scene_id'],a['id'],v['version'],'contain');self.assertNotEqual(result['scenes'][0]['edit_id'],'original');self.assertEqual(s.get(j['id'])['checkpoints'],j['checkpoints']);self.assertEqual(q.get(a['id'])['state'],'applied')
            self.assertEqual(q.apply(j['id'],v['scenes'][0]['scene_id'],a['id'],v['version'],'contain')['version'],result['version'])
    def test_stale_apply_rejected_without_overwriting_current_image(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);v=q.editor.view(j['id']);a=self.start(q,j);q.step('worker');q.editor.replace(j['id'],v['scenes'][0]['scene_id'],picture('blue'),'cover',v['version'])
            with self.assertRaises(ValueError):q.apply(j['id'],v['scenes'][0]['scene_id'],a['id'],v['version'],'cover')
            self.assertEqual(q.get(a['id'])['state'],'completed')
    def test_uncertain_requires_explicit_resume_and_same_task_id(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);a=self.start(q,j);q.runner.side_effect=TimeoutError('delivery unknown');q.step('worker');self.assertEqual(q.get(a['id'])['state'],'uncertain');self.assertFalse(q.step('worker'))
            q.resume(j['id'],a['scene'],a['id']);self.assertEqual(q.get(a['id'])['id'],a['id']);self.assertEqual(q.get(a['id'])['state'],'queued')
    def test_cancel_does_not_abort_or_publish_an_unrelated_request(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);a=self.start(q,j);q.cancel(j['id'],a['scene'],a['id']);self.assertEqual(q.get(a['id'])['state'],'cancelled');self.assertFalse(q.step('worker'));q.runner.assert_not_called()
    def test_foreign_task_and_unknown_provider_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);a=self.start(q,j);v=q.editor.view(j['id'])
            with self.assertRaises(ValueError):q.apply(j['id'],v['scenes'][1]['scene_id'],a['id'],v['version'],'cover')
            with self.assertRaises(ValueError):q.start(j['id'],a['scene'],'prompt','flow','x',v['version'])
    def test_result_file_path_cannot_escape_expected_download_root(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);a=self.start(q,j);bad=Path(t)/'other.png';bad.write_bytes(picture());q.runner.side_effect=lambda task:{'task_id':task['id'],'file_path':str(bad),'sha256':digest(bad),'request_id':'bad'};q.step('worker');self.assertEqual(q.get(a['id'])['state'],'failed')
    def test_worker_respects_existing_production_lease(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);q=self.queue(s);self.start(q,j);s.lock('production');self.assertFalse(q.step('images'));q.runner.assert_not_called();s.release('production')

class ComfySceneRunnerTests(unittest.TestCase):
    def test_comfy_runner_uses_isolated_qwen_receipt_and_common_candidate_validation(self):
        from videostudio.scene_images import SceneImageJobs
        with tempfile.TemporaryDirectory() as t:
            store,j=ready_job(t);q=QueueTests().queue(store);sid=q.editor.view(j['id'])['scenes'][0]['scene_id'];created=q.start(j['id'],sid,'Qwen scene prompt','comfy','comfy-runner-key',q.editor.view(j['id'])['version']);task_id=created['id']
            with store.db() as c:c.execute("UPDATE scene_image_tasks SET state='running' WHERE id=?",(task_id,))
            task=q.get(task_id)
            def run(journal_job,kind,graph,path,check,strict_resume=False):
                Image.new('RGB',(768,1376),'green').save(path,format='PNG')
                self.assertEqual(kind,'images-scene-'+task_id);self.assertTrue(strict_resume);self.assertEqual(graph['4']['inputs']['prompt'],'Qwen scene prompt');self.assertTrue(Path(journal_job['output']).name==task_id)
                check();return {'prompt_id':'comfy-prompt-'+task_id}
            q.pipeline=Mock(comfy_asset=Mock(side_effect=run))
            result=q._run_comfy(task);validated=q._validate(task,result)
            self.assertEqual(result['request_id'],'comfy-prompt-'+task_id);self.assertEqual((result['width'],result['height']),(768,1376))
            self.assertTrue(Path(validated['candidate_path']).is_file());q.pipeline.comfy_asset.assert_called_once()
    def test_busy_comfy_maps_to_resumable_idle_state_without_receipt_or_candidate(self):
        from videostudio.scene_images import SceneImageJobs,ImageTaskIssue
        with tempfile.TemporaryDirectory() as t:
            store,j=ready_job(t);q=QueueTests().queue(store);task_id=str(uuid.uuid4());sid=q.editor.view(j['id'])['scenes'][0]['scene_id'];task={'id':task_id,'job':j['id'],'scene':sid,'prompt':'prompt'}
            q.pipeline=Mock(comfy_asset=Mock(side_effect=RuntimeError('ComfyUI busy with other work; no submission/unload/interrupt performed')))
            with self.assertRaises(ImageTaskIssue) as caught:q._run_comfy(task)
            self.assertEqual(caught.exception.code,'needs_comfy_idle');q.pipeline.comfy_asset.assert_called_once()
            self.assertFalse((q.download_root/(task_id+'.png')).exists())
            self.assertFalse((q.download_root/'comfy-tasks'/task_id/('images-scene-'+task_id+'-receipt.json')).exists())
    def test_comfy_provider_is_accepted_and_pending_deferral_blocks_duplicate_scene_task(self):
        with tempfile.TemporaryDirectory() as t:
            store,j=ready_job(t);q=QueueTests().queue(store);v=q.editor.view(j['id']);sid=v['scenes'][0]['scene_id']
            a=q.start(j['id'],sid,'qwen prompt','comfy','comfy-key',v['version'])
            self.assertEqual(a['provider'],'comfy');self.assertEqual(a['state'],'queued')
            with store.db() as c:c.execute("UPDATE scene_image_tasks SET state='needs_comfy_idle' WHERE id=?",(a['id'],))
            with self.assertRaisesRegex(ValueError,'already has a pending'):q.start(j['id'],sid,'another','comfy','second-key',v['version'])
            q.resume(j['id'],sid,a['id']);self.assertEqual(q.get(a['id'])['state'],'queued')

class GenerationAPITests(unittest.TestCase):
    def test_routes_are_same_origin_and_do_not_apply_implicitly(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        class FixturePipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as t:
            store,j=ready_job(t);app=create_app(store,FixturePipeline(),False)
            with TestClient(app) as c:
                view=c.get('/api/jobs/'+j['id']+'/scene-editor').json();sid=view['scenes'][0]['scene_id'];base='/api/jobs/'+j['id']+'/scene-editor/scenes/'+sid+'/generations'
                self.assertEqual(c.get(base).json()['providers'],['chatgpt','comfy'])
                data={'prompt':'one accurate scene','provider':'chatgpt','version':view['version']}
                self.assertEqual(c.post(base,json=data,headers={'Origin':'https://evil.invalid','Idempotency-Key':'api-key'}).status_code,403)
                started=c.post(base,json=data,headers={'Idempotency-Key':'api-key'});self.assertEqual(started.status_code,202);task=started.json();self.assertEqual(task['state'],'queued');self.assertIsNone(task['image_url'])
                self.assertEqual(c.post(base,json=data,headers={'Idempotency-Key':'api-key'}).json()['id'],task['id'])
                self.assertEqual(c.get(base+'/'+task['id']+'/image').status_code,422)
                self.assertEqual(c.post(base+'/'+task['id']+'/cancel',json={}).json()['state'],'cancelled')
                comfy=c.post(base,json={'prompt':'qwen scene','provider':'comfy','version':view['version']},headers={'Idempotency-Key':'comfy-api-key'})
                self.assertEqual(comfy.status_code,202);self.assertEqual(comfy.json()['provider'],'comfy')
                self.assertEqual(c.get('/api/jobs/'+j['id']+'/scene-editor').json()['version'],view['version'])

class AsyncImageRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_download_arms_capture_before_opening_viewer_and_keeps_events_during_click(self):
        from videostudio.cdp_images import ChatGPTImages
        from PIL import Image
        class Bridge:
            def __init__(self,url,marker,image):
                self.url=url;self.marker=marker;self.image_data=image;self.viewer_open=False;self.point_values=iter([100,120,120,140,140,140]);self.preview_calls=0;self.eval_calls=[]
                self.cdp=CDP(self)
            async def evaluate(self,session,expression):
                self.eval_calls.append(expression)
                if 'const base=' in expression:
                    return {'mode':'unknown','login':False,'challenge':False,'url':self.url,'image_turns':[{'user':self.marker,'state':'complete','images':[self.image_data]}]}
                if "querySelectorAll('[role=dialog]')" in expression:
                    if not self.viewer_open:return None
                    x=next(self.point_values)
                    return {'x':x,'y':200,'width':44,'height':40}
                if 'button[data-testid="generated-image-preview"]' in expression:
                    self.preview_calls+=1;return {'x':50,'y':100,'width':80,'height':90}
                raise AssertionError('Unexpected page expression')
        class CDP:
            def __init__(self,owner):self.owner=owner;self.calls=[];self.capture_armed=False;self.download_path=None;self.releases=0;self.download_click=(None,None);self.events_arrived_inside_click=False
            async def command(self,method,params=None,session=None,timeout=10):
                params=params or {};self.calls.append((method,dict(params)))
                if method=='Page.getFrameTree':return {'frameTree':{'frame':{'id':'owned-frame'}}}
                if method=='Browser.setDownloadBehavior':
                    if params.get('behavior')=='allowAndName':self.capture_armed=True;self.download_path=Path(params['downloadPath'])
                    else:self.capture_armed=False
                    return {}
                if method=='Input.dispatchMouseEvent' and params.get('type')=='mouseReleased':
                    self.releases+=1
                    if self.releases==1:self.owner.viewer_open=True
                    elif self.releases==2:
                        self.download_click=(params['x'],params['y']);self.events_arrived_inside_click=self.capture_armed
                        self.assert_download()
                    return {}
                return {}
            def assert_download(self):
                assert self.capture_armed and self.download_path
                guid=str(uuid.uuid4());self.download_path.mkdir(parents=True,exist_ok=True)
                Image.effect_noise((512,912),80).convert('RGB').save(self.download_path/guid,format='PNG')
                frame='owned-frame';self.owner.image.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':frame,'guid':guid,'url':'https://signed.invalid/never-log-this','suggestedFilename':'private.png'}})
                self.owner.image.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'inProgress','receivedBytes':100,'totalBytes':2000}})
                self.owner.image.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed','receivedBytes':2000,'totalBytes':2000}})
        task=str(uuid.uuid4());url='https://chatgpt.com/c/owned';marker='[VideoStudio image request '+'d'*64+']';found={'src':'blob:https://chatgpt.com/image','width':941,'height':1672,'loaded':True}
        with tempfile.TemporaryDirectory() as t:
            bridge=Bridge(url,marker,found);image=ChatGPTImages(bridge,Path(t));bridge.image=image;image.download_behavior_uncertain=True
            result=await image._download(task,'target','session',marker,found,url)
            self.assertEqual(result['width'],512);self.assertEqual(result['height'],912);self.assertEqual(result['sha256'],digest(Path(result['file_path'])))
            reset_index=next(i for i,(m,p) in enumerate(bridge.cdp.calls) if m=='Browser.setDownloadBehavior' and p.get('behavior')=='default')
            allow_index=next(i for i,(m,p) in enumerate(bridge.cdp.calls) if m=='Browser.setDownloadBehavior' and p.get('behavior')=='allowAndName')
            self.assertLess(reset_index,allow_index);self.assertFalse(image.download_behavior_uncertain)
            preview_index=next(i for i,(m,p) in enumerate(bridge.cdp.calls) if m=='Input.dispatchMouseEvent' and p.get('type')=='mouseReleased')
            self.assertLess(allow_index,preview_index);self.assertTrue(bridge.cdp.events_arrived_inside_click);self.assertEqual(bridge.cdp.download_click,(140,200))
            self.assertNotIn('Input.insertText',[m for m,_ in bridge.cdp.calls])
            traces=list((Path(t)/'downloads'/task).glob('download-attempt-*.json'));self.assertEqual(len(traces),1)
            trace=json.loads(traces[0].read_text(encoding='utf8'));phases=[x['phase'] for x in trace['steps']]
            self.assertIn('control_reflowed_before_click',phases);self.assertIn('download_click_acknowledged',phases)
            self.assertEqual([e['accepted'] for e in trace['events']],[True,True,True])

    async def test_sending_receipt_recovers_matching_image_without_send(self):
        from unittest.mock import AsyncMock,MagicMock
        from videostudio.cdp_images import ChatGPTImages
        from videostudio.cdp_requests import RequestJournal
        import asyncio
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);journal=RequestJournal(root/'journal.db');task=str(uuid.uuid4());job='__image__'+task;r=journal.prepare(job,'apple');journal.claim_send(r['id']);journal.set_conversation(job,'https://chatgpt.com/c/owned','owned')
            marker='[VideoStudio image request '+r['id']+']'
            b=MagicMock();b.journal=journal;b.job_lock=asyncio.Lock();b.connect=AsyncMock();b.session=AsyncMock(return_value='session');b.cdp.command=AsyncMock(side_effect=lambda method,*a,**kw:{'targetInfos':[{'targetId':'owned','type':'page','url':'https://chatgpt.com/c/owned'}]} if method=='Target.getTargets' else {})
            b.evaluate=AsyncMock(return_value={'mode':'chat','login':False,'challenge':False,'url':'https://chatgpt.com/c/owned','image_turns':[{'user':marker,'state':'complete','images':[{'src':'blob:https://chatgpt.com/good','width':941,'height':1672,'loaded':True}]}]})
            path=root/(task+'.png');Image.new('RGB',(512,912),'green').save(path)
            image=ChatGPTImages(b,root);image._download=AsyncMock(return_value={'task_id':task,'file_path':str(path),'sha256':digest(path)})
            result=await image.generate(task,'apple',timeout=1);self.assertEqual(result['request_id'],r['id']);image._download.assert_awaited_once()
            methods=[c.args[0] for c in b.cdp.command.call_args_list];self.assertNotIn('Input.insertText',methods);self.assertNotIn('Input.dispatchMouseEvent',methods)
            b.evaluate.reset_mock();await image.generate(task,'apple');b.evaluate.assert_not_awaited()

if __name__=='__main__':unittest.main()
