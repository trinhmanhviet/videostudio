import tempfile,unittest
from pathlib import Path
from videostudio.output_layout import publish_video,publish_pair,job_deliverables,publish_subtitles
from videostudio.core import Store

class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'db',self.root/'out')
        self.job,_=self.store.create(dict(idea='Test',project='Project',voice_id='voice',duration_seconds=30),'one')
        self.folder=Path(self.job['output'])
        self.srt=self.folder/'subtitles.srt';self.srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nXin chào\n',encoding='utf8')
        self.job['checkpoints']['subtitles']={'srt_path':str(self.srt)}
    def tearDown(self):self.tmp.cleanup()
    def video(self,name='video.mp4'):
        path=self.folder/name;path.write_bytes(b'fixture');return str(path)
    def test_copies_beside_each_version_and_keeps_original(self):
        first=publish_video(self.job,{'video':self.video(),'assets':[]})
        self.job['checkpoints']['render']=first
        second=publish_video(self.job,{'video':self.video(),'assets':[]})
        self.assertNotEqual(first['video'],second['video'])
        for result in (first,second):
            subtitle=Path(result['video']).with_suffix('.srt')
            self.assertEqual(subtitle.read_bytes(),self.srt.read_bytes())
            self.assertIn(str(subtitle),[a['path'] for a in result['assets']])
        self.assertTrue(self.srt.exists())
        self.job['checkpoints']['render']=second
        self.assertIn(Path(first['video']).with_suffix('.srt'),job_deliverables(self.job))
    def test_pair_has_its_own_srt_files(self):
        result=publish_pair(self.job,{'video':self.video(),'video_ngang':self.video('wide.mp4'),'assets':[]})
        for key in ('video','video_ngang'):
            self.assertEqual(Path(result[key]).with_suffix('.srt').read_bytes(),self.srt.read_bytes())
    def test_edited_captions_only_use_current_overlays(self):
        overlays=self.folder/'edit-overlays.ass'
        overlays.write_text('[Events]\nDialogue: 0,0:00:00.00,0:00:10.00,Title,,0,0,0,,Title\nDialogue: 1000,0:00:02.00,0:00:03.50,Caption,,0,0,0,,{\\b1}Nội dung\\Nmới\n',encoding='utf8')
        result=publish_video(self.job,{'video':self.video(),'edit_plan_sha256':'snapshot','assets':[]})
        text=Path(result['video']).with_suffix('.ass').read_text(encoding='utf8')
        self.assertEqual(text,overlays.read_text(encoding='utf8'))
        self.assertFalse(Path(result['video']).with_suffix('.srt').exists())
    def test_disabled_editor_captions_never_reintroduce_original(self):
        result=publish_video(self.job,{'video':self.video(),'edit_plan_sha256':'snapshot','assets':[]})
        self.assertFalse(Path(result['video']).with_suffix('.srt').exists())
    def test_manual_meme_render_never_exports_stale_checkpoint_captions(self):
        result=publish_video(self.job,{'video':self.video(),'renderer':'meme-hyperframes-v1-rerender','assets':[]})
        self.assertFalse(Path(result['video']).with_suffix('.srt').exists())
    def test_backfill_can_keep_existing_external_subtitles(self):
        result=publish_video(self.job,{'video':self.video(),'assets':[]})
        target=Path(result['video']).with_suffix('.srt');target.write_text('User edited',encoding='utf8')
        publish_subtitles(self.job,result,overwrite=False)
        self.assertEqual(target.read_text(encoding='utf8'),'User edited')

if __name__=='__main__':unittest.main()
