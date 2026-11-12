import tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from videostudio import speech_worker as sw

class SpeechBatchTests(unittest.TestCase):
    def test_pytorch_accepts_512_outputs_and_uses_arbitrary_sdk_batch_size(self):
        with tempfile.TemporaryDirectory() as folder:
            outputs=[Path(folder)/f'{i}.wav' for i in range(512)]
            texts=[str(i) for i in range(512)]
            def save(audio,path):Path(path).write_text(str(len(audio)))
            model=types.SimpleNamespace(backend='pytorch',infer_batch=Mock(return_value=[np.ones(3)*.2 for _ in texts]),save=save)
            with patch.dict('os.environ',{},clear=True):
                sw.synthesize_batch(model,texts,{'kind':'preset','id':'voice'},outputs,batch_size=33)
            model.infer_batch.assert_called_once_with(texts,voice='voice',batch_size=33)
            self.assertTrue(all(path.is_file() for path in outputs))
            self.assertFalse(list(Path(folder).glob('*.part.wav')))

    def test_pytorch_batch_writes_one_wave_per_text_in_original_order(self):
        with tempfile.TemporaryDirectory() as folder:
            outputs=[Path(folder)/'a.wav',Path(folder)/'b.wav']
            def save(audio,path):Path(path).write_text(str(len(audio)))
            model=types.SimpleNamespace(backend='pytorch',infer_batch=Mock(return_value=[np.ones(12)*.2,np.ones(25)*.3]),save=save)
            sw.synthesize_batch(model,['First','Second'],{'kind':'preset','id':'voice'},outputs)
            model.infer_batch.assert_called_once_with(['First','Second'],voice='voice',batch_size=2)
            self.assertEqual([p.read_text() for p in outputs],['12','25'])

    def test_onnx_uses_the_old_single_inference_per_line(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(sw,'synthesize') as synth:
            outputs=[Path(folder)/'a.wav',Path(folder)/'b.wav']
            synth.side_effect=lambda tts,text,v,path:Path(path).write_text(text)
            sw.synthesize_batch(types.SimpleNamespace(backend='onnx'),['A','B'],{'id':'voice'},outputs)
            self.assertEqual([p.read_text() for p in outputs],['A','B']);self.assertEqual(synth.call_count,2)

    def test_mismatched_batch_result_is_not_committed(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'a.wav'
            model=types.SimpleNamespace(backend='pytorch',infer_batch=Mock(return_value=[]))
            with self.assertRaises(RuntimeError):sw.synthesize_batch(model,['First'],{'kind':'preset','id':'voice'},[output])
            self.assertFalse(output.exists())

    def test_changed_clone_is_rejected_before_batch_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            ref=Path(folder)/'ref.wav';ref.write_bytes(b'reference')
            model=types.SimpleNamespace(backend='pytorch',infer_batch=Mock())
            with self.assertRaisesRegex(RuntimeError,'Clone reference changed'):
                sw.synthesize_batch(model,['Text'],{'kind':'clone','reference_path':str(ref),'sha256':'wrong'},[Path(folder)/'out.wav'])
            model.infer_batch.assert_not_called()
