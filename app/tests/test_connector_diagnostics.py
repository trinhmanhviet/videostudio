import unittest
from videostudio.connector_diagnostics import sanitize_status
class DiagnosticsTests(unittest.TestCase):
 def test_runtime_version_is_preserved_without_leaking_raw_state(self):
  self.assertEqual(sanitize_status({'runtime_version':'0.3.3','raw_state':'PRIVATE'}),{'runtime_version':'0.3.3'})
 def test_keeps_error_code_and_recent_bounded_logs(self):
  s=sanitize_status({'build':'0.1.24','stage':'error','enabled':False,'error':{'code':'BRIDGE_INTERRUPTED','message':'Receiving end does not exist','raw_prompt':'PRIVATE'},'logs':[{'at':i,'message':'x'*3000,'code':'NETWORK'} for i in range(30)]})
  self.assertEqual(s['error']['code'],'BRIDGE_INTERRUPTED');self.assertNotIn('raw_prompt',s['error']);self.assertEqual(len(s['logs']),15);self.assertEqual(len(s['logs'][0]['message']),600)
 def test_redacts_credentials(self):
  s=sanitize_status({'error':{'code':'AUTH','message':'Bearer abc123 access_token=token123 password=secretvalue'}})
  self.assertNotIn('abc123',s['error']['message']);self.assertNotIn('token123',s['error']['message']);self.assertNotIn('secretvalue',s['error']['message'])
 def test_missing_diagnostics_does_not_change_existing_shape(self):
  original={'build':'0.1.24','stage':'idle','enabled':False,'connected':True};self.assertEqual(sanitize_status(original),original)
if __name__=='__main__':unittest.main()
