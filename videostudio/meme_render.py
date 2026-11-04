"""Render a meme video: 3-band 9:16 layout, catalog sprites, simple comic motion, hard cuts.

Frames are composed with Pillow and piped to FFmpeg as raw RGB, so the output is identical on
every run and needs nothing beyond Pillow + FFmpeg. Audio = narration + music + synthesized SFX.
"""
from __future__ import annotations

import array
import hashlib
import json
import math
import random
import subprocess
import time
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .core import PermanentError, digest

RENDERER_VERSION = 'meme-render-v3'
HANDHELD = {'phone', 'mug', 'camera_prop', 'megaphone_prop', 'clipboard_prop', 'hammer_prop', 'money', 'medal',
            'gamepad', 'laptop_prop', 'umbrella_prop', 'smartphone', 'tv_remote', 'phone_charger', 'pen', 'paper_money',
            'wallet', 'toothbrush', 'game_controller', 'headphones'}
W, H = 720, 1280            # composition size; encoded as 1080x1920
OUT_W, OUT_H = 1080, 1920
FPS = 30
TOP_H, BOTTOM_H = 236, 236
SW, SH = W, H - TOP_H - BOTTOM_H   # scene window 720x808
FLOOR = 0.885                       # feet line, fraction of scene height
UNIT = 2.05                         # sheet pixels -> scene pixels for full-size sprites
PAPER = (255, 249, 233)
INK = (20, 20, 20)
RED = (205, 28, 28)
SFX_RATE = 48000

FONT_CANDIDATES = (
    'C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/tahomabd.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
    '/Library/Fonts/Arial Bold.ttf',
)


def font(size):
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise PermanentError('No bold TrueType font with Vietnamese glyphs found for meme captions')


# ---------------------------------------------------------------- text helpers
def wrap(text, face, width):
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if face.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_text(text, width, max_lines, start, minimum):
    size = start
    while True:
        face = font(size)
        lines = wrap(text, face, width)
        if len(lines) <= max_lines or size <= minimum:
            return face, lines[:max_lines] if size <= minimum else lines
        size -= 2


def draw_block(image, text, box, color, start, minimum, max_lines, stroke=0, stroke_color=INK):
    x0, y0, x1, y1 = box
    face, lines = fit_text(text, x1 - x0, max_lines, start, minimum)
    draw = ImageDraw.Draw(image)
    ascent, descent = face.getmetrics()
    step = ascent + descent + 4
    total = step * len(lines)
    y = y0 + (y1 - y0 - total) / 2
    for line in lines:
        width = face.getlength(line)
        draw.text(((x0 + x1 - width) / 2, y), line, font=face, fill=color, stroke_width=stroke, stroke_fill=stroke_color)
        y += step


def bands(hook, payoff):
    frame = Image.new('RGB', (W, H), PAPER)
    draw = ImageDraw.Draw(frame)
    draw_block(frame, hook.upper(), (28, 18, W - 28, TOP_H - 16), INK, 54, 30, 3)
    if payoff:
        draw_block(frame, payoff.upper(), (28, H - BOTTOM_H + 16, W - 28, H - 18), RED, 48, 28, 3)
    draw.rectangle([0, TOP_H - 6, W, TOP_H], fill=INK)
    draw.rectangle([0, H - BOTTOM_H, W, H - BOTTOM_H + 6], fill=INK)
    return frame


def caption(text):
    layer = Image.new('RGBA', (SW, 190), (0, 0, 0, 0))
    draw_block(layer, text, (24, 8, SW - 24, 182), (255, 255, 255), 42, 30, 2, stroke=5)
    return layer


# ---------------------------------------------------------------- motion helpers
def ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def pop_scale(t, duration=0.3):
    if t >= duration:
        return 1.0
    x = t / duration
    if x < 0.6:
        return 0.35 + (1.12 - 0.35) * ease_out(x / 0.6)
    return 1.12 - 0.12 * ease_out((x - 0.6) / 0.4)


def shake(t, seed, amplitude=11.0, duration=0.55):
    if t >= duration:
        return 0, 0
    decay = 1 - t / duration
    rng = random.Random(seed * 1000 + int(t * FPS))
    return rng.uniform(-1, 1) * amplitude * decay, rng.uniform(-1, 1) * amplitude * decay


