import json,tempfile,unittest
from pathlib import Path
from videostudio.providers import Pipeline
from videostudio.core import PermanentError

class PragmaticScriptTests(unittest.TestCase):
    def job(self,t):
        return {'output':t,'request':{'workflow_mode':'research','idea':'test'},'checkpoints':{'research':{'sources':[],'context':{}}}}
    def draft(self):
        return {'narration':'Một câu đúng. Một chi tiết chưa rõ. Kết thúc.', 'scenes':[
            {'scene_id':'a','narration':'Một câu đúng.','visual_prompt':'first'},
            {'scene_id':'b','narration':'Một chi tiết chưa rõ.','visual_prompt':'second'},
            {'scene_id':'c','narration':'Kết thúc.','visual_prompt':'third'}]}
    def test_one_review_omits_uncertain_detail_without_rewriting_or_rechecking(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);p._script_draft=lambda *args:self.draft();calls=[]
            def review(*args):
                calls.append(1)
                if len(calls)>1:raise AssertionError('No rewrite/review loop allowed')
                return {'accepted':False,'blocking_issues':[{'scene_index':1,'category':'unsupported_specific','reason':'not established'}],'issues':['style could be better']}
            p.llm_json=review
            result=p.script(self.job(t),lambda:None)
            self.assertEqual(len(calls),1)
            self.assertEqual([s['scene_id'] for s in result['scenes']],['a','c'])
            self.assertEqual(result['narration'],'Một câu đúng. Kết thúc.')
            self.assertTrue(result['quality_review']['accepted'])
            self.assertFalse(result['quality_review']['model_accepted'])
            self.assertEqual(result['quality_review']['omitted_scene_indices'],[1])
            self.assertFalse(json.loads((Path(t)/'script-attempt-00.review.json').read_text())['accepted'])
    def test_failed_fourth_review_recovers_latest_saved_draft_without_any_chatgpt_call(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline)
            def forbidden(*args):raise AssertionError('Saved failed script must not send another prompt')
            p._script_draft=p.llm_json=forbidden
            for i in [0,3]:
                d=self.draft();d['scenes'][0]['narration']=f'Bản {i}.'
                (Path(t)/f'script-attempt-{i:02}.draft.json').write_text(json.dumps(d))
                (Path(t)/f'script-attempt-{i:02}.review.json').write_text(json.dumps({'accepted':False,'blocking_issues':[{'scene_index':1,'reason':'unclear'}]}))
            result=p.script(self.job(t),lambda:None)
            self.assertEqual(result['scenes'][0]['narration'],'Bản 3.')
    def test_style_only_rejection_does_not_block_usable_script(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);p._script_draft=lambda *args:self.draft()
            p.llm_json=lambda *args:{'accepted':False,'blocking_issues':[],'issues':['could be shorter']}
            result=p.script(self.job(t),lambda:None)
            self.assertEqual(len(result['scenes']),3)
            self.assertEqual(result['quality_review']['omitted_scene_indices'],[])
    def test_no_usable_scene_is_not_pretended_to_be_a_valid_script(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);p._script_draft=lambda *args:self.draft()
            p.llm_json=lambda *args:{'accepted':False,'blocking_issues':[{'scene_index':i,'reason':'unsupported'} for i in range(3)]}
            with self.assertRaises(PermanentError):p.script(self.job(t),lambda:None)
    def test_keeps_frozen_visual_traits_when_their_original_scene_is_omitted(self):
        p=Pipeline.__new__(Pipeline);d=self.draft()
        d['characters']=[{'character_id':'person','appearance_evidence':['blue shirt']}]
        for scene in d['scenes']:scene['character_ids']=['person']
        d['scenes'][1]['visual_prompt']='person in blue shirt'
        result=p._pragmatic_research_script(d,{'accepted':False,'blocking_issues':[{'scene_index':1}]})
        self.assertIn('blue shirt',result['scenes'][0]['visual_prompt'])
        self.assertEqual(d['scenes'][0]['visual_prompt'],'first')

if __name__=='__main__':unittest.main()
