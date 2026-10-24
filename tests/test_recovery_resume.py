import tempfile,unittest
from pathlib import Path
from videostudio.core import Store,Worker,STAGES
from videostudio.exchanges import Exchanges
class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name);self.s=Store(p/'db',p/'out');self.ex=Exchanges(self.s);self.scope=self.ex.scope();self.job,_=self.s.create({'idea':'test','voice_id':'chosen','duration_seconds':12},'one',self.scope)
 def tearDown(self):self.temp.cleanup()
 def fail_speech(self):
  h={stage:(lambda j,check:{'ok':True}) for stage in STAGES}
  def speech(j,check):raise TimeoutError('Chrome connector response unavailable; request retained for correlated recovery, not resubmitted')
  h['speech']=speech;w=Worker(self.s,h,backoff=0)
  for _ in range(6):w.step()
  return h
 def test_one_extra_attempt_is_persistent_not_counter_reset(self):
  h=self.fail_speech();before=self.s.get(self.job['id']);self.assertEqual(before['state'],'failed');self.assertEqual(before['attempts']['speech'],3)
  after=self.s.resume(self.job['id'],self.scope);self.assertEqual(after['attempts']['speech'],3);self.assertEqual(after['checkpoints'],before['checkpoints']);self.assertEqual(self.s.attempt_limit(self.job['id'],'speech'),4)
  fresh=Store(self.s.path,self.s.outputs);Worker(fresh,h,backoff=0).step();after=fresh.get(self.job['id']);self.assertEqual(after['attempts']['speech'],4);self.assertEqual(after['state'],'failed')
  with self.assertRaises(ValueError):fresh.resume(self.job['id'],self.scope)
 def test_repaired_attempt_can_continue_without_new_job(self):
  h=self.fail_speech();self.s.resume(self.job['id'],self.scope);h['speech']=lambda j,c:{'duration':12};h['verify']=lambda j,c:{'verified':True}
  w=Worker(self.s,h,backoff=0)
  for _ in range(6):w.step()
  j=self.s.get(self.job['id']);self.assertEqual(j['state'],'completed');self.assertEqual(j['attempts']['speech'],4);self.assertEqual(len(self.s.list()),1)
 def test_foreign_scope_and_completed_or_active_rejected(self):
  with self.assertRaises(ValueError):self.s.resume(self.job['id'],self.scope)
  self.s.cancel(self.job['id'])
  with self.assertRaises(ValueError):self.s.resume(self.job['id'],self.ex.scope())
  j=self.s.resume(self.job['id'],self.scope);self.assertFalse(j['cancel']);self.assertEqual(j['state'],'queued')
if __name__=='__main__':unittest.main()
