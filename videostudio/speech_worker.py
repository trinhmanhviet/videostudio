"""Offline VieNeu subprocess with one model per narration stage."""
import json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path


def load_model(cache):
    cache=Path(cache).resolve()
    if not cache.is_dir():raise RuntimeError('Existing speech model cache required')
    torch_lib=r'D:\1_SD_and_workflow\ComfyUI-Easy-Install\ComfyUI-Easy-Install\python_embeded\Lib\site-packages\torch\lib'
    if os.path.isdir(torch_lib):
        try:os.add_dll_directory(torch_lib)
        except Exception:pass
        os.environ['PATH']=torch_lib+';'+os.environ.get('PATH','')
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/'hub'),HUGGINGFACE_HUB_CACHE=str(cache/'hub'),HF_MODULES_CACHE=str(cache/'modules'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import onnxruntime as ort
    _orig_session=ort.InferenceSession
    def _gpu_sess(path,*args,**kwargs):
        if kwargs.get('providers')==['CPUExecutionProvider'] and 'CUDAExecutionProvider' in ort.get_available_providers() and os.getenv('VS_SPEECH_DEVICE','cuda')!='cpu':
            kwargs['providers']=['CUDAExecutionProvider','CPUExecutionProvider']
        return _orig_session(path,*args,**kwargs)
    ort.InferenceSession=_gpu_sess
    from vieneu import Vieneu
    return Vieneu(backend='onnx')


def synthesize(tts, text, v, output):
    if v['kind']=='clone':
        from .core import digest
        p=Path(v['reference_path'])
        if digest(p)!=v['sha256']:raise RuntimeError('Clone reference changed')
        audio=tts.infer(text,ref_audio=str(p),denoise=True)
    else:audio=tts.infer(text,voice=v['id'])
    import numpy as np
    peak=float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak>0.95:
        audio=audio*(0.95/peak)
    tts.save(audio, str(output))


def main():
    if sys.argv[1] == '--job':
        config = json.loads(sys.argv[2])
        model = None
        for line in sys.stdin.buffer:
            request = json.loads(line)
            if model is None:
                model = load_model(config['cache'])
            output = Path(request['output'])
            partial = output.with_suffix('.part.wav')
            synthesize(model, request['text'], config['voice'], partial)
            partial.replace(output)
        return
    request = json.loads(sys.argv[1])
    model = load_model(request['cache'])
    synthesize(model, request['text'], request['voice'], request['output'])


class SpeechJob:
    """Run sequential utterances in an owned subprocess, with cancellation between polls."""

    def __init__(self, python, cache, voice, check):
        self.python = python
        self.config = {'cache': str(cache), 'voice': voice}
        self.check = check
        self.process = None
        self.pending = None

    def __enter__(self):
        self.check()
        self.log = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(
                [self.python, '-u', '-m', 'videostudio.speech_worker', '--job',
                 json.dumps(self.config, ensure_ascii=False)],
                stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except BaseException:
            self.log.close()
            raise
        return self

    def _worker_error(self):
        self.log.seek(max(0, self.log.seek(0, os.SEEK_END) - 3000))
        detail = self.log.read().decode('utf-8', errors='replace').strip()
        return RuntimeError(detail or 'VieNeu worker exited before producing audio')

    def write_line(self, text, output, timeout=900):
        self.check()
        output = Path(output).resolve()
        self.pending = output.with_name(f'.{output.stem}.{uuid.uuid4().hex}.wav')
        request = json.dumps({'text': text, 'output': str(self.pending)}, ensure_ascii=False)
        deadline = time.monotonic() + timeout
        try:
            self.process.stdin.write((request + '\n').encode('utf-8'))
            self.process.stdin.flush()
        except OSError as error:
            raise self._worker_error() from error
        while True:
            self.check()
            if self.pending.is_file():
                self.pending.replace(output)
                self.pending = None
                return
            if self.process.poll() is not None:
                raise self._worker_error()
            if time.monotonic() >= deadline:
                raise TimeoutError('VieNeu did not finish the current utterance in time')
            time.sleep(0.1)

    def __exit__(self, exc_type, *_):
        try:
            if exc_type is not None and self.process.poll() is None:
                self.process.kill()
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        finally:
            self.log.close()
            if self.pending is not None:
                self.pending.unlink(missing_ok=True)
                self.pending.with_suffix('.part.wav').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
