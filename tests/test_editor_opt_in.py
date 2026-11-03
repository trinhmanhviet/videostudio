import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from videostudio.providers import Pipeline,flow_reference_enabled
from videostudio.core import PermanentError

class OptionalEditingIntegrationTests(unittest.TestCase):
    def job(self, request=None):
        return {'id':'00000000-0000-4000-8000-000000000001','output':'.',
                'request':{'duration_seconds':8,'image_provider':'flow',**(request or {})},
                'checkpoints':{'plan':{},'images':{},'speech':{'duration_seconds':8}}}
    def test_old_ui_plan_handler_does_not_opt_into_new_editing(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline.plan=Mock(return_value={'title':'Keep existing production'})
        result=pipeline.handlers()['plan'](self.job(),lambda:None)
        self.assertEqual(result,{'title':'Keep existing production'})
    def test_explicit_new_ui_plan_records_preset_without_mutating_returned_draft(self):
        pipeline=Pipeline.__new__(Pipeline);draft={'title':'New workspace'};pipeline.plan=Mock(return_value=draft)
        result=pipeline.handlers()['plan'](self.job({'edit_preset':'science'}),lambda:None)
        self.assertEqual(result.get('editing_version'),1);self.assertEqual(result.get('edit_preset'),'science')
        self.assertNotIn('editing_version',draft)
    def test_old_ui_music_does_not_dispatch_new_chapter_music(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline.accepted_music=Mock(return_value=False)
        with patch('videostudio.edit_audio.generate_chapter_music') as chapter:
            with self.assertRaises(PermanentError):pipeline.music(self.job(),lambda:None)
            chapter.assert_not_called()
    def test_explicit_workflow_uses_chapter_music_including_intentional_mute(self):
        pipeline=Pipeline.__new__(Pipeline)
        with patch('videostudio.edit_audio.generate_chapter_music',return_value={'intentional_mute':True}) as chapter:
            result=pipeline.music(self.job({'edit_preset':'everyday','music_enabled':False}),lambda:None)
            self.assertTrue(result['intentional_mute']);chapter.assert_called_once()
    def test_reference_toggle_is_explicit_and_does_not_change_old_jobs(self):
        self.assertTrue(flow_reference_enabled(self.job()))
        self.assertFalse(flow_reference_enabled(self.job({'references_enabled':False})))
    def test_frozen_edit_export_dispatches_exact_plan_before_legacy_renderer(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline.ffmpeg='ffmpeg';pipeline.ffprobe='ffprobe';pipeline.scene_editor=Mock()
        job=self.job();job['checkpoints']['images']['edit_plan_snapshot']='frozen.json'
        with patch('videostudio.edit_render.render_edit_plan',return_value={'video':'new.mp4','assets':[]}) as render,patch('videostudio.output_layout.publish_video',side_effect=lambda j,result:result):
            result=pipeline.render(job,lambda:None)
            self.assertEqual(result['video'],'new.mp4');render.assert_called_once();pipeline.scene_editor.require_user_review.assert_not_called()

if __name__=='__main__':unittest.main()
