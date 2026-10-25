import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
import httpx
from test_scene_editor import ready_job,picture
from videostudio.providers import Pipeline,image_graph
from videostudio.scene_images import SceneImageJobs,ImageTaskIssue
from videostudio.core import digest

class ComfyAssetTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.out=self.root/'isolated-task';self.out.mkdir()
        self.task_id=str(uuid.uuid4());self.path=self.root/(self.task_id+'.png');self.graph=image_graph('a medieval practice-yard scene',456,'videostudio/scene-candidates/'+self.task_id)
        self.png=picture('green');self.calls=[]
        self.pipeline=Pipeline(SimpleNamespace(root=self.root));self.pipeline.comfy='http://127.0.0.1:8188';self.pipeline.gpu_ownership=self.root/'gpu.json'
        self.transport=httpx.MockTransport(self.handle);self.real_client=httpx.Client
    def tearDown(self):self.temp.cleanup()
    def handle(self,req):
        self.calls.append((req.method,req.url.path))
        if req.method=='GET' and req.url.path=='/queue':return httpx.Response(200,json={'queue_running':[],'queue_pending':[]})
        if req.method=='GET' and req.url.path=='/system_stats':return httpx.Response(200,json={'devices':[{'vram_free':16*1024**3,'torch_vram_total':0}]})
        if req.method=='POST' and req.url.path=='/prompt':return httpx.Response(200,json={'prompt_id':'prompt-'+self.task_id})
        if req.method=='GET' and req.url.path=='/history/prompt-'+self.task_id:
            return httpx.Response(200,json={'prompt-'+self.task_id:{'status':{'status_str':'success'},'outputs':{'8':{'images':[{'type':'output','subfolder':'videostudio/scene-candidates','filename':self.task_id+'_00001.png'}]}}}})
        if req.method=='GET' and req.url.path=='/view':return httpx.Response(200,content=self.png,headers={'Content-Type':'image/png'})
        return httpx.Response(500,json={'unexpected':req.method+' '+req.url.path})
    def client_patch(self):return patch('videostudio.providers.httpx.Client',side_effect=lambda **kw:self.real_client(base_url=kw.get('base_url'),timeout=kw.get('timeout'),transport=self.transport))
    def call(self,check=lambda:None):return self.pipeline.comfy_asset({'id':self.task_id,'output':str(self.out)},'images-scene-'+self.task_id,self.graph,self.path,check,strict_resume=True)
    def test_fresh_prompt_history_view_receipt_and_resume_without_duplicate_post(self):
        with self.client_patch(),patch('videostudio.gpu.headroom',return_value=(16*1024**3,False)),patch('videostudio.gpu.record_owned'),patch('videostudio.gpu.free_comfy') as free:
            value=self.call()
            self.assertEqual(value['prompt_id'],'prompt-'+self.task_id);self.assertEqual(Path(value['path']).read_bytes(),self.png)
            receipt=self.out/('images-scene-'+self.task_id+'-receipt.json');self.assertEqual(json.loads(receipt.read_text())['prompt_id'],value['prompt_id'])
            post_count=sum(1 for m,p in self.calls if m=='POST' and p=='/prompt');self.assertEqual(post_count,1)
            self.assertNotIn(('POST','/free'),self.calls);self.assertNotIn(('POST','/interrupt'),self.calls);free.assert_not_called()
            before=len(self.calls);again=self.call();self.assertEqual(again['prompt_id'],value['prompt_id']);self.assertEqual(len(self.calls),before)
    def test_busy_shared_queue_never_submits_or_changes_queue(self):
        def busy(req):
            self.calls.append((req.method,req.url.path))
            if req.url.path=='/queue':return httpx.Response(200,json={'queue_running':[[1,'foreign-pid']], 'queue_pending':[]})
            return httpx.Response(500)
        transport=httpx.MockTransport(busy)
        with patch('videostudio.providers.httpx.Client',side_effect=lambda **kw:self.real_client(base_url=kw.get('base_url'),timeout=kw.get('timeout'),transport=transport)),patch('videostudio.gpu.headroom') as head:
            with self.assertRaisesRegex(RuntimeError,'busy with other work'):self.call()
            head.assert_not_called();self.assertNotIn(('POST','/prompt'),self.calls);self.assertFalse((self.out/('images-scene-'+self.task_id+'-receipt.json')).exists())
    def test_unknown_receipts_never_resubmit(self):
        kind='images-scene-'+self.task_id;receipt=self.out/(kind+'-receipt.json')
        for body in ({'state':'submitting'},{'prompt_id':'old-pid'}):
            self.calls.clear();receipt.write_text(json.dumps(body));self.path.unlink(missing_ok=True)
            def reconcile(req):
                self.calls.append((req.method,req.url.path))
                if req.url.path=='/history/old-pid':return httpx.Response(200,json={})
                if req.url.path=='/queue':return httpx.Response(200,json={'queue_running':[],'queue_pending':[]})
                return httpx.Response(500)
            transport=httpx.MockTransport(reconcile)
            with patch('videostudio.providers.httpx.Client',side_effect=lambda **kw:self.real_client(base_url=kw.get('base_url'),timeout=kw.get('timeout'),transport=transport)):
                with self.assertRaises(Exception):self.call()
            self.assertNotIn(('POST','/prompt'),self.calls)
    def test_cancel_check_stops_polling_without_shared_interrupt(self):
        checks=0
        def check():
            nonlocal checks
            checks+=1
            if checks>1:raise RuntimeError('cancelled locally')
        with self.client_patch(),patch('videostudio.gpu.headroom',return_value=(16*1024**3,False)),patch('videostudio.gpu.record_owned'):
            with self.assertRaisesRegex(RuntimeError,'cancelled locally'):self.call(check)
        self.assertEqual(sum(1 for m,p in self.calls if m=='POST' and p=='/prompt'),1)
        self.assertNotIn(('POST','/interrupt'),self.calls);self.assertNotIn(('POST','/free'),self.calls)

class ComfySceneQueueTests(unittest.TestCase):
    def test_comfy_candidate_uses_existing_task_and_apply_is_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            store,j=ready_job(t);q=SceneImageJobs(store);view=q.editor.view(j['id']);sid=view['scenes'][0]['scene_id'];task=q.start(j['id'],sid,'Qwen scene','comfy','comfy-key',view['version'])
            def runner(tk):
                p=q.download_root/(tk['id']+'.png');p.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(768,1376),'green').save(p)
                return {'task_id':tk['id'],'file_path':str(p),'sha256':digest(p),'request_id':'comfy-prompt','width':768,'height':1376,'source':'comfy_qwen_image_2_1'}
            q.runner=Mock(side_effect=runner);self.assertTrue(q.step('mock-worker'));candidate=q.get(task['id'])
            self.assertEqual(candidate['state'],'completed');self.assertEqual(q.editor.view(j['id'])['scenes'][0]['edit_id'],'original')
            after=q.apply(j['id'],sid,task['id'],view['version'],'cover');self.assertEqual(after['scenes'][0]['edit_id'],q.get(task['id'])['applied_edit_id']);self.assertEqual(q.get(task['id'])['state'],'applied')
