"""CPU FFmpeg composition using real generated assets. No silent/fake output."""
import json, subprocess, time, math
from pathlib import Path
from .core import digest, PermanentError
from .captions import SUBTITLE_BOTTOM_MARGIN

def ensure_clean_audio(path, check, ffmpeg='ffmpeg'):
    """Check release audio and repair peak clipping while copying video."""
    for attempt in range(3):
        try:
            return audio_report(path, check, ffmpeg)
        except PermanentError as error:
            if 'clipped' not in str(error) or attempt == 2:
                raise
            path = Path(path)
            fixed = path.with_name(path.stem + '.quiet.mp4')
            run([ffmpeg, '-v', 'error', '-y', '-i', str(path), '-map', '0:v', '-map', '0:a', '-c:v', 'copy',
                 '-af', 'volume=0.7,alimiter=limit=0.8:level=false', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(fixed)], check)
            fixed.replace(path)


def render_scenes(job):
    checkpoint=job['checkpoints']['images']
    provider=checkpoint.get('image_provider',job.get('request',{}).get('image_provider'))
    return [{**scene,'image_provider':scene.get('image_provider',provider)} for scene in checkpoint['scenes']]

def scenes_are_wide(scenes):
    """True when most pictures are landscape; older portrait videos keep their single vertical render."""
    from PIL import Image
    wide=0
    for scene in scenes:
        try:
            with Image.open(scene['path']) as picture:wide+=picture.width>picture.height
        except (OSError,KeyError,TypeError):pass
    return bool(scenes) and wide*2>=len(scenes)

def visual_clip_identity(sha, duration, provider=None, wide=False):
    import hashlib
    policy='1920x1080-30-pan-v1' if wide else '1080x1920-30-pan-v1'
    if provider=='flow':policy+='-flow-bottom-crop-6pct-v1'
    return hashlib.sha256((sha+str(duration)+policy).encode()).hexdigest()

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

def audio_report(path,check,ffmpeg='ffmpeg',peak_limit=1.05,clipped_fraction_limit=.001):
    import array,math
    raw=run([ffmpeg,'-v','error','-i',path,'-ar','16000','-ac','1','-rematrix_maxval','1.0','-f','f32le','-'],check)
    if not raw or len(raw)>100000000:raise PermanentError('Empty/oversized audio analysis')
    values=array.array('f');values.frombytes(raw)
    if not all(math.isfinite(x) for x in values):raise PermanentError('Nonfinite audio samples')
    rms=math.sqrt(sum(x*x for x in values)/len(values));peak=max(abs(x) for x in values)
    clipped=sum(abs(x)>=.999 for x in values)/len(values)
    if rms<.001 or peak>peak_limit or clipped>clipped_fraction_limit:raise PermanentError('Silent or clipped audio')
    return {'full_decode_ok':True,'finite_samples':True,'rms':rms,'peak':peak,'clipped_fraction':clipped,'semantic_completeness_verified':False}

# Supersampled so the slow zoom stays smooth; the visual track keeps enough quality for the final encode.
WIDE_MOTION="scale=2560:1440:force_original_aspect_ratio=increase:flags=lanczos,crop=2560:1440,zoompan=z='1.02+0.015*sin(on/90)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30,setsar=1"

