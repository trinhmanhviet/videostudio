import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videostudio.providers import NarrationDurationError, Pipeline, flow_reference_enabled, validate_flow_character_manifest


class FlowCharacterManifestTests(unittest.TestCase):
    def valid_script(self):
        return {
            'narration': 'Cha đứng bên sông. Cha nhìn về phía đồng.',
            'source_paths': [],
            'characters': [{
                'character_id': 'father',
                'name': 'the father',
                'appearance_evidence': ['weathered face and gray beard'],
            }],
            'scenes': [
                {'narration': 'Cha đứng bên sông.', 'visual_prompt': 'A man with a weathered face and gray beard by a river at dawn.', 'character_ids': ['father']},
                {'narration': 'Cha nhìn về phía đồng.', 'visual_prompt': 'The same man with a weathered face and gray beard looks across the fields.', 'character_ids': ['father']},
            ],
        }

    def test_flow_manifest_accepts_explicit_repeating_character_evidence(self):
        script = self.valid_script()
        result = validate_flow_character_manifest(script)
        self.assertIs(result, script)
        self.assertEqual(script['flow_character_manifest_version'], 1)
        self.assertEqual(script['narration'], 'Cha đứng bên sông. Cha nhìn về phía đồng.')
        self.assertEqual(script['scenes'][0]['narration'], 'Cha đứng bên sông.')
        self.assertEqual(script['scenes'][0]['visual_prompt'], 'A man with a weathered face and gray beard by a river at dawn.')

    def test_flow_manifest_rejects_unknown_or_duplicate_scene_ids(self):
        script = self.valid_script()
        script['scenes'][0]['character_ids'] = ['unknown']
        with self.assertRaisesRegex(ValueError, 'Unknown Flow character_id'):
            validate_flow_character_manifest(script)
        script = self.valid_script()
        script['scenes'][0]['character_ids'] = ['father', 'father']
        with self.assertRaisesRegex(ValueError, 'Duplicate character_id'):
            validate_flow_character_manifest(script)

    def test_recurring_character_without_evidence_is_kept_and_drawn_without_a_portrait(self):
        # The video must not stop on a missing description: the character stays in the script with no
        # evidence, and its scenes are drawn without an identity portrait.
        script = self.valid_script()
        script['characters'][0]['appearance_evidence'] = []
        validate_flow_character_manifest(script)
        self.assertEqual(script['characters'][0]['appearance_evidence'], [])

    def test_unquoted_evidence_is_dropped_and_quoted_evidence_is_kept(self):
        script = self.valid_script()
        script['characters'][0]['appearance_evidence'] = ['blue wool coat', script['scenes'][0]['visual_prompt'].split('.')[0]]
        validate_flow_character_manifest(script)
        self.assertEqual(script['characters'][0]['appearance_evidence'], [script['scenes'][0]['visual_prompt'].split('.')[0].strip()])

    def test_overlong_evidence_is_shortened_at_a_clause_boundary(self):
        script = self.valid_script()
        long_text = script['scenes'][0]['visual_prompt'][:300]
        script['characters'][0]['appearance_evidence'] = [long_text]
        validate_flow_character_manifest(script)
        kept = script['characters'][0]['appearance_evidence']
        self.assertEqual(len(kept), 1)
        self.assertLessEqual(len(kept[0]), 180)
        self.assertIn(kept[0], script['scenes'][0]['visual_prompt'])

    def test_empty_cast_is_explicit_and_valid_for_non_character_scenes(self):
        script = {'characters': [], 'scenes': [{'narration': 'Mặt trời mọc.', 'visual_prompt': 'Sunrise over a quiet mountain valley.', 'character_ids': []}]}
        validate_flow_character_manifest(script)
        self.assertEqual(script['flow_character_manifest_version'], 1)

    def test_scene_mentions_use_registered_flow_names_in_scene_order(self):
        mother_id='22222222-2222-4222-8222-222222222222'
        father_id='11111111-1111-4111-8111-111111111111'
        references={
            'father':{'character_id':father_id,'name':'father','project_url':'https://flow.google.com/project/abc'},
            'mother':{'character_id':mother_id,'name':'mother','project_url':'https://flow.google.com/project/abc'},
        }
        mentions=Pipeline._flow_scene_mentions({'character_ids':['mother','father']},references)
        self.assertEqual(mentions,[
            {'character_id':mother_id,'name':'mother','project_url':'https://flow.google.com/project/abc'},
            {'character_id':father_id,'name':'father','project_url':'https://flow.google.com/project/abc'},
        ])

    def test_flow_script_prompt_requests_manifest_without_rewriting_scene_text(self):
        p = Pipeline.__new__(Pipeline)
        script = self.valid_script()
        p.llm_json = Mock(return_value=script)
        job = {
            'request': {'image_provider': 'flow', 'duration_seconds': 30, 'idea': 'Một câu chuyện về người cha'},
            'checkpoints': {'plan': {}, 'research': {'sources': []}},
        }
        result = p._script_draft(job, lambda: None, [])
        prompt = p.llm_json.call_args.args[0]
        self.assertIn('FLOW CHARACTER REFERENCES', prompt)
        self.assertIn('character_ids', prompt)
        self.assertEqual(result['narration'], script['narration'])
        self.assertEqual(result['scenes'], script['scenes'])
        self.assertEqual(result['flow_character_manifest_version'], 1)

    def test_non_flow_script_prompt_does_not_enable_flow_manifest_mode(self):
        p = Pipeline.__new__(Pipeline)
        script = {'narration': 'Mặt trời mọc.', 'source_paths': [], 'scenes': [{'narration': 'Mặt trời mọc.', 'visual_prompt': 'Sunrise over a valley.'}]}
        p.llm_json = Mock(return_value=script)
        job = {
            'request': {'image_provider': 'comfy', 'duration_seconds': 30, 'idea': 'Bình minh'},
            'checkpoints': {'plan': {}, 'research': {'sources': []}},
        }
        result = p._script_draft(job, lambda: None, [])
        self.assertNotIn('FLOW CHARACTER REFERENCES', p.llm_json.call_args.args[0])
        self.assertNotIn('flow_character_manifest_version', result)

    def test_flow_natural_duration_preserves_script_and_manifest_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline.__new__(Pipeline)
            script = self.valid_script();script['flow_character_manifest_version'] = 1
            p._speech_attempt = Mock(return_value={'duration_seconds': 35, 'assets': []})
            p.llm_json = Mock(return_value={'scenes': [
                {'narration': 'Cha nhìn ra đồng.', 'visual_prompt': 'A man with a weathered face and gray beard watches a field.', 'character_ids': ['father']},
                {'narration': 'Cha bước chậm.', 'visual_prompt': 'The same man with a weathered face and gray beard walks slowly.', 'character_ids': ['father']},
            ]})
            job = {'id': 'test-flow-job', 'output': tmp, 'request': {'image_provider': 'flow', 'duration_seconds': 30, 'voice_id': 'voice'}, 'checkpoints': {'script': script, 'research': {'sources': []}}}
            with patch.dict('os.environ', {'VS_DURATION_REWRITE_ATTEMPTS': '2'}):
                result = p.speech(job, lambda: None)
            final = json.loads((Path(tmp) / 'final-script.json').read_text(encoding='utf8'))
            self.assertEqual(result['duration_attempts'], 1)
            p.llm_json.assert_not_called()
            self.assertEqual(final['narration'], script['narration'])
            self.assertEqual(final['characters'], script['characters'])
            self.assertEqual([s['character_ids'] for s in final['scenes']], [['father'], ['father']])

    def test_native_character_receipt_is_stable_across_retries_without_portrait_uploads(self):
        job_id = 'd4e93c6c-f93e-49e5-9c88-0cd29b719e0d'
        character_id = '11111111-1111-4111-8111-111111111111'
        project_url = 'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'
        p = Pipeline.__new__(Pipeline);calls=[]
        def create(job, character, prompt, check, *, task_id=None):
            calls.append((character['character_id'], task_id, prompt))
            return {'task_id':task_id,'character_id':character_id,'name':character['character_id'],'project_url':project_url}
        p._browser_flow_character=Mock(side_effect=create)
        with tempfile.TemporaryDirectory() as tmp:
            script=validate_flow_character_manifest(self.valid_script())
            job={'id':job_id,'output':tmp,'checkpoints':{'script':script}}
            first,assets=p._flow_native_characters(job,lambda:None)
            second,_=p._flow_native_characters(job,lambda:None)
            expected=str(__import__('uuid').uuid5(__import__('uuid').UUID(job_id),'flow-native-character:father'))
            self.assertEqual(first['father']['task_id'],expected)
            self.assertEqual(second['father']['character_id'],character_id)
            self.assertEqual(second['father']['name'],'father')
            self.assertEqual(len(calls),1)
            self.assertEqual(len(assets),1)
            self.assertFalse((Path(tmp)/'flow-character-references'/'father.png').exists())
            self.assertTrue((Path(tmp)/'flow-character-references.json').is_file())


    def test_recurring_character_without_quoted_traits_gets_a_portrait_from_its_planned_description(self):
        long_sentence = ('A 26-year-old Han Chinese woman, 163 cm tall with a petite, agile build, a small heart-shaped face, bright '
                         'almond-shaped eyes, a rounded nose tip, a distinctive beauty mark beside her left eyebrow and an asymmetrical '
                         'blue-black chin-length bob tucked behind one ear.')
        p = Pipeline.__new__(Pipeline);prompts=[]
        def create(job, character, prompt, check, *, task_id=None):
            prompts.append(prompt)
            return {'task_id':task_id,'character_id':'11111111-1111-4111-8111-111111111111','name':character['character_id'],
                    'project_url':'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc'}
        p._browser_flow_character=Mock(side_effect=create)
        with tempfile.TemporaryDirectory() as tmp:
            script=self.valid_script();script['characters'][0]['appearance_evidence']=[]
            script=validate_flow_character_manifest(script)
            job={'id':'d4e93c6c-f93e-49e5-9c88-0cd29b719e0d','output':tmp,'checkpoints':{'script':script,
                 'plan':{'characters':[{'character_id':'father','description':long_sentence+' She wears a purple apron.'}]}}}
            refs,_=p._flow_native_characters(job,lambda:None)
        self.assertIn('father',refs)
        self.assertIn('beauty mark beside her left eyebrow',prompts[0])
        self.assertIn('She wears a purple apron.',prompts[0])

    def test_long_form_flow_uses_references_without_five_minute_limit(self):
        for duration in (8,300,301,1800,7200):
            self.assertTrue(flow_reference_enabled({'request':{'image_provider':'flow','duration_seconds':duration}}))


if __name__ == '__main__':
    unittest.main()
