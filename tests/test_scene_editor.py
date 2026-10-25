import copy,importlib,importlib.util,io,json,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from fastapi.testclient import TestClient
from videostudio.core import Store,Worker,STAGES,validate_request,digest
from videostudio.media import asset
REQ={'idea':'A short scene test','voice_id':'fixture','duration_seconds':8}

def picture(color='red'):
    b=io.BytesIO();Image.new('RGB',(80,100),color).save(b,format='PNG');return b.getvalue()

def ready_job(root,mode='quick',state='completed'):
    s=Store(Path(root)/'jobs.db',Path(root)/'out');data=dict(REQ,quality_mode=mode)
    # Current baseline does not support quality_mode: use old request for fixture allocation.
    j,_=s.create(REQ,'source');p=Path(j['output']);cps={}
    for stage in ('plan','research','script'):cps[stage]={'assets':[]}
    speech=p/'speech.wav'
    with wave.open(str(speech),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\x00\x01'*112000)
    subs=p/'subtitles.ass';subs.write_text('subtitle fixture',encoding='utf8')
    music=p/'music.wav';music.write_bytes(speech.read_bytes())
    utterances=[];imgs=[];assets=[]
    for i in range(2):
        img=p/f'images-{i:04}.png';img.write_bytes(picture('red' if i==0 else 'blue'));assets.append(asset(img))
        utterances.append({'narration':f'cau {i}','visual_prompt':'scene','path':str(speech),'start':i*3.5,'end':(i+1)*3.5,'duration':3.5})
        imgs.append({'path':str(img),'duration':3.5 if i==0 else 4.5})
    cps['speech']={'path':str(speech),'duration_seconds':7,'utterances':utterances,'assets':[asset(speech)]}
    cps['images']={'scenes':imgs,'assets':assets};cps['subtitles']={'path':str(subs),'assets':[asset(subs)]};cps['music']={'path':str(music),'assets':[asset(music)]}
    original=p/'video.mp4';original.write_bytes(b'original-mp4-fixture')
    if state=='completed':cps.update(render={'video':str(original),'assets':[asset(original)]},verify={'verified':True})
    with s.db() as c:
        for stage,cp in cps.items():c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],stage,json.dumps(cp)))
        c.execute('UPDATE jobs SET state=?,stage=?,request=? WHERE id=?',(state,'verify' if state=='completed' else 'render',json.dumps(data),j['id']))
    return s,s.get(j['id'])

class ModeTests(unittest.TestCase):
    def test_modes_are_validated_and_default_quick_is_compatible(self):
        self.assertEqual(validate_request(dict(REQ,quality_mode='quick'))['quality_mode'],'quick')
        self.assertEqual(validate_request(dict(REQ,quality_mode='careful'))['quality_mode'],'careful')
        for mode in ('required','foo',True,None):
            with self.assertRaises(ValueError):validate_request(dict(REQ,quality_mode=mode))
    def test_explicit_quick_does_not_require_unavailable_vlm(self):
        from videostudio.visual_quality import gate_mode
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required'}):
            self.assertEqual(gate_mode({'output':t,'request':{'quality_mode':'quick'},'checkpoints':{}}),'legacy')

