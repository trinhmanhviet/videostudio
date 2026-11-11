import array
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from videostudio.core import PermanentError,digest
from videostudio.media import run,audio_report,probe
from videostudio.music import normalize_music_levels

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class MusicLevelRepairTests(unittest.TestCase):
    def test_above_full_scale_input_is_normalized_without_changing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'hot.wav'
            run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2','-af','volume=11','-c:a','pcm_f32le',source],lambda:None)
            original=digest(source)
            with self.assertRaisesRegex(PermanentError,'Silent or clipped'):audio_report(source,lambda:None)
            result=normalize_music_levels(source,root,lambda:None)
            self.assertEqual(digest(source),original)
            self.assertGreater(result['raw_audio_quality']['peak'],1.05)
            self.assertGreater(result['raw_audio_quality']['clipped_fraction'],.001)
            self.assertLess(result['audio_quality']['peak'],.95)
            self.assertLessEqual(result['audio_quality']['clipped_fraction'],.001)
            self.assertGreater(result['audio_quality']['rms'],.001)
            self.assertAlmostEqual(float(probe(result['path'])['format']['duration']),2,delta=.03)
            self.assertEqual(normalize_music_levels(source,root,lambda:None)['path'],result['path'])
    def test_silent_music_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'silent.wav'
            run(['ffmpeg','-v','error','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',1,source],lambda:None)
            with self.assertRaisesRegex(PermanentError,'Silent or clipped'):normalize_music_levels(source,root,lambda:None)
