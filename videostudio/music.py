"""Local soundtrack extension with crossfaded loops, never downloads music."""
import math
from pathlib import Path
from .media import probe,run,asset
from .core import PermanentError

def normalize_music_levels(source,folder,check,ffmpeg='ffmpeg'):
    from .media import audio_report
    from .core import digest
    import json
    source=Path(source);identity=digest(source);out=Path(folder)/('music-normalized-'+identity[:12]+'.wav')
    # Sparse floating/MP3 reconstruction overshoot can be attenuated. Silence,
    # nonfinite samples or widespread full-scale saturation are still rejected.
    raw=audio_report(source,check,ffmpeg,peak_limit=4.0)
    if not out.is_file():
        partial=out.with_suffix('.part.wav')
        run([ffmpeg,'-v','error','-y','-i',source,'-af','loudnorm=I=-20:TP=-2:LRA=7,alimiter=limit=0.89:level=false','-ar','48000','-ac','2','-c:a','pcm_s24le',partial],check)
        partial.replace(out)
    quality=audio_report(out,check,ffmpeg,peak_limit=1.1)
    report=Path(folder)/('music-normalization-'+identity[:12]+'.json')
    report.write_text(json.dumps({'source_sha256':identity,'source_unchanged':digest(source)==identity,'raw':raw,'normalized':quality,'policy':'loudnorm-I-20-TP-2-LRA7-limiter-no-autolevel','semantic_listening_performed':False},indent=2))
    return {'path':str(out),'audio_quality':quality,'raw_audio_quality':raw,'assets':[asset(source),asset(out),asset(report)]}

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
