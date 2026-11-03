"""FFmpeg renderer for frozen edit plans. Sources are read-only; clips are hashed."""
from __future__ import annotations

import json
import math
import os
import textwrap
import uuid
from pathlib import Path

from .core import digest
from .edit_plan import load_edit_snapshot
from .media import asset, probe, run
from .visual_quality import atomic_json, fingerprint

COMPOSITE_WINDOW_SECONDS = 30
MAX_COMPOSITE_INPUTS = 24


def edit_clip_identity(clip, source_hash, canvas):
    # Placement/text/audio changes do not force a fresh camera-motion encode.
    effect = {k: clip.get(k) for k in ('kind', 'source_start', 'fit', 'crop', 'motion', 'opacity', 'transition', 'width', 'height')}
    effect['duration'] = round(float(clip['end']) - float(clip['start']), 6)
    return fingerprint({'renderer': 'edit-visual-v1', 'source_sha256': source_hash, 'canvas': canvas, 'effect': effect})


def _dimensions(clip, canvas):
    return tuple(max(2, int(canvas[k] * clip.get(k, 1)) // 2 * 2) for k in ('width', 'height'))


def _camera_filter(clip, canvas):
    width, height = _dimensions(clip, canvas); fps = canvas['fps']
    filters = []
    crop = clip.get('crop')
    if crop:
        filters.append(f"crop=iw*{crop['width']}:ih*{crop['height']}:iw*{crop['x']}:ih*{crop['y']}")
    if clip.get('fit', 'cover') == 'contain':
        filters.extend([f'scale={width}:{height}:force_original_aspect_ratio=decrease', f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black'])
    else:
        filters.extend([f'scale={width}:{height}:force_original_aspect_ratio=increase', f'crop={width}:{height}'])
    motion = clip.get('motion', {}); mode = motion.get('type', 'none'); amount = float(motion.get('amount', .05))
    frames = max(1, math.ceil((clip['end'] - clip['start']) * fps) - 1)
    progress = f'min(on/{frames},1)'
    zoom = '1'; x = 'iw/2-iw/zoom/2'; y = 'ih/2-ih/zoom/2'
    if mode == 'zoom_in': zoom = f'1+{amount}*{progress}'
    elif mode == 'zoom_out': zoom = f'1+{amount}*(1-{progress})'
    elif mode.startswith('pan_'):
        zoom = str(1 + amount)
        if mode in ('pan_left', 'pan_right'): x = f'(iw-iw/zoom)*' + (f'(1-{progress})' if mode == 'pan_left' else progress)
        else: y = f'(ih-ih/zoom)*' + (f'(1-{progress})' if mode == 'pan_up' else progress)
    if mode != 'none' and amount:
        # Supersampling makes small portrait camera moves smooth at export size.
        filters.extend([f'scale={width*2}:{height*2}', f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"])
    filters.extend([f'fps={fps}', 'setsar=1', 'format=yuv420p'])
    return ','.join(filters)


def _cached_clip(clip, source, canvas, directory, check, ffmpeg):
    identity = edit_clip_identity(clip, source['sha256'], canvas)
    target = directory / (identity + '.mp4'); receipt = directory / (identity + '.json')
    if target.is_file() and receipt.is_file():
        try:
            saved = json.loads(receipt.read_text())
            if saved['identity'] == identity and saved['sha256'] == digest(target): return target, True, identity
        except (ValueError, KeyError, OSError): pass
    check(); part = directory / (identity + '.' + uuid.uuid4().hex + '.part.mp4')
    args = [ffmpeg, '-v', 'error', '-y']
    if clip['kind'] == 'image': args.extend(['-loop', '1', '-framerate', canvas['fps']])
    else: args.extend(['-ss', clip.get('source_start', 0)])
    args.extend(['-i', source['path'], '-an', '-vf', _camera_filter(clip, canvas), '-t', clip['end'] - clip['start'], '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', part])
    try:
        run(args, check)
        part.replace(target)
        atomic_json(receipt, {'identity': identity, 'sha256': digest(target), 'source_sha256': source['sha256']})
    finally: part.unlink(missing_ok=True)
    return target, False, identity


def _ass_stamp(seconds):
    cs = max(0, round(float(seconds) * 100)); hours, cs = divmod(cs, 360000); minutes, cs = divmod(cs, 6000); secs, cs = divmod(cs, 100)
    return f'{hours}:{minutes:02}:{secs:02}.{cs:02}'


def _ass_color(color, alpha='00'):
    return '&H' + alpha + color[5:7] + color[3:5] + color[1:3]


def _text(value):
    # ASS override syntax is reserved for renderer-authored positions/styles.
    return str(value).replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r', '').replace('\n', r'\N')


def _write_overlays(job, plan, output):
    width, height = plan['canvas']['width'], plan['canvas']['height']
    header = f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
    styles, events = [], []
    tracks = {t['id']: t for t in plan['tracks']}
    for index, clip in enumerate(plan['clips']):
        if clip['kind'] != 'text' or not clip.get('enabled', True) or not tracks[clip['track_id']]['visible']: continue
        style = 'Text' + str(index); foreground = _ass_color(clip.get('color', '#FFFFFF'))
        background = _ass_color(clip.get('background') or '#000000', '40' if clip.get('background') else 'FF')
        border = 3 if clip.get('background') else 1
        styles.append(f"Style: {style},Arial,{clip.get('size',48)},{foreground},{foreground},{background},{background},0,0,0,0,100,100,0,0,{border},2,0,5,{round(width*.07)},{round(width*.07)},0,1\n")
        x=round(clip.get('x',.5)*width);y=round(clip.get('y',.2)*height)
        transition=clip.get('transition',{});mode=transition.get('type','none');fade=min(float(transition.get('duration',0)),(clip['end']-clip['start'])/2)
        tags=f"\\q0\\alpha&H{round((1-clip.get('opacity',1))*255):02X}&"
        if mode in ('slide_left','slide_right') and fade:
            origin=x+(width if mode=='slide_left' else -width)
            tags+=f'\\move({origin},{y},{x},{y},0,{round(fade*1000)})'
        else:tags+=f'\\pos({x},{y})'
        if mode in ('fade','dissolve') and fade:tags+=f'\\fad({round(fade*1000)},{round(fade*1000) if mode=="fade" else 0})'
        position='{'+tags+'}'
        events.append(f"Dialogue: {index+1},{_ass_stamp(clip['start'])},{_ass_stamp(clip['end'])},{style},,0,0,0,,{position}{_text(clip['text'])}\n")
    captions = plan['captions']
    if captions['enabled']:
        color = _ass_color(captions['color']); size = max(8, round(captions['font_size'] * width / 1080)); margin = round(captions['bottom_margin'] * height / 1920)
        styles.append(f'Style: Caption,Arial,{size},{color},{color},&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,{round(width*.08)},{round(width*.08)},{margin},1\n')
        for index, utt in enumerate(job['checkpoints']['speech']['utterances']):
            start, end = float(utt['start']), min(float(utt['end']), plan['duration'])
            if end <= start: continue
            cues = [c for c in captions.get('emphasis', []) if c['utterance_index'] == index]
            boundaries = sorted({start, end, *[min(end, max(start, c[k])) for c in cues for k in ('start', 'end')]})
            for left, right in zip(boundaries, boundaries[1:]):
                text = _text('\n'.join(textwrap.wrap(utt['narration'], width=32, break_long_words=False, break_on_hyphens=False)))
                for cue in cues:
                    if cue['start'] <= left and cue['end'] >= right:
                        escaped = _text(cue['text'])
                        text = text.replace(escaped, '{\\c' + _ass_color(captions['accent_color']) + '\\b1}' + escaped + '{\\c' + color + '\\b0}', 1)
                events.append(f'Dialogue: 1000,{_ass_stamp(left)},{_ass_stamp(right)},Caption,,0,0,0,,{text}\n')
    if not events: return None
    path = output / 'edit-overlays.ass'
    path.write_text(header + ''.join(styles) + '\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n' + ''.join(events), encoding='utf8')
    return path


def _filter_filename(path):
    return "'" + str(path.resolve()).replace('\\', '/').replace(':', r'\:').replace("'", r"'\''") + "'"


def _cached_text_layer(clip,canvas,directory,check,ffmpeg):
    """Cache an actual transparent title frame; composite it at its track position."""
    fields={key:clip.get(key) for key in ('text','size','color','background','x','y')}
    identity=fingerprint({'renderer':'edit-text-rgba-v2','text':fields,'canvas':canvas})
    target=directory/(identity+'.png');receipt=directory/(identity+'-text.json')
    if target.is_file() and receipt.is_file():
        try:
            saved=json.loads(receipt.read_text())
            if saved.get('identity')==identity and saved.get('sha256')==digest(target):return target,True,identity
        except (ValueError,OSError):pass
    folder=directory/('text-'+identity);folder.mkdir(parents=True,exist_ok=True)
    static=dict(clip,start=0,end=1,opacity=1,transition={'type':'none','duration':0})
    descriptor={'canvas':canvas,'clips':[static],'tracks':[{'id':clip['track_id'],'visible':True}],'captions':{'enabled':False}}
    subtitles=_write_overlays({},descriptor,folder)
    part=directory/(identity+'.'+uuid.uuid4().hex+'.part.png')
    try:
        run([ffmpeg,'-v','error','-y','-f','lavfi','-i',f"color=c=black@0.0:s={canvas['width']}x{canvas['height']}:r=1,format=rgba",
             '-vf','subtitles=filename='+_filter_filename(subtitles)+':alpha=1','-frames:v','1','-threads','1',part],check)
        part.replace(target);atomic_json(receipt,{'identity':identity,'sha256':digest(target)})
    finally:part.unlink(missing_ok=True)
    return target,False,identity


def _extension(clip, visual):
    following = next((c for c in visual if c['track_id'] == clip['track_id'] and abs(c['start'] - clip['end']) < .001), None)
    return following.get('transition', {}).get('duration', 0) if following and following.get('transition', {}).get('type') == 'dissolve' else 0


def _compose_track(visual, clips, canvas, duration, output, check, ffmpeg):
    """Bound both decoder count and Windows command length, preserving global timing."""
    width, height, fps = (canvas[k] for k in ('width', 'height', 'fps'))
    total_frames = math.ceil(duration*fps); window_frames = max(1, round(COMPOSITE_WINDOW_SECONDS*fps))
    segments = []
    for number, frame_start in enumerate(range(0, total_frames, window_frames)):
        check(); start = frame_start/fps; end = min(total_frames, frame_start+window_frames)/fps; length = end-start
        selected = [(clip, path, _extension(clip, visual)) for clip, path in zip(visual, clips) if clip['start'] < end and clip['end'] + _extension(clip, visual) > start]
        # Dense layers can also be composed in passes; each pass only opens 24 decoders.
        batches = [selected[i:i+MAX_COMPOSITE_INPUTS] for i in range(0, len(selected), MAX_COMPOSITE_INPUTS)] or [[]]
        previous = None
        for batch_index, batch in enumerate(batches):
            args = [ffmpeg, '-v', 'error', '-y', '-filter_complex_threads', '1']
            if previous: args.extend(['-threads', '1', '-i', previous])
            else: args.extend(['-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps}:d={length}'])
            offsets = []
            for clip, path, extension in batch:
                offset = min(max(0, start-clip['start']), max(0, clip['end']-clip['start']-1/fps))
                offsets.append(offset)
                if clip['kind']=='text':args.extend(['-threads','1','-loop','1','-framerate',fps,'-i',path])
                else:args.extend(['-threads', '1', '-ss', offset, '-i', path])
            graph = ['[0:v]setpts=PTS-STARTPTS,format=yuv420p[base0]']
            for index, ((clip, path, extension), offset) in enumerate(zip(batch, offsets)):
                transition = clip.get('transition', {}); mode = transition.get('type', 'none'); fade = float(transition.get('duration', 0))
                local_start = max(0, clip['start']-start); local_end = min(length, clip['end']+extension-start)
                filters = [f'setpts=PTS-STARTPTS+{offset}/TB', f'tpad=stop_mode=clone:stop_duration={extension+1/fps}', 'format=yuva420p', f"colorchannelmixer=aa={clip.get('opacity',1)}"]
                if mode in ('fade', 'dissolve') and fade:
                    filters.append(f'fade=t=in:st=0:d={fade}:alpha=1')
                    if mode == 'fade': filters.append(f"fade=t=out:st={max(0,clip['end']-clip['start']-fade)}:d={fade}:alpha=1")
                if clip['kind']=='text' and extension:
                    filters.append(f"fade=t=out:st={clip['end']-clip['start']}:d={extension}:alpha=1")
                filters.append(f'setpts=PTS-STARTPTS+{local_start}/TB')
                graph.append(f'[{index+1}:v]' + ','.join(filters) + f'[layer{index}]')
                layer_width, layer_height = _dimensions(clip, canvas)
                x = '0' if clip['kind']=='text' else f"{clip.get('x',.5)*width-layer_width/2:.6f}"; y = '0' if clip['kind']=='text' else f"{clip.get('y',.5)*height-layer_height/2:.6f}"
                if mode in ('slide_left', 'slide_right') and fade:
                    direction = 1 if mode == 'slide_left' else -1
                    x += f"+({direction*width})*max(0,1-(t+{start}-({clip['start']}))/{fade})"
                graph.append(f"[base{index}][layer{index}]overlay=x='{x}':y='{y}':enable='gte(t,{local_start})*lt(t,{local_end})':eof_action=pass:repeatlast=0[base{index+1}]")
            target = output / f'edit-composite-{number:05}-{batch_index:03}.mp4'
            script = output / 'edit-composite.ffgraph'; script.write_text(';'.join(graph), encoding='utf8')
            args.extend(['-filter_complex_script', script, '-map', f'[base{len(batch)}]', '-an', '-t', length, '-r', fps, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', target])
            run(args, check)
            if previous: previous.unlink(missing_ok=True)
            previous = target
        segments.append(previous)
    listing = output / 'edit-composite-concat.txt'
    listing.write_text('\n'.join("file '" + str(p.resolve()).replace('\\', '/').replace("'", "'\\''") + "'" for p in segments), encoding='utf8')
    track = output / 'edit-visual-track.mp4'
    run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing, '-an', '-c:v', 'copy', track], check)
    for path in segments: path.unlink(missing_ok=True)
    return track, len(segments)


def render_edit_plan(job, check, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    snapshot = load_edit_snapshot(job); plan = snapshot['plan']; assets = snapshot['resolved_assets']
    output = Path(job['output']); output.mkdir(parents=True, exist_ok=True)
    cache = Path(snapshot['cache_directory']); cache.mkdir(parents=True, exist_ok=True)
    tracks = {t['id']: t for t in plan['tracks']}; order = {t['id']: i for i, t in enumerate(plan['tracks'])}
    visual = sorted([c for c in plan['clips'] if c['kind'] in ('image', 'video','text') and c.get('enabled', True) and tracks[c['track_id']]['visible']], key=lambda c: (order[c['track_id']], c['start'], c['id']))
    clips = []; hits = 0; keys = [];text_hits=0;text_keys=[]
    for clip in visual:
        if clip['kind']=='text':
            path,hit,key=_cached_text_layer(clip,plan['canvas'],cache,check,ffmpeg);text_hits+=int(hit);text_keys.append(key)
        else:
            path, hit, key = _cached_clip(clip, assets[clip['asset_id']], plan['canvas'], cache, check, ffmpeg);hits+=int(hit);keys.append(key)
        clips.append(path)
    from .edit_audio import mix_edit_audio
    audio_folder = cache.parent / 'editor-audio-cache'; audio_folder.mkdir(parents=True, exist_ok=True)
    audio_identity = fingerprint({'policy': 'edit-audio-shared-v1', 'duration': plan['duration'], 'tracks': [{k: t[k] for k in ('id', 'kind', 'muted') if k in t} for t in plan['tracks']], 'narration': plan.get('narration', {}), 'clips': [c for c in plan['clips'] if c['kind'] == 'audio'], 'music': plan['music'], 'sfx': plan['sfx'], 'sources': {c['asset_id']: assets[c['asset_id']]['sha256'] for collection in ('clips', 'music', 'sfx') for c in plan[collection] if c.get('kind') == 'audio'}})
    audio = mix_edit_audio(job, plan, assets, audio_folder / (audio_identity + '.wav'), check, ffmpeg, ffprobe)
    fps = plan['canvas']['fps']; duration = plan['duration']
    track, segment_count = _compose_track(visual, clips, plan['canvas'], duration, output, check, ffmpeg)
    args = [ffmpeg, '-v', 'error', '-y', '-threads', '1', '-i', track, '-i', audio['path']]
    overlays = _write_overlays(job, dict(plan,clips=[]), output)
    if overlays: args.extend(['-vf', f'subtitles=filename={_filter_filename(overlays)}'])
    target = output / 'video.mp4'; part = output / ('edit-' + uuid.uuid4().hex + '.part.mp4')
    args.extend(['-map', '0:v:0', '-map', '1:a:0', '-t', duration, '-r', fps, '-c:v', 'libx264' if overlays else 'copy'])
    if overlays: args.extend(['-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p'])
    args.extend(['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', part])
    try:
        run(args, check)
        metadata = probe(part, ffprobe)
        if abs(float(metadata['format']['duration']) - duration) > max(.2, 2/fps): raise ValueError('Edit render duration mismatch')
        if not any(s['codec_type'] == 'audio' for s in metadata['streams']): raise ValueError('Edit render has no audio stream')
        run([ffmpeg, '-v', 'error', '-xerror', '-i', part, '-f', 'null', '-'], check)
        part.replace(target)
    finally: part.unlink(missing_ok=True)
    return {'video': str(target), 'duration_seconds': duration, 'edit_plan_revision': plan['revision'], 'edit_plan_sha256': fingerprint(plan), 'full_decode_ok': True, 'composite_segments': segment_count, 'visual_cache': {'directory': str(cache), 'hits': hits, 'misses': len(keys)-hits, 'keys': keys},'text_cache':{'hits':text_hits,'misses':len(text_keys)-text_hits}, 'audio': audio, 'assets': [asset(target)]}


def verify_edit_render(job,check,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    """Verify the exact frozen canvas/timeline, including an intentional user mute."""
    snapshot=load_edit_snapshot(job);plan=snapshot['plan'];path=job['checkpoints']['render']['video']
    metadata=probe(path,ffprobe);duration=float(metadata['format']['duration']);fps=float(plan['canvas']['fps'])
    video=next((s for s in metadata.get('streams',[]) if s.get('codec_type')=='video'),None)
    audio=next((s for s in metadata.get('streams',[]) if s.get('codec_type')=='audio'),None)
    if not video or not audio or not math.isfinite(duration) or abs(duration-plan['duration'])>max(.25,2/fps):raise ValueError('Edited video streams or timeline differ from frozen plan')
    rate=video.get('avg_frame_rate','0/1').split('/');actual_fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
    if video['width']!=plan['canvas']['width'] or video['height']!=plan['canvas']['height'] or abs(actual_fps-fps)>.03:raise ValueError('Edited video canvas differs from frozen plan')
    run([ffmpeg,'-v','error','-xerror','-i',path,'-f','null','-'],check,timeout=900)
    tracks={track['id']:track for track in plan['tracks']}
    audible=False
    for collection in ('clips','music','sfx'):
        for clip in plan[collection]:
            track=tracks[clip['track_id']]
            if clip.get('kind')!='audio' or not clip.get('enabled',True) or clip.get('muted') or clip.get('mute') or track.get('muted') or clip.get('volume',1)<=0:continue
            if track['kind']=='narration' and (plan.get('narration',{}).get('muted') or plan.get('narration',{}).get('volume',1)<=0):continue
            audible=True
    if audible and job['checkpoints']['render'].get('editing_source')=='automatic_defaults':
        from .media import audio_report
        quality=audio_report(path,check,ffmpeg)
    else:quality={'full_decode_ok':True,'user_mix':True,'intentional_mute':not audible,'non_silence_check_required':False}
    return {'verified':True,'duration_seconds':duration,'full_video_decode_ok':True,'audio_quality':quality,
            'edit_plan_sha256':fingerprint(plan),'visual_quality':{'status':'user_edit','scope':'frozen_source_assets'},
            'semantic_viewing_performed':False,'assets':[asset(path)]}
