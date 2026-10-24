import unittest
from videostudio.cdp_page import correlate_turns


class TurnCorrelationTests(unittest.TestCase):
    def test_modern_complete_turn_matches_user_marker_and_not_last_arbitrary_text(self):
        state={'matched':False,'text':'','generating':False,'turns':[{'user':'old marker','assistant':'wrong','state':'complete'},{'user':'[request xyz] prompt','assistant':'{"request_id":"xyz","result":{"ok":true}}','state':'complete','id':'message'}]}
        got=correlate_turns(state,'[request xyz]')
        self.assertTrue(got['matched']);self.assertFalse(got['generating'])
        self.assertIn('"xyz"',got['text']);self.assertEqual(got['messageId'],'message')
    def test_streaming_turn_never_counts_as_completed(self):
        state={'matched':False,'turns':[{'user':'[request xyz]','assistant':'{"ok":true}','state':'streaming'}]}
        got=correlate_turns(state,'[request xyz]')
        self.assertTrue(got['generating']);self.assertEqual(got['text'],'')
    def test_unrelated_turn_is_not_a_response(self):
        state={'matched':False,'turns':[{'user':'unrelated','assistant':'{"ok":true}','state':'complete'}]}
        self.assertFalse(correlate_turns(state,'expected')['matched'])
    def test_ambiguous_duplicate_markers_fail_closed(self):
        row={'user':'marker','assistant':'{}','state':'complete'}
        self.assertFalse(correlate_turns({'matched':False,'turns':[row,row]},'marker')['matched'])
    def test_legacy_correlated_messages_are_preserved(self):
        state={'matched':True,'text':'legacy','generating':False}
        self.assertEqual(correlate_turns(state,'marker'),state)

if __name__=='__main__':unittest.main()
