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
    def test_recovery_can_read_matching_image_under_open_viewer_without_known_mode(self):
        q=self.module();s=self.state();s['mode']='unknown';self.assertIsNotNone(q.match_image(s,'[image-marker]'))
        s['mode']='work';self.assertIsNone(q.match_image(s,'[image-marker]'))
        s['mode']='unknown';s['login']=True;self.assertIsNone(q.match_image(s,'[image-marker]'))
    def test_wrapper_requests_image_not_json(self):
        q=self.module();wrapped=q.image_prompt('draw an apple','f'*64)
        self.assertIn('draw an apple',wrapped);self.assertIn('[VideoStudio image request '+('f'*64)+']',wrapped);self.assertNotIn('Return exactly one JSON',wrapped)

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
                data={'prompt':'one accurate scene','provider':'chatgpt','version':view['version']}
                self.assertEqual(c.post(base,json=data,headers={'Origin':'https://evil.invalid','Idempotency-Key':'api-key'}).status_code,403)
                started=c.post(base,json=data,headers={'Idempotency-Key':'api-key'});self.assertEqual(started.status_code,202);task=started.json();self.assertEqual(task['state'],'queued');self.assertIsNone(task['image_url'])
                self.assertEqual(c.post(base,json=data,headers={'Idempotency-Key':'api-key'}).json()['id'],task['id'])
                self.assertEqual(c.get(base+'/'+task['id']+'/image').status_code,422)
                self.assertEqual(c.post(base+'/'+task['id']+'/cancel',json={}).json()['state'],'cancelled')
                self.assertEqual(c.get('/api/jobs/'+j['id']+'/scene-editor').json()['version'],view['version'])

class AsyncImageRecoveryTests(unittest.IsolatedAsyncioTestCase):
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
