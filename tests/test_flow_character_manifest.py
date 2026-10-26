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

    def test_recurring_character_without_evidence_fails_closed(self):
        script = self.valid_script()
        script['characters'][0]['appearance_evidence'] = []
        with self.assertRaisesRegex(ValueError, 'no explicit appearance evidence'):
            validate_flow_character_manifest(script)

    def test_appearance_evidence_must_be_verbatim_in_a_relevant_scene_prompt(self):
        script = self.valid_script()
        script['characters'][0]['appearance_evidence'] = ['blue wool coat']
        with self.assertRaisesRegex(ValueError, 'not a verbatim substring'):
            validate_flow_character_manifest(script)

    def test_empty_cast_is_explicit_and_valid_for_non_character_scenes(self):
        script = {'characters': [], 'scenes': [{'narration': 'Mặt trời mọc.', 'visual_prompt': 'Sunrise over a quiet mountain valley.', 'character_ids': []}]}
        validate_flow_character_manifest(script)
        self.assertEqual(script['flow_character_manifest_version'], 1)

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

    def test_flow_short_duration_rewrite_preserves_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline.__new__(Pipeline)
            script = self.valid_script();script['flow_character_manifest_version'] = 1
            p._speech_attempt = Mock(side_effect=[NarrationDurationError('too long'), {'duration_seconds': 29.5, 'assets': []}])
            p.llm_json = Mock(return_value={'scenes': [
                {'narration': 'Cha nhìn ra đồng.', 'visual_prompt': 'A man with a weathered face and gray beard watches a field.', 'character_ids': ['father']},
                {'narration': 'Cha bước chậm.', 'visual_prompt': 'The same man with a weathered face and gray beard walks slowly.', 'character_ids': ['father']},
            ]})
            job = {'id': 'test-flow-job', 'output': tmp, 'request': {'image_provider': 'flow', 'duration_seconds': 30, 'voice_id': 'voice'}, 'checkpoints': {'script': script, 'research': {'sources': []}}}
            with patch.dict('os.environ', {'VS_DURATION_REWRITE_ATTEMPTS': '2'}):
                result = p.speech(job, lambda: None)
            final = json.loads((Path(tmp) / 'final-script.json').read_text(encoding='utf8'))
            self.assertEqual(result['duration_attempts'], 2)
            self.assertEqual(final['characters'], script['characters'])
            self.assertEqual([s['character_ids'] for s in final['scenes']], [['father'], ['father']])

    def test_portrait_task_id_and_receipt_are_stable_across_retries(self):
        job_id = 'd4e93c6c-f93e-49e5-9c88-0cd29b719e0d'
        p = Pipeline.__new__(Pipeline);calls=[]
        def generate(provider, job, index, prompt, path, check, *, task_id=None, reference_media_ids=None):
            calls.append((provider,task_id,prompt,reference_media_ids))
            Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_bytes(b'portrait-bytes')
            import hashlib
            return {'task_id':task_id,'media_id':'11111111-1111-4111-8111-111111111111','project_url':'https://flow.google.com/project/abc','sha256':hashlib.sha256(b'portrait-bytes').hexdigest(),'width':768,'height':1024}
        p._browser_scene_image=Mock(side_effect=generate)
        with tempfile.TemporaryDirectory() as tmp:
            script=validate_flow_character_manifest(self.valid_script())
            job={'id':job_id,'output':tmp,'checkpoints':{'script':script}}
            first,assets=p._flow_character_portraits(job,lambda:None)
            second,_=p._flow_character_portraits(job,lambda:None)
            expected=str(__import__('uuid').uuid5(__import__('uuid').UUID(job_id),'flow-character-reference:father'))
            self.assertEqual(first['father']['task_id'],expected)
            self.assertEqual(second['father']['media_id'],'11111111-1111-4111-8111-111111111111')
            self.assertEqual(len(calls),1)
            self.assertEqual(len(assets),2)
            self.assertTrue((Path(tmp)/'flow-character-references.json').is_file())


    def test_long_form_flow_preserves_existing_path_without_reference_mode(self):
        self.assertFalse(flow_reference_enabled({'request':{'image_provider':'flow','duration_seconds':301}}))
        self.assertTrue(flow_reference_enabled({'request':{'image_provider':'flow','duration_seconds':300}}))


if __name__ == '__main__':
    unittest.main()
