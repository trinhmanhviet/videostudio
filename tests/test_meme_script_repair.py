import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from test_meme_mode import story
from videostudio.meme_script import validate,MemeScriptError
from videostudio.meme_catalog import load_catalog
from videostudio import meme_pipeline

class ScriptTypeRepairTests(unittest.TestCase):
    def test_wrong_asset_types_are_validation_errors_then_lenient_defaults(self):
        catalog=load_catalog();request={'idea':'x','duration_seconds':20}
        for field in ('pose','face','prop','partner','bg'):
            for value in (['stand_talk'],{'id':'stand_talk'},True,123):
                bad=story();bad['beats'][0][field]=value
                with self.subTest(field=field,value=value):
                    with self.assertRaises(MemeScriptError):validate(bad,catalog,request)
                    fixed=validate(bad,catalog,request,lenient=True)
                    self.assertEqual(len(fixed['beats']),8)
        for fx in ({'id':'sweat'},[['sweat']], [{'id':'sweat'}],True):
            bad=story();bad['beats'][0]['fx']=fx
            with self.subTest(fx=fx):
                with self.assertRaises(MemeScriptError):validate(bad,catalog,request)
                self.assertEqual(validate(bad,catalog,request,lenient=True)['beats'][0]['fx'],[])
    def test_saved_bad_reply_advances_to_repair_and_is_not_parsed_again(self):
        with tempfile.TemporaryDirectory() as folder:
            job={'id':'j','output':folder,'request':{'idea':'x','duration_seconds':20,'workflow_mode':'meme'},'checkpoints':{}}
            bad=story();bad['beats'][0]['pose']=['stand_talk']
            path=Path(folder)/'meme-script-attempt-00.json';path.write_text(json.dumps(bad),encoding='utf-8')
            pipeline=Mock();pipeline.llm_json.return_value=story()
            result=meme_pipeline.script(pipeline,job,lambda:None)
            self.assertEqual(len(result['scenes']),8);self.assertEqual(pipeline.llm_json.call_count,1)
            self.assertIn('pose',pipeline.llm_json.call_args.args[0])
            pipeline.llm_json.reset_mock();original=Path.read_text
            def read(value,*args,**kwargs):
                if value==path:raise AssertionError('Known rejected response parsed again')
                return original(value,*args,**kwargs)
            with patch.object(Path,'read_text',read):meme_pipeline.script(pipeline,job,lambda:None)
            pipeline.llm_json.assert_not_called()
    def test_budget_is_bounded_and_malformed_ids_do_not_poison_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            job={'id':'j','output':folder,'request':{'idea':'x','duration_seconds':20,'workflow_mode':'meme'},'checkpoints':{}}
            bad=story();bad['beats'][0].update(pose=['stand_talk'],bg={'id':'room_day'},fx=[{}])
            pipeline=Mock();pipeline.llm_json.return_value=bad
            result=meme_pipeline.script(pipeline,job,lambda:None)
            self.assertEqual(pipeline.llm_json.call_count,3);self.assertEqual(result['scenes'][0]['meme']['pose'],'stand_talk')
            pipeline.llm_json.reset_mock();meme_pipeline.script(pipeline,job,lambda:None);pipeline.llm_json.assert_not_called()
