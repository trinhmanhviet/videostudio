"""Owned offline KhanhTTS worker. Imports CUDA/model packages only on first work."""
import json,os,sys
from pathlib import Path
from .speech_worker import SpeechJob,MAX_SPEECH_BATCH_SIZE

class KhanhSpeechJob(SpeechJob):
    worker_module='videostudio.khanh_speech_worker'
    engine_name='KhanhTTS'
    def __init__(self,python,cache,reference,check,batch_size=None,snapshot=None,steps=32):
        super().__init__(python,cache,reference,check,batch_size)
        # OmniVoice is a larger model; bound each GPU submission independently
        # from the caller's queue batch while retaining one WAV per utterance.
        self.batch_size=min(self.batch_size,8)
        self.config.update(reference=reference,snapshot=str(snapshot),steps=steps,batch_size=self.batch_size)

def load_model(config):
    cache=Path(config['cache']).resolve();snapshot=Path(config['snapshot']).resolve()
    from .speech_engine import khanh_snapshot_ready
    if not khanh_snapshot_ready(snapshot):raise RuntimeError('Existing complete offline KhanhTTS model required')
    reference=config['reference']
    from .core import digest
    if digest(reference['path'])!=reference['sha256']:raise RuntimeError('Voice reference changed')
    os.environ.update(HF_HOME=str(cache),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    # Keep temporary/JIT files in the Khanh runtime; borrowed CUDA dependencies
    # and the working VieNeu environment remain read-only.
    runtime=Path(sys.executable).resolve().parents[2]
    for key,name in (('NUMBA_CACHE_DIR','numba-cache'),('TEMP','tmp'),('TMP','tmp')):
        directory=runtime/name;directory.mkdir(parents=True,exist_ok=True);os.environ[key]=str(directory)
    import torch
    from omnivoice import OmniVoice
    if not torch.cuda.is_available():raise RuntimeError('KhanhTTS requires the installed CUDA runtime')
    model=OmniVoice.from_pretrained(str(snapshot),device_map='cuda:0',dtype=torch.float16,attn_implementation='sdpa',load_asr=False,local_files_only=True)
    model.eval()
    with torch.inference_mode():prompt=model.create_voice_clone_prompt(reference['path'],reference['text'])
    return model,prompt

def synthesize_batch(model,prompt,texts,outputs,steps):
    if len(texts)!=len(outputs) or not 1<=len(texts)<=MAX_SPEECH_BATCH_SIZE:raise ValueError('One output required per utterance')
    if type(steps) is not int or steps not in (16,32):raise ValueError('khanh_steps must be 16 or 32')
    import numpy as np
    import soundfile as sf
    import torch
    with torch.inference_mode():
        waves=model.generate(text=texts,language='vi',voice_clone_prompt=prompt,num_step=steps,fade_duration=.01,pad_duration=.05)
    if len(waves)!=len(outputs):raise RuntimeError('KhanhTTS result count differs from utterances')
    for audio,output in zip(waves,outputs):
        audio=np.asarray(audio,dtype=np.float32)
        if audio.ndim!=1 or not audio.size or not np.isfinite(audio).all():raise RuntimeError('Empty or non-finite speech waveform')
        peak=float(np.abs(audio).max())
        if peak>.95:audio=audio*(.95/peak)
        output=Path(output);partial=output.with_suffix('.part.wav')
        sf.write(str(partial),audio,model.sampling_rate,subtype='PCM_16');partial.replace(output)

def main():
    config=json.loads(sys.argv[2]);model=None;prompt=None
    for line in sys.stdin.buffer:
        request=json.loads(line)
        if model is None:model,prompt=load_model(config)
        items=request['utterances'] if 'utterances' in request else [{'text':request['text'],'output':request['output']}]
        if not isinstance(items,list) or not 1<=len(items)<=MAX_SPEECH_BATCH_SIZE:raise ValueError('Invalid utterance batch')
        for start in range(0,len(items),config['batch_size']):
            chunk=items[start:start+config['batch_size']]
            synthesize_batch(model,prompt,[item['text'] for item in chunk],[item['output'] for item in chunk],config['steps'])

if __name__=='__main__':main()
