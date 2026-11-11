"""Workflow metadata must survive request revalidation and voice derivation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from videostudio.core import Store, validate_request
from videostudio.workflow import compile_workflow, default_workflow
from videostudio.api import create_app

BASE={'idea':'A fixture story','voice_id':'preset:base','duration_seconds':8}
class ReadyFixture:
    def handlers(self):return {}
    def preflight(self):return {'ready':True,'checks':[]}

class WorkflowRequestIntegrationTests(unittest.TestCase):
    def test_editor_service_uses_the_pipeline_configured_media_executables(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'jobs.db',Path(folder)/'out');pipeline=ReadyFixture()
            pipeline.ffmpeg='C:/custom tools/ffmpeg.exe';pipeline.ffprobe='C:/custom tools/ffprobe.exe'
            app=create_app(store,pipeline,False)
            self.assertEqual(app.state.edit_plan_service.ffmpeg,pipeline.ffmpeg)
            self.assertEqual(app.state.edit_plan_service.ffprobe,pipeline.ffprobe)
    def test_revalidation_preserves_explicit_voice_pitch_and_preset(self):
        graph=default_workflow('science')
        next(n for n in graph['nodes'] if n['type']=='speech')['config']={'voice_id':'preset:old','pitch':4}
        request=compile_workflow(graph,BASE)
        updated=validate_request({**request,'voice_id':'preset:new','pitch':-2,'edit_preset':'everyday'})
        self.assertEqual(updated['voice_id'],'preset:new');self.assertEqual(updated['pitch'],-2)
        self.assertEqual(updated['edit_preset'],'everyday');self.assertEqual(updated['workflow'],graph)
    def test_optional_fields_are_strict_and_old_requests_unchanged(self):
        normal=validate_request(BASE)
        self.assertNotIn('workflow',normal);self.assertNotIn('music_enabled',normal)
        for key in ('references_enabled','captions_enabled','music_enabled','sfx_enabled'):
            self.assertIs(validate_request({**BASE,key:False})[key],False)
            for value in ('false',0,None):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_request({**BASE,key:value})
        for value in ('unknown',None,True):
            with self.assertRaises(ValueError):validate_request({**BASE,'edit_preset':value})
        graph=default_workflow();graph['edges']=[]
        with self.assertRaises(ValueError):validate_request({**BASE,'workflow':graph})
    def test_derived_voice_does_not_recompile_old_speech_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'jobs.db',Path(tmp)/'out');graph=default_workflow()
            next(n for n in graph['nodes'] if n['type']=='speech')['config']={'voice_id':'preset:old','pitch':4}
            parent,_=store.create(compile_workflow(graph,BASE),'parent')
            with store.db() as c:c.execute("UPDATE jobs SET state='completed',stage='verify' WHERE id=?",(parent['id'],))
            child=store.create_derived(parent['id'],'preset:new',pitch=-3)
            self.assertEqual(child['request']['voice_id'],'preset:new');self.assertEqual(child['request']['pitch'],-3)
            self.assertEqual(child['request']['workflow'],parent['request']['workflow'])
    def test_api_registers_services_and_compiles_only_new_submission_boundary(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'VS_STORYFORGE_ROOT':tmp,'VS_LLM_TRANSPORT':'cdp'}):
            store=Store(Path(tmp)/'jobs.db',Path(tmp)/'out');pipeline=ReadyFixture();app=create_app(store,pipeline,False)
            self.assertIs(app.state.edit_plan_service,pipeline.edit_plan_service)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/edit-presets').status_code,200)
                self.assertEqual(client.get('/api/workflows').status_code,200)
                scope=client.post('/api/connector/sessions').json()['project_id']
                route=f'/story-video/projects/{scope}/production'
                self.assertIn('id="create"',client.get(route).text)
                self.assertNotIn('id="workflowWorkspace"',client.get(route).text)
                self.assertIn('id="workflowWorkspace"',client.get(route+'?workspace=editor').text)
                self.assertIn('data-chatgpt-web-action="start"',client.get(route+'?connector_test=true&workspace=editor').text)
                graph=default_workflow('science')
                next(n for n in graph['nodes'] if n['type']=='images')['config']={'provider':'comfy','batch_size':1}
                next(n for n in graph['nodes'] if n['type']=='references')['config']['enabled']=False
                next(n for n in graph['nodes'] if n['type']=='speech')['config']={'voice_id':'preset:node'}
                next(n for n in graph['nodes'] if n['type']=='music')['config']['enabled']=False
                data={**BASE,'workflow':graph}
                response=client.post('/api/jobs',json=data,headers={'Idempotency-Key':'workflow-submit'})
                self.assertEqual(response.status_code,201,response.text);job=response.json()['job']
                self.assertEqual(job['request']['image_provider'],'comfy');self.assertEqual(job['request']['voice_id'],'preset:node')
                self.assertEqual(job['request']['edit_preset'],'science');self.assertFalse(job['request']['music_enabled'])
                replay=client.post('/api/jobs',json=data,headers={'Idempotency-Key':'workflow-submit'})
                self.assertEqual(replay.status_code,201,replay.text);self.assertFalse(replay.json()['created'])
                self.assertEqual(replay.json()['id'],job['id'])
                graph['edges']=[]
                self.assertEqual(client.post('/api/jobs',json={**BASE,'workflow':graph},headers={'Idempotency-Key':'invalid-graph'}).status_code,422)
                self.assertEqual(len(store.list()),1)
if __name__=='__main__':unittest.main()
