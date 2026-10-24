import tempfile
import unittest
from pathlib import Path
from videostudio.cdp_requests import RequestJournal, IndeterminateRequest


class RequestJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'requests.db'
        self.j=RequestJournal(self.path)
    def tearDown(self):self.tmp.cleanup()
    def test_same_job_and_prompt_reuse_request_different_job_does_not(self):
        a=self.j.prepare('job-a','hello');b=self.j.prepare('job-a','hello');c=self.j.prepare('job-b','hello')
        self.assertEqual(a['id'],b['id']);self.assertNotEqual(a['id'],c['id'])
    def test_uncertain_send_survives_restart_and_never_allows_second_send(self):
        r=self.j.prepare('job','hello');self.j.claim_send(r['id'])
        restarted=RequestJournal(self.path)
        with self.assertRaises(IndeterminateRequest):restarted.claim_send(r['id'])
    def test_completed_result_is_immutable_and_cached(self):
        r=self.j.prepare('job','hello');self.j.complete(r['id'],{'ok':True})
        self.assertEqual(self.j.prepare('job','hello')['response'],{'ok':True})
        with self.assertRaises(ValueError):self.j.complete(r['id'],{'ok':False})
    def test_completion_requires_matching_request_marker(self):
        r=self.j.prepare('job','hello')
        with self.assertRaises(ValueError):self.j.accept(r['id'],{'request_id':'old','result':{'old':True}})
        self.j.accept(r['id'],{'request_id':r['id'],'result':{'new':True}})
        self.assertEqual(self.j.get(r['id'])['response'],{'new':True})
    def test_conversation_url_must_be_chatgpt(self):
        with self.assertRaises(ValueError):self.j.set_conversation('job','https://evil.example/c/x','a')
        self.j.set_conversation('job','https://chatgpt.com/c/abc','target')
        self.assertEqual(self.j.conversation('job')['target'],'target')

if __name__=='__main__':unittest.main()
