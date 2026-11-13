"""Frame-based regression for the automatic still-image renderer (two seconds)."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from videostudio import media
from videostudio.core import digest


def marker_centers(path, width, height):
    """Measure four symmetric luma markers, independent of chroma compression."""
    command = ['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    points = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        while True:
            raw = process.stdout.read(width * height)
            if not raw:
                break
            if len(raw) != width * height:
                raise AssertionError('Partial decoded frame')
            image = Image.frombytes('L', (width, height), raw)
            centers = []
            for dx, dy in [(-200, -200), (200, -200), (-200, 200), (200, 200)]:
                x, y = width // 2 + dx - 65, height // 2 + dy - 65
                values = image.crop((x, y, x + 130, y + 130)).point(lambda v: max(v - 32, 0)).tobytes()
                mass = sum(values)
                if not mass:
                    raise AssertionError('Motion marker disappeared')
                centers.append((x + sum((i % 130) * v for i, v in enumerate(values)) / mass,
                                y + sum((i // 130) * v for i, v in enumerate(values)) / mass))
            points.append(centers)
        error = process.stderr.read()
        if process.wait():
            raise AssertionError(error.decode(errors='replace'))
    return points


class MotionIdentityTests(unittest.TestCase):
    def test_old_quantized_clips_are_invalidated_for_each_aspect_and_provider(self):
        for wide in (False, True):
            for provider in (None, 'flow'):
                policy = '1920x1080-30-pan-v1' if wide else '1080x1920-30-pan-v1'
                if provider == 'flow':
                    policy += '-flow-bottom-crop-6pct-v1'
                old = hashlib.sha256(('source-sha' + str(2.0) + policy).encode()).hexdigest()
                self.assertNotEqual(media.visual_clip_identity('source-sha', 2.0, provider, wide), old)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MotionFrameTests(unittest.TestCase):
    def test_center_does_not_jump_while_zoom_still_moves_and_cache_is_reused(self):
        for wide, width, height in [(False, 1080, 1920), (True, 1920, 1080)]:
            with self.subTest(wide=wide), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root / 'source.png'
                image = Image.new('RGB', (width, height), (12, 12, 12)); draw = ImageDraw.Draw(image)
                for dx, dy in [(-200, -200), (200, -200), (-200, 200), (200, 200)]:
                    x, y = width // 2 + dx, height // 2 + dy
                    draw.rectangle((x - 12, y - 12, x + 11, y + 11), fill='white')
                image.save(source); source_sha = digest(source)
                scenes = [{'path': str(source), 'duration': 2}]
                track = media.visual_track(scenes, root / 'track.mp4', lambda: None, wide=wide)
                points = marker_centers(track, width, height)
                self.assertEqual(len(points), 60)
                centers = [tuple(sum(p[axis] for p in frame) / 4 for axis in (0, 1)) for frame in points]
                max_jump = max(abs(b[axis] - a[axis]) for a, b in zip(centers, centers[1:]) for axis in (0, 1))
                self.assertLess(max_jump, .2, f'Centered zoom snapped by {max_jump:.3f} output pixels')
                # This must not pass by freezing the image or disabling motion.
                separation = [frame[1][0] - frame[0][0] for frame in points]
                self.assertGreater(max(separation) - min(separation), 2)
                clip = root / ('visual-wide-0000.mp4' if wide else 'visual-0000.mp4')
                stamp = clip.stat().st_mtime_ns
                with patch.object(media, 'run', wraps=media.run) as run:
                    media.visual_track(scenes, track, lambda: None, wide=wide)
                self.assertEqual(run.call_count, 1)  # Concat only; no re-encode.
                self.assertEqual(clip.stat().st_mtime_ns, stamp)
                receipt = clip.with_suffix('.json')
                saved = json.loads(receipt.read_text()); saved['identity'] = 'old-pan-v1'
                receipt.write_text(json.dumps(saved))
                with patch.object(media, 'run', wraps=media.run) as run:
                    media.visual_track(scenes, track, lambda: None, wide=wide)
                self.assertEqual(run.call_count, 2)  # Just this stale clip and concat.
                self.assertEqual(digest(source), source_sha)
                self.assertEqual(json.loads(receipt.read_text())['identity'],
                                 media.visual_clip_identity(source_sha, 2.0, wide=wide))


if __name__ == '__main__':
    unittest.main()
