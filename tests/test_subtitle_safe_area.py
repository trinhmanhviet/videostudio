import array
import math
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image
from videostudio.captions import write_captions
from videostudio import media


class SubtitleSafeAreaTests(unittest.TestCase):
    def test_legacy_ass_is_raised_in_new_render_and_visual_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            Image.new('RGB',(1080,1920),'black').save(root/'image.png')
            for name,frequency in (('speech',250),('music',440)):
                samples=array.array('h',(int(1000*math.sin(2*math.pi*frequency*i/16000)) for i in range(32000)))
                with wave.open(str(root/(name+'.wav')),'wb') as wav:
                    wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(samples.tobytes())
            captions=write_captions([{'start':0,'end':2,'narration':'Dòng phụ đề an toàn.'}],root/'subtitles.srt')
            ass=Path(captions['ass_path'])
            # An old output can carry 130px ASS margins. The renderer must
            # override them without rewriting the user's saved subtitle file.
            source=ass.read_text(encoding='utf8')
            legacy=source.replace(',90,90,576,1',',90,90,130,1').replace(',90,90,288,1',',90,90,130,1')
            ass.write_text(legacy,encoding='utf8')
            video=media.render(root/'image.png',root/'speech.wav',root/'music.wav',ass,root/'normal.mp4',2,lambda:None)['video']
            self.assert_subtitle_band(video,root/'normal.png')
            revision=media.render_visual_revision([{'path':str(root/'image.png'),'duration':2}],video,ass,root/'revision.mp4',2,lambda:None)['video']
            self.assert_subtitle_band(revision,root/'revision.png')
            self.assertEqual(ass.read_text(encoding='utf8'),legacy)

    def assert_subtitle_band(self,video,frame):
        media.run(['ffmpeg','-v','error','-y','-ss','0.5','-i',video,'-frames:v','1',frame],lambda:None)
        with Image.open(frame) as image:
            bounds=image.convert('L').point(lambda value:255 if value>180 else 0).getbbox()
        self.assertIsNotNone(bounds,'Subtitle glyphs should be present')
        self.assertGreater(bounds[1],1150)
        self.assertLessEqual(bounds[3],1344,'Text must remain above the lower 30% social overlay area')
