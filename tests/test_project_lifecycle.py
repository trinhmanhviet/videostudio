import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.exchanges import Exchanges

REQ={'idea':'Test idea','voice_id':'fixture','duration_seconds':8}

class ProjectLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
  self.store=Store(self.root/'db',self.root/'outputs')
  self.client=TestClient(create_app(self.store,SimpleNamespace(handlers=lambda:{}),False))
  self.ex=Exchanges(self.store); self.bridge=self.ex.scope()
 def tearDown(self):
  self.client.close();self.tmp.cleanup()
 def job(self,project='Test',state='failed',bridge=True):
  j,_=self.store.create(dict(REQ,project=project),str(self.root/str(len(self.store.list()))),self.bridge if bridge else None)
  with self.store.db() as c:c.execute('UPDATE jobs SET state=? WHERE id=?',(state,j['id']))
  return j
 def delete(self,name='Test',files=False,confirm=True):
  return self.client.post('/api/projects/delete',json={'name':name,'delete_files':files,'confirm':confirm})
 def test_archive_search_paging_and_metadata_survive_reopen(self):
  self.job('ĐIỆN ẢNH')
  for n in range(23):self.client.post('/api/projects',json={'name':f'Project {n}'})
  response=self.client.get('/api/projects?page_size=10&page=2').json()
  self.assertEqual(response.get('total'),25);self.assertEqual(len(response['items']),10)
  self.assertEqual(self.client.get('/api/projects?page_size=11').status_code,422)
  self.assertEqual(self.client.get('/api/projects?q=điện').json()['projects'],['ĐIỆN ẢNH'])
  self.assertEqual(self.client.post('/api/projects/archive',json={'name':'ĐIỆN ẢNH','archived':True}).status_code,200)
  self.assertNotIn('ĐIỆN ẢNH',self.client.get('/api/projects').json()['projects'])
  reopened=TestClient(create_app(self.store,SimpleNamespace(handlers=lambda:{}),False))
  self.assertEqual(reopened.get('/api/projects?archived=true&q=điện').json()['projects'],['ĐIỆN ẢNH']);reopened.close()
  self.client.post('/api/projects/archive',json={'name':'ĐIỆN ẢNH','archived':False})
  self.assertIn('ĐIỆN ẢNH',self.client.get('/api/projects').json()['projects'])
 def test_delete_keeps_files_and_audit_and_dismisses_owned_jobs(self):
  j=self.job();target=Path(j['output'])/'keep';target.write_text('fixture')
  response=self.delete();self.assertEqual(response.status_code,200,response.text)
  self.assertTrue(response.json()['files_preserved']);self.assertTrue(target.exists())
  self.assertNotIn('Test',self.client.get('/api/projects').json()['projects'])
  self.assertTrue(self.ex.bridge_job(self.bridge,j['id'])['dismissed']);self.assertEqual(self.store.get(j['id'])['state'],'failed')
  self.assertEqual(self.delete().status_code,200)
  self.assertEqual(self.client.post('/api/projects',json={'name':'Test'}).status_code,409)
 def test_default_project_does_not_resurrect(self):
  self.assertEqual(self.delete('Dự án mặc định').status_code,200)
  self.assertNotIn('Dự án mặc định',self.client.get('/api/projects').json()['projects'])
 def test_reject_active_job_without_changing_files(self):
  j=self.job(state='queued');response=self.delete(files=True)
  self.assertEqual(response.status_code,409);self.assertTrue(Path(j['output']).is_dir())
  self.assertIn('Test',self.client.get('/api/projects').json()['projects'])
 def test_reject_active_scene_image_task(self):
  j=self.job()
  with self.store.db() as c:c.execute("INSERT INTO scene_image_tasks VALUES('t','k',?,'s','p','flow',0,'x','x','running',NULL,NULL,NULL,0,0)",(j['id'],))
  self.assertEqual(self.delete().status_code,409)
 def test_delete_requires_explicit_confirmation_and_origin(self):
  j=self.job()
  self.assertEqual(self.delete(files=True,confirm=False).status_code,422)
  self.assertEqual(self.client.post('/api/projects/delete',json={'name':'Test','confirm':True},headers={'Origin':'https://untrusted.invalid'}).status_code,403)
  self.assertTrue(Path(j['output']).exists())
 def test_delete_files_removes_only_owned_output(self):
  j=self.job();outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('safe')
  result=self.delete(files=True);self.assertEqual(result.status_code,200,result.text)
  self.assertTrue(result.json()['files_deleted']);self.assertFalse(Path(j['output']).exists());self.assertTrue((outside/'keep').exists())
 def test_all_paths_validated_before_deleting_any(self):
  first=self.job();other=self.job(bridge=False)
  with self.store.db() as c:c.execute('UPDATE jobs SET output=? WHERE id=?',(str(self.store.outputs),other['id']))
  response=self.delete(files=True);self.assertEqual(response.status_code,409,response.text)
  self.assertTrue(Path(first['output']).exists());self.assertTrue(self.store.outputs.is_dir())
 def test_external_checkpoint_or_scene_export_blocks_deletion(self):
  j=self.job();other=self.job('Other',bridge=False)
  with self.store.db() as c:c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(other['id'],'speech',json.dumps({'assets':[{'path':str(Path(j['output'])/'audio.wav')}]})))
  response=self.delete(files=True);self.assertEqual(response.status_code,409,response.text);self.assertTrue(Path(j['output']).exists())
  with self.store.db() as c:
   c.execute('DELETE FROM checkpoints');c.execute('INSERT INTO scene_exports VALUES(?,?,0,0,?)',(other['id'],j['id'],'snapshot'))
  self.assertEqual(self.delete(files=True).status_code,409)
 def test_rename_failure_rolls_back_outputs_and_project(self):
  first=self.job();second=self.job(bridge=False)
  original=Path.rename;calls=[]
  def rename(path,target):
   calls.append(path)
   if len(calls)==2:raise OSError('fixture rename failure')
   return original(path,target)
  with patch.object(Path,'rename',rename):result=self.delete(files=True)
  self.assertEqual(result.status_code,409,result.text)
  self.assertTrue(Path(first['output']).exists());self.assertTrue(Path(second['output']).exists())
  self.assertIn('Test',self.client.get('/api/projects').json()['projects'])
 def test_dismiss_optional_delete_body_and_confirmation(self):
  j=self.job();url=f'/api/connector/bridges/{self.bridge}/jobs/{j["id"]}/dismiss'
  result=self.client.post(url);self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json().get('files_preserved'))
  self.assertEqual(self.client.post(url,json={'delete_files':True}).status_code,422)
  result=self.client.post(url,json={'delete_files':True,'confirm':True})
  self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['files_deleted']);self.assertFalse(Path(j['output']).exists())
  self.assertTrue(self.ex.bridge_job(self.bridge,j['id'])['dismissed'])
  smoke=self.ex.enqueue_smoke(self.bridge);self.assertEqual(self.ex.bridge_pending(self.bridge)['items'][0]['id'],smoke)

 def test_deleted_project_blocks_new_jobs_but_preserves_receipt_replay(self):
  j=self.job();self.assertEqual(self.delete().status_code,200)
  replay,created=self.store.create(dict(REQ,project='Test'),str(self.root/'0'),self.bridge)
  self.assertFalse(created);self.assertEqual(replay['id'],j['id'])
  with self.assertRaisesRegex(ValueError,'dự án khác'):
   self.store.create(dict(REQ,project='Test'),'fresh-deleted-project')
  self.assertEqual(self.client.post('/api/projects/archive',json={'name':'Test','archived':False}).status_code,409)
 def test_other_job_output_alias_blocks_without_checkpoints(self):
  j=self.job();other=self.job('Other',bridge=False)
  with self.store.db() as c:c.execute('UPDATE jobs SET output=? WHERE id=?',(j['output'],other['id']))
  self.assertEqual(self.delete(files=True).status_code,409);self.assertTrue(Path(j['output']).exists())
 def test_output_outside_root_and_scene_edit_sharing_are_rejected(self):
  j=self.job();other=self.job('Other',bridge=False);outside=self.root/'outside';outside.mkdir()
  with self.store.db() as c:c.execute('UPDATE jobs SET output=? WHERE id=?',(str(outside),j['id']))
  self.assertEqual(self.delete(files=True).status_code,409);self.assertTrue(outside.exists())
  with self.store.db() as c:
   c.execute('UPDATE jobs SET output=? WHERE id=?',(j['output'],j['id']))
   c.execute('INSERT INTO scene_image_edits VALUES(?,?,?,?,?,?,0)',('edit',other['id'],'scene',str(Path(j['output'])/'shared.png'),'sha','cover'))
  self.assertEqual(self.delete(files=True).status_code,409)
 def test_delete_files_rejects_active_scene_image_dismiss(self):
  j=self.job()
  with self.store.db() as c:c.execute("INSERT INTO scene_image_tasks VALUES('t','k',?,'s','p','flow',0,'x','x','queued',NULL,NULL,NULL,0,0)",(j['id'],))
  url=f'/api/connector/bridges/{self.bridge}/jobs/{j["id"]}/dismiss'
  self.assertEqual(self.client.post(url,json={'delete_files':True,'confirm':True}).status_code,409)
  self.assertFalse(self.ex.bridge_job(self.bridge,j['id'])['dismissed']);self.assertTrue(Path(j['output']).exists())
 def test_quarantine_cleanup_failure_keeps_committed_deletion(self):
  j=self.job()
  with patch('videostudio.project_lifecycle.shutil.rmtree',side_effect=PermissionError('locked fixture')):
   result=self.delete(files=True)
  self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['cleanup_pending'])
  self.assertFalse(Path(j['output']).exists());self.assertEqual(len(list(self.store.outputs.glob('.deleted-*'))),1)
  self.assertNotIn('Test',self.client.get('/api/projects').json()['projects'])

 def test_deleted_project_blocks_retry_resume_and_derived(self):
  j=self.job();self.delete()
  self.assertEqual(self.client.post(f'/api/jobs/{j["id"]}/retry').status_code,409)
  with self.assertRaisesRegex(ValueError,'dự án khác'):self.store.resume(j['id'],self.bridge)
  with self.store.db() as c:c.execute("UPDATE jobs SET state='completed' WHERE id=?",(j['id'],))
  with self.assertRaisesRegex(ValueError,'dự án khác'):self.store.create_derived(j['id'],'other-voice')
 def test_deleted_dismissed_files_block_retry(self):
  j=self.job();url=f'/api/connector/bridges/{self.bridge}/jobs/{j["id"]}/dismiss'
  self.assertEqual(self.client.post(url,json={'delete_files':True,'confirm':True}).status_code,200)
  self.assertEqual(self.client.post(f'/api/jobs/{j["id"]}/retry').status_code,409)
  with self.assertRaisesRegex(ValueError,'tệp đã bị xóa'):self.store.resume(j['id'],self.bridge)

 def test_deleted_project_blocks_editor_export_start_resume_and_comfy_recovery(self):
  from test_scene_editor import ready_job
  from videostudio.scene_editor import SceneEditor
  from videostudio.project_lifecycle import ProjectLifecycle
  store,job=ready_job(self.root/'scene-fixture')
  app=create_app(store,SimpleNamespace(handlers=lambda:{}),False);client=TestClient(app)
  editor=SceneEditor(store);view=editor.view(job['id']);sid=view['scenes'][0]['scene_id'];images=app.state.image_jobs
  task=images.start(job['id'],sid,'scene prompt','comfy','existing-image',view['version'])
  with store.db() as c:c.execute("UPDATE scene_image_tasks SET state='uncertain' WHERE id=?",(task['id'],))
  ProjectLifecycle(store).delete('Dự án mặc định',False)
  before=len(store.list())
  result=client.post(f'/api/jobs/{job["id"]}/scene-editor/export',json={'version':view['version'],'confirm_all':True},headers={'Idempotency-Key':'closed-export'})
  self.assertIn(result.status_code,(409,422),result.text);self.assertEqual(len(store.list()),before)
  for operation in (lambda:editor.set_mode(job['id'],'careful',view['version']),lambda:images.start(job['id'],sid,'fresh prompt','comfy','fresh-image',view['version']),lambda:images.resume(job['id'],sid,task['id'])):
   with self.subTest(operation=operation):
    with self.assertRaisesRegex(ValueError,'dự án khác'):operation()
  with store.db() as c:c.execute("UPDATE scene_image_tasks SET state='failed',error='Unsafe Comfy output' WHERE id=?",(task['id'],))
  with patch.object(images,'_run_comfy',side_effect=AssertionError('must not contact live service')):
   with self.assertRaisesRegex(ValueError,'dự án khác'):images.recover_existing_comfy_result(job['id'],sid,task['id'])
  client.close()

if __name__=='__main__':unittest.main()
