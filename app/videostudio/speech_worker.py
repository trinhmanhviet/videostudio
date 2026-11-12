"""Offline VieNeu subprocess with one model per narration stage."""
import json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path


_DLL_HANDLES={}
DEFAULT_SPEECH_BATCH_SIZE=256
MAX_SPEECH_BATCH_SIZE=512


def speech_batch_size(value=None):
    """Resolve scheduling only; utterance audio identity is independent of batching."""
    if value is None:
        value=int(os.getenv('VS_SPEECH_BATCH_SIZE',str(DEFAULT_SPEECH_BATCH_SIZE)))
    if type(value) is not int or not 1<=value<=MAX_SPEECH_BATCH_SIZE:
        raise ValueError(f'speech_batch_size must be an integer from 1 to {MAX_SPEECH_BATCH_SIZE}')
    if os.getenv('VS_SPEECH_DEVICE','cuda').strip().lower()=='cpu' or os.getenv('VS_SPEECH_BACKEND','auto').strip().lower()=='onnx':
        return 1
    return value


def _add_onnx_dlls():
    # Prefer the speech environment's CUDA libraries. The old Comfy DLL fallback
    # is only for ONNX installations without their own torch CUDA wheel.
    local=Path(sys.executable).parent.parent/'Lib/site-packages/torch/lib'
    legacy=Path(r'D:\1_SD_and_workflow\ComfyUI-Easy-Install\ComfyUI-Easy-Install\python_embeded\Lib\site-packages\torch\lib')
    directory=next((str(path) for path in (local,legacy) if path.is_dir()),None)
    if directory:
        if directory not in _DLL_HANDLES:
            try:_DLL_HANDLES[directory]=os.add_dll_directory(directory)
            except (AttributeError,OSError):pass
        paths=os.environ.get('PATH','').split(os.pathsep)
        if directory not in paths:os.environ['PATH']=directory+os.pathsep+os.environ.get('PATH','')


