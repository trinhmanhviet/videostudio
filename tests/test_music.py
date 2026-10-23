import unittest,tempfile,subprocess
from pathlib import Path
from videostudio.music import extend_music
from videostudio.media import probe
class MusicTests(unittest.TestCase):
    def test_crossfade_covers_requested_duration(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);source=p/'source.wav';out=p/'covered.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-y',str(source)],check=True)
            r=extend_music(source,5.2,out,lambda:None)
            self.assertEqual(r['repeats'],3);self.assertGreater(r['crossfade_seconds'],0)
            self.assertAlmostEqual(float(probe(out)['format']['duration']),5.2,places=2)
            subprocess.run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],check=True)
if __name__=='__main__':unittest.main()
