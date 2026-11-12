import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from videostudio import speech_worker
from videostudio.core import Cancelled


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
    if text == 'wait':
        import time
        time.sleep(30)
    Path(output).write_text(text, encoding='utf-8')

speech_worker.load_model = load_model
speech_worker.synthesize = synthesize
speech_worker.main()
'''


class SpeechJobWorkerTests(unittest.TestCase):
    def test_batch_cancellation_keeps_completed_outputs_and_removes_pending_files(self):
        spawn=subprocess.Popen
        def start_fake_model(args,**kwargs):return spawn([sys.executable,'-u','-c',FAKE_MODEL,*args[4:]],**kwargs)
        completed=[]
        def check():
            if completed:raise Cancelled()
        with tempfile.TemporaryDirectory() as folder,patch.object(speech_worker.subprocess,'Popen',side_effect=start_fake_model):
            root=Path(folder);outputs=[root/'first.wav',root/'waiting.wav']
            with self.assertRaises(Cancelled):
                with speech_worker.SpeechJob(sys.executable,root,{'id':'test'},check,batch_size=512) as worker:
                    worker.write_lines(['Completed','wait'],outputs,on_complete=completed.append)
            self.assertEqual(outputs[0].read_text(encoding='utf8'),'Completed')
            self.assertFalse(outputs[1].exists())
            self.assertEqual(completed,[0])
            self.assertFalse(list(root.glob('.*.wav')))
            self.assertIsNotNone(worker.process.poll())

    def test_default_256_batch_accepts_all_outputs_and_keeps_order(self):
        spawn=subprocess.Popen
        def start_fake_model(args,**kwargs):return spawn([sys.executable,'-u','-c',FAKE_MODEL,*args[4:]],**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),patch.object(speech_worker.subprocess,'Popen',side_effect=start_fake_model):
            root=Path(folder);texts=[f'Câu thứ {i}.' for i in range(256)];outputs=[root/f'{i:04}.wav' for i in range(256)];completed=[]
            with speech_worker.SpeechJob(sys.executable,root,{'id':'test'},lambda:None) as worker:
                self.assertEqual(worker.batch_size,256)
                worker.write_lines(texts,outputs,on_complete=completed.append)
            self.assertEqual([path.read_text(encoding='utf8') for path in outputs],texts)
            self.assertCountEqual(completed,range(256))
    def test_batch_preserves_each_completed_line_and_receipt_callback_on_failure(self):
        spawn=subprocess.Popen
        def start_fake_model(args,**kwargs):return spawn([sys.executable,'-u','-c',FAKE_MODEL,*args[4:]],**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);outputs=[root/'one.wav',root/'failed.wav'];completed=[]
            with patch.object(speech_worker.subprocess,'Popen',side_effect=start_fake_model):
                with self.assertRaises(RuntimeError):
                    with speech_worker.SpeechJob(sys.executable,root,{'id':'test'},lambda:None) as worker:
                        worker.write_lines(['Câu đầu.','error'],outputs,on_complete=completed.append)
            self.assertEqual(outputs[0].read_text(encoding='utf8'),'Câu đầu.')
            self.assertFalse(outputs[1].exists());self.assertEqual(completed,[0])
            self.assertFalse(list(root.glob('.*.wav')))

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