class EditorTests(unittest.TestCase):
    def editor(self,s):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.scene_editor'),'Scene editor implementation missing')
        return importlib.import_module('videostudio.scene_editor').SceneEditor(s)
    def test_mode_switch_preserves_edit_and_timeline(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);e=self.editor(s);before=copy.deepcopy(j['checkpoints']);v=e.view(j['id'])
            a=e.replace(j['id'],v['scenes'][0]['scene_id'],picture('green'),'contain',v['version']);b=e.set_mode(j['id'],'careful',a['version']);c=e.set_mode(j['id'],'quick',b['version'])
            self.assertEqual(c['scenes'][0]['image_sha256'],a['scenes'][0]['image_sha256']);self.assertEqual(before,s.get(j['id'])['checkpoints'])
            self.assertEqual(c['scenes'][0]['duration'],v['scenes'][0]['duration'])
    def test_export_snapshot_reuses_audio_and_only_changes_image(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);e=self.editor(s);v=e.view(j['id']);a=e.replace(j['id'],v['scenes'][0]['scene_id'],picture('green'),'cover',v['version'])
            child=e.export(j['id'],a['version'],'export-key',False)
            self.assertEqual(set(child['checkpoints']),set(STAGES)-{'render','verify'})
            self.assertEqual(child['checkpoints']['images']['reuse_audio']['sha256'],digest(Path(j['output'])/'video.mp4'))
            for stage in ('speech','music','subtitles'):self.assertEqual(child['checkpoints'][stage],j['checkpoints'][stage])
            self.assertEqual(child['checkpoints']['images']['scenes'][1]['path'],j['checkpoints']['images']['scenes'][1]['path'])
            self.assertNotEqual(child['checkpoints']['images']['scenes'][0]['path'],j['checkpoints']['images']['scenes'][0]['path'])
            frozen=child['checkpoints']['images']['scenes'][0]['path'];e.replace(j['id'],v['scenes'][0]['scene_id'],picture('yellow'),'cover',a['version'])
            self.assertEqual(s.get(child['id'])['checkpoints']['images']['scenes'][0]['path'],frozen)
            self.assertEqual((Path(j['output'])/'video.mp4').read_bytes(),b'original-mp4-fixture')
    def test_stale_write_and_export_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);e=self.editor(s);v=e.view(j['id']);e.set_mode(j['id'],'careful',v['version'])
            with self.assertRaises(ValueError):e.replace(j['id'],v['scenes'][0]['scene_id'],picture(),'cover',v['version'])
            with self.assertRaises(ValueError):e.export(j['id'],v['version'],'stale',False)
    def test_restore_original_and_approval_are_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t,'careful');e=self.editor(s);v=e.view(j['id']);sid=v['scenes'][0]['scene_id']
            a=e.replace(j['id'],sid,picture('green'),'cover',v['version'])
            with self.assertRaises(ValueError):e.approve(j['id'],sid,v['scenes'][0]['image_sha256'],a['version'])
            approved=e.approve(j['id'],sid,a['scenes'][0]['image_sha256'],a['version'])
            self.assertEqual(approved['scenes'][0]['review_status'],'user_approved')
            restored=e.restore(j['id'],sid,'original',approved['version']);self.assertEqual(restored['scenes'][0]['image_sha256'],v['scenes'][0]['image_sha256']);self.assertEqual(restored['scenes'][0]['review_status'],'needs_review')
    def test_careful_requires_approval_but_bulk_user_confirmation_works(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t,'careful');e=self.editor(s);v=e.view(j['id'])
            with self.assertRaises(ValueError):e.export(j['id'],v['version'],'blocked',False)
            child=e.export(j['id'],v['version'],'approved',True)
            self.assertEqual(child['checkpoints']['images']['visual_qa_status'],'user_approved');self.assertNotIn('verify',child['checkpoints'])
            self.assertEqual(e.export(j['id'],v['version'],'approved',True)['id'],child['id'])
    def test_invalid_upload_rejected_without_new_revision(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);e=self.editor(s);v=e.view(j['id']);sid=v['scenes'][0]['scene_id']
            for data in (b'<svg/>',b'not image',b''):
                with self.assertRaises(ValueError):e.replace(j['id'],sid,data,'cover',v['version'])
            with self.assertRaises(ValueError):e.replace(j['id'],sid,picture(),'stretch',v['version'])
            self.assertEqual(e.view(j['id'])['version'],v['version'])
    def test_waiting_releases_worker_and_does_not_consume_retry(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t,'careful',state='queued');e=self.editor(s)
            handlers={'render':lambda job,check:e.require_user_review(job)}
            w=Worker(s,handlers);self.assertTrue(w.step());a=s.get(j['id']);self.assertEqual(a['state'],'awaiting_visual_review');self.assertEqual(a['attempts'].get('render',0),0);self.assertFalse(w.step());self.assertTrue(s.lock('another'));s.release('another')

    def test_foreign_edit_id_and_excess_pixels_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t);e=self.editor(s);v=e.view(j['id']);sid=v['scenes'][0]['scene_id'];v=e.replace(j['id'],sid,picture('green'),'contain',v['version']);edit=v['scenes'][0]['edit_id']
            with self.assertRaises(ValueError):e.image_file(j['id'],v['scenes'][1]['scene_id'],edit)
            with self.assertRaises(ValueError):e.image_file(j['id'],sid,'../../secret')
            large=io.BytesIO();Image.new('RGB',(8193,32)).save(large,format='PNG')
            with self.assertRaises(ValueError):e.replace(j['id'],sid,large.getvalue(),'cover',v['version'])
    def test_waiting_persists_after_restart_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t,'careful',state='awaiting_visual_review');e=self.editor(s);v=e.view(j['id']);s2=Store(s.path,s.outputs);e2=self.editor(s2)
            self.assertEqual(e2.view(j['id'])['mode'],'careful');self.assertFalse(Worker(s2,{}).step())
            self.assertEqual(s2.cancel(j['id'])['state'],'cancelled')

class EditorAPITests(unittest.TestCase):
    def test_origin_and_binary_upload(self):
        from videostudio.api import create_app
        class FakePipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as t:
            s,j=ready_job(t)
            with TestClient(create_app(s,FakePipeline(),False)) as c:
                base='/api/jobs/'+j['id']+'/scene-editor';r=c.get(base);self.assertEqual(r.status_code,200);v=r.json();sid=v['scenes'][0]['scene_id']
                endpoint=base+'/scenes/'+sid+'/image?fit=contain&version='+str(v['version'])
                self.assertEqual(c.post(endpoint,content=picture(),headers={'Origin':'https://evil.invalid','Content-Type':'image/png'}).status_code,403)
                upload=c.post(endpoint,content=picture('green'),headers={'Content-Type':'image/png'});self.assertEqual(upload.status_code,200)
                self.assertEqual(c.get(upload.json()['scenes'][0]['image_url']).status_code,200)
                self.assertEqual(c.post(endpoint,content=b'<svg/>').status_code,422)
if __name__=='__main__':unittest.main()
