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

def assemble_scene_soundtracks(clips, target_seconds, output, check, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Assemble per-scene music clips with smooth crossfades into one continuous soundtrack covering target_seconds."""
    if not clips:
        raise PermanentError('No scene music clips to assemble')
    target_seconds = float(target_seconds)
    if not math.isfinite(target_seconds) or target_seconds<=0:raise PermanentError('Invalid soundtrack target duration')
    output = Path(output)
    if len(clips) == 1:
        return extend_music(clips[0]['path'], target_seconds, output, check, ffmpeg, ffprobe)

    durs = []
    for c in clips:
        d = float(probe(c['path'], ffprobe)['format']['duration'])
        if not math.isfinite(d) or d<=0:raise PermanentError('Invalid scene music duration')
        durs.append(d)
    timings=[float(c.get('duration',target_seconds/len(clips))) for c in clips]
    if any(not math.isfinite(d) or d<=0 for d in timings):raise PermanentError('Invalid scene timeline duration')
    # Preserve the measured timeline. Legacy clips without timings share it evenly.
    total=sum(timings)
    timings=[d*target_seconds/total for d in timings]
    fade = min(1.5, min(durs)*0.15, min(timings)*0.5)
    inputs = []
    for c in clips:
        inputs.extend(['-stream_loop','-1','-i', str(Path(c['path']).resolve())])

    chain = ''
    for i,duration in enumerate(timings):
        length=duration+(fade if i<len(clips)-1 else 0)
        chain+=f'[{i}:a]aresample=48000,atrim=duration={length:.6f},asetpts=PTS-STARTPTS[clip{i}];'
    left = 'clip0'
    for i in range(1, len(clips)):
        out_label = f'fade{i}' if i < len(clips) - 1 else 'merged'
        chain += f'[{left}][clip{i}]acrossfade=d={fade:.6f}:c1=tri:c2=tri[{out_label}];'
        left = out_label

    chain += f'[{left}]atrim=duration={target_seconds:.6f},asetpts=PTS-STARTPTS[out]'
    run([ffmpeg, '-v', 'error', '-y', *inputs, '-filter_complex', chain, '-map', '[out]', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(output)], check)
    actual = float(probe(output, ffprobe)['format']['duration'])
    if abs(actual - target_seconds) > 0.3:
        raise PermanentError(f'Assembled soundtrack {actual:.2f}s does not cover target {target_seconds:.2f}s')
    return {
        'path': str(output),
        'duration_seconds': actual,
        'scene_tracks': len(clips),
        'crossfade_seconds': fade,
        'assets': [asset(output)]
    }
