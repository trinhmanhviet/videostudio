import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
import httpx
from videostudio.providers import Pipeline
from videostudio.core import PermanentError
class ResearchRecoveryTests(unittest.TestCase):
 def job(self,t):return {'output':t,'request':{'idea':'medieval farming'},'checkpoints':{'plan':{'research_required':True,'research_query':'farming','source_urls':['https://en.wikipedia.org/wiki/Test']}}}
 def test_403_gets_alternate_not_bypass(self):
  with tempfile.TemporaryDirectory() as t:
   p=Pipeline.__new__(Pipeline);p.knowledge=None;calls=[]
   p.llm_json=lambda prompt,check:{'source_urls':['https://www.britannica.com/topic/agriculture']}
   def fetch(url,path):
    calls.append(url)
    if 'wikipedia' in url:raise httpx.HTTPStatusError('403 forbidden',request=httpx.Request('GET',url),response=httpx.Response(403))
    Path(path).write_text('Actual evidence');return {'path':str(path),'text':'Actual evidence','sha256':'fixture'}
   with patch('videostudio.sources.fetch_source',side_effect=fetch):r=p.research(self.job(t),lambda:None)
   self.assertEqual(len(calls),2);self.assertEqual(r['retrieval_errors'][0]['http_status'],403);self.assertTrue((Path(t)/'sources.json').exists())
 def test_budget_exhaustion_preserves_diagnostics(self):
  with tempfile.TemporaryDirectory() as t:
   p=Pipeline.__new__(Pipeline);p.knowledge=None;attempt=[]
   def llm(prompt,check):attempt.append(1);return {'source_urls':[f'https://www.britannica.com/test-{len(attempt)}']}
   p.llm_json=llm
   with patch('videostudio.sources.fetch_source',side_effect=ValueError('unavailable')):
    with self.assertRaises(PermanentError):p.research(self.job(t),lambda:None)
   self.assertEqual(len(attempt),2);self.assertEqual(len(json.loads((Path(t)/'research-retrieval-errors.json').read_text())['errors']),3)
if __name__=='__main__':unittest.main()