class Layer:
    def __init__(self, image, cx, bottom, scale, flip=False, kind='sprite'):
        self.image = image.transpose(Image.FLIP_LEFT_RIGHT) if flip else image
        self.cx, self.bottom, self.scale, self.kind = cx, bottom, scale, kind
        self._cache = {}

    def scaled(self, factor):
        key = round(self.scale * factor, 3)
        hit = self._cache.get(key)
        if hit is None:
            size = (max(1, round(self.image.width * key)), max(1, round(self.image.height * key)))
            hit = self.image.resize(size, Image.BILINEAR if len(self._cache) > 2 else Image.LANCZOS)
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = hit
        return hit

    def box(self, factor=1.0):
        w = self.image.width * self.scale * factor
        h = self.image.height * self.scale * factor
        return self.cx - w / 2, self.bottom - h, self.cx + w / 2, self.bottom

    def paste(self, canvas, factor=1.0, dx=0.0, dy=0.0):
        sprite = self.scaled(factor)
        x = round(self.cx - sprite.width / 2 + dx)
        y = round(self.bottom - sprite.height + dy)
        canvas.alpha_composite(sprite, (x, y)) if 0 <= x and 0 <= y and x + sprite.width <= canvas.width and y + sprite.height <= canvas.height else _paste_clipped(canvas, sprite, x, y)


