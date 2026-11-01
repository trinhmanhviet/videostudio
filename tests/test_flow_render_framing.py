import tempfile
import unittest
from pathlib import Path

from PIL import Image
from videostudio import media
from videostudio.captions import write_captions


class FlowRenderFramingTests(unittest.TestCase):
    def test_uploaded_replacement_does_not_inherit_flow_crop(self):
        job={'request':{'image_provider':'flow'},'checkpoints':{'images':{'scenes':[
            {'path':'original.png','duration':2},
            {'path':'replacement.png','duration':2,'image_provider':'upload'}]}}}
        scenes=media.render_scenes(job)
        self.assertEqual(scenes[0]['image_provider'],'flow')
        self.assertEqual(scenes[1]['image_provider'],'upload')
        self.assertNotIn('image_provider',job['checkpoints']['images']['scenes'][0])

    def test_flow_crop_removes_bottom_strip_and_invalidates_old_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.png'
            image=Image.new('RGB',(768,1376),'black')
            image.paste('red',(0,1294,768,1376));image.save(source)
            def frame_red():
                data=media.run(['ffmpeg','-v','error','-i',root/'visual-track.mp4','-frames:v','1',
                                '-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],lambda:None)
                return data[0]
            scene={'path':str(source),'duration':0.1}
            media.visual_track([scene],root/'visual-track.mp4',lambda:None)
            self.assertGreater(frame_red(),3)
            scene['image_provider']='flow'
            media.visual_track([scene],root/'visual-track.mp4',lambda:None)
            self.assertLess(frame_red(),3)

    def test_subtitle_style_places_text_fifteen_percent_above_bottom(self):
        with tempfile.TemporaryDirectory() as folder:
            result=write_captions([{'narration':'Một câu phụ đề.','start':0,'end':2}],Path(folder)/'subtitles.srt')
            self.assertEqual(result['safe_margins_pixels']['bottom'],288)
            self.assertIn(',90,90,288,1',Path(result['ass_path']).read_text(encoding='utf8'))
