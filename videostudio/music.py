"""Local soundtrack extension with crossfaded loops, never downloads music."""
import math
from pathlib import Path
from .media import probe,run,asset
from .core import PermanentError

def extend_music(source,target,output,check,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    seconds=float(probe(source,ffprobe)['format']['duration'])
    if not math.isfinite(seconds) or seconds<1:raise PermanentError('Music source too short for a natural loop')
    fade=min(2.0,seconds*.15)
    repeats=max(1,math.ceil((target-fade)/(seconds-fade)))
    if repeats>300:raise PermanentError('Music loop count exceeds resource budget')
    if repeats==1:chain=f'[0:a]atrim=duration={target},asetpts=PTS-STARTPTS[out]'
    else:
        chain='';left='0:a'
        for i in range(1,repeats):
            out=f'fade{i}'
            chain+=f'[{left}][{i}:a]acrossfade=d={fade}:c1=tri:c2=tri[{out}];';left=out
        chain+=f'[{left}]asetpts=N/SR/TB,atrim=duration={target}[out]'
    inputs=[]
    for _ in range(repeats):inputs.extend(['-i',source])
    run([ffmpeg,'-v','error','-y',*inputs,'-filter_complex',chain,'-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le',output],check)
    actual=float(probe(output,ffprobe)['format']['duration'])
    if abs(actual-target)>.1:raise PermanentError('Music extension does not cover target duration')
    return {'path':str(output),'duration_seconds':actual,'repeats':repeats,'crossfade_seconds':fade if repeats>1 else 0,'assets':[asset(output)]}
