import unittest,tempfile,wave,struct,math
from pathlib import Path
from videostudio.captions import wrap_caption,write_captions
from videostudio.media import render,probe
class CaptionTests(unittest.TestCase):
    def test_preserves_accents_and_words(self):
        text='Một buổi sáng yên bình, cô gái mở cửa nhìn ra khu vườn.'
        value=wrap_caption(text)
        self.assertEqual(' '.join(value.split()),text)
        self.assertTrue(all(len(line)<=32 for line in value.splitlines()))
    def test_rejects_overflow(self):
        with self.assertRaises(ValueError):wrap_caption('từ '*100)
    def test_rejects_overlapping_cues(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):write_captions([{'start':0,'end':2,'narration':'Xin chào'},{'start':1,'end':3,'narration':'Tạm biệt'}],Path(t)/'a.srt')
    def test_measured_cues(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.srt';result=write_captions([{'start':0,'end':1.25,'narration':'Xin chào'},{'start':1.25,'end':2,'narration':'Tạm biệt'}],p)
            self.assertEqual(result['cue_count'],2);self.assertIn('00:00:01,250',p.read_text(encoding='utf8'))
class MultiSceneTests(unittest.TestCase):
    def test_cpu_render_two_measured_scenes(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            for name,color in [('one','green'),('two','blue')]:Image.new('RGB',(180,320),color).save(p/(name+'.png'))
            for name,freq in [('speech',250),('music',440)]:
                with wave.open(str(p/(name+'.wav')),'wb') as f:
                    f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b''.join(struct.pack('<h',int(1000*math.sin(2*math.pi*freq*i/16000))) for i in range(32000)))
            write_captions([{'start':0,'end':1,'narration':'Cảnh thứ nhất'},{'start':1,'end':2,'narration':'Cảnh thứ hai'}],p/'a.srt')
            scenes=[{'path':str(p/'one.png'),'duration':1},{'path':str(p/'two.png'),'duration':1}]
            r=render(scenes,p/'speech.wav',p/'music.wav',p/'a.srt',p/'video.mp4',2,lambda:None)
            stream=next(s for s in probe(r['video'])['streams'] if s['codec_type']=='video')
            self.assertEqual((stream['width'],stream['height']),(1080,1920));self.assertEqual(stream['avg_frame_rate'],'30/1')
            self.assertTrue((p/'visual-0000.json').exists());self.assertTrue((p/'visual-0001.json').exists())
if __name__=='__main__':unittest.main()
