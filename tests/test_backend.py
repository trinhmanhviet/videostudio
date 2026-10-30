import json, tempfile, unittest, wave, math, struct, shutil, subprocess
from pathlib import Path
from unittest.mock import patch
from videostudio.core import Store, Worker, STAGES, PermanentError, validate_request, output_slug
from videostudio.media import render,verify,asset,probe
from videostudio.voices import Voices

REQUEST={'idea':'A real video','voice_id':'preset:test','duration_seconds':8}

class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'jobs.db',self.root/'out')
    def tearDown(self):self.tmp.cleanup()
    def handlers(self,calls):
        def h(stage):
            def f(j,check):check();calls.append(stage);return {'verified':True} if stage=='verify' else {'stage':stage}
            return f
        return {s:h(s) for s in STAGES}
    def test_idempotency_and_collision(self):
        a,new=self.s.create(REQUEST,'key');b,new2=self.s.create(REQUEST,'key');c,_=self.s.create(REQUEST,'other')
        self.assertTrue(new);self.assertFalse(new2);self.assertEqual(a['id'],b['id']);self.assertNotEqual(a['output'],c['output'])
        with self.assertRaises(ValueError):self.s.create(dict(REQUEST,idea='Different'),'key')
    def test_flow_batch_size_validation_and_legacy_idempotency(self):
        self.assertEqual(validate_request(REQUEST)['flow_batch_size'],1)
        for size in (1,10,20,30):
            self.assertEqual(validate_request({**REQUEST,'flow_batch_size':size})['flow_batch_size'],size)
        for size in (True,False,0,2,31,'10',10.0,None):
            with self.subTest(size=size),self.assertRaises(ValueError):
                validate_request({**REQUEST,'flow_batch_size':size})
        with self.assertRaises(ValueError):
            validate_request({**REQUEST,'image_provider':'comfy','flow_batch_size':10})
        first,_=self.s.create(REQUEST,'legacy')
        with self.s.db() as connection:
            legacy=dict(first['request']);legacy.pop('flow_batch_size')
            connection.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(legacy,sort_keys=True,ensure_ascii=False),first['id']))
        replay,created=self.s.create({**REQUEST,'flow_batch_size':1},'legacy')
        self.assertFalse(created);self.assertEqual(replay['id'],first['id'])
        with self.assertRaisesRegex(ValueError,'different request'):
            self.s.create({**REQUEST,'flow_batch_size':10},'legacy')

    def test_output_directory_transliterates_vietnamese_title(self):
        j,_=self.s.create({**REQUEST,'idea':'Cá trích ướp muối'},'vietnamese-title')
        self.assertRegex(Path(j['output']).name,r'^ca-trich-uop-muoi-\d{8}-\d{6}$')
    def test_output_slug_normalizes_edge_cases(self):
        cases=(
            ('ĐỒNG Nai', 'dong-nai'),
            ('ca\u0301 phe\u0302', 'ca-phe'),
            ('  Lịch---sử!! ', 'lich-su'),
            ('a'*59+'  đuôi', 'a'*59),
            ('東京', 'video'),
        )
        for source,expected in cases:
            with self.subTest(source=source):self.assertEqual(output_slug(source),expected)
    def test_recovery_keeps_checkpoints(self):
        calls=[];j,_=self.s.create(REQUEST,'key');w=Worker(self.s,self.handlers(calls));w.step();w.step()
        fresh=Store(self.root/'jobs.db',self.root/'out');w=Worker(fresh,self.handlers(calls))
        while w.step():pass
        self.assertEqual(calls,list(STAGES));self.assertEqual(fresh.get(j['id'])['state'],'completed')
    def test_finite_retry_survives_restart(self):
        j,_=self.s.create(REQUEST,'key');calls=[];handlers=self.handlers(calls)
        def fail(*args):raise RuntimeError('offline')
        handlers['plan']=fail
        for _ in range(8):Worker(self.s,handlers,max_attempts=3,backoff=0).step()
        j=self.s.get(j['id']);self.assertEqual(j['state'],'failed');self.assertEqual(j['attempts']['plan'],3)
    def test_interrupted_running_consumes_budget(self):
        j,_=self.s.create(REQUEST,'key')
        with self.s.db() as c:
            c.execute("UPDATE jobs SET state='running',stage='plan' WHERE id=?",(j['id'],));c.execute('INSERT INTO attempts VALUES(?,?,?)',(j['id'],'plan',3))
        calls=[];Worker(self.s,self.handlers(calls),backoff=0).step()
        self.assertFalse(calls);self.assertEqual(self.s.get(j['id'])['state'],'failed')
    def test_cancel_during_stage_no_checkpoint(self):
        j,_=self.s.create(REQUEST,'key');handlers=self.handlers([])
        def h(j,check):self.s.cancel(j['id']);check()
        handlers['plan']=h;Worker(self.s,handlers).step();j=self.s.get(j['id'])
        self.assertEqual(j['state'],'cancelled');self.assertFalse(j['checkpoints'])
    def test_cancel_queued(self):
        j,_=self.s.create(REQUEST,'key');self.s.cancel(j['id']);self.assertFalse(Worker(self.s,self.handlers([])).step())
    def test_corrupt_checkpoint_is_failure(self):
        j,_=self.s.create(REQUEST,'key');p=self.root/'a';p.write_text('real');handlers=self.handlers([])
        handlers['plan']=lambda j,c:{'assets':[asset(p)]}
        w=Worker(self.s,handlers);w.step();p.write_text('tampered');w.step()
        self.assertEqual(self.s.get(j['id'])['state'],'failed')
    def test_lock_excludes_other_worker(self):
        self.assertTrue(self.s.lock('first'));self.assertFalse(Worker(self.s,self.handlers([])).step());self.s.release('first')
    def test_no_fake_verification(self):
        j,_=self.s.create(REQUEST,'key');h=self.handlers([]);h['verify']=lambda j,c:{};w=Worker(self.s,h,backoff=0)
        while w.step():pass
        self.assertEqual(self.s.get(j['id'])['state'],'failed')
    def test_image_provider_defaults_to_flow_and_validates_choices(self):
        self.assertEqual(validate_request(REQUEST)['image_provider'],'flow')
        for provider in ('flow','chatgpt','comfy'):
            self.assertEqual(validate_request({**REQUEST,'image_provider':provider})['image_provider'],provider)
        for provider in ('unknown','',None,2):
            with self.assertRaises(ValueError):validate_request({**REQUEST,'image_provider':provider})
    def test_duration_validation(self):
        for d in (True,-1,0,7201,'30',float('nan')):
            with self.assertRaises(ValueError):validate_request(dict(REQUEST,duration_seconds=d))
        self.assertEqual(validate_request(dict(REQUEST,duration_seconds=7200))['duration_seconds'],7200)
        self.assertEqual(validate_request(dict(REQUEST,pitch=-3.5))['pitch'],-3.5)
        self.assertEqual(len(validate_request(dict(REQUEST,idea='a'*95000))['idea']),95000)
        with self.assertRaises(ValueError):validate_request(dict(REQUEST,idea='a'*100001))
        for bad_p in (True,-13,13,'0',float('nan'),float('inf')):
            with self.assertRaises(ValueError):validate_request(dict(REQUEST,pitch=bad_p))
    def test_voice_import_preserves_ids(self):
        root=self.root/'story';p=root/'Voices'/'Work'/'Previews'/'one';p.mkdir(parents=True);(p/'request.json').write_text(json.dumps({'voice_id':'original'}))
        ref=self.root/'ref.wav';ref.write_bytes(b'actual-reference-fixture')
        export=self.root/'voices.json';export.write_text(json.dumps({'complete':True,'voices':[{'id':'clone:database-id','kind':'clone','name':'Original clone','reference_path':str(ref),'sha256':asset(ref)['sha256']}]}))
        v=Voices(root,export).catalog();self.assertEqual({x['id'] for x in v['voices']},{'original','clone:database-id'});self.assertTrue(v['complete'])
        self.assertFalse(Voices(root).catalog()['complete'])

