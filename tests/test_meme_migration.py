import copy
import hashlib
import json
import math
import shutil
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from videostudio.core import Store, validate_request, PermanentError
from videostudio.media import asset


class UnifiedMemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'jobs.db', self.root/'output')
        self.request = {'idea':'Một câu chuyện', 'voice_id':'test', 'duration_seconds':20, 'workflow_mode':'meme'}

    def legacy(self, state='failed'):
        job, _ = self.store.create(self.request, 'old-key')
        lines = ['Tôi bắt đầu câu chuyện.', 'Rồi mọi chuyện kết thúc.']
        script = {'narration':' '.join(lines), 'scenes':[{'scene_id':f'old-{i}', 'narration':t, 'narration_lines':[t], 'meme':{'line':t,'bg':'room_day'}} for i,t in enumerate(lines)], 'meme':{'version':1}}
        voice = Path(job['output'])/'voice.wav'; voice.write_bytes(b'original TTS')
        speech = {'utterances':[dict(s,path=str(voice),start=i,end=i+1,duration=1) for i,s in enumerate(script['scenes'])], 'path':str(voice), 'duration_seconds':2, 'assets':[asset(voice)]}
        with self.store.db() as c:
            req = dict(self.request, image_provider='flow',flow_batch_size=1,text_provider='chatgpt',meme_engine='pillow')
            c.execute('UPDATE jobs SET request=?,state=? WHERE id=?',(json.dumps(req),state,job['id']))
            for stage,value in {'plan':{},'research':{},'script':script,'speech':speech,'music':{'path':str(voice),'assets':[asset(voice)]},'images':{'old':True},'render':{'video':'old.mp4'}}.items():
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],stage,json.dumps(value)))
        return self.store.get(job['id'])

    def test_default_and_legacy_requests_use_the_same_engine(self):
        from videostudio.meme_animation import enabled
        self.assertTrue(enabled({'request':self.request}))
        self.assertEqual(validate_request(dict(self.request,meme_engine='pillow')),validate_request(self.request))

    def test_old_idempotency_key_replays_without_changing_the_old_job(self):
        job = self.legacy('completed'); before = copy.deepcopy(job)
        replay, created = self.store.create(self.request,'old-key')
        self.assertFalse(created); self.assertEqual(replay,before)

    def test_completed_job_migration_is_a_noop(self):
        from videostudio.meme_migration import migrate_job
        job = self.legacy('completed')
        self.assertEqual(migrate_job(self.store,job['id']),job)
        self.assertFalse((Path(job['output'])/'comedy-migration-v1').exists())

    def test_incomplete_job_conversion_preserves_narration_tts_music_and_original_files(self):
        from videostudio.meme_migration import migrate_job
        old = self.legacy(); migrated = migrate_job(self.store,old['id'])
        self.assertEqual(migrated['checkpoints']['script']['narration'],old['checkpoints']['script']['narration'])
        for stage in ('music','plan','research'):
            self.assertEqual(migrated['checkpoints'][stage],old['checkpoints'][stage])
        self.assertEqual(migrated['checkpoints']['script']['migration']['speech'],old['checkpoints']['speech'])
        self.assertEqual(migrated['request']['meme_engine'],'hyperframes')
        self.assertNotIn('render',migrated['checkpoints']); self.assertNotIn('images',migrated['checkpoints'])
        self.assertEqual(migrate_job(self.store,old['id']),migrated)
        backup = json.loads((Path(old['output'])/'comedy-migration-v1/original.json').read_text(encoding='utf8'))
        self.assertEqual(backup['job']['checkpoints'],old['checkpoints'])
        self.assertEqual(Path(old['checkpoints']['speech']['path']).read_bytes(),b'original TTS')

    def test_active_worker_lease_blocks_migration_without_mutation(self):
        from videostudio.meme_migration import migrate_job
        old = self.legacy(); self.store.lock('other',60)
        with self.assertRaisesRegex(ValueError,'idle|lease'):
            migrate_job(self.store,old['id'])
        self.assertEqual(self.store.get(old['id']),old)

    def test_restart_worker_reclaims_abandoned_running_legacy_job(self):
        from videostudio.core import Worker
        old=self.legacy('running')
        with self.store.db() as c:
            c.execute('INSERT INTO worker_lock VALUES(1,?,?)',('dead worker',time.time()-60))
            c.execute('UPDATE jobs SET stage=? WHERE id=?',('images',old['id']))
        speech=Mock(return_value={'assets':[],'reused_original_tts':True})
        worker=Worker(self.store,{'speech':speech})
        self.assertTrue(worker.step())
        speech.assert_called_once()
        adapted=speech.call_args.args[0]
        self.assertEqual(adapted['state'],'queued')
        self.assertEqual(adapted['request']['meme_engine'],'hyperframes')
        self.assertIn('speech',adapted['checkpoints']['script']['migration'])
        self.assertEqual(self.store.get(old['id'])['state'],'queued')
        backup=json.loads((Path(old['output'])/'comedy-migration-v1/original.json').read_text(encoding='utf8'))
        self.assertEqual(backup['job']['state'],'running')

    def test_running_legacy_job_requires_a_current_matching_worker_lease(self):
        from videostudio.meme_migration import migrate_job
        old=self.legacy('running')
        for owner in (None,'unleased caller'):
            with self.assertRaisesRegex(ValueError,'idle|lease'):
                migrate_job(self.store,old['id'],lease_owner=owner)
        self.store.lock('live worker',60)
        for owner in (None,'other worker'):
            with self.assertRaisesRegex(ValueError,'idle|lease'):
                migrate_job(self.store,old['id'],lease_owner=owner)
        self.assertEqual(self.store.get(old['id']),old)

    def test_new_script_calls_one_writer_for_all_durations(self):
        from videostudio import meme_animation
        for duration in (20,420):
            job = {'request':dict(self.request,duration_seconds=duration),'output':str(self.root),'checkpoints':{}}
            with patch('videostudio.comedy_story.write_story',return_value={'comedy':True}) as writer:
                self.assertEqual(meme_animation.script(SimpleNamespace(),job,lambda:None),{'comedy':True})
                writer.assert_called_once()

    def test_saved_hyperframes_script_is_recovered_without_ai(self):
        from videostudio.meme_migration import saved_script
        from videostudio.meme_animation_script import AnimationCatalog
        data = json.loads((Path(__file__).parent/'fixtures/meme-animation-script.json').read_text(encoding='utf8'))
        (self.root/'animation-script.json').write_text(json.dumps(data),encoding='utf8')
        result = saved_script({'output':str(self.root),'request':self.request},AnimationCatalog())
        self.assertEqual([b['text'] for b in result['animation_script']['beats']],[b['text'] for b in data['beats']])

    def test_saved_legacy_reply_before_checkpoint_does_not_start_a_new_story(self):
        from videostudio.meme_migration import migrate_job
        job,_ = self.store.create(self.request,'uncommitted')
        with self.store.db() as c:
            c.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(self.request),job['id']))
        lines = ['Đây là câu đã viết.','Đây là câu kết đã viết.']
        path = Path(job['output'])/'meme-script.json'
        path.write_text(json.dumps({'beats':[{'line':t} for t in lines]}),encoding='utf8')
        migrated = migrate_job(self.store,job['id'])
        self.assertEqual([s['narration'] for s in migrated['checkpoints']['script']['scenes']],lines)

    def test_changed_legacy_media_blocks_conversion_with_original_job_intact(self):
        from videostudio.meme_migration import migrate_job
        old = self.legacy(); Path(old['checkpoints']['speech']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(PermanentError,'changed|missing'):
            migrate_job(self.store,old['id'])
        self.assertEqual(self.store.get(old['id']),old)

    def test_rendered_memory_requires_successful_final_verification(self):
        from videostudio import meme_animation
        job={'id':'verified','request':self.request,'checkpoints':{
            'script':{'comedy':{'story':{'logline':'Original story'},'critic':{}}},
            'render':{'video':'fixture.mp4'},'speech':{'duration_seconds':2}}}
        pipeline=SimpleNamespace(store=self.store,ffmpeg='ffmpeg',ffprobe='ffprobe')
        with patch.object(meme_animation,'verify_media',return_value={'verified':True}),patch.object(meme_animation,'run'),patch.object(meme_animation,'audio_report'),patch('videostudio.comedy_memory.record') as record:
            meme_animation.verify(pipeline,job,lambda:None)
            self.assertEqual(record.call_args.args[-1],'rendered')
        with patch.object(meme_animation,'verify_media',side_effect=PermanentError('decode failed')),patch('videostudio.comedy_memory.record') as record:
            with self.assertRaises(PermanentError):meme_animation.verify(pipeline,job,lambda:None)
            record.assert_not_called()

    def test_partial_legacy_tts_is_imported_to_owned_hf_cache_without_touching_original(self):
        from videostudio.meme_migration import migrate_job, reuse_legacy_voice
        job=self.legacy()
        with self.store.db() as c:c.execute("DELETE FROM checkpoints WHERE job=? AND stage='speech'",(job['id'],))
        source=Path(job['output'])/'speech-0000.wav';source.write_bytes(b'already spoken')
        receipt=source.with_suffix('.json');receipt.write_text(json.dumps({'identity':'original identity','sha256':asset(source)['sha256']}),encoding='utf8')
        migrated=migrate_job(self.store,job['id']);target=Path(job['output'])/'episode/raw-voice'
        reuse_legacy_voice(migrated,target)
        self.assertEqual((target/source.name).read_bytes(),source.read_bytes())
        self.assertEqual((target/receipt.name).read_bytes(),receipt.read_bytes())
        self.assertEqual(source.read_bytes(),b'already spoken')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_production_partial_tts_layout_reuses_only_matching_voice_and_text(self):
        from videostudio.meme_migration import migrate_job, reuse_legacy_voice
        from videostudio.providers import Pipeline
        from videostudio.media import run
        job=self.legacy()
        with self.store.db() as c:c.execute("DELETE FROM checkpoints WHERE job=? AND stage='speech'",(job['id'],))
        revision=Path(job['output'])/'narration-attempt-00';revision.mkdir()
        voice={'id':'test','kind':'preset'}
        originals={}
        for index,scene in enumerate(job['checkpoints']['script']['scenes']):
            wav=revision/f'speech-{index:04}.wav'
            with wave.open(str(wav),'wb') as output:
                output.setparams((1,2,16000,0,'NONE','not compressed'))
                output.writeframes(b''.join(int(5000*math.sin(n*.2)).to_bytes(2,'little',signed=True) for n in range(8000)))
            identity=hashlib.sha256(json.dumps({'narration':scene['narration'],'voice':voice},sort_keys=True).encode()).hexdigest()
            receipt=wav.with_suffix('.json');receipt.write_text(json.dumps({'identity':identity,'sha256':asset(wav)['sha256']}),encoding='utf8')
            originals[wav.name]=wav.read_bytes();originals[receipt.name]=receipt.read_bytes()
        migrated=migrate_job(self.store,job['id']);target=Path(job['output'])/'episode/raw-voice'
        self.assertEqual(len(migrated['checkpoints']['script']['migration'].get('raw_utterances',[])),2)
        for name,contents in originals.items():
            self.assertEqual((Path(job['output'])/'comedy-migration-v1/files/narration-attempt-00'/name).read_bytes(),contents)
        reuse_legacy_voice(migrated,target)
        pipeline=Pipeline.__new__(Pipeline);pipeline.voices=Mock();pipeline.voices.selected.return_value=voice
        pipeline.store=None;pipeline.ffmpeg='ffmpeg';pipeline.ffprobe='ffprobe';pipeline.speech_python='python';pipeline.speech_cache=str(self.root/'cache')
        with patch('videostudio.providers.SpeechJob', side_effect=RuntimeError('TTS invoked')):
            result=pipeline._speech_attempt(migrated,lambda:None,target)
        self.assertEqual(len(result['utterances']),2)
        # Ordinary cache validation must reject copied audio for another voice.
        pipeline.voices.selected.return_value={'id':'different','kind':'preset'}
        with patch('videostudio.providers.SpeechJob', side_effect=RuntimeError('TTS invoked')):
            with self.assertRaisesRegex(RuntimeError,'TTS invoked'):pipeline._speech_attempt(migrated,lambda:None,target)
        pipeline.voices.selected.return_value=voice
        changed=copy.deepcopy(migrated);changed['checkpoints']['script']['scenes'][0]['narration_lines']=['Changed narration.']
        with patch('videostudio.providers.SpeechJob', side_effect=RuntimeError('TTS invoked')):
            with self.assertRaisesRegex(RuntimeError,'TTS invoked'):pipeline._speech_attempt(changed,lambda:None,target)
        for name,contents in originals.items():self.assertEqual((revision/name).read_bytes(),contents)

    def test_preserved_legacy_music_is_mixed_quietly_without_modifying_its_source(self):
        from videostudio import meme_animation
        video=self.root/'video.part.mp4';video.write_bytes(b'voice and SFX')
        music=self.root/'original.mp3';music.write_bytes(b'original music')
        job={'request':{'music_volume':.35},'checkpoints':{'script':{'migration':{'version':'test'}},'music':{'path':str(music),'assets':[asset(music)]}}}
        def encode(args,check):Path(args[-1]).write_bytes(b'video with quiet music')
        with patch.object(meme_animation,'run',side_effect=encode) as encode_call:
            result=meme_animation.mix_legacy_music(SimpleNamespace(ffmpeg='ffmpeg'),job,video,20,lambda:None)
        self.assertTrue(result['reused']);self.assertEqual(music.read_bytes(),b'original music')
        self.assertEqual(video.read_bytes(),b'video with quiet music')
        self.assertIn('volume=0.175',encode_call.call_args.args[0][encode_call.call_args.args[0].index('-filter_complex')+1])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_preserved_music_mix_decodes_with_actual_ffmpeg(self):
        from videostudio import meme_animation
        from videostudio.media import run, probe
        video=self.root/'video.part.mp4';music=self.root/'original.wav';check=lambda:None
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=white:s=64x64:r=10:d=1',
             '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-c:a','aac','-shortest',video],check)
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=220:duration=0.3',music],check)
        before=asset(music)
        job={'request':{'music_volume':.35},'checkpoints':{'script':{'migration':{'version':'test'}},'music':{'path':str(music),'assets':[before]}}}
        result=meme_animation.mix_legacy_music(SimpleNamespace(ffmpeg='ffmpeg'),job,video,1,check)
        self.assertTrue(result['reused']);self.assertEqual(asset(music),before)
        self.assertAlmostEqual(float(probe(video)['format']['duration']),1,delta=.1)
        run(['ffmpeg','-v','error','-i',video,'-f','null','-'],check)

    def test_current_writer_final_artifact_restores_quality_from_phase_receipts(self):
        from videostudio.meme_migration import saved_script
        from videostudio.meme_animation_script import AnimationCatalog
        (self.root/'comedy').mkdir();(self.root/'comedy/inputs.json').write_text('{}',encoding='utf8')
        (self.root/'animation-script.json').write_text('{}',encoding='utf8')
        self.assertIsNone(saved_script({'output':str(self.root),'request':self.request},AnimationCatalog()))

    def test_checkpoint_mirrors_are_backed_up_before_worker_replaces_them(self):
        from videostudio.meme_migration import migrate_job
        old=self.legacy();mirror=Path(old['output'])/'speech.json';mirror.write_text('original checkpoint mirror',encoding='utf8')
        migrate_job(self.store,old['id'])
        self.assertEqual((Path(old['output'])/'comedy-migration-v1/files/speech.json').read_text(encoding='utf8'),'original checkpoint mirror')
        self.assertEqual(mirror.read_text(encoding='utf8'),'original checkpoint mirror')

