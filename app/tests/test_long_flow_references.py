import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from videostudio.providers import Pipeline,validate_flow_character_manifest


class LongFlowReferencesTests(unittest.TestCase):
    def test_saved_script_draft_is_upgraded_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);draft={'narration':'Keep this line.','scenes':[{'narration':'Keep this line.','visual_prompt':'A man with short black hair'}]}
            path=root/'script-attempt-00.draft.json';path.write_text(json.dumps(draft));original=path.read_bytes()
            (root/'script-attempt-00.review.json').write_text(json.dumps({'accepted':True,'blocking_issues':[]}))
            pipeline=Pipeline.__new__(Pipeline)
            pipeline.llm_json=Mock(return_value={'characters':[{'character_id':'father','name':'Father','appearance_evidence':['short black hair']}],'scene_character_ids':[['father']]})
            job={'id':'test','output':folder,'request':{'duration_seconds':1800,'image_provider':'flow','workflow_mode':'research'},'checkpoints':{'plan':{},'research':{'sources':[]}}}
            result=pipeline.script(job,lambda:None)
            validate_flow_character_manifest(result)
            self.assertEqual(result['narration'],draft['narration'])
            self.assertEqual(path.read_bytes(),original)
            pipeline.llm_json.assert_called_once()

    def test_two_chapters_share_character_identity_without_duration_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            pipeline=Pipeline.__new__(Pipeline)
            character={'character_id':'father','name':'Father','appearance_evidence':['short black hair']}
            pipeline.llm_json=Mock(side_effect=[{'chapters':[{'index':1},{'index':2}]},
                {'narration':'First sentence.','scenes':[{'narration':'First sentence.','visual_prompt':'A man with short black hair','character_ids':['father']}],'characters':[character]},
                {'narration':'Second sentence.','scenes':[{'narration':'Second sentence.','visual_prompt':'The man by the window','character_ids':['father']}],'characters':[character]}])
            job={'output':folder,'request':{'duration_seconds':1800,'image_provider':'flow','workflow_mode':'research'},'checkpoints':{'plan':{},'research':{'sources':[]}}}
            result=pipeline._script_draft(job,lambda:None,[])
            validate_flow_character_manifest(result)
            self.assertEqual(len(result['characters']),1)
            self.assertTrue(all(s['character_ids']==['father'] for s in result['scenes']))
            self.assertTrue(all('short black hair' in s['visual_prompt'] for s in result['scenes']))
            self.assertIn('canonical_characters',pipeline.llm_json.call_args.args[0])

    def test_cached_legacy_chapters_get_metadata_once_without_rewriting_narration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'chapters.json').write_text(json.dumps({'chapters':[{'index':1},{'index':2}]}))
            for i in (1,2):(root/f'chapter-{i:02}.json').write_text(json.dumps({'narration':f'Keep line {i}.','scenes':[{'narration':f'Keep line {i}.','visual_prompt':'A man with short black hair'}]}))
            pipeline=Pipeline.__new__(Pipeline)
            pipeline.llm_json=Mock(return_value={'characters':[{'character_id':'father','name':'Father','appearance_evidence':['short black hair']}],'scene_character_ids':[['father']]})
            job={'output':folder,'request':{'duration_seconds':1800,'image_provider':'flow'},'checkpoints':{'plan':{},'research':{'sources':[]}}}
            for _ in range(2):
                result=pipeline._script_draft(job,lambda:None,[])
                validate_flow_character_manifest(result)
                self.assertEqual(result['narration'],'Keep line 1. Keep line 2.')
            self.assertEqual(pipeline.llm_json.call_count,2)