class MediaTests(unittest.TestCase):
    def test_real_ffmpeg_duration_and_audio(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);Image.new('RGB',(180,320),(25,95,60)).save(p/'image.png')
            for name,freq in [('speech',250),('music',440)]:
                with wave.open(str(p/(name+'.wav')),'wb') as f:
                    f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b''.join(struct.pack('<h',int(1500*math.sin(2*math.pi*freq*i/16000))) for i in range(32000)))
            (p/'subtitles.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\nCPU integration fixture\n')
            r=render(p/'image.png',p/'speech.wav',p/'music.wav',p/'subtitles.srt',p/'video.mp4',2,lambda:None)
            self.assertFalse((p/'visual-disclosure.txt').exists(), 'Viewer video must not carry the AI-reconstruction banner')
            self.assertTrue(verify(r['video'],2)['verified'])
            self.assertEqual({s['codec_type'] for s in probe(r['video'])['streams']},{'video','audio'})
            with self.assertRaises(PermanentError):verify(r['video'],20)
            with self.assertRaises(PermanentError):render(p/'image.png',p/'speech.wav',p/'music.wav',p/'subtitles.srt',p/'bad.mp4',8,lambda:None)

class ApiTests(unittest.TestCase):
    def test_flow_batch_size_admission_and_health(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        class FakePipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'jobs.db',Path(t)/'out')
            with patch.dict('os.environ',{'VS_FLOW_BATCH_ENABLED':'0','VS_FLOW_BATCH_VALIDATED_SIZES':'10,20,30'}),TestClient(create_app(store,FakePipeline(),False)) as client:
                self.assertEqual(client.get('/api/health').json()['flow_batch_sizes'],[1])
                blocked=client.post('/api/jobs',json={**REQUEST,'flow_batch_size':10},headers={'Idempotency-Key':'blocked'})
                self.assertEqual(blocked.status_code,422)
                self.assertEqual(store.list(),[])
            with patch.dict('os.environ',{'VS_FLOW_BATCH_ENABLED':'1','VS_FLOW_BATCH_VALIDATED_SIZES':'10'}),TestClient(create_app(store,FakePipeline(),False)) as client:
                self.assertEqual(client.get('/api/health').json()['flow_batch_sizes'],[1,10])
                accepted=client.post('/api/jobs',json={**REQUEST,'flow_batch_size':10},headers={'Idempotency-Key':'approved'})
                self.assertEqual(accepted.status_code,201)
                self.assertEqual(accepted.json()['job']['request']['flow_batch_size'],10)
                self.assertEqual(client.post('/api/jobs',json={**REQUEST,'flow_batch_size':20},headers={'Idempotency-Key':'unapproved'}).status_code,422)

    def test_job_form_advertises_disabled_unvalidated_batch_sizes_and_sends_integer(self):
        html=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text(encoding='utf8')
        self.assertIn('<select id="flowBatchSize"',html)
        for size in (10,20,30):
            self.assertIn(f'<option value="{size}" disabled>',html)
        self.assertIn("flow_batch_size:Number($('#flowBatchSize').value)",html)
        self.assertIn('health.flow_batch_sizes',html)
        self.assertIn("if(!flow)select.value='1'",html)
        self.assertIn("availableFlowBatchSizes=[1]",html)
        self.assertIn('updateFlowBatchChoices();',html)

    def test_batch_selector_behavior_with_mocked_health(self):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        html=Path(__file__).resolve().parents[1]/'static'/'index.html'
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(process.argv[1],'utf8'),start=html.indexOf('let availableFlowBatchSizes=[1];'),stop=html.indexOf('refreshFlowBatchChoices();',start)+'refreshFlowBatchChoices();'.length;
assert(start>0 && stop>start);
const provider={value:'flow'},selector={value:'1',disabled:false,options:[1,10,20,30].map(n=>({value:String(n),disabled:n!==1,textContent:''}))},note={textContent:''};
let response={flow_batch_sizes:[1]},fail=false;
const context=vm.createContext({$:id=>({'#imageProvider':provider,'#flowBatchSize':selector,'#flowBatchNote':note,'#imageProviderNote':{textContent:''}}[id]),api:async()=>{if(fail)throw Error('offline');return response},console});
vm.runInContext(html.slice(start,stop),context);
(async()=>{
 response={flow_batch_sizes:[1,10]};await vm.runInContext('refreshFlowBatchChoices()',context);
 assert.deepEqual(selector.options.map(o=>o.disabled),[false,false,true,true]);
 vm.runInContext('flowBatchChoiceInitialized=false',context);await vm.runInContext('refreshFlowBatchChoices()',context);
 assert.equal(selector.value,'10');
 selector.value='1';selector.onchange();await vm.runInContext('refreshFlowBatchChoices()',context);assert.equal(selector.value,'1');
 selector.value='10';provider.value='chatgpt';vm.runInContext('updateFlowBatchChoices()',context);
 assert.equal(selector.value,'1');assert.equal(selector.disabled,true);
 provider.value='flow';fail=true;await vm.runInContext('refreshFlowBatchChoices()',context);
 assert.deepEqual(selector.options.map(o=>o.disabled),[false,true,true,true]);
 assert.equal(Number(selector.value),1);assert.equal(Number.isInteger(Number(selector.value)),true);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',script,str(html)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_api_local_no_generation(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        class FakePipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[{'name':'test_fixture','ok':True}]}
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'a.db',Path(t)/'out')
            with TestClient(create_app(store,FakePipeline(),False)) as c:
                self.assertEqual(c.get('/api/health').status_code,200)
                self.assertTrue(c.get('/api/preflight').json()['ready'])
                self.assertEqual(c.get('/').status_code,200)
                r=c.post('/api/jobs',json=REQUEST,headers={'Idempotency-Key':'a'});self.assertEqual(r.status_code,201)
                jid=r.json()['job']['id'];self.assertEqual(r.json()['job']['request']['image_provider'],'flow')
                self.assertFalse(c.post('/api/jobs',json=REQUEST,headers={'Idempotency-Key':'a'}).json()['created'])
                self.assertEqual(c.post('/api/jobs',json=REQUEST).status_code,422)
                self.assertEqual(c.post('/api/jobs',json=REQUEST,headers={'Idempotency-Key':'b','Origin':'https://evil.example'}).status_code,403)
                self.assertEqual(c.get('/api/jobs/'+jid+'/files/video.mp4').status_code,404)
                self.assertEqual(c.post('/api/jobs/'+jid+'/cancel').json()['state'],'cancelled')
                # Test project scoping, empty project creation, and listing
                c.post('/api/projects',json={'name':'Empty Studio Project'})
                c.post('/api/jobs',json={**REQUEST,'project':'Egg Coffee'},headers={'Idempotency-Key':'p1'})
                projects=c.get('/api/projects').json()['projects']
                self.assertIn('Egg Coffee',projects)
                self.assertIn('Empty Studio Project',projects)
                self.assertIn('Dự án mặc định',projects)
                # Test system logs endpoint
                logs=c.get('/api/system/logs').json()
                self.assertIn('events',logs)
                # Test retry endpoint on failed job
                with store.db() as conn:
                    conn.execute("UPDATE jobs SET state='failed',stage='script',error='Script quality/grounding retry budget exhausted' WHERE id=?",(jid,))
                failed_job=c.get('/api/jobs/'+jid).json()
                self.assertIsNotNone(failed_job.get('diagnostics'))
                retry_res=c.post('/api/jobs/'+jid+'/retry',json={'idea':'New better idea'})
                self.assertEqual(retry_res.status_code,200)
                self.assertEqual(retry_res.json()['status'],'queued')
                self.assertEqual(retry_res.json()['request']['idea'],'New better idea')
                # Test change-voice derived job creation
                with store.db() as conn:
                    conn.execute("UPDATE jobs SET state='completed',stage='verify' WHERE id=?",(jid,))
                    conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",(jid,'plan',json.dumps({'title':'T'})))
                    conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",(jid,'images',json.dumps({'scenes':[]})))
                cv_res=c.post('/api/jobs/'+jid+'/change-voice',json={'voice_id':'Thiện Minh','pitch':-2})
                self.assertEqual(cv_res.status_code,200)
                new_j=cv_res.json()
                self.assertEqual(new_j['request']['voice_id'],'Thiện Minh')
                self.assertEqual(new_j['request']['pitch'],-2)
                self.assertEqual(new_j['stage'],'speech')
                self.assertIn('plan',new_j['checkpoints'])
                self.assertEqual(c.post('/api/jobs/'+jid+'/change-voice',json={'voice_id':'Thiện Minh','pitch':True}).status_code,422)
                self.assertEqual(c.post('/api/jobs/'+jid+'/change-voice',json={'voice_id':'Thiện Minh','pitch':15}).status_code,422)

    def test_preflight_rejects_before_job_allocation(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        class Blocked:
            def handlers(self):return {}
            def preflight(self):return {'ready':False,'checks':[{'name':'required','ok':False}]}
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'a.db',Path(t)/'out')
            with TestClient(create_app(store,Blocked(),False)) as c:
                r=c.post('/api/jobs',json=REQUEST,headers={'Idempotency-Key':'blocked'})
                self.assertEqual(r.status_code,503)
                self.assertEqual(store.list(),[])

if __name__=='__main__':unittest.main()
