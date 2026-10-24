"""Offline VieNeu subprocess. Only verified Vieneu.infer/save contract used."""
import json, os, sys
from pathlib import Path

def main():
    d=json.loads(sys.argv[1]);cache=Path(d['cache']).resolve()
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
    tts=Vieneu(backend='onnx')
    v=d['voice']
    if v['kind']=='clone':
        from .core import digest
        p=Path(v['reference_path'])
        if digest(p)!=v['sha256']:raise RuntimeError('Clone reference changed')
        audio=tts.infer(d['text'],ref_audio=str(p),denoise=True)
    else:audio=tts.infer(d['text'],voice=v['id'])
    tts.save(audio,d['output'])
if __name__=='__main__':main()
