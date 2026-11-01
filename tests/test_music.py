import unittest,tempfile,subprocess
from pathlib import Path
from videostudio.music import extend_music, assemble_scene_soundtracks
from videostudio.media import probe
from videostudio.core import PermanentError

class MusicTests(unittest.TestCase):
    def test_scene_music_changes_at_measured_scene_boundary_without_silent_tail(self):
        import array
        from videostudio.media import run
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);clips=[]
            for frequency in (220,880):
                source=root/f'{frequency}.wav'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={frequency}:duration=10','-y',str(source)],check=True)
                clips.append({'path':str(source),'duration':2})
            output=root/'mixed.wav';assemble_scene_soundtracks(clips,4,output,lambda:None)
            raw=run(['ffmpeg','-v','error','-ss','3.5','-i',output,'-t','0.2','-ar','16000','-ac','1','-f','f32le','-'],lambda:None)
            samples=array.array('f');samples.frombytes(raw)
            crossings=sum((a<0)!=(b<0) for a,b in zip(samples,samples[1:]))
            self.assertGreater(crossings,250,'Scene 2 should play its own 880Hz track, not scene 1 or silence')

    def test_crossfade_covers_requested_duration(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);source=p/'source.wav';out=p/'covered.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-y',str(source)],check=True)
            r=extend_music(source,5.2,out,lambda:None)
            self.assertEqual(r['repeats'],3);self.assertGreater(r['crossfade_seconds'],0)
            self.assertAlmostEqual(float(probe(out)['format']['duration']),5.2,places=2)
            subprocess.run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],check=True)

    def test_assemble_scene_soundtracks_multiple_clips(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            clips = []
            freqs = [220, 330, 440]
            for i, freq in enumerate(freqs):
                clip_path = p / f'scene_music_{i}.wav'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={freq}:duration=3','-y',str(clip_path)],check=True)
                clips.append({'path': str(clip_path)})

            out = p / 'soundtrack.wav'
            res = assemble_scene_soundtracks(clips, target_seconds=8.5, output=out, check=lambda: None)
            self.assertEqual(res['scene_tracks'], 3)
            self.assertTrue(Path(res['path']).is_file())
            dur = float(probe(out)['format']['duration'])
            self.assertAlmostEqual(dur, 8.5, delta=0.2)
            subprocess.run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],check=True)

    def test_assemble_scene_soundtracks_single_clip(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            source = p / 'single.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-y',str(source)],check=True)
            out = p / 'soundtrack_single.wav'
            res = assemble_scene_soundtracks([{'path': str(source)}], target_seconds=4.0, output=out, check=lambda: None)
            dur = float(probe(out)['format']['duration'])
            self.assertAlmostEqual(dur, 4.0, places=1)

    def test_assemble_scene_soundtracks_empty_raises(self):
        with self.assertRaises(PermanentError):
            assemble_scene_soundtracks([], target_seconds=5.0, output='dummy.wav', check=lambda: None)

if __name__=='__main__':unittest.main()
