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

def audio_report(path,check,ffmpeg='ffmpeg',peak_limit=1.001):
    import array,math
    raw=run([ffmpeg,'-v','error','-i',path,'-ar','16000','-ac','1','-f','f32le','-'],check)
    if not raw or len(raw)>100000000:raise PermanentError('Empty/oversized audio analysis')
    values=array.array('f');values.frombytes(raw)
    if not all(math.isfinite(x) for x in values):raise PermanentError('Nonfinite audio samples')
    rms=math.sqrt(sum(x*x for x in values)/len(values));peak=max(abs(x) for x in values)
    clipped=sum(abs(x)>=.999 for x in values)/len(values)
    if rms<.001 or peak>peak_limit or clipped>.001:raise PermanentError('Silent or clipped audio')
    return {'full_decode_ok':True,'finite_samples':True,'rms':rms,'peak':peak,'clipped_fraction':clipped,'semantic_completeness_verified':False}

def visual_track(scenes,output,check,ffmpeg='ffmpeg'):
    import hashlib
    target=Path(output);clips=[]
    if not scenes:raise PermanentError('Storyboard contains no scenes')
    for index,scene in enumerate(scenes):
        check();source=Path(scene['path']).resolve();duration=float(scene['duration'])
        if duration<=0:raise PermanentError('Empty scene duration')
        identity=hashlib.sha256((digest(source)+str(duration)+'1080x1920-30-pan-v1').encode()).hexdigest()
        clip=target.parent/f'visual-{index:04}.mp4';receipt=clip.with_suffix('.json')
        reusable=clip.is_file() and receipt.is_file()
        if reusable:
            saved=json.loads(receipt.read_text());reusable=saved.get('identity')==identity and saved.get('sha256')==digest(clip)
        if not reusable:
            part=clip.with_suffix('.part.mp4')
            run([ffmpeg,'-v','error','-y','-loop','1','-i',source,'-vf',"scale=1120:1992:force_original_aspect_ratio=increase,crop=1120:1992,zoompan=z='1.02+0.015*sin(on/90)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1",'-t',duration,'-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',part],check)
            part.replace(clip);receipt.write_text(json.dumps({'identity':identity,'sha256':digest(clip)}))
        clips.append(clip)
    # Paths are generated locally and cannot include user-provided filter text.
    listing=target.parent/'visual-concat.txt'
    listing.write_text('\n'.join("file '"+str(p.resolve()).replace('\\','/').replace("'","'\\''")+"'" for p in clips),encoding='utf-8')
    run([ffmpeg,'-v','error','-y','-f','concat','-safe','0','-i',listing,'-c','copy',target],check)
    return target

def render(image,speech,music,subtitles,output,seconds,check,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    speech_seconds=float(probe(speech,ffprobe)['format']['duration'])
    # Keep the selected voice's natural pace. Upstream must rewrite narration
    # when it does not fit; never truncate speech or hide the error with atempo.
    tolerance=min(2.0,max(.25,seconds*.03))
    if speech_seconds>seconds or seconds-speech_seconds>tolerance:
        raise PermanentError(f'Narration {speech_seconds:.2f}s does not naturally fit target {seconds}s (allowed trailing hold {tolerance:.2f}s); rewrite narration required')
    target=Path(output); tmp=target.with_name(target.stem+'.part.mp4')
    from .music import extend_music
    prepared_music=extend_music(music,seconds,target.parent/'music-covered.wav',check,ffmpeg,ffprobe)
    music=prepared_music['path']
    # Scene-level subtitle cues are authored from actual utterance intervals.
    sub=Path(subtitles).name
    (target.parent/'visual-disclosure.txt').write_text('Hình minh họa tạo bằng AI',encoding='utf8')
    fade=min(1.5,seconds/5)
    filt=f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,drawtext=textfile=visual-disclosure.txt:font=Arial:fontcolor=white@0.72:fontsize=28:x=90:y=90,subtitles=filename={sub}[v];[1:a]aresample=48000,apad=whole_dur={seconds},asplit=2[a][side];[2:a]volume=0.12,aresample=48000,afade=t=in:d={fade},afade=t=out:st={seconds-fade}:d={fade}[m];[m][side]sidechaincompress=threshold=0.025:ratio=6:attack=20:release=300[duck];[a][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[mix]'
    # Filter paths are relative to output directory; no shell and no user filter text.
    args=[ffmpeg,'-y','-loop','1','-i',str(Path(image[0]['path'] if isinstance(image,list) else image).resolve()),'-i',str(Path(speech).resolve()),'-i',str(Path(music).resolve()),'-filter_complex',filt,'-map','[v]','-map','[mix]','-t',str(seconds),'-r','30','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(tmp.resolve())]
    if isinstance(image,list):
        track=visual_track(image,target.parent/'visual-track.mp4',check,ffmpeg)
        # Replace only the initial still-input options with the composed video input.
        start=args.index('-loop');stop=args.index('-i',start)+2
        args[start:stop]=['-i',str(track.resolve())]
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
    video=next(s for s in data['streams'] if s['codec_type']=='video')
    rate=video.get('avg_frame_rate','0/1').split('/')
    fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
    if video.get('width')!=1080 or video.get('height')!=1920 or abs(fps-30)>.01:
        raise PermanentError('Expected 1080x1920 at 30fps')
    # Decode entire output; a readable header alone is not a completed render.
    return {'verified':True,'duration_seconds':actual,'assets':[asset(path)]}
