import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from videostudio.providers import Pipeline,NarrationDurationError
from videostudio.core import PermanentError
class RewriteTests(unittest.TestCase):
    def job(self,t):return {'id':'test-job','output':t,'request':{'duration_seconds':30,'voice_id':'unchanged-clone'},'checkpoints':{'script':{'narration':'Xin chào','scenes':[{'narration':'Xin chào','visual_prompt':'Morning light'}]},'research':{'sources':[]}}}
    def test_rewrite_uses_finite_budget_and_final_script(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);calls=[];prompts=[]
            def synth(j,check,revision):
                calls.append(j['request']['voice_id'])
                if len(calls)<3:raise NarrationDurationError('Measured 35 seconds, target 30')
                return {'duration_seconds':29.5,'assets':[]}
            p._speech_attempt=synth
            p.llm_json=lambda prompt,check:prompts.append(prompt) or {'scenes':[{'narration':'Nắng sớm dịu dàng.','visual_prompt':'Same morning light'}]}
            with patch.dict('os.environ',{'VS_DURATION_REWRITE_ATTEMPTS':'3'}):result=p.speech(self.job(t),lambda:None)
            self.assertEqual(calls,['unchanged-clone']*3);self.assertEqual(len(prompts),2);self.assertEqual(result['duration_attempts'],3);self.assertTrue((Path(t)/'final-script.json').is_file())
    def test_exhaustion_does_not_change_duration_or_voice(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);calls=[]
            def synth(j,check,revision):calls.append(j['request'].copy());raise NarrationDurationError('Too long')
            p._speech_attempt=synth;p.llm_json=lambda prompt,check:{'scenes':[{'narration':'Ngắn hơn.','visual_prompt':'Same scene'}]}
            with patch.dict('os.environ',{'VS_DURATION_REWRITE_ATTEMPTS':'2'}):
                with self.assertRaises(PermanentError):p.speech(self.job(t),lambda:None)
            self.assertEqual(len(calls),2);self.assertTrue(all(x['duration_seconds']==30 and x['voice_id']=='unchanged-clone' for x in calls))
if __name__=='__main__':unittest.main()
