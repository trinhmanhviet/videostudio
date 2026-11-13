import copy,json,math,os,re,shutil,struct,tempfile,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from videostudio.core import validate_request,digest
from videostudio.media import asset,probe
ROOT=Path(__file__).resolve().parents[1]
class AnimationPipelineTests(unittest.TestCase):
 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_selected_engine_does_not_reuse_legacy_aggregate_speech(self):
  from videostudio import meme_animation as m
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   pipeline,job=self.fixture(folder)
   job['request'].update(speech_engine='khanhtts',khanh_steps=16,speech_speed=1.2,speech_rhythm='story')
   job['checkpoints']['script']['migration']={'voice_id':'test','speech':{'utterances':[], 'assets':[]}}
   result=m.speech(pipeline,job,lambda:None)
   pipeline._speech_attempt.assert_called_once()
   self.assertEqual(result['speech_engine'],'khanhtts')
   self.assertAlmostEqual(result['speed'],1.15*1.2)
 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_migrated_speech_preserves_original_aggregate_audio(self):
  from videostudio import meme_animation as m
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   pipeline,job=self.fixture(folder)
   old=Path(job['output'])/'speech.wav';old.write_bytes(b'original aggregate audio')
   job['checkpoints']['script']['migration']={'version':'test'}
   result=m.speech(pipeline,job,lambda:None)
   self.assertEqual(old.read_bytes(),b'original aggregate audio')
   self.assertNotEqual(result['path'],str(old))
 def test_all_meme_requests_use_hyperframes(self):
  from videostudio.meme_animation import enabled
  base={'idea':'test','voice_id':'test','duration_seconds':45,'workflow_mode':'meme'}
  self.assertTrue(enabled({'request':validate_request(base),'checkpoints':{}}))
  self.assertTrue(enabled({'request':validate_request({**base,'meme_engine':'hyperframes'}),'checkpoints':{}}))
  for mode in ['unknown',True,[]]:
   with self.assertRaises(ValueError):validate_request({**base,'meme_engine':mode})
 def fixture(self,folder):
  source=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf-8'))
  source['beats']=source['beats'][:2];source['beats'][0]['text']='Lời kể <b>không phải HTML</b>.'
  source['title']=['<script>TEST</script>','KHÔNG CHẠY CODE'];source['narrator_voice']='test';source['speed']=1.15
  for c in source['cast'].values():c['voice']='test'
  job={'id':'123e4567-e89b-42d3-a456-426614174000','output':str(Path(folder)/'output'),'request':{'idea':'test','voice_id':'test','pitch':0,'duration_seconds':45,'workflow_mode':'meme','meme_engine':'hyperframes'},'checkpoints':{'script':{'animation_script':source,'meme_engine':'hyperframes','narration':' '.join(b['text'] for b in source['beats']),'scenes':[{'scene_id':f'meme-{i:04}','narration':b['text'],'narration_lines':[b['text']]} for i,b in enumerate(source['beats'])]}}}
  Path(job['output']).mkdir();pipeline=SimpleNamespace(ffmpeg='ffmpeg',ffprobe='ffprobe',store=Mock(),voices=Mock(),comfy_asset=Mock(side_effect=AssertionError('No model at render/music')))
  pipeline.voices.selected.return_value={'id':'test','kind':'preset'}
  def raw(j,check,revision):
   revision.mkdir(exist_ok=True);rows=[];assets=[]
   for i,b in enumerate(source['beats']):
    p=revision/f'raw-{i}.wav'
    if not p.exists():
     with wave.open(str(p),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b''.join(struct.pack('<h',int(5000*math.sin(n*.2))) for n in range(8000)))
    rows.append({'path':str(p),'narration':b['text'],'scene_id':f'meme-{i:04}'});assets.append(asset(p))
   return {'utterances':rows,'assets':assets}
  pipeline._speech_attempt=Mock(side_effect=raw)
  return pipeline,job
 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_speech_uses_tempo_then_engine_timing_and_keeps_sources_for_retry(self):
  from videostudio import meme_animation as m
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   pipeline,job=self.fixture(folder);result=m.speech(pipeline,job,lambda:None)
   self.assertGreater(result['duration_seconds'],sum(u['duration'] for u in result['utterances']))
   self.assertLess(result['utterances'][0]['duration'],.5)
   script=Path(job['output'])/'episode/script.json';html=script.with_name('index.html').read_text(encoding='utf-8')
   self.assertIn('&lt;script&gt;TEST&lt;/script&gt;',html);self.assertNotIn('<script>TEST</script>',html)
   self.assertIn('&lt;b&gt;không phải HTML&lt;/b&gt;',html)
   before={a['path']:a['sha256'] for a in result['assets']}
   again=m.speech(pipeline,job,lambda:None)
   self.assertEqual(result['duration_seconds'],again['duration_seconds'])
   for path,sha in before.items():self.assertEqual(digest(path),sha)
   job['checkpoints']['speech']=result
   images=m.images(pipeline,job,lambda:None);self.assertEqual(images['image_provider'],'meme_assets');self.assertTrue(images['assets'])
   music=m.music(pipeline,job,lambda:None);self.assertTrue(music['intentional_mute']);pipeline.comfy_asset.assert_not_called()
 def test_preflight_skips_only_unused_models_for_explicit_animation(self):
  from videostudio import meme_animation as m
  status={'ready':False,'checks':[{'name':n,'ok':False} for n in ('model:x','comfy_nodes','extension_transport')]}
  r={'workflow_mode':'meme','meme_engine':'hyperframes'}
  result=m.preflight_for_request(status,r)
  self.assertFalse(result['ready']);self.assertEqual([c['ok'] for c in result['checks']],[True,True,False])
  self.assertEqual(m.preflight_for_request(status,{'workflow_mode':'meme'}),result)
  self.assertIs(m.preflight_for_request(status,{'workflow_mode':'research'}),status)
 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_derived_voice_flags_and_render_cache_preserve_published_file(self):
  from videostudio import meme_animation as m
  from videostudio.core import PermanentError
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   pipeline,job=self.fixture(folder)
   job['request'].update(captions_enabled=False,sfx_enabled=False)
   job['checkpoints']['script']['animation_script']['narrator_voice']='old'
   for c in job['checkpoints']['script']['animation_script']['cast'].values():c['voice']='old'
   for stage in ('speech','images','music'):job['checkpoints'][stage]=getattr(m,stage)(pipeline,job,lambda:None)
   ep=Path(job['output'])/'episode';html=(ep/'index.html').read_text(encoding='utf8')
   self.assertNotIn('id="cap0"',html);self.assertNotIn('id="sfx"',html)
   stored=json.loads((ep/'script.json').read_text(encoding='utf8'))
   self.assertEqual(stored['narrator_voice'],'test')
   self.assertEqual(job['checkpoints']['script']['animation_script']['narrator_voice'],'old')
   def fake_render(args,*a,**kw):Path(args[-1]).write_bytes(b'encoded test video')
   with patch.object(m,'command',side_effect=fake_render) as renderer,patch.object(m,'verify_media'),patch('videostudio.media.ensure_clean_audio',return_value={'ok':True}):
    first=m.render(pipeline,job,lambda:None);again=m.render(pipeline,job,lambda:None)
    self.assertEqual(first,again);self.assertEqual(renderer.call_count,1)
    self.assertTrue(Path(first['video']).is_file());self.assertFalse((Path(job['output'])/'video.part.mp4').exists())
    (ep/'index.html').write_text('changed',encoding='utf8')
    with self.assertRaises(PermanentError):m.render(pipeline,job,lambda:None)
 @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
 def test_returning_to_a_scene_cannot_duplicate_internal_dom_ids(self):
  from videostudio import meme_animation as m
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   pipeline,job=self.fixture(folder);data=job['checkpoints']['script']['animation_script']
   first=copy.deepcopy(data['beats'][0]);scene=copy.deepcopy(data['scenes'][first['scene']])
   order=['room','other','room','room_2'];data['scenes']={key:scene for key in set(order)}
   data['beats']=[dict(copy.deepcopy(first),scene=key) for key in order]
   job['checkpoints']['script']['scenes']=[{'scene_id':f'meme-{i:04}','narration':first['text'],'narration_lines':[first['text']]} for i in range(4)]
   m.speech(pipeline,job,lambda:None)
   ep=Path(job['output'])/'episode';ids=re.findall(r'\bid="([^"]+)"',(ep/'index.html').read_text(encoding='utf8'))
   self.assertEqual(len(ids),len(set(ids)))
   self.assertEqual(len(json.loads((ep/'staging.json').read_text(encoding='utf8'))['scenes']),4)
 @unittest.skipUnless(os.name=='nt','Windows process ownership')
 def test_cancel_stops_only_the_owned_render_process_tree(self):
  from videostudio import meme_animation as m
  with tempfile.TemporaryDirectory(dir=ROOT.parent/'data'/'test-tmp') as folder:
   child=Mock(pid=123456);child.poll.return_value=None
   with patch.object(m.subprocess,'Popen',return_value=child),patch.object(m.subprocess,'run') as stop:
    with self.assertRaisesRegex(RuntimeError,'cancelled'):
     m.command(['node','local-engine'],Mock(side_effect=[None,RuntimeError('cancelled')]),Path(folder)/'test.log')
    self.assertEqual(stop.call_args.args[0],['taskkill','/PID','123456','/T','/F'])