def _paste_clipped(canvas, sprite, x, y):
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(sprite.width, canvas.width - x), min(sprite.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(sprite.crop((left, top, right, bottom)), (x + left, y + top))


# ---------------------------------------------------------------- beat composition
class Beat:
    def __init__(self, catalog, beat, start, end, index):
        self.beat, self.start, self.end, self.index = beat, start, end, index
        self.duration = max(0.05, end - start)
        shot = beat['shot']
        background = catalog.background(beat['bg'], (SW, SH)).convert('RGBA')
        if shot in ('close', 'insert'):
            background = background.filter(ImageFilter.GaussianBlur(3))
        self.static = background.copy()
        self.main = None
        self.fx = []
        self.zoom, self.focus = 1.0, (SW / 2, SH / 2)
        floor = SH * FLOOR

        def sprite_layer(ident, cx, flip=False, boost=1.0):
            item = catalog.items[ident]
            scale = UNIT * item.get('scale', 1.0) * boost
            bottom = SH + 4 if item['kind'] == 'half' else floor
            if item['kind'] == 'half':
                scale *= 1.25
            return Layer(catalog.sprite(ident), cx, bottom, scale, flip)

        if shot in ('wide', 'medium'):
            two = bool(beat.get('partner'))
            self.main = sprite_layer(beat['pose'], SW * (0.33 if two else 0.5))
            if two:
                partner = sprite_layer(beat['partner'], SW * 0.72, flip=True)
                partner.paste(self.static)
            # Hand-held objects are already drawn in the poses; a giant copy on the floor looks wrong.
            # Standing objects (table, lamp, furniture, food...) go on the floor beside a wide shot.
            if beat.get('prop') and shot == 'wide' and beat['prop'] not in HANDHELD:
                prop = catalog.items[beat['prop']]
                side = 0.14 if two else 0.84
                layer = Layer(catalog.sprite(beat['prop']), SW * side, floor, UNIT * 0.9 * prop.get('scale', 1.0))
                layer.paste(self.static)
            x0, y0, x1, y1 = self.main.box()
            head = ((x0 + x1) / 2, y0 + (y1 - y0) * 0.24)
            if shot == 'medium':
                self.zoom, self.focus = (1.0, head) if catalog.items[beat['pose']]['kind'] == 'half' else (1.45, (head[0], head[1] + SH * 0.12))
            fx_spots = [(x1 - (x1 - x0) * 0.05, y0 + (y1 - y0) * 0.1), (x0 + (x1 - x0) * 0.02, y0 + (y1 - y0) * 0.18)]
        elif shot == 'close':
            face = catalog.sprite(beat['face'])
            scale = SW * 0.74 / face.width
            self.main = Layer(face, SW / 2, SH * 0.5 + face.height * scale / 2, scale)
            x0, y0, x1, y1 = self.main.box()
            fx_spots = [(x1 - 10, y0 + 30), (x0 + 20, y0 + 60)]
        else:  # insert
            prop = catalog.sprite(beat['prop'])
            scale = min(SW * 0.56 / prop.width, SH * 0.5 / prop.height)
            self.main = Layer(prop, SW / 2, SH * 0.5 + prop.height * scale / 2, scale)
            x0, y0, x1, y1 = self.main.box()
            fx_spots = [(x1, y0 + 10), (x0, y0 + 40)]
        for ident, (x, y) in zip(beat.get('fx', []), fx_spots):
            sprite = catalog.sprite(ident)
            scale = min(UNIT * 1.05, SW * 0.32 / sprite.width) * (1.25 if shot == 'close' else 1.0)
            h = sprite.height * scale
            self.fx.append(Layer(sprite, min(SW - 30, max(30, x)), min(SH - 10, max(h + 10, y + h / 2)), scale, kind='fx'))

    def frame(self, t):
        motion = self.beat.get('motion', 'none')
        canvas = self.static.copy()
        factor, dx, dy = 1.0 + 0.012 * math.sin(t * 5.0), 0.0, 0.0
        if motion == 'pop':
            factor *= pop_scale(t)
        elif motion in ('slide_left', 'slide_right'):
            sign = -1 if motion == 'slide_left' else 1
            dx = sign * SW * 0.9 * (1 - ease_out(t / 0.28))
        elif motion == 'bounce':
            dy = -abs(math.sin(t * math.pi * 3.2)) * 22
        self.main.paste(canvas, factor, dx, dy)
        for k, layer in enumerate(self.fx):
            appear = t - 0.08 - 0.07 * k
            if appear < 0:
                continue
            layer.paste(canvas, pop_scale(appear, 0.25), 0, math.sin(t * 6 + k) * 4)
        zoom, focus = self.zoom, self.focus
        sx = sy = 0.0
        if motion == 'zoom_in':
            zoom *= 1.0 + 0.2 * ease_in_out(t / self.duration)
        elif motion == 'punch':
            zoom *= 1.12 + 0.25 * (1 - ease_out(t / 0.3))
            sx, sy = shake(t, self.index, 8, 0.35)
        elif motion == 'shake':
            sx, sy = shake(t, self.index)
        else:
            zoom *= 1.0 + 0.03 * ease_in_out(t / self.duration)
        if zoom > 1.001 or sx or sy:
            cw, ch = SW / zoom, SH / zoom
            left = min(max(0.0, focus[0] - cw / 2 + sx), SW - cw)
            top = min(max(0.0, focus[1] - ch / 2 + sy), SH - ch)
            if zoom <= 1.001:
                left, top = sx + 12, sy + 12
                cw, ch = SW - 24, SH - 24
            canvas = canvas.resize((SW, SH), Image.BILINEAR, box=(left, top, left + cw, top + ch))
        return canvas.convert('RGB')


# ---------------------------------------------------------------- sound effects
def _tone(samples, start, seconds, gen):
    first = int(start * SFX_RATE)
    count = int(seconds * SFX_RATE)
    for i in range(count):
        j = first + i
        if j >= len(samples):
            break
        samples[j] += gen(i / SFX_RATE, i / max(1, count))


def synthesize_sfx(events, seconds, path):
    samples = [0.0] * (int(seconds * SFX_RATE) + 1)
    rng = random.Random(11)
    noise = [rng.uniform(-1, 1) for _ in range(SFX_RATE)]
    for start, name in events:
        if name == 'pop':
            _tone(samples, start, 0.09, lambda t, p: math.sin(2 * math.pi * (500 + 2600 * p) * t) * (1 - p) * 0.6)
        elif name == 'whoosh':
            state = {'v': 0.0}

            def gen(t, p, state=state):
                state['v'] = state['v'] * 0.92 + noise[int(t * SFX_RATE) % SFX_RATE] * 0.08
                return state['v'] * math.sin(math.pi * p) * 2.2
            _tone(samples, start, 0.32, gen)
        elif name == 'boing':
            _tone(samples, start, 0.45, lambda t, p: math.sin(2 * math.pi * (240 - 120 * p) * t + 6 * math.sin(2 * math.pi * 14 * t)) * (1 - p) ** 1.5 * 0.55)
        elif name == 'thud':
            _tone(samples, start, 0.25, lambda t, p: (math.sin(2 * math.pi * 70 * t) * 0.8 + noise[int(t * SFX_RATE) % SFX_RATE] * 0.2) * (1 - p) ** 2 * 0.8)
        elif name == 'ding':
            _tone(samples, start, 0.7, lambda t, p: (math.sin(2 * math.pi * 1568 * t) + 0.4 * math.sin(2 * math.pi * 3136 * t)) * (1 - p) ** 2.5 * 0.35)
    data = array.array('h', (max(-32767, min(32767, int(v * 32767))) for v in samples))
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SFX_RATE)
        out.writeframes(data.tobytes())
    return path


def ensure_clean_audio(path, check, ffmpeg='ffmpeg'):
    """Run the release audio check; if only peaks are too hot, re-encode the audio quieter (video copied)."""
    from .media import audio_report, run
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


# ---------------------------------------------------------------- main entry
def timeline(utterances):
    beats = []
    for index, u in enumerate(utterances):
        beat = u.get('meme')
        if not isinstance(beat, dict):
            raise PermanentError('Meme utterance lacks its beat description')
        beats.append((beat, float(u['start']), float(u['end']), u.get('narration') or beat['line']))
    return beats


