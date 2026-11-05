import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from videostudio import meme_animation

ROOT = Path(__file__).resolve().parents[1]


class LongAnimationTests(unittest.TestCase):
    def setup_job(self, folder):
        example = json.loads((ROOT / 'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
        request = {'idea': 'Kể trọn câu chuyện gia đình từ mở đầu tới câu chốt, không cắt ngắn.',
                   'duration_seconds': 420, 'voice_id': 'selected', 'workflow_mode': 'meme', 'meme_engine': 'hyperframes'}
        job = {'id': 'test', 'output': folder, 'request': request, 'checkpoints': {}}
        calls = []
        def reply(prompt, check):
            calls.append(prompt)
            if '[MEME_OUTLINE]' in prompt:
                result = copy.deepcopy(example); result.pop('beats')
                result['parts'] = [{'summary': f'Diễn biến phần {i+1}', 'ending': f'Nối phần {i+2}'} for i in range(9)]
                return result
            match = re.search(r'\[MEME_PART (\d+)/9; target=(\d+)\]', prompt)
            self.assertIsNotNone(match, 'A long script must never request all beats at once')
            number, target = map(int, match.groups())
            return {'part': number, 'beats': [dict(copy.deepcopy(example['beats'][i % 8]), text=f'Phần {number} câu {i+1}.') for i in range(target)]}
        pipeline = SimpleNamespace(store=Mock(), llm_json=Mock(side_effect=reply))
        return pipeline, job, calls, reply

    def test_seven_minutes_is_written_in_bounded_parts_with_one_fixed_cast(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as folder:
            pipeline, job, calls, _ = self.setup_job(folder)
            result = meme_animation.script(pipeline, job, lambda: None)
            self.assertEqual(len(result['animation_script']['beats']), 168)
            self.assertEqual(len(calls), 10)
            self.assertTrue(all('126-210' not in p and '126–210' not in p for p in calls))
            self.assertTrue(all(c['voice'] == 'selected' for c in result['animation_script']['cast'].values()))
            self.assertTrue(all(int(n) <= 20 for p in calls for n in re.findall(r'target=(\d+)', p)))
            self.assertIn('Phần 9 câu', result['narration'])

    def test_resume_keeps_finished_parts_after_transport_timeout(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as folder:
            pipeline, job, calls, reply = self.setup_job(folder)
            failed = False
            def flaky(prompt, check):
                nonlocal failed
                if '[MEME_PART 2/' in prompt and not failed:
                    failed = True
                    raise TimeoutError('Browser temporarily unavailable')
                return reply(prompt, check)
            pipeline.llm_json.side_effect = flaky
            with self.assertRaises(TimeoutError):meme_animation.script(pipeline, job, lambda: None)
            result = meme_animation.script(pipeline, job, lambda: None)
            self.assertEqual(len(result['animation_script']['beats']), 168)
            self.assertEqual(sum('[MEME_OUTLINE]' in p for p in calls), 1)
            self.assertEqual(sum('[MEME_PART 1/' in p for p in calls), 1)
            # A completed script is a durable checkpoint even before the worker commits it.
            count = pipeline.llm_json.call_count
            self.assertEqual(result, meme_animation.script(pipeline, job, lambda: None))
            self.assertEqual(pipeline.llm_json.call_count, count)
