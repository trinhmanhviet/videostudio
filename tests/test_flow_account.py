import hashlib
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from PIL import Image

from videostudio.core import Store


class FlowAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root/'jobs.db', self.root/'outputs')
        self.job, _ = self.store.create({'idea':'test', 'voice_id':'voice', 'duration_seconds':8}, str(uuid.uuid4()))
        self.jid = self.job['id']
        self.prompt = 'A blue room with a red chair'
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='failed',stage='images' WHERE id=?", (self.jid,))
            for stage, value in [('script', {'scenes':[{'visual_prompt':self.prompt}]}), ('speech', {'utterances':[{'visual_prompt':self.prompt,'duration':8}]})]:
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(self.jid,stage,json.dumps(value)))
        self.services = []

    def tearDown(self):
        for service in self.services:
            for thread in list(service._threads.values()):
                thread.join(2)
        self.tmp.cleanup()

    def service(self, **kwargs):
        from videostudio.flow_account import FlowAccountService
        service = FlowAccountService(self.store, flow_root=self.root/'flow', browser_check=lambda:True,
                                     reconciler=kwargs.pop('reconciler', lambda job, tasks: ''), **kwargs)
        self.services.append(service)
        return service

    def wait(self, service):
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            status = service.status(self.jid)
            if status['phase'] in ('ready','error'):
                return status
            time.sleep(.01)
        self.fail('handoff did not settle')

    def test_new_service_is_idle(self):
        status = self.service().status(self.jid)
        self.assertEqual(status['phase'], 'idle')
        self.assertTrue(status['can_prepare'])

    def test_prepare_pauses_without_cancelling_then_continues_same_job(self):
        service = self.service()
        service.prepare(self.jid)
        status = self.wait(service)
        self.assertEqual(status['phase'], 'ready')
        self.assertEqual(status['missing_count'], 1)
        self.assertEqual(self.store.get(self.jid)['state'], 'awaiting_flow_account')
        self.assertFalse(self.store.get(self.jid)['cancel'])
        self.assertTrue(service.blocks_workers())
        self.assertFalse(service.blocks_browser_changes())
        service.continue_job(self.jid)
        self.assertEqual(self.store.get(self.jid)['state'], 'queued')
        self.assertEqual(len(self.store.list()), 1)
        uuid.UUID(service.active_run(self.jid))
        self.assertFalse(service.blocks_workers())

    def test_running_prepare_waits_for_cooperative_pause(self):
        service = self.service()
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='running' WHERE id=?",(self.jid,))
        service.prepare(self.jid)
        self.assertTrue(service.pause_requested(self.jid))
        self.assertTrue(service.blocks_browser_changes())
        self.assertEqual(self.store.get(self.jid)['state'],'running')
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='awaiting_flow_account' WHERE id=?",(self.jid,))
        self.assertEqual(self.wait(service)['phase'], 'ready')

    def test_preserves_attested_output_and_original_receipt(self):
        service = self.service()
        output = Path(self.job['output'])/'images-0000.png'
        image = Image.new('RGB',(512,512),'blue')
        image.putpixel((0,0),(255,0,0));image.save(output)
        sha = hashlib.sha256(output.read_bytes()).hexdigest()
        cp = {'provider':'flow','prompt':self.prompt,'sha256':sha,'character_mentions':[], 'media_id':'media','project_url':'https://flow.google.com/project/old'}
        output.with_suffix('.checkpoint.json').write_text(json.dumps(cp))
        service.prepare(self.jid)
        self.assertEqual(self.wait(service)['cached_count'], 1)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),sha)

    def test_corrupt_attested_image_fails_without_overwriting(self):
        service = self.service()
        output = Path(self.job['output'])/'images-0000.png'
        output.write_bytes(b'corrupt')
        output.with_suffix('.checkpoint.json').write_text(json.dumps({'provider':'flow','prompt':self.prompt,'sha256':'wrong','character_mentions':[]}))
        service.prepare(self.jid)
        self.assertEqual(self.wait(service)['phase'],'error')
        self.assertEqual(output.read_bytes(),b'corrupt')

    def test_continue_requires_debug_browser_and_ready(self):
        service = self.service()
        with self.assertRaises(ValueError):service.continue_job(self.jid)
        service.prepare(self.jid);self.wait(service)
        service.browser_check = lambda:False
        with self.assertRaisesRegex(ValueError,'debug'):service.continue_job(self.jid)
        self.assertEqual(self.store.get(self.jid)['state'],'awaiting_flow_account')

    def test_cancelled_and_wrong_stage_cannot_prepare(self):
        service = self.service()
        with self.store.db() as c:c.execute("UPDATE jobs SET cancel=1 WHERE id=?",(self.jid,))
        with self.assertRaises(ValueError):service.prepare(self.jid)
        with self.store.db() as c:c.execute("UPDATE jobs SET cancel=0,stage='speech' WHERE id=?",(self.jid,))
        with self.assertRaises(ValueError):service.prepare(self.jid)

    def test_restarted_service_does_not_mutate_until_explicit_recovery(self):
        service = self.service()
        with self.store.db() as c:
            c.execute('INSERT INTO flow_account_changes VALUES(?,?,?,?)',(self.jid,'reconciling','{}',time.time()))
        another = self.service()
        self.assertEqual(another.status(self.jid)['phase'],'reconciling')
        another.recover_after_restart()
        self.assertEqual(another.status(self.jid)['phase'],'error')
        self.assertFalse(another.blocks_workers())

    def test_missing_old_account_keeps_valid_cache_and_allows_explicit_continue(self):
        def unavailable(job,tasks):
            raise ConnectionError('old Flow project unavailable')
        service = self.service(reconciler=unavailable)
        service.prepare(self.jid)
        status = self.wait(service)
        self.assertEqual(status['phase'],'ready')
        self.assertIn('old Flow project unavailable',status['message'])
        self.assertTrue(status['can_continue'])

    def receipt_image(self, service, **updates):
        task_id=str(uuid.uuid5(uuid.UUID(self.jid),'bulk-scene-image:0'))
        service.flow_root.mkdir(parents=True,exist_ok=True)
        image=Image.new('RGB',(512,512),'blue');image.putpixel((0,0),(255,0,0))
        image.save(service.flow_root/(task_id+'.png'))
        receipt={'task_id':task_id,'job_id':self.jid,'stage':'downloaded','character_mentions':[],
                 'prompt_sha256':hashlib.sha256(self.prompt.encode()).hexdigest(),
                 'download_sha256':hashlib.sha256((service.flow_root/(task_id+'.png')).read_bytes()).hexdigest(),
                 'media_id':'old-media','project_url':'https://flow.google.com/project/old',**updates}
        path=service.flow_root/'tasks'/(task_id+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(receipt))
        return path

    def test_cached_receipt_is_copied_to_output_without_rewriting_history(self):
        service=self.service();path=self.receipt_image(service);before=path.read_bytes()
        service.prepare(self.jid)
        self.assertEqual(self.wait(service)['cached_count'],1)
        self.assertEqual(path.read_bytes(),before)
        checkpoint=json.loads((Path(self.job['output'])/'images-0000.checkpoint.json').read_text())
        self.assertEqual(checkpoint['prompt'],self.prompt)
        self.assertEqual(checkpoint['media_id'],'old-media')

    def test_conditioning_hash_mismatch_rejected_even_when_png_is_valid(self):
        service=self.service();self.receipt_image(service,conditioning_sha256='wrong')
        service.prepare(self.jid)
        self.assertEqual(self.wait(service)['phase'],'error')
        self.assertFalse((Path(self.job['output'])/'images-0000.png').exists())

    def test_cancel_while_reconciling_never_returns_ready_or_queues_job(self):
        import threading
        started=threading.Event();release=threading.Event()
        def reconcile(job,tasks):
            started.set();release.wait(2)
        service=self.service(reconciler=reconcile);service.prepare(self.jid)
        self.assertTrue(started.wait(2))
        self.store.cancel(self.jid);release.set()
        self.assertEqual(self.wait(service)['phase'],'error')
        self.assertFalse(service.status(self.jid)['can_continue'])
        with self.assertRaises(ValueError):service.continue_job(self.jid)

    def test_prepare_is_idempotent_and_continuation_allocates_one_namespace(self):
        service=self.service();service.prepare(self.jid);self.wait(service)
        service.prepare(self.jid)
        service.continue_job(self.jid);run=service.active_run(self.jid)
        service.continue_job(self.jid)
        self.assertEqual(service.active_run(self.jid),run)

    def test_other_running_video_prevents_account_handoff(self):
        service=self.service()
        other,_=self.store.create({'idea':'other','voice_id':'voice','duration_seconds':8},str(uuid.uuid4()))
        with self.store.db() as c:c.execute("UPDATE jobs SET state='running' WHERE id=?",(other['id'],))
        with self.assertRaisesRegex(ValueError,'video khác'):service.prepare(self.jid)

    def test_full_prompt_matching_rejects_duplicate_assets_and_scene_fingerprints(self):
        service=self.service()
        from videostudio.cdp_flow import FlowImages
        task={'index':0,'prompt':self.prompt,'character_mentions':[]}
        fingerprint=FlowImages._batch_prompt_fingerprint(self.prompt,[])
        self.assertEqual(service._unambiguous_matches([task],{fingerprint:['media']}),[(task,'media')])
        self.assertEqual(service._unambiguous_matches([task],{fingerprint:['media','other']}),[])
        self.assertEqual(service._unambiguous_matches([task,{**task,'index':1}],{fingerprint:['media']}),[])
        self.assertEqual(service._unambiguous_matches([task],{FlowImages._batch_prompt_fingerprint(self.prompt+' extra',[]):['media']}),[])

    def test_native_entity_ids_are_required_for_matching(self):
        service=self.service()
        from videostudio.cdp_flow import FlowImages
        entity=str(uuid.uuid4())
        task={'prompt':self.prompt,'character_mentions':[{'name':'Hero','character_id':entity}]}
        full='Hero '+self.prompt
        self.assertEqual(service._unambiguous_matches([task],{FlowImages._batch_prompt_fingerprint(full,[]):['media']}),[])
        self.assertEqual(service._unambiguous_matches([task],{FlowImages._batch_prompt_fingerprint(full,[entity]):['media']}),[(task,'media')])

    def test_continue_tab_selection_rejects_multiple_tabs_without_closing_any(self):
        service=self.service()
        tab={'type':'page','url':'https://flow.google.com/','targetId':'one'}
        self.assertEqual(service._select_continue_tab([tab]),tab)
        with self.assertRaisesRegex(ValueError,'một tab'):service._select_continue_tab([tab,{**tab,'targetId':'two'}])
        with self.assertRaisesRegex(ValueError,'Mở'):service._select_continue_tab([])

    def test_second_handoff_pins_the_active_run_project(self):
        service=self.service();run=str(uuid.uuid4())
        with self.store.db() as c:c.execute('INSERT OR REPLACE INTO flow_account_changes VALUES(?,?,?,?)',(self.jid,'running',json.dumps({'active_run':run}),time.time()))
        projects=service.flow_root/'projects';projects.mkdir(parents=True)
        (projects/(self.jid+'.json')).write_text(json.dumps({'project_url':'https://flow.google.com/project/old'}))
        (projects/(run+'.json')).write_text(json.dumps({'project_url':'https://flow.google.com/project/current'}))
        tasks=[{'receipts':[{'job_id':self.jid,'project_url':'https://flow.google.com/project/old'},{'job_id':run,'project_url':'https://flow.google.com/project/current'}]}]
        self.assertEqual(service._reconciliation_projects(self.store.get(self.jid),tasks),{'https://flow.google.com/project/current'})

    def test_cdp_reconcile_scans_once_downloads_existing_at_1k_without_history_changes(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from videostudio.cdp_flow import FlowImages
        service=self.service();receipt_path=self.receipt_image(service,stage='waiting_result')
        original=receipt_path.read_bytes()
        receipt=json.loads(original);(service.flow_root/(receipt['task_id']+'.png')).unlink()
        with self.store.db() as c:c.execute("UPDATE jobs SET state='awaiting_flow_account' WHERE id=?",(self.jid,))
        job=self.store.get(self.jid);tasks=service._scene_tasks(job);events=[]
        fingerprint=FlowImages._batch_prompt_fingerprint

        class FakeCDP:
            async def connect(self,endpoint):events.append('connect')
            async def command(self,name,*args,**kwargs):
                if name=='Browser.getBrowserCommandLine':return {'arguments':['--user-data-dir='+str(service.flow_root.resolve())]}
                if name=='Target.getTargets':return {'targetInfos':[{'type':'page','url':'https://flow.google.com/project/old','targetId':'target'}]}
                raise AssertionError('Unexpected CDP command '+name)
            async def close(self):events.append('close')

        class FakeBridge:
            def __init__(self,**kwargs):self.cdp=FakeCDP()
            async def session(self,target):return 'session'

        class FakeLauncher:
            def __init__(self):self.config=SimpleNamespace(profile=service.flow_root)
            def discover(self):return 'ws://127.0.0.1/fake'

        class FakeFlow:
            _batch_prompt_fingerprint=staticmethod(fingerprint)
            def __init__(self,bridge,root):self.root=root
            async def _snapshot(self,*args):return {'composerAvailable':True,'draftEmpty':True}
            async def _scan_grid_tiles(self,*args):events.append('scan');return [{'media_id':'saved-existing'}]
            async def _read_detail_prompt_for_media(self,*args):return {'prompt':service.store.get(job['id'])['checkpoints']['speech']['utterances'][0]['visual_prompt'],'mention_entity_ids':[]}
            def _write_receipt(self,task,value):
                self.root.joinpath('tasks',task+'.json').write_text(json.dumps(value))
            async def _download_2k(self,task,target,session,value,prompt,media_id):
                self.assert_original=task!=receipt['task_id']
                if not self.assert_original:raise AssertionError('Original task was rewritten')
                if value['download_resolution_requested']!='1K':raise AssertionError('Wrong download size')
                events.append('download:'+media_id)
                path=self.root/(task+'.png');Image.new('RGB',(512,512),'green').save(path)
                value.update(stage='downloaded',download_path=str(path),download_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                self._write_receipt(task,value);return value

        with patch('videostudio.cdp_daemon.ChromeChatGPTBridge',FakeBridge),patch('videostudio.chrome_browser.DedicatedChrome',FakeLauncher),patch('videostudio.cdp_flow.FlowImages',FakeFlow):
            coroutine=service._reconcile_browser_async(job,tasks)
            try:coroutine.send(None)
            except StopIteration as result:self.assertIn('1',result.value)
            else:self.fail('Offline CDP fixture unexpectedly yielded')
        self.assertEqual(events.count('scan'),1)
        self.assertIn('download:saved-existing',events)
        self.assertEqual(receipt_path.read_bytes(),original)
        self.assertTrue((Path(job['output'])/'images-0000.checkpoint.json').is_file())


if __name__ == '__main__':unittest.main()
