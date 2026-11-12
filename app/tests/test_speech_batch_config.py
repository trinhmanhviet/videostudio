"""Per-job speech scheduling uses CPU fixtures, never the real speech model."""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videostudio import speech_worker as sw
from videostudio.content_factory import ContentFactory
from videostudio.core import Store, validate_request
from videostudio.workflow import compile_workflow, default_workflow, validate_workflow

BASE = {'idea': 'A narration', 'voice_id': 'voice', 'duration_seconds': 30}


class SpeechBatchConfigTests(unittest.TestCase):
    def test_request_accepts_every_integer_in_supported_range(self):
        for size in (1, 33, 256, 512):
            with self.subTest(size=size):
                self.assertEqual(validate_request({**BASE, 'speech_batch_size': size})['speech_batch_size'], size)

    def test_request_rejects_non_integer_and_out_of_range_values(self):
        for size in (True, False, 33.0, 0, 513, '256', None):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'speech_batch_size'):
                validate_request({**BASE, 'speech_batch_size': size})

    def test_omitted_field_preserves_legacy_request_and_idempotency(self):
        self.assertNotIn('speech_batch_size', validate_request(BASE))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Store(root / 'jobs.db', root / 'out')
            first, _ = store.create(BASE, 'legacy')
            replay, created = store.create(BASE, 'legacy')
            self.assertEqual(first['id'], replay['id'])
            self.assertFalse(created)
            self.assertNotIn('speech_batch_size', replay['request'])
            with self.assertRaisesRegex(ValueError, 'different request'):
                store.create({**BASE, 'speech_batch_size': 256}, 'legacy')

    def test_explicit_job_size_wins_over_environment_and_default_is_256(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sw.SpeechJob('python', '.', {}, lambda: None).batch_size, 256)
        with patch.dict(os.environ, {'VS_SPEECH_BATCH_SIZE': '128'}, clear=True):
            self.assertEqual(sw.SpeechJob('python', '.', {}, lambda: None).batch_size, 128)
            for size in (1, 33, 256, 512):
                worker = sw.SpeechJob('python', '.', {}, lambda: None, batch_size=size)
                self.assertEqual(worker.batch_size, size)
                self.assertEqual(worker.config['batch_size'], size)

    def test_worker_rejects_invalid_explicit_sizes(self):
        for size in (True, False, 33.0, 0, 513, '256'):
            with self.subTest(size=size), self.assertRaises(ValueError):
                sw.SpeechJob('python', '.', {}, lambda: None, batch_size=size)

    def test_cpu_and_onnx_force_single_utterance(self):
        for env in ({'VS_SPEECH_DEVICE': ' CPU '}, {'VS_SPEECH_BACKEND': ' ONNX '}):
            with patch.dict(os.environ, env, clear=True):
                worker = sw.SpeechJob('python', '.', {}, lambda: None, batch_size=512)
                self.assertEqual(worker.batch_size, 1)
                self.assertEqual(worker.config['batch_size'], 1)

    def test_workflow_validates_and_compiles_speech_size_and_seeds_default(self):
        graph = default_workflow()
        speech = next(n for n in graph['nodes'] if n['type'] == 'speech')['config']
        self.assertEqual(speech['speech_batch_size'], 256)
        for size in (1, 33, 256, 512):
            speech['speech_batch_size'] = size
            self.assertEqual(compile_workflow(graph, BASE)['speech_batch_size'], size)
        for size in (True, False, 33.0, 0, 513):
            speech['speech_batch_size'] = size
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'speech_batch_size'):
                validate_workflow(graph)
        speech.pop('speech_batch_size')
        self.assertNotIn('speech_batch_size', validate_workflow(graph)['nodes'][3]['config'])
        self.assertNotIn('speech_batch_size', compile_workflow(graph, BASE))

    def test_factory_preserves_defaults_and_per_item_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Store(root / 'jobs.db', root / 'out')
            factory = ContentFactory(store, lambda *_: None)
            batch = factory.create_batch({'project': 'Test', 'style': 'news', 'input_mode': 'script',
                'defaults': {'voice_id': 'voice', 'duration_seconds': 30, 'speech_batch_size': 256},
                'items': [{'content': 'First'}, {'content': 'Second', 'speech_batch_size': 33}]}, 'batch', 'bridge')
            self.assertEqual([item['request']['speech_batch_size'] for item in batch['items']], [256, 33])

    def test_cli_job_and_one_shot_use_configured_inference_size(self):
        items = [{'text': str(i), 'output': str(i) + '.wav'} for i in range(34)]
        config = {'cache': '.', 'voice': {'id': 'voice'}, 'batch_size': 33}
        for mode in ('job', 'one-shot'):
            argv = ['worker', '--job', json.dumps(config)] if mode == 'job' else ['worker', json.dumps({**config, 'utterances': items})]
            stdin = types.SimpleNamespace(buffer=io.BytesIO((json.dumps({'utterances': items}) + '\n').encode()))
            with self.subTest(mode=mode), patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', stdin), patch.object(sw, 'load_model', return_value=object()), patch.object(sw, 'synthesize_batch') as synth:
                sw.main()
                self.assertEqual(synth.call_args.kwargs['batch_size'], 33)


if __name__ == '__main__':
    unittest.main()
