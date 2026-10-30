import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio.core import PermanentError, Store, validate_request
from videostudio.providers import Pipeline, NarrationDurationError, timeline_duration


class WorkflowModeRequestTests(unittest.TestCase):
    base = {'idea': 'A factual topic', 'voice_id': 'preset:test', 'duration_seconds': 45}

    def test_legacy_api_request_without_mode_stays_legacy_compatible(self):
        self.assertNotIn('workflow_mode', validate_request(self.base))

    def test_accepts_explicit_direct_chatgpt_research_mode(self):
        self.assertEqual(validate_request({**self.base,'workflow_mode':'research'})['workflow_mode'], 'research')

    def test_accepts_supplied_narration_and_keeps_lines(self):
        request = {**self.base, 'workflow_mode': 'provided_narration',
                   'idea': 'Dòng lời đọc thứ nhất.\n\nDòng thứ hai.'}
        normalized = validate_request(request)
        self.assertEqual(normalized['workflow_mode'], 'provided_narration')
        self.assertEqual(normalized['idea'], request['idea'])

    def test_rejects_unknown_mode_and_blank_supplied_lines(self):
        with self.assertRaises(ValueError):
            validate_request({**self.base, 'workflow_mode': 'skip_everything'})
        with self.assertRaises(ValueError):
            validate_request({**self.base, 'workflow_mode': 'provided_narration', 'idea': ' \n  \n'})

    def test_store_job_identity_includes_workflow_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'jobs.db', Path(tmp) / 'out')
            job, _ = store.create({**self.base, 'workflow_mode': 'provided_narration',
                                   'idea': 'Line one.\nLine two.'}, 'mode-key')
            self.assertEqual(job['request']['workflow_mode'], 'provided_narration')
            self.assertEqual(store.get(job['id'])['request']['idea'], 'Line one.\nLine two.')


class ResearchModeTests(unittest.TestCase):
    def test_provided_mode_uses_measured_speech_duration_everywhere(self):
        job={'request':{'workflow_mode':'provided_narration','duration_seconds':45},'checkpoints':{'speech':{'duration_seconds':31.25}}}
        self.assertEqual(timeline_duration(job),31.25)

    def test_requests_without_workflow_mode_also_use_measured_duration(self):
        job={'request':{'duration_seconds':45},'checkpoints':{'speech':{'duration_seconds':31.25}}}
        self.assertEqual(timeline_duration(job),31.25)

    def test_plan_requests_direct_structured_facts_without_required_urls(self):
        from types import SimpleNamespace
        pipeline=Pipeline.__new__(Pipeline);pipeline.preflight=lambda scope=None:{'ready':True,'checks':[]}
        pipeline.voices=SimpleNamespace(selected=lambda voice:None)
        prompts=[]
        context={'summary':'A directly researched summary.','facts':[{'claim':'One claim','explanation':'A direct explanation.'}],'uncertainties':[]}
        pipeline.llm_json=lambda prompt,check:(prompts.append(prompt) or {'title':'Topic','visual_prompt':'sieve','music_prompt':'quiet instrumental','research_context':context})
        job={'id':'job','request':{'workflow_mode':'research','idea':'topic','voice_id':'preset:test'}}
        with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp'}):result=pipeline.plan(job,lambda:None)
        self.assertEqual(result['research_context'],context)
        self.assertIn('Do not make independent URL access a prerequisite',prompts[0])
        self.assertNotIn('source_urls',result)

    def test_research_returns_chatgpt_context_without_fetching_urls(self):
        pipeline = Pipeline.__new__(Pipeline)
        context = {'summary': 'Direct research context', 'facts': [{'claim': 'A fact', 'basis': 'ChatGPT response'}], 'caveats': ['uncertain']}
        job = {'id': 'job', 'output': tempfile.mkdtemp(),
               'request': {'workflow_mode': 'research'},
               'checkpoints': {'plan': {'research_context': context}}}
        with patch('videostudio.sources.fetch_source', side_effect=AssertionError('must not fetch URLs')):
            result = pipeline.research(job, lambda: None)
        self.assertEqual(result['mode'], 'chatgpt_unverified')
        self.assertEqual(result['context'], context)
        self.assertEqual(result['sources'], [])


class ProvidedNarrationTests(unittest.TestCase):
    def test_visual_planning_maps_every_line_without_rewriting_narration(self):
        pipeline = Pipeline.__new__(Pipeline)
        calls = []
        def llm(prompt, check):
            calls.append(prompt)
            return {'scenes': [
                {'line_id': 'line-0001', 'visual_prompt': 'A ceramic sieve in a Neolithic kitchen', 'character_ids': []},
                {'line_id': 'line-0002', 'visual_prompt': 'Milk curds separating from whey', 'character_ids': []},
            ], 'characters': []}
        pipeline.llm_json = llm
        lines = 'Chiếc rây giữ lại sữa.\nSữa đông tách khỏi nước.'
        job = {'id': 'job', 'output': tempfile.mkdtemp(),
               'request': {'workflow_mode': 'provided_narration', 'idea': lines, 'duration_seconds': 30,
                           'image_provider': 'chatgpt'},
               'checkpoints': {'plan': {'title': 'Cheese', 'visual_style': 'warm documentary'},
                               'research': {'context': {}, 'sources': []}}}
        result = pipeline._provided_script_draft(job, lambda: None)
        self.assertEqual([scene['narration'] for scene in result['scenes']], lines.splitlines())
        self.assertEqual([scene['scene_id'] for scene in result['scenes']], ['line-0001', 'line-0002'])
        self.assertIn('visual metadata only', calls[0].lower())

    def test_visual_mapping_must_cover_each_input_line_exactly_once(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.llm_json = lambda prompt, check: {'scenes': [
            {'line_id': 'line-0001', 'visual_prompt': 'A sieve', 'character_ids': []},
            {'line_id': 'line-0001', 'visual_prompt': 'Milk', 'character_ids': []},
        ], 'characters': []}
        job = {'id': 'job', 'output': tempfile.mkdtemp(),
               'request': {'workflow_mode': 'provided_narration', 'idea': 'First line.\nSecond line.', 'duration_seconds': 30},
               'checkpoints': {'plan': {'title': 'test'}, 'research': {'context': {}, 'sources': []}}}
        with self.assertRaises(ValueError):
            pipeline._provided_script_draft(job, lambda: None)

    def test_supplied_narration_is_never_rewritten_after_duration_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'VS_DURATION_REWRITE_ATTEMPTS': '3'}):
            pipeline = Pipeline.__new__(Pipeline)
            original = {'narration': 'Keep these exact words.', 'scenes': [
                {'scene_id': 'line-0001', 'narration': 'Keep these exact words.', 'visual_prompt': 'A quiet room'}]}
            job = {'id': 'job', 'output': tmp,
                   'request': {'workflow_mode': 'provided_narration', 'idea': 'Keep these exact words.',
                               'duration_seconds': 30, 'voice_id': 'preset:test'},
                   'checkpoints': {'script': original, 'research': {'context': {}, 'sources': []}}}
            pipeline._speech_attempt = lambda *args: (_ for _ in ()).throw(NarrationDurationError('too long'))
            pipeline.llm_json = lambda *args: self.fail('must not ask ChatGPT to rewrite supplied narration')
            with self.assertRaises(PermanentError):
                pipeline.speech(job, lambda: None)


if __name__ == '__main__':
    unittest.main()