def visual_track(scenes,output,check,ffmpeg='ffmpeg',wide=False):
    import hashlib
    target=Path(output);clips=[]
    if not scenes:raise PermanentError('Storyboard contains no scenes')
    for index,scene in enumerate(scenes):
        check();source=Path(scene['path']).resolve();duration=float(scene['duration'])
        if not math.isfinite(duration) or duration<=0:raise PermanentError('Invalid scene duration')
        identity=visual_clip_identity(digest(source),duration,scene.get('image_provider'),wide)
        clip=target.parent/f"{'visual-wide' if wide else 'visual'}-{index:04}.mp4";receipt=clip.with_suffix('.json')
        reusable=clip.is_file() and receipt.is_file()
        if reusable:
            saved=json.loads(receipt.read_text());reusable=saved.get('identity')==identity and saved.get('sha256')==digest(clip)
        if not reusable:
            part=clip.with_suffix('.part.mp4')
            framing='crop=iw:trunc(ih*0.94/2)*2:0:0,' if scene.get('image_provider')=='flow' else ''
            motion=WIDE_MOTION if wide else framing+"scale=1120:1992:force_original_aspect_ratio=increase,crop=1120:1992,zoompan=z='1.02+0.015*sin(on/90)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1"
            run([ffmpeg,'-v','error','-y','-loop','1','-i',source,'-vf',motion,'-t',duration,'-an','-c:v','libx264','-preset','veryfast',*(['-crf','14'] if wide else []),'-pix_fmt','yuv420p',part],check)
            part.replace(clip);receipt.write_text(json.dumps({'identity':identity,'sha256':digest(clip)}))
        clips.append(clip)
    # Paths are generated locally and cannot include user-provided filter text.
    listing=target.parent/('visual-wide-concat.txt' if wide else 'visual-concat.txt')
    listing.write_text('\n'.join("file '"+str(p.resolve()).replace('\\','/').replace("'","'\\''")+"'" for p in clips),encoding='utf-8')
    run([ffmpeg,'-v','error','-y','-f','concat','-safe','0','-i',listing,'-c','copy',target],check)
    return target

def _check_narration(speech,seconds,ffprobe):
    speech_seconds=float(probe(speech,ffprobe)['format']['duration'])
    # Seconds is the measured timeline, independent of the planning estimate.
    # Retain a short existing visual tail for previously generated soundtracks.
    tolerance=min(5.0,max(2.0,seconds*.25))
    if not math.isfinite(seconds) or seconds<=0 or not math.isfinite(speech_seconds) or speech_seconds<=0 or speech_seconds>seconds or seconds-speech_seconds>tolerance:
        raise PermanentError(f'Narration {speech_seconds:.2f}s is inconsistent with measured timeline {seconds}s')

def _mix_filter(seconds,music_volume):
    fade=min(1.5,seconds/5)
    vol=max(0.0,min(1.0,float(music_volume)))
    return f'[1:a]aresample=48000,apad=whole_dur={seconds},asplit=2[a][side];[2:a]volume={vol:.2f},aresample=48000,afade=t=in:d={fade},afade=t=out:st={seconds-fade}:d={fade}[m];[m][side]sidechaincompress=threshold=0.08:ratio=2.5:attack=30:release=400[duck];[a][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[mix]'

def _run_in(folder,args,check,timeout=1800):
    """Subtitle filter paths are relative to the job folder, so FFmpeg runs there."""
    p=subprocess.Popen([str(a) for a in args],cwd=folder,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);start=time.monotonic()
    try:
        while True:
            check()
            try:_,err=p.communicate(timeout=.25);break
            except subprocess.TimeoutExpired:
                if time.monotonic()-start>timeout:raise TimeoutError('Render timed out')
        if p.returncode:raise RuntimeError(err.decode(errors='replace')[-3000:])
    finally:
        if p.poll() is None:p.kill();p.communicate()

def render_pair(scenes,speech,music,captions,folder,seconds,check,ffmpeg='ffmpeg',ffprobe='ffprobe',music_volume=0.35,reuse_audio=None):
    """One landscape picture track, two deliverables: clean full 16:9 (YouTube makes its own captions), and a centred 4:3 crop with title and captions on a 9:16 page."""
    from .bilingual_captions import DOC_PICTURE_TOP
    folder=Path(folder).resolve()
    track=visual_track(scenes,folder/'visual-wide-track.mp4',check,ffmpeg,wide=True).resolve()
    doc=folder/'video.mp4';wide=folder/'video-ngang.mp4';doc_part=folder/'video.part.mp4';wide_part=folder/'video-ngang.part.mp4'
    quality=['-t',str(seconds),'-r','30','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart']
    doc_sub=Path(captions['doc']).name
    if reuse_audio:
        verify(reuse_audio,seconds,ffprobe)
        args=[ffmpeg,'-v','error','-y','-i',track,'-i',Path(reuse_audio).resolve(),'-vf','setsar=1','-map','0:v:0','-map','1:a:0',*quality,'-c:a','copy',wide_part]
    else:
        _check_narration(speech,seconds,ffprobe)
        from .music import extend_music
        covered=extend_music(music,seconds,folder/'music-covered.wav',check,ffmpeg,ffprobe)['path']
        args=[ffmpeg,'-v','error','-y','-i',track,'-i',Path(speech).resolve(),'-i',Path(covered).resolve(),'-filter_complex','[0:v]setsar=1[v];'+_mix_filter(seconds,music_volume),'-map','[v]','-map','[mix]',*quality,'-c:a','aac','-b:a','192k',wide_part]
    _run_in(folder,args,check)
    verify(wide_part,seconds,ffprobe,size=(1920,1080))
    page=f'color=c=black:s=1080x1920:r=30[page];[0:v]crop=1440:1080:240:0,scale=1080:810:flags=lanczos,setsar=1[picture];[page][picture]overlay=0:{DOC_PICTURE_TOP}:shortest=1,subtitles=filename={doc_sub}[v]'
    _run_in(folder,[ffmpeg,'-v','error','-y','-i',track,'-i',wide_part,'-filter_complex',page,'-map','[v]','-map','1:a:0',*quality,'-c:a','copy',doc_part],check)
    verify(doc_part,seconds,ffprobe)
    wide_part.replace(wide);doc_part.replace(doc)
    return {'video':str(doc),'video_ngang':str(wide),'assets':[asset(doc),asset(wide)]}

