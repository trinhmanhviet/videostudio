import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import speech_worker


FAKE_MODEL = '''
from pathlib import Path
from videostudio import speech_worker

def load_model(cache):
    with (Path(cache) / 'loads.txt').open('a') as marker:
        marker.write('loaded\\n')
    return object()

def synthesize(model, text, voice, output):
    if text == 'error':
        raise RuntimeError('fixture inference failure')
    Path(output).write_text(text, encoding='utf-8')

speech_worker.load_model = load_model
speech_worker.synthesize = synthesize
speech_worker.main()
'''


class SpeechJobWorkerTests(unittest.TestCase):
    def test_job_reuses_one_loaded_model_and_keeps_completed_lines_on_failure(self):
        spawn = subprocess.Popen

        def start_fake_model(args, **kwargs):
            return spawn([sys.executable, '-u', '-c', FAKE_MODEL, *args[4:]], **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second, failed = (root / name for name in ('a.wav', 'b.wav', 'c.wav'))
            with patch.object(speech_worker.subprocess, 'Popen', side_effect=start_fake_model) as start:
                with self.assertRaisesRegex(RuntimeError, 'fixture inference failure'):
                    with speech_worker.SpeechJob(sys.executable, root, {'id': 'test'}, lambda: None) as worker:
                        worker.write_line('Câu đầu.', first)
                        worker.write_line('Câu sau.', second)
                        worker.write_line('error', failed)
                start.assert_called_once()
            self.assertEqual((root / 'loads.txt').read_text().splitlines(), ['loaded'])
            self.assertEqual(first.read_text(encoding='utf-8'), 'Câu đầu.')
            self.assertEqual(second.read_text(encoding='utf-8'), 'Câu sau.')
            self.assertFalse(failed.exists())
            self.assertIsNotNone(worker.process.poll())
