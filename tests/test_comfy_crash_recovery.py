import json,tempfile,unittest,httpx
from pathlib import Path
from videostudio.comfy_recovery import prepare_music_recovery,resolve_music_kind
from videostudio.core import Store,STAGES
from videostudio.exchanges import Exchanges
PID='11111111-1111-4111-8111-111111111111'
class CrashRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'job';self.root.mkdir();self.output=Path(self.temp.name)/'comfy-output';self.output.mkdir();self.write_evidence(self.root)
 def tearDown(self):self.temp.cleanup()
 def write_evidence(self,root):
  (root/'music-receipt.json').write_text(json.dumps({'prompt_id':PID}))
  (root/'comfy-crash-evidence.json').write_text(json.dumps({'old_prompt_id':PID,'old_process_absent':True,'exception_code':'0xc0000005','faulting_module':'torch_cpu.dll'}))
 def client(self,history=None,queue=None):
  def request(r):
   self.assertEqual(r.method,'GET')
   return httpx.Response(200,json=(history or {}) if '/history/' in r.url.path else (queue if queue is not None else {'queue_running':[],'queue_pending':[]}))
  return httpx.Client(base_url='http://comfy/',transport=httpx.MockTransport(request))
 def test_prepare_once_preserves_old_receipt_and_uses_distinct_attempt(self):
  before=(self.root/'music-receipt.json').read_bytes()
  with self.client() as c:
   r=prepare_music_recovery(self.root,c,self.output,'job');again=prepare_music_recovery(self.root,c,self.output,'job')
  self.assertTrue(r['created']);self.assertFalse(again['created']);self.assertEqual(r['kind'],'music-crash-recovery-01');self.assertEqual((self.root/'music-receipt.json').read_bytes(),before)
  self.assertEqual((self.root/'receipts'/('music-original-'+PID+'.json')).read_bytes(),before)
 def test_existing_history_queue_and_artifact_block_regeneration(self):
  with self.client(history={PID:{}}) as c:
   with self.assertRaises(ValueError):prepare_music_recovery(self.root,c,self.output,'job')
  with self.client(queue={'queue_running':[['foreign']],'queue_pending':[]}) as c:
   with self.assertRaises(ValueError):prepare_music_recovery(self.root,c,self.output,'job')
  (self.root/'music.mp3').write_bytes(b'partial or complete candidate')
  with self.client() as c:
   with self.assertRaises(ValueError):prepare_music_recovery(self.root,c,self.output,'job')
  self.assertFalse((self.root/'music-crash-recovery.json').exists())
 def test_evidence_cannot_be_changed_after_authorization(self):
  with self.client() as c:prepare_music_recovery(self.root,c,self.output,'job')
  (self.root/'comfy-crash-evidence.json').write_text('{}')
  with self.assertRaises(ValueError):resolve_music_kind(self.root)
 def test_service_recovery_preserves_attempts_and_cannot_override_cancel(self):
  s=Store(Path(self.temp.name)/'db',Path(self.temp.name)/'outputs');ex=Exchanges(s);scope=ex.scope();j,_=s.create({'idea':'test','voice_id':'selected','duration_seconds':12},'key',scope);root=Path(j['output']);self.write_evidence(root)
  with self.client() as c:prepare_music_recovery(root,c,self.output,j['id'])
  with s.db() as c:
   for stage in STAGES[:STAGES.index('music')]:c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],stage,'{}'))
   c.execute('INSERT INTO attempts VALUES(?,?,?)',(j['id'],'music',3));c.execute("UPDATE jobs SET state='failed',stage='music',error='connection refused' WHERE id=?",(j['id'],))
  before=s.get(j['id']);s.resume(j['id'],scope,actor='service_recovery');after=s.get(j['id']);self.assertEqual(after['attempts']['music'],3);self.assertEqual(after['checkpoints'],before['checkpoints']);self.assertEqual(s.attempt_limit(j['id'],'music'),4)
  with s.db() as c:c.execute("UPDATE jobs SET state='failed',cancel=1 WHERE id=?",(j['id'],))
  with self.assertRaises(ValueError):s.resume(j['id'],scope,actor='service_recovery')
if __name__=='__main__':unittest.main()
