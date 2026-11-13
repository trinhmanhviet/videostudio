"""Engine selection and reference provenance, with no model inference."""
import hashlib,json,tempfile,unittest,shutil,math,struct,wave,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock

from videostudio import speech_engine as se
from videostudio.core import validate_request,digest

BASE={'idea':'A narration','voice_id':'voice','duration_seconds':30}

class SpeechEngineTests(unittest.TestCase):
    def test_validation_preserves_omissions_and_rejects_unsafe_options(self):
        result=validate_request(BASE)
        for key in ('speech_engine','khanh_steps','speech_rhythm','speech_speed','speech_reference_text'):
            self.assertNotIn(key,result)
        for fields in ({'speech_engine':'other'},{'khanh_steps':True},{'khanh_steps':24},
                       {'speech_speed':float('nan')},{'speech_speed':True},{'speech_speed':.49},
                       {'speech_speed':2.01},{'speech_rhythm':'laugh'},{'speech_reference_text':''}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):validate_request({**BASE,**fields})
        self.assertEqual(validate_request({**BASE,'speech_engine':'khanhtts','khanh_steps':16,'speech_speed':.5})['khanh_steps'],16)

    def test_legacy_identity_is_byte_identical_and_batch_does_not_change_it(self):
        voice={'id':'voice','kind':'preset'}
        old=hashlib.sha256(json.dumps({'narration':'Hello','voice':voice},sort_keys=True).encode()).hexdigest()
        self.assertEqual(se.speech_identity('Hello',voice,{}),old)
        self.assertEqual(se.speech_identity('Hello',voice,{'speech_engine':'vieneu','speech_speed':1,'speech_rhythm':'natural','speech_batch_size':33}),old)
        self.assertNotEqual(se.speech_identity('Hello',voice,{'speech_speed':1.1}),old)
        self.assertNotEqual(se.speech_identity('Hello',voice,{'speech_rhythm':'story'}),old)

    def test_preset_reference_requires_matching_recorded_voice_and_exact_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'preview.wav';sample.write_bytes(b'wave')
            voice={'id':'voice','kind':'preset','sample_path':str(sample)}
            pipeline=SimpleNamespace(voices=SimpleNamespace(root=root))
            with self.assertRaisesRegex(ValueError,'transcript'):se.resolve_reference(pipeline,voice,{})
            (root/'request.json').write_text(json.dumps({'voice_id':'other','text':'Wrong voice'}))
            with self.assertRaisesRegex(ValueError,'transcript'):se.resolve_reference(pipeline,voice,{})
            (root/'request.json').write_text(json.dumps({'voice_id':'voice','text':'Exact words'}))
            ref=se.resolve_reference(pipeline,voice,{})
            self.assertEqual(ref['text'],'Exact words');self.assertEqual(ref['sha256'],digest(sample))
            first=se.speech_identity('Hi',voice,{'speech_engine':'khanhtts'},pipeline)
            self.assertNotEqual(first,se.speech_identity('Hi',voice,{'speech_engine':'khanhtts','khanh_steps':16},pipeline))
            sample.write_bytes(b'newwave')
            self.assertNotEqual(first,se.speech_identity('Hi',voice,{'speech_engine':'khanhtts'},pipeline))

    def test_clone_accepts_user_transcript_only_for_verified_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            ref=Path(folder)/'ref.wav';ref.write_bytes(b'reference')
            voice={'id':'clone:v','kind':'clone','reference_path':str(ref),'sha256':digest(ref)}
            pipeline=SimpleNamespace(voices=SimpleNamespace(root=Path(folder)))
            with self.assertRaisesRegex(ValueError,'transcript'):se.resolve_reference(pipeline,voice,{})
            resolved=se.resolve_reference(pipeline,voice,{'speech_reference_text':'The exact reference words'})
            self.assertEqual(resolved['text'],'The exact reference words')
            ref.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):se.resolve_reference(pipeline,voice,{'speech_reference_text':'Words'})

    def test_default_delegates_to_legacy_worker_without_processing(self):
        worker=Mock();factory=Mock(return_value=worker)
        pipeline=SimpleNamespace(speech_python='python',speech_cache='cache')
        self.assertIs(se.create_speech_job(pipeline,{'id':'voice'},{'speech_batch_size':33},lambda:None,worker_factory=factory),worker)
        self.assertEqual(factory.call_args.args[0:3],('python','cache',{'id':'voice'}))
        self.assertEqual(factory.call_args.args[4],33)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_speed_and_story_pauses_are_published_per_utterance_before_callback(self):
        class FakeWorker:
            batch_size=8
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def write_lines(self,texts,outputs,timeout=900,on_complete=None):
                for index,output in enumerate(outputs):
                    with wave.open(str(output),'wb') as wav:
                        wav.setparams((1,2,16000,0,'NONE','not compressed'))
                        wav.writeframes(b''.join(struct.pack('<h',int(4000*math.sin(n*.2))) for n in range(16000)))
                    on_complete(index)
        with tempfile.TemporaryDirectory() as folder:
            outputs=[Path(folder)/'a.wav',Path(folder)/'b.wav'];done=[]
            pipeline=SimpleNamespace(speech_python='python',speech_cache='cache',ffmpeg='ffmpeg')
            with se.create_speech_job(pipeline,{'id':'voice'},{'speech_speed':2,'speech_rhythm':'story'},lambda:None,worker_factory=lambda *args:FakeWorker()) as worker:
                def completed(index):
                    with wave.open(str(outputs[index]),'rb') as wav:done.append((index,wav.getnframes()/wav.getframerate()))
                worker.write_lines(['First.','Second!'],outputs,on_complete=completed)
            self.assertEqual([row[0] for row in done],[0,1])
            self.assertAlmostEqual(done[0][1],.85,delta=.03);self.assertAlmostEqual(done[1][1],.95,delta=.03)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),['a.wav','b.wav'])

    def test_workflow_and_factory_preserve_engine_fields(self):
        from videostudio.workflow import compile_workflow,default_workflow
        from videostudio.content_factory import REQUEST_FIELDS
        graph=default_workflow();fields={'speech_engine':'khanhtts','khanh_steps':16,'speech_rhythm':'story','speech_speed':1.2,'speech_reference_text':'Exact reference words'}
        next(n for n in graph['nodes'] if n['type']=='speech')['config'].update(fields)
        compiled=compile_workflow(graph,BASE)
        for key,value in fields.items():self.assertIn(key,REQUEST_FIELDS);self.assertEqual(compiled[key],value)

    def test_khanh_worker_uses_only_offline_model_and_no_asr(self):
        import sys
        from videostudio import khanh_speech_worker as kw
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'audio_tokenizer').mkdir()
            for name in ('config.json','model.safetensors','tokenizer.json','audio_tokenizer/config.json','audio_tokenizer/model.safetensors'):(root/name).write_text('{}')
            reference=root/'ref.wav';reference.write_bytes(b'ref')
            model=Mock();model.create_voice_clone_prompt.return_value='prompt'
            omni=SimpleNamespace(OmniVoice=SimpleNamespace(from_pretrained=Mock(return_value=model)))
            context=Mock();context.__enter__=Mock();context.__exit__=Mock(return_value=False)
            torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True),float16='fp16',inference_mode=lambda:context)
            config={'cache':str(root),'snapshot':str(root),'reference':{'path':str(reference),'sha256':digest(reference),'text':'Exact words'}}
            with patch.dict(sys.modules,torch=torch,omnivoice=omni),patch.object(kw.sys,'executable',str(root/'runtime/.venv/Scripts/python.exe')),patch.dict('os.environ',{}):loaded,prompt=kw.load_model(config)
            self.assertIs(loaded,model);self.assertEqual(prompt,'prompt')
            options=omni.OmniVoice.from_pretrained.call_args.kwargs
            self.assertIs(options['local_files_only'],True);self.assertIs(options['load_asr'],False)
            model.create_voice_clone_prompt.assert_called_once_with(str(reference),'Exact words')

    def test_khanh_job_cancellation_preserves_completed_line_and_cleans_pending(self):
        from videostudio import khanh_speech_worker as kw,speech_worker as sw
        from videostudio.core import Cancelled
        fake='''
from pathlib import Path
from videostudio import khanh_speech_worker as kw
def load(config):
    (Path(config['cache'])/'loaded.txt').write_text('loaded')
    return object(),object()
def synth(model,prompt,texts,outputs,steps):
    import time
    for text,output in zip(texts,outputs):
        if text=='wait':time.sleep(30)
        Path(output).write_text(text)
kw.load_model=load
kw.synthesize_batch=synth
kw.main()
'''
        spawn=subprocess.Popen
        def start(args,**kwargs):return spawn([sys.executable,'-u','-c',fake,*args[4:]],**kwargs)
        done=[]
        def check():
            if done:raise Cancelled()
        with tempfile.TemporaryDirectory() as folder,patch.object(sw.subprocess,'Popen',side_effect=start):
            root=Path(folder);outputs=[root/'first.wav',root/'wait.wav']
            with self.assertRaises(Cancelled):
                with kw.KhanhSpeechJob(sys.executable,root,{},check,33,root,16) as worker:
                    self.assertEqual(worker.batch_size,8)
                    worker.write_lines(['finished','wait'],outputs,on_complete=done.append)
            self.assertEqual(outputs[0].read_text(),'finished');self.assertFalse(outputs[1].exists())
            self.assertFalse(list(root.glob('.*.wav')));self.assertIsNotNone(worker.process.poll())

    def test_engine_preflight_replaces_only_selected_speech_gate(self):
        original={'ready':False,'checks':[{'name':'speech','ok':False},{'name':'ffmpeg','ok':True}]}
        pipeline=SimpleNamespace(voices=SimpleNamespace(selected=lambda _:{}))
        self.assertIs(se.preflight_for_request(original,pipeline,{}),original)
        with patch.object(se,'engine_status',return_value={'ready':True,'reason':''}):
            status=se.preflight_for_request(original,pipeline,{'voice_id':'voice','speech_engine':'khanhtts'})
        self.assertTrue(status['ready']);self.assertFalse(original['checks'][0]['ok'])
        self.assertEqual(status['checks'][1],original['checks'][1])

    def test_preview_speech_units_keep_words_and_punctuation(self):
        self.assertEqual(se.speech_units(' First sentence. Next one!\nA final paragraph'),['First sentence.','Next one!','A final paragraph'])
        self.assertFalse(se.engine_status(SimpleNamespace(),request={'speech_engine':'vieneu'})['ready'])

    def test_missing_preset_reference_prepares_only_when_requested_and_reuses_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);python=root/'python.exe';python.write_bytes(b'fixture')
            snapshot=root/'snapshot';snapshot.mkdir();(snapshot/'audio_tokenizer').mkdir()
            for name in ('config.json','model.safetensors','tokenizer.json','audio_tokenizer/config.json','audio_tokenizer/model.safetensors'):(snapshot/name).write_text('{}')
            pipeline=SimpleNamespace(speech_python=str(python),speech_cache=str(root),khanh_python=str(python),khanh_snapshot=snapshot,speech_reference_cache=root/'references')
            voice={'id':'preset-without-sample','kind':'preset'};request={'speech_engine':'khanhtts'}
            calls=[]
            class PrepareWorker:
                def __init__(self,*args):calls.append(args)
                def __enter__(self):return self
                def __exit__(self,*args):calls.append('closed')
                def write_line(self,text,path,timeout=900):
                    self.text=text
                    with wave.open(str(path),'wb') as wav:
                        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(struct.pack('<h',2000)*16000)
            with patch.object(se,'SpeechJob',PrepareWorker):
                status=se.engine_status(pipeline,voice,request)
                self.assertTrue(status['ready']);self.assertTrue(status['needs_reference_prepare']);self.assertEqual(calls,[])
                first=se.prepare_reference(pipeline,voice,request,lambda:None)
                self.assertEqual(first['text'],se.PRESET_REFERENCE_TEXT);self.assertEqual(calls[-1],'closed')
                self.assertEqual(se.prepare_reference(pipeline,voice,request,lambda:None),first);self.assertEqual(len(calls),2)
                self.assertFalse(se.engine_status(pipeline,voice,request)['needs_reference_prepare'])
                self.assertEqual(se.resolve_reference(pipeline,voice,request)['sha256'],digest(first['path']))
                clone={**voice,'kind':'clone'}
                self.assertFalse(se.engine_status(pipeline,clone,request)['ready'])
                with self.assertRaises(ValueError):se.prepare_reference(pipeline,clone,request,lambda:None)