def render(image,speech,music,subtitles,output,seconds,check,ffmpeg='ffmpeg',ffprobe='ffprobe',music_volume=0.35):
    _check_narration(speech,seconds,ffprobe)
    target=Path(output); tmp=target.with_name(target.stem+'.part.mp4')
    from .music import extend_music
    prepared_music=extend_music(music,seconds,target.parent/'music-covered.wav',check,ffmpeg,ffprobe)
    music=prepared_music['path']
    # Scene-level subtitle cues are authored from actual utterance intervals.
    sub=Path(subtitles).name
    filt=f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,subtitles=filename={sub}:force_style=MarginV={SUBTITLE_BOTTOM_MARGIN}[v];'+_mix_filter(seconds,music_volume)
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

def render_visual_revision(scenes,audio_source,subtitles,output,seconds,check,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    """Change visuals only; stream-copy the verified original soundtrack unchanged."""
    verify(audio_source,seconds,ffprobe)
    target=Path(output);tmp=target.with_name(target.stem+'.part.mp4')
    track=visual_track(scenes,target.parent/'visual-track.mp4',check,ffmpeg)
    sub=Path(subtitles).name
    args=[ffmpeg,'-v','error','-y','-i',str(track.resolve()),'-i',str(Path(audio_source).resolve()),'-vf','subtitles=filename='+sub+f':force_style=MarginV={SUBTITLE_BOTTOM_MARGIN}','-map','0:v:0','-map','1:a:0','-t',str(seconds),'-r','30','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(tmp.resolve())]
    p=subprocess.Popen(args,cwd=target.parent,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);start=time.monotonic()
    try:
        while True:
            check()
            try:_,err=p.communicate(timeout=.25);break
            except subprocess.TimeoutExpired:
                if time.monotonic()-start>900:raise TimeoutError('Visual revision render timed out')
        if p.returncode:raise RuntimeError(err.decode(errors='replace')[-3000:])
        verify(tmp,seconds,ffprobe);tmp.replace(target)
    finally:
        if p.poll() is None:p.kill();p.communicate()
    return {'video':str(target),'audio_stream_copied':True,'assets':[asset(target)]}

def verify(path,seconds,ffprobe='ffprobe',size=(1080,1920)):
    data=probe(path,ffprobe); kinds={s['codec_type'] for s in data['streams']}
    actual=float(data['format']['duration'])
    if not math.isfinite(seconds) or seconds<=0 or not math.isfinite(actual) or actual<=0 or not {'video','audio'}<=kinds or abs(actual-seconds)>max(.25,seconds*.01):raise PermanentError(f'Invalid video streams/duration: {actual} vs {seconds}')
    video=next(s for s in data['streams'] if s['codec_type']=='video')
    rate=video.get('avg_frame_rate','0/1').split('/')
    fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
    if (video.get('width'),video.get('height'))!=tuple(size) or abs(fps-30)>.01:
        raise PermanentError(f'Expected {size[0]}x{size[1]} at 30fps')
    # Decode entire output; a readable header alone is not a completed render.
    return {'verified':True,'duration_seconds':actual,'assets':[asset(path)]}
