"""Offline VieNeu subprocess. Only verified Vieneu.infer/save contract used."""
import json, os, sys
from pathlib import Path

def main():
    d=json.loads(sys.argv[1]);cache=Path(d['cache']).resolve()
    if not cache.is_dir():raise RuntimeError('Existing speech model cache required')
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/'hub'),HUGGINGFACE_HUB_CACHE=str(cache/'hub'),HF_MODULES_CACHE=str(cache/'modules'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from vieneu import Vieneu
    # Explicit existing CPU/ONNX runtime: no opportunistic GPU load/download.
    tts=Vieneu(backend='onnx',device='cpu');v=d['voice']
    if v['kind']=='clone':
        from .core import digest
        p=Path(v['reference_path'])
        if digest(p)!=v['sha256']:raise RuntimeError('Clone reference changed')
        audio=tts.infer(d['text'],ref_audio=str(p),denoise=True)
    else:audio=tts.infer(d['text'],voice=v['id'])
    tts.save(audio,d['output'])
if __name__=='__main__':main()