def render_meme(job, check, catalog, ffmpeg='ffmpeg', ffprobe='ffprobe', music_volume=None):
    from .media import asset, probe
    cp = job['checkpoints']
    meta = cp['script'].get('meme') or {}
    speech = cp['speech']
    seconds = float(speech['duration_seconds'])
    beats = timeline(speech['utterances'])
    out_dir = Path(job['output'])
    target = out_dir / 'video.mp4'
    music_path = cp.get('music', {}).get('path')
    volume = float(job['request'].get('music_volume', 0.35) if music_volume is None else music_volume)
    identity = hashlib.sha256(json.dumps({
        'v': RENDERER_VERSION, 'beats': [(b[0], round(b[1], 3), round(b[2], 3), b[3]) for b in beats],
        'hook': meta.get('hook'), 'payoff': meta.get('payoff'), 'catalog': catalog.fingerprint(),
        'speech': digest(speech['path']), 'music': digest(music_path) if music_path else None, 'volume': volume,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = out_dir / 'meme-render.json'
    if target.is_file() and receipt.is_file():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('identity') == identity and saved.get('sha256') == digest(target):
            return {**saved['result'], 'assets': [asset(target)], 'reused': True}

    sfx_events = [(start, b['sfx']) for b, start, _, _ in beats if b.get('sfx') not in (None, 'none')]
    sfx_path = synthesize_sfx(sfx_events, seconds, out_dir / 'meme-sfx.wav')
    inputs = ['-i', str(Path(speech['path']).resolve()), '-i', str(sfx_path.resolve())]
    mix = f'[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{seconds:.3f}[s];[2:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.6,apad,atrim=0:{seconds:.3f}[x];'
    labels = '[s][x]'
    if music_path:
        from .music import extend_music
        covered = extend_music(music_path, seconds, out_dir / 'music-covered.wav', check, ffmpeg, ffprobe)
        inputs += ['-i', str(Path(covered['path']).resolve())]
        mix += f'[3:a]aresample=48000,aformat=channel_layouts=stereo,volume={max(0.0, min(1.0, volume)) * 0.75:.3f},apad,atrim=0:{seconds:.3f}[m];'
        labels += '[m]'
    count = labels.count('[')
    # Narration is already normalized per utterance and music to -20 LUFS: sum, then only limit peaks.
    mix += f'{labels}amix=inputs={count}:normalize=0:duration=first,alimiter=limit=0.89:level=false,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a]'
    part = target.with_name('video.part.mp4')
    log = out_dir / 'meme-render.log'
    args = [ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0',
            *inputs, '-filter_complex', f'[0:v]scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1,format=yuv420p[v];' + mix,
            '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-r', str(FPS),
            '-c:a', 'aac', '-b:a', '192k', '-t', f'{seconds:.3f}', '-movflags', '+faststart', str(part)]

    template = bands(meta.get('hook') or job['request']['idea'][:60], meta.get('payoff') or '')
    captions = [caption(text) for _, _, _, text in beats]
    total = int(math.ceil(seconds * FPS))
    with open(log, 'wb') as err:
        process = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
        try:
            current, composed = -1, None
            started = time.monotonic()
            for n in range(total):
                if n % 30 == 0:
                    check()
                t = n / FPS
                index = current if current >= 0 and beats[current][1] <= t < beats[current][2] else None
                if index is None:
                    index = next((i for i, b in enumerate(beats) if b[1] <= t < b[2]), len(beats) - 1 if t >= beats[-1][1] else 0)
                if index != current:
                    current = index
                    beat, start, end, _ = beats[index]
                    composed = Beat(catalog, beat, start, end if index < len(beats) - 1 else seconds, index)
                scene = composed.frame(max(0.0, t - composed.start))
                frame = template.copy()
                frame.paste(scene, (0, TOP_H))
                cap = captions[current]
                frame.paste(cap, (0, TOP_H + SH - cap.height - 6), cap)
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            while process.poll() is None:
                check()
                time.sleep(0.2)
        except BrokenPipeError:
            pass
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if process.returncode:
        raise PermanentError('Meme render failed: ' + log.read_text(encoding='utf-8', errors='replace')[-2000:])
    ensure_clean_audio(part, check, ffmpeg)
    part.replace(target)
    data = probe(target, ffprobe)
    actual = float(data['format']['duration'])
    result = {'video': str(target), 'duration_seconds': actual, 'renderer': RENDERER_VERSION, 'beats': len(beats),
              'render_seconds': round(time.monotonic() - started, 1), 'sfx_events': len(sfx_events)}
    receipt.write_text(json.dumps({'identity': identity, 'sha256': digest(target), 'result': result}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**result, 'assets': [asset(target), asset(receipt)]}
