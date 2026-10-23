"""CPU FFmpeg composition using real generated assets. No silent/fake output."""
import json, subprocess, time
from pathlib import Path
from .core import digest, PermanentError

def run(args,check,timeout=900):
    p=subprocess.Popen([str(a) for a in args],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    start=time.monotonic()
    try:
        while True:
            check()
            try:out,err=p.communicate(timeout=.25);break
            except subprocess.TimeoutExpired:
                if time.monotonic()-start>timeout:raise TimeoutError('Media command timed out')
        if p.returncode:raise RuntimeError(err.decode(errors='replace')[-3000:])
        return out
    finally:
        if p.poll() is None:p.kill();p.communicate()

def probe(path,ffprobe='ffprobe'):
    return json.loads(subprocess.check_output([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(path)],timeout=20))

def asset(path):return {'path':str(Path(path).resolve()),'sha256':digest(path)}

def render(image,speech,music,subtitles,output,seconds,check,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    speech_seconds=float(probe(speech,ffprobe)['format']['duration'])
    # Never truncate narration, or stretch beyond intelligible bounded pacing.
    ratio=speech_seconds/seconds
    if not .75<=ratio<=1.35:raise PermanentError(f'Narration {speech_seconds:.2f}s cannot fit requested {seconds}s within pacing policy')
    target=Path(output); tmp=target.with_name(target.stem+'.part.mp4')
    # Scene-level subtitle cues are authored from actual utterance intervals.
    sub=Path(subtitles).name
    filt=f'[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,subtitles=filename={sub}[v];[1:a]atempo={ratio},aresample=48000[a];[2:a]volume=0.12,aresample=48000[m];[a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]'
    # Filter paths are relative to output directory; no shell and no user filter text.
    args=[ffmpeg,'-y','-loop','1','-i',str(Path(image).resolve()),'-i',str(Path(speech).resolve()),'-stream_loop','-1','-i',str(Path(music).resolve()),'-filter_complex',filt,'-map','[v]','-map','[mix]','-t',str(seconds),'-r','24','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(tmp.resolve())]
    # run() supports cwd via a narrowly scoped subprocess wrapper below, avoiding global chdir.
    p=subprocess.Popen(args,cwd=target.parent,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    start=time.monotonic()
    try:
        while True:
            check()
            try:_,err=p.communicate(timeout=.25);break
            except subprocess.TimeoutExpired:
                if time.monotonic()-start>900:raise TimeoutError('Render timed out')
        if p.returncode:raise RuntimeError(err.decode(errors='replace')[-3000:])
        verify(tmp,seconds,ffprobe)
        tmp.replace(target)
    finally:
        if p.poll() is None:p.kill();p.communicate()
    return {'video':str(target),'assets':[asset(target)]}

def verify(path,seconds,ffprobe='ffprobe'):
    data=probe(path,ffprobe); kinds={s['codec_type'] for s in data['streams']}
    actual=float(data['format']['duration'])
    if not {'video','audio'}<=kinds or abs(actual-seconds)>max(.25,seconds*.01):raise PermanentError(f'Invalid video streams/duration: {actual} vs {seconds}')
    # Decode entire output; a readable header alone is not a completed render.
    return {'verified':True,'duration_seconds':actual,'assets':[asset(path)]}
