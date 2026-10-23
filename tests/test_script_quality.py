import unittest,tempfile
from pathlib import Path
from videostudio.providers import Pipeline
from videostudio.core import PermanentError
class ScriptQualityTests(unittest.TestCase):
    def test_rejects_invented_quote_with_finite_budget(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);calls=[]
            p._script_draft=lambda j,check,feedback:{'narration':'A fact','scenes':[]}
            def review(prompt,check):calls.append(prompt);return {'accepted':True,'claims':[{'statement':'Claim','source_path':'source','quote':'fabricated reference quote'}],'issues':[]}
            p.llm_json=review
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            with self.assertRaises(PermanentError):p.script(j,lambda:None)
            self.assertEqual(len(calls),2)
    def test_accepts_exact_evidence_quote(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);p._script_draft=lambda j,c,f:{'narration':'A fact','scenes':[]}
            p.llm_json=lambda p,c:{'accepted':True,'claims':[{'statement':'Claim','source_path':'source','quote':'independently retrieved reference'}],'issues':[]}
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            self.assertTrue(p.script(j,lambda:None)['quality_review']['accepted'])
            self.assertTrue((Path(t)/'script-quality.json').exists())
if __name__=='__main__':unittest.main()