def load_model(cache):
    cache=Path(cache).resolve()
    if not cache.is_dir():raise RuntimeError('Existing speech model cache required')
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/'hub'),HUGGINGFACE_HUB_CACHE=str(cache/'hub'),HF_MODULES_CACHE=str(cache/'modules'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    backend=os.getenv('VS_SPEECH_BACKEND','auto').strip().lower()
    if backend not in ('auto','onnx','pytorch'):raise ValueError('VS_SPEECH_BACKEND must be onnx or pytorch (or auto)')
    cpu=os.getenv('VS_SPEECH_DEVICE','cuda').strip().lower()=='cpu'
    cuda=False
    if not cpu and backend!='onnx':
        try:
            import torch
            cuda=torch.cuda.is_available()
        except (ImportError,OSError,RuntimeError):cuda=False
    from vieneu import Vieneu
    if cuda:
        # Do not patch auxiliary ONNX encoders or add Comfy's torch DLLs here.
        ort=sys.modules.get('onnxruntime')
        if ort is not None and hasattr(ort.InferenceSession,'_vs_original'):
            ort.InferenceSession=ort.InferenceSession._vs_original
        return Vieneu(backend='pytorch',device='cuda')
    if not cpu:_add_onnx_dlls()
    import onnxruntime as ort
    _orig_session=getattr(ort.InferenceSession,'_vs_original',ort.InferenceSession)
    def _gpu_sess(path,*args,**kwargs):
        if kwargs.get('providers')==['CPUExecutionProvider'] and 'CUDAExecutionProvider' in ort.get_available_providers() and os.getenv('VS_SPEECH_DEVICE','cuda').strip().lower()!='cpu':
            kwargs['providers']=['CUDAExecutionProvider','CPUExecutionProvider']
        return _orig_session(path,*args,**kwargs)
    _gpu_sess._vs_original=_orig_session
    ort.InferenceSession=_gpu_sess
    # ONNX device='cpu' avoids importing torch via VieNeu's device auto-detect;
    # the existing explicit ORT provider adapter controls ONNX GPU placement.
    return Vieneu(backend='onnx',device='cpu')


def _voice_kwargs(v):
    if v['kind']=='clone':
        from .core import digest
        p=Path(v['reference_path'])
        if digest(p)!=v['sha256']:raise RuntimeError('Clone reference changed')
        return {'ref_audio':str(p),'denoise':True}
    return {'voice':v['id']}


def _save_audio(tts,audio,output):
    import numpy as np
    if not len(audio) or not np.isfinite(audio).all():raise RuntimeError('Empty or non-finite speech waveform')
    peak=float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak>0.95:
        audio=audio*(0.95/peak)
    tts.save(audio, str(output))


def synthesize(tts, text, v, output):
    _save_audio(tts,tts.infer(text,**_voice_kwargs(v)),output)


def synthesize_batch(tts,texts,voice,outputs,batch_size=None):
    if len(texts)!=len(outputs) or not 1<=len(texts)<=MAX_SPEECH_BATCH_SIZE:raise ValueError(f'One output required per utterance (1–{MAX_SPEECH_BATCH_SIZE})')
    size=speech_batch_size(batch_size)
    if getattr(tts,'backend',None)=='pytorch':
        audios=tts.infer_batch(texts,**_voice_kwargs(voice),batch_size=min(size,len(texts)))
        if len(audios)!=len(outputs):raise RuntimeError('Speech batch result count does not match utterances')
        for audio,output in zip(audios,outputs):
            output=Path(output);partial=output.with_suffix('.part.wav')
            _save_audio(tts,audio,partial);partial.replace(output)
    else:
        for text,output in zip(texts,outputs):
            output=Path(output);partial=output.with_suffix('.part.wav')
            synthesize(tts,text,voice,partial);partial.replace(output)


def main():
    if sys.argv[1] == '--job':
        config = json.loads(sys.argv[2])
        size = speech_batch_size(config.get('batch_size'))
        model = None
        for line in sys.stdin.buffer:
            request = json.loads(line)
            if model is None:
                model = load_model(config['cache'])
            if 'utterances' in request:
                items=request['utterances']
                if not isinstance(items,list) or not 1<=len(items)<=MAX_SPEECH_BATCH_SIZE:raise ValueError('Invalid utterance batch')
                synthesize_batch(model,[item['text'] for item in items],config['voice'],[item['output'] for item in items],batch_size=size)
                continue
            output = Path(request['output'])
            partial = output.with_suffix('.part.wav')
            synthesize(model, request['text'], config['voice'], partial)
            partial.replace(output)
        return
    request = json.loads(sys.argv[1])
    size = speech_batch_size(request.get('batch_size'))
    model = load_model(request['cache'])
    if 'utterances' in request:
        items=request['utterances']
        if not isinstance(items,list) or not 1<=len(items)<=MAX_SPEECH_BATCH_SIZE:raise ValueError('Invalid utterance batch')
        synthesize_batch(model,[item['text'] for item in items],request['voice'],[item['output'] for item in items],batch_size=size)
    else:
        synthesize(model, request['text'], request['voice'], request['output'])


class SpeechJob:
    """Run sequential utterances in an owned subprocess, with cancellation between polls."""

    def __init__(self, python, cache, voice, check, batch_size=None):
        self.python = python
        self.batch_size=speech_batch_size(batch_size)
        self.config = {'cache': str(cache), 'voice': voice, 'batch_size': self.batch_size}
        self.check = check
        self.process = None
        self.pending = None
        self.pending_batch={}

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

    def write_lines(self,texts,outputs,timeout=900,on_complete=None):
        if len(texts)!=len(outputs) or not 1<=len(texts)<=MAX_SPEECH_BATCH_SIZE:raise ValueError(f'One output required per utterance (1–{MAX_SPEECH_BATCH_SIZE})')
        outputs=[Path(path).resolve() for path in outputs]
        if len(set(outputs))!=len(outputs):raise ValueError('Utterance outputs must be unique')
        self.check();items=[]
        for index,(text,output) in enumerate(zip(texts,outputs)):
            pending=output.with_name(f'.{output.stem}.{uuid.uuid4().hex}.wav')
            self.pending_batch[pending]=(index,output);items.append({'text':text,'output':str(pending)})
        deadline=time.monotonic()+timeout
        try:
            self.process.stdin.write((json.dumps({'utterances':items},ensure_ascii=False)+'\n').encode('utf8'));self.process.stdin.flush()
        except OSError as error:raise self._worker_error() from error
        while self.pending_batch:
            self.check()
            for pending,(index,output) in list(self.pending_batch.items()):
                if pending.is_file():
                    pending.replace(output);del self.pending_batch[pending]
                    if on_complete:on_complete(index)
            if not self.pending_batch:return
            if self.process.poll() is not None:raise self._worker_error()
            if time.monotonic()>=deadline:raise TimeoutError('VieNeu did not finish the utterance batch in time')
            time.sleep(.1)

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
            for pending in self.pending_batch:
                pending.unlink(missing_ok=True);pending.with_suffix('.part.wav').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
