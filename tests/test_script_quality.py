import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from videostudio.providers import Pipeline, UncertainDeliveryError
from videostudio.core import PermanentError
class ScriptQualityTests(unittest.TestCase):
    def test_rejects_invented_quote_with_finite_budget(self):
        with tempfile.TemporaryDirectory() as t, patch.dict('os.environ',{'VS_SCRIPT_REPAIR_ATTEMPTS':'2'}):
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
    def test_style_suggestions_are_nonblocking_when_evidence_is_valid(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline)
            p._script_draft=lambda j,c,f:{'narration':'Lời bình về người thợ','scenes':[{'narration':'Lời bình về người thợ','visual_prompt':'a workshop'}],'source_paths':['source']}
            p.llm_json=lambda prompt,check:{'accepted':False,'blocking_issues':[],'issues':['Lời bình có thể gọn hơn'],'claims':[{'statement':'Lịch sử giáp','source_path':'source','quote':'independently retrieved reference'}]}
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            result=p.script(j,lambda:None)
            self.assertEqual(result['narration'],'Lời bình về người thợ')
            self.assertTrue((Path(t)/'script-quality.json').exists())

    def test_repairs_only_flagged_scene_and_persists_rejected_review(self):
        with tempfile.TemporaryDirectory() as t, patch.dict('os.environ',{'VS_SCRIPT_REPAIR_ATTEMPTS':'3'}):
            p=Pipeline.__new__(Pipeline); drafted=[]
            initial={'narration':'Một câu đúng. Một câu suy diễn.','source_paths':['source'], 'scenes':[
                {'narration':'Một câu đúng.','visual_prompt':'first scene'},
                {'narration':'Một câu suy diễn.','visual_prompt':'second scene'}]}
            p._script_draft=lambda j,c,f:(drafted.append(1) or initial.copy())
            quote={'statement':'Lịch sử giáp','source_path':'source','quote':'independently retrieved reference'}
            responses=[
                {'accepted':False,'blocking_issues':[{'scene_index':1,'category':'unsupported_fact','reason':'Không có bằng chứng'}],'issues':['Sửa câu 2'],'claims':[quote]},
                {'changes':[{'index':1,'narration':'Một câu đã kiểm chứng.','visual_prompt':'second scene'}]},
                {'accepted':True,'blocking_issues':[],'issues':[],'claims':[quote]},
            ]
            p.llm_json=lambda prompt,check:responses.pop(0)
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            result=p.script(j,lambda:None)
            self.assertEqual(len(drafted),1)
            self.assertEqual([s['narration'] for s in result['scenes']],['Một câu đúng.','Một câu đã kiểm chứng.'])
            self.assertTrue((Path(t)/'script-attempt-00.review.json').exists())
            self.assertTrue((Path(t)/'script-attempt-01.draft.json').exists())

    def test_resume_uses_saved_draft_and_review_without_repeating_calls(self):
        with tempfile.TemporaryDirectory() as t, patch.dict('os.environ',{'VS_SCRIPT_REPAIR_ATTEMPTS':'3'}):
            p=Pipeline.__new__(Pipeline); drafts=[]
            p._script_draft=lambda j,c,f:(drafts.append(1) or {'narration':'Sai','source_paths':['source'],'scenes':[{'narration':'Sai','visual_prompt':'scene'}]})
            quote={'statement':'Claim','source_path':'source','quote':'independently retrieved reference'}
            calls=[]
            def first(prompt,check):
                calls.append('review')
                return {'accepted':False,'blocking_issues':[{'scene_index':0,'category':'unsupported_fact','reason':'sai'}],'issues':['sai'],'claims':[quote]}
            p.llm_json=first
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            # Simulate interruption after durable review: no second prompt may be sent for it.
            with self.assertRaises(RuntimeError):
                def interrupted(prompt,check):
                    if calls:raise RuntimeError('connection dropped after review')
                    return first(prompt,check)
                p.llm_json=interrupted
                p.script(j,lambda:None)
            self.assertTrue((Path(t)/'script-attempt-00.review.json').exists())
            resumed=[]
            def second(prompt,check):
                resumed.append(prompt)
                if len(resumed)==1:return {'changes':[{'index':0,'narration':'Đúng','visual_prompt':'scene'}]}
                return {'accepted':True,'blocking_issues':[],'issues':[],'claims':[quote]}
            p.llm_json=second
            self.assertEqual(p.script(j,lambda:None)['scenes'][0]['narration'],'Đúng')
            self.assertEqual(len(drafts),1)
            self.assertEqual(len(resumed),2)

    def test_uncertain_review_reconciles_identical_prompt_after_stage_retry(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline);drafted=[];prompts=[]
            p._script_draft=lambda j,c,f:(drafted.append(1) or {'narration':'Đúng','scenes':[{'narration':'Đúng','visual_prompt':'armor'}],'source_paths':['source']})
            def review(prompt,check):
                prompts.append(prompt)
                if len(prompts)==1:raise UncertainDeliveryError('receipt retained')
                return {'accepted':True,'claims':[{'statement':'Claim','source_path':'source','quote':'independently retrieved reference'}],'issues':[]}
            p.llm_json=review
            j={'output':t,'request':{'idea':'test'},'checkpoints':{'research':{'sources':[{'path':'source','text':'The actual independently retrieved reference text.'}]}}}
            with self.assertRaises(UncertainDeliveryError):p.script(j,lambda:None)
            self.assertEqual(p.script(j,lambda:None)['narration'],'Đúng')
            self.assertEqual(len(drafted),1)
            self.assertEqual(prompts[0],prompts[1])

    def test_chapters_pipeline_for_long_duration_video(self):
        with tempfile.TemporaryDirectory() as t:
            p=Pipeline.__new__(Pipeline); calls=[]
            def fake_llm(prompt,check):
                calls.append(prompt)
                if 'Plan a cohesive' in prompt:
                    return {'chapters':[
                        {'index':1,'title':'Mở đầu và biến cố','summary':'Giáp xích thế kỷ 11'},
                        {'index':2,'title':'Cao trào và súng đạn','summary':'Giáp tấm và súng hỏa mai'}
                    ]}
                elif 'Chapter 1' in prompt:
                    return {'narration':'Một thanh kiếm chém xuống. Người thợ rèn phải tìm cách giữ hiệp sĩ sống sót.','source_paths':['source'],
                            'scenes':[{'narration':'Một thanh kiếm chém xuống.','visual_prompt':'close-up 35mm f/2.0 of sword clash'},
                                     {'narration':'Người thợ rèn phải tìm cách giữ hiệp sĩ sống sót.','visual_prompt':'medium shot of medieval forge'}]}
                elif 'Chapter 2' in prompt:
                    return {'narration':'Súng hỏa mai xuất hiện trên chiến trường. Áo giáp tấm dày hơn nhưng quá nặng.','source_paths':['source'],
                            'scenes':[{'narration':'Súng hỏa mai xuất hiện trên chiến trường.','visual_prompt':'musket smoke on battlefield'},
                                     {'narration':'Áo giáp tấm dày hơn nhưng quá nặng.','visual_prompt':'heavy bullet-proof breastplate'}]}
                raise ValueError('Unexpected prompt: '+prompt[:50])
            p.llm_json=fake_llm
            j={'output':t,'request':{'duration_seconds':600,'idea':'Lịch sử áo giáp'},'checkpoints':{'plan':{},'research':{'sources':[{'path':'source','text':'Nguồn tham khảo bảo tàng.'}]}}}
            d=p._script_draft(j,lambda:None,[])
            self.assertEqual(len(calls),3)
            self.assertEqual(len(d['scenes']),4)
            self.assertTrue((Path(t)/'chapters.json').exists())
            self.assertTrue((Path(t)/'chapter-01.json').exists())
            self.assertTrue((Path(t)/'chapter-02.json').exists())
            self.assertIn('Một thanh kiếm chém xuống',d['narration'])
            self.assertIn('Súng hỏa mai xuất hiện',d['narration'])

if __name__=='__main__':unittest.main()
