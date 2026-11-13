import tempfile, unittest, wave, base64, io, threading
from unittest.mock import patch
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from videostudio.core import Store
from videostudio.voice_studio import VoiceStudio
from videostudio.voice_studio_api import register_voice_studio

OWNER='test-owner-00000001'
class Voices:
    def selected(self, vid):
        if vid!='preset': raise ValueError('Unknown voice')
        return {'id':'preset','name':'Giọng thật','kind':'preset'}
class Pipeline: pass
class VoiceStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'jobs.sqlite3',self.root/'out')
        self.calls=[]
        def render(task,output,check):
            check();self.calls.append(task['request']);output.mkdir(parents=True,exist_ok=True)
            with wave.open(str(output/'audio.wav'),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','NONE'));w.writeframes(b'\x01\x01'*1600)
            (output/'audio.mp3').write_bytes(b'mp3-fixture')
            return {'duration_seconds':.1}
        self.service=VoiceStudio(self.store,Pipeline(),Voices(),render=render)
        self.body={'text':'Một câu thật.','voice_id':'preset','speech_rhythm':'story','speech_speed':1.25}
    def tearDown(self):self.tmp.cleanup()
    def create(self,key='key'):return self.service.create(OWNER,self.body,key)
    def test_idempotency_conflict_and_exact_settings(self):
        a=self.create();self.assertEqual(self.create()['id'],a['id'])
        with self.assertRaises(ValueError):self.service.create(OWNER,{**self.body,'text':'Changed'},'key')
        self.assertTrue(self.service.step('worker'));a=self.service.get(OWNER,a['id'])
        self.assertEqual(a['state'],'completed');self.assertEqual(a['request']['speech_rhythm'],'story')
        self.assertEqual(self.calls[0]['speech_speed'],1.25)
        self.assertTrue(self.service.file(OWNER,a['id'],'wav').is_file())
        with self.assertRaises(KeyError):self.service.file('other-owner-000001',a['id'],'wav')
    def test_video_and_scene_idle_guards_prevent_synthesis(self):
        self.create();self.store.create({'idea':'idea','project':'p','voice_id':'preset','duration_seconds':30},'video')
        self.assertFalse(self.service.step('worker'));self.assertEqual(self.calls,[])
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='completed'")
            db.execute('CREATE TABLE scene_image_tasks(id TEXT,state TEXT)')
            db.execute("INSERT INTO scene_image_tasks VALUES('scene','running')")
        self.assertFalse(self.service.step('worker'));self.assertEqual(self.calls,[])
        with self.store.db() as db:db.execute("UPDATE scene_image_tasks SET state='completed'")
        self.assertTrue(self.service.step('worker'))
    def test_failure_retry_versions_ownership_and_cancel(self):
        a=self.create();original=self.service.render
        def fail(*args):raise RuntimeError('runtime failed')
        self.service.render=fail;self.service.step('worker');a=self.service.get(OWNER,a['id']);self.assertEqual(a['state'],'failed')
        with self.assertRaises(KeyError):self.service.retry('other-owner-000001',a['id'],a['version'])
        a=self.service.retry(OWNER,a['id'],a['version']);self.assertEqual(a['version'],2)
        self.service.render=original;self.service.step('worker');a=self.service.get(OWNER,a['id'])
        a=self.service.update(OWNER,a['id'],{'title':'Tên mới','saved':True},a['version']);self.assertTrue(a['saved'])
        self.service.delete(OWNER,a['id'],a['version']);self.assertEqual(self.service.history(OWNER)['total'],0)
        with self.assertRaises(KeyError):self.service.file(OWNER,a['id'],'wav')
        b=self.create('second');self.service.cancel(OWNER,b['id'],b['version']);self.assertFalse(self.service.step('worker'))
    def test_recover_and_foreign_lease(self):
        a=self.create()
        with self.store.db() as db:db.execute("UPDATE voice_studio_tasks SET state='running' WHERE id=?",(a['id'],))
        self.store.lock('other-worker');self.assertEqual(self.service.recover(),0);self.assertFalse(self.service.step('mine'))
        self.store.release('other-worker');self.assertEqual(self.service.recover(),1);self.assertTrue(self.service.step('mine'))
    def test_unsafe_audio_path_and_invalid_request_rejected(self):
        a=self.create();self.service.step('worker')
        with self.assertRaises(ValueError):self.service.file(OWNER,a['id'],'../../secrets')
        for field,value in [('speech_speed',float('nan')),('speech_engine','fake'),('khanh_steps',17),('speech_rhythm','laugh')]:
            with self.assertRaises(ValueError):self.service.create(OWNER,{**self.body,field:value},'bad')
        with self.assertRaises(ValueError):self.service.create(OWNER,{**self.body,'speech_reference_id':'../../bad'},'bad')
    def test_api_same_origin_ownership_and_versions(self):
        app=FastAPI()
        def same_origin(request):
            if request.headers.get('origin')=='https://evil.test':raise HTTPException(403,'foreign')
        service=register_voice_studio(app,self.store,Pipeline(),Voices(),same_origin);service.render=self.service.render
        with TestClient(app) as client:
            h={'X-Voice-Owner':OWNER,'Idempotency-Key':'api'}
            r=client.post('/api/voice-studio/tasks',json=self.body,headers={**h,'Origin':'https://evil.test'});self.assertEqual(r.status_code,403)
            r=client.post('/api/voice-studio/tasks',json=self.body,headers=h);self.assertEqual(r.status_code,200,r.text);a=r.json()
            self.assertEqual(client.get('/api/voice-studio/tasks/'+a['id'],headers={'X-Voice-Owner':'other-owner-000001'}).status_code,200)
            self.assertEqual(client.patch('/api/voice-studio/tasks/'+a['id'],json={'version':99,'title':'bad'},headers=h).status_code,409)
            service.step('worker')
            url='/api/voice-studio/tasks/'+a['id']+'/audio/wav?owner='
            self.assertEqual(client.get(url+OWNER).status_code,200)
            self.assertEqual(client.get(url+'other-owner-000001').status_code,200)
    def test_uploaded_reference_preserves_transcript_and_is_owner_scoped(self):
        out=io.BytesIO()
        with wave.open(out,'wb') as w:
            w.setparams((1,2,16000,0,'NONE','NONE'));w.writeframes(b'\x00\x01'*16000)
        transcript='  Lời chính xác.\nDòng hai.  '
        ref=self.service.add_reference(OWNER,{'name':'Mẫu kể','transcript':transcript,'audio_base64':base64.b64encode(out.getvalue()).decode()})
        self.assertEqual(ref['transcript'],transcript)
        self.assertTrue(self.service.reference_file(OWNER,ref['id']).is_file())
        with self.assertRaises(KeyError):self.service.reference_file('other-owner-000001',ref['id'])
        request={**self.body,'speech_reference_id':ref['id'],'speech_engine':'khanhtts'}
        task=self.service.create(OWNER,request,'ref-task')
        voice=self.service._voice(OWNER,task['request'])
        self.assertEqual(voice['reference_text'],transcript)
        self.assertNotIn('sha256',self.service.references(OWNER)['items'][0])
        with self.assertRaises(ValueError):self.service.delete_reference(OWNER,ref['id'])
        self.service.cancel(OWNER,task['id'],task['version']);self.service.delete(OWNER,task['id'],task['version'])
        self.service.delete_reference(OWNER,ref['id']);self.assertEqual(self.service.references(OWNER)['items'],[])
    def test_shutdown_is_requeued_but_explicit_cancel_stops_renderer(self):
        task=self.create();self.service.stop_event=threading.Event();self.service.stop_event.set()
        self.service.step('worker');self.assertEqual(self.service.get(OWNER,task['id'])['state'],'queued')
        self.assertEqual(self.calls,[]);self.service.stop_event.clear()
        def cancel(task,output,check):
            self.service.cancel(OWNER,task['id'],task['version']);check()
            self.fail('cancel check failed')
        self.service.render=cancel;self.service.step('worker')
        self.assertEqual(self.service.get(OWNER,task['id'])['state'],'cancelled')
    def test_output_integrity_and_reference_invalid_data(self):
        task=self.create();self.service.step('worker');path=self.service.file(OWNER,task['id'],'wav')
        path.write_bytes(b'corrupt')
        with self.assertRaises(KeyError):self.service.file(OWNER,task['id'],'wav')
        for raw in ['not-base64','YQ==']:
            with self.assertRaises(ValueError):self.service.add_reference(OWNER,{'name':'Mẫu','transcript':'Lời đọc','audio_base64':raw})
    def test_render_uses_shared_units_and_adapter_no_models(self):
        task=self.create();task['owner']=OWNER
        seen=[]
        class Job:
            batch_size=2
            def __enter__(job):return job
            def __exit__(job,*args):pass
            def write_lines(job,texts,paths):
                seen.extend(texts)
                for path in paths:
                    with wave.open(str(path),'wb') as w:
                        w.setparams((1,2,16000,0,'NONE','NONE'));w.writeframes(b'\x01\x01'*1600)
        output=self.root/'render';output.mkdir()
        def run(args,check):
            check();target=Path(args[-1])
            if target.suffix=='.wav':
                with wave.open(str(target),'wb') as w:
                    w.setparams((1,2,16000,0,'NONE','NONE'));w.writeframes(b'\x01\x01'*3200)
            else:target.write_bytes(b'mp3')
        with patch('videostudio.speech_engine.create_speech_job',return_value=Job()) as adapter,patch('videostudio.speech_engine.speech_units',return_value=['Một.','Hai.']),patch('videostudio.media.run',side_effect=run),patch('videostudio.media.audio_report',return_value={'full_decode_ok':True}):
            result=self.service._render(task,output,lambda:None)
        self.assertEqual(seen,['Một.','Hai.']);self.assertAlmostEqual(result['duration_seconds'],.2)
        self.assertEqual(adapter.call_args.args[2]['speech_rhythm'],'story')

if __name__=='__main__':unittest.main()
