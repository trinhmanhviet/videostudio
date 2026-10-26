import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from videostudio.core import PermanentError, digest
from videostudio.providers import Pipeline


class InitialImageProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job_id=str(uuid.uuid4());self.output=self.root/'job';self.output.mkdir()
        self.job={'id':self.job_id,'output':str(self.output),'request':{'duration_seconds':8},'checkpoints':{'speech':{'duration_seconds':6,'utterances':[
            {'scene_id':'scene-0','visual_prompt':'prompt zero','duration':2},
            {'scene_id':'scene-1','visual_prompt':'prompt one','duration':2},
            {'scene_id':'scene-2','visual_prompt':'prompt two','duration':2},
        ]}}}
        self.pipeline=Pipeline.__new__(Pipeline);self.pipeline.comfy='http://127.0.0.1:8188';self.pipeline.store=None
        def fake_comfy(job,kind,graph,path,check):
            Path(path).parent.mkdir(parents=True,exist_ok=True);Image.effect_noise((768,1376),80).convert('RGB').save(path,format='PNG');check()
            return {'path':str(path),'prompt_id':'fixture-'+kind,'assets':[]}
        self.pipeline.comfy_asset=Mock(side_effect=fake_comfy)
    def tearDown(self):self.tmp.cleanup()

    def _remote_fixture(self,provider):
        calls=[]
        def post(url,*,json,headers,timeout,trust_env):
            self.assertFalse(trust_env)
            self.assertEqual(headers['X-VS-Client'],'videostudio')
            calls.append((url,json))
            task_id=json['task_id'];source_root=self.root/'data'/(('flow-images' if provider=='flow' else 'chatgpt-images'))
            source=source_root/(task_id+'.png');source.parent.mkdir(parents=True,exist_ok=True)
            Image.effect_noise((768,1376),80).convert('RGB').save(source,format='PNG')
            data={'task_id':task_id,'file_path':str(source),'sha256':digest(source),'request_id':provider+'-'+task_id,'width':768,'height':1376,'source':provider}
            if provider=='flow':
                self.assertEqual(json['job_id'],self.job_id)
                data.update(media_id=str(uuid.uuid5(uuid.UUID(task_id),'media')),project_url='https://flow.google.com/project/12345678-1234-1234-1234-123456789abc')
            return httpx.Response(200,json={'ok':True,'data':data})
        return calls,post

    def test_flow_routes_each_scene_serially_with_stable_task_ids_and_checkpoints(self):
        self.job['request']['image_provider']='flow';calls,post=self._remote_fixture('flow')
        with patch('videostudio.providers.ROOT',self.root,create=True),patch('videostudio.providers.httpx.post',side_effect=post),patch('videostudio.visual_quality.gate_mode',return_value='legacy'):
            result=self.pipeline.images(self.job,lambda:None)
            self.assertEqual(len(result['scenes']),3)
            for index,(url,body) in enumerate(calls):
                self.assertTrue(url.endswith('/api/flow/images/generate'))
                expected=str(uuid.uuid5(uuid.UUID(self.job_id),f'bulk-scene-image:{index}'))
                self.assertEqual(body['task_id'],expected);self.assertEqual(body['prompt'],f'prompt {('zero','one','two')[index]}')
                checkpoint=self.output/f'images-{index:04}.checkpoint.json'
                self.assertTrue(checkpoint.is_file())
            self.pipeline.images(self.job,lambda:None)
            self.assertEqual(len(calls),3,'verified per-scene checkpoints must prevent duplicate Flow submissions')

    def test_chatgpt_routes_each_scene_through_existing_browser_endpoint(self):
        self.job['request']['image_provider']='chatgpt';calls,post=self._remote_fixture('chatgpt')
        with patch('videostudio.providers.ROOT',self.root,create=True),patch('videostudio.providers.httpx.post',side_effect=post),patch('videostudio.visual_quality.gate_mode',return_value='legacy'):
            result=self.pipeline.images(self.job,lambda:None)
        self.assertEqual(len(result['scenes']),3)
        self.assertTrue(all(url.endswith('/api/images/generate') for url,_ in calls))
        self.assertTrue(all('job_id' not in body for _,body in calls))

    def test_comfy_routes_to_existing_qwen_graph_and_legacy_jobs_stay_comfy(self):
        calls=[]
        def comfy(job,kind,graph,path,check):
            calls.append((kind,graph));Image.effect_noise((768,1376),80).convert('RGB').save(path,format='PNG');check()
            return {'path':str(path),'prompt_id':'comfy-'+kind,'assets':[]}
        self.job['request']['image_provider']='comfy';self.pipeline.comfy_asset=Mock(side_effect=comfy)
        with patch('videostudio.visual_quality.gate_mode',return_value='legacy'):
            self.pipeline.images(self.job,lambda:None)
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0][1]['4']['inputs']['prompt'],'prompt zero')
        legacy_output=self.root/'legacy';legacy_output.mkdir()
        legacy={**self.job,'output':str(legacy_output),'request':{'duration_seconds':8}}
        self.pipeline.comfy_asset.reset_mock();self.pipeline.images(legacy,lambda:None)
        self.assertEqual(self.pipeline.comfy_asset.call_count,3)

    def test_required_visual_qa_rejects_noncomfy_provider_before_any_submission(self):
        self.job['request']['image_provider']='flow';self.pipeline.comfy_asset=Mock(side_effect=AssertionError('must not generate'))
        with patch('videostudio.visual_quality.gate_mode',return_value='required'),patch('videostudio.providers.httpx.post') as post:
            with self.assertRaises(PermanentError):self.pipeline.images(self.job,lambda:None)
        self.pipeline.comfy_asset.assert_not_called();post.assert_not_called()


    def _flow_character_script(self):
        phrase='weathered face and gray beard'
        self.job['checkpoints']['script']={'flow_character_manifest_version':1,'characters':[{'character_id':'father','name':'the father','appearance_evidence':[phrase]}],'scenes':[
            {'visual_prompt':'A man with a '+phrase,'character_ids':['father']},
            {'visual_prompt':'A landscape without a character','character_ids':[]},
            {'visual_prompt':'The same man with a '+phrase,'character_ids':['father']},
        ]}
        for index in (0,2):self.job['checkpoints']['speech']['utterances'][index]['character_ids']=['father']

    def test_flow_scene_requests_use_ordered_portrait_media_ids_and_reuse_receipts(self):
        self.job['request']['image_provider']='flow';self._flow_character_script();reference_id=str(uuid.uuid4())
        reference={'media_id':reference_id,'sha256':'a'*64,'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}
        self.pipeline._flow_character_portraits=Mock(return_value=({'father':reference},[]))
        calls,post=self._remote_fixture('flow')
        with patch('videostudio.providers.ROOT',self.root,create=True),patch('videostudio.providers.httpx.post',side_effect=post),patch('videostudio.visual_quality.gate_mode',return_value='legacy'),patch.dict('os.environ',{'VS_FLOW_REFERENCE_UI_VERIFIED':'1'}):
            result=self.pipeline.images(self.job,lambda:None)
            self.assertEqual(result['reference_mode'],'flow_portraits')
            self.assertEqual([body.get('reference_media_ids',[]) for _,body in calls],[[reference_id],[],[reference_id]])
            self.assertEqual(calls[0][1]['reference_identity'],[{'character_id':'father','media_id':reference_id,'sha256':'a'*64,'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}])
            self.assertIn('attached character portrait references',calls[0][1]['prompt'])
            checkpoint=json.loads((self.output/'images-0000.checkpoint.json').read_text(encoding='utf8'))
            self.assertEqual(checkpoint['reference_media_ids'],[reference_id])
            self.pipeline.images(self.job,lambda:None)
        self.assertEqual(len(calls),3,'scene receipts must prevent duplicate Flow generations')

    def test_changed_flow_reference_never_overwrites_existing_scene_image(self):
        self.job['request']['image_provider']='flow';self._flow_character_script();first_id=str(uuid.uuid4())
        reference={'media_id':first_id,'sha256':'a'*64,'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}
        self.pipeline._flow_character_portraits=Mock(return_value=({'father':reference},[]))
        calls,post=self._remote_fixture('flow')
        with patch('videostudio.providers.ROOT',self.root,create=True),patch('videostudio.providers.httpx.post',side_effect=post),patch('videostudio.visual_quality.gate_mode',return_value='legacy'),patch.dict('os.environ',{'VS_FLOW_REFERENCE_UI_VERIFIED':'1'}):
            self.pipeline.images(self.job,lambda:None)
            original=digest(self.output/'images-0000.png')
            second_id=str(uuid.uuid4());changed_reference={'media_id':second_id,'sha256':'b'*64,'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'};self.pipeline._flow_character_portraits=Mock(return_value=({'father':changed_reference},[]))
            with self.assertRaisesRegex(PermanentError,'refusing to overwrite'):
                self.pipeline.images(self.job,lambda:None)
            self.assertEqual(digest(self.output/'images-0000.png'),original)
        self.assertEqual(len(calls),3)

    def test_flow_reference_mode_blocks_before_any_portrait_until_ui_verified(self):
        self.job['request']['image_provider']='flow';self._flow_character_script()
        self.pipeline._flow_character_portraits=Mock(side_effect=AssertionError('portrait must not be submitted'))
        calls,post=self._remote_fixture('flow')
        with patch('videostudio.providers.ROOT',self.root,create=True),patch('videostudio.providers.httpx.post',side_effect=post),patch('videostudio.visual_quality.gate_mode',return_value='legacy'),patch.dict('os.environ',{'VS_FLOW_REFERENCE_UI_VERIFIED':'0'},clear=False):
            with self.assertRaisesRegex(PermanentError,'not live-verified'):
                self.pipeline.images(self.job,lambda:None)
        self.assertEqual(calls,[])
        self.pipeline._flow_character_portraits.assert_not_called()

if __name__=='__main__':
    unittest.main()
