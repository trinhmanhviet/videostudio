import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from videostudio.core import PermanentError, digest
from videostudio.providers import Pipeline, scene_image_prompt


class FlowCheckpointReuseTests(unittest.TestCase):
    def test_completed_batch_writes_source_and_submitted_prompts_for_retry(self):
        for stale in (False, True):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'images-0000.png'
                checkpoint=path.with_suffix('.checkpoint.json')
                if stale:checkpoint.write_text(json.dumps({'provider':'flow','prompt':'old draft'}),encoding='utf8')
                job={'id':str(uuid.uuid4()),'output':folder,'request':{'duration_seconds':8},
                     'checkpoints':{'speech':{'scenes':[{'visual_prompt':'A @prop on a table','duration':8}], 'duration_seconds':8}}}
                pipeline=Pipeline.__new__(Pipeline)
                def generate(job,tasks,check,timeout):
                    picture=Image.new('RGB',(512,512),'black')
                    picture.paste('white',(0,0,256,512));picture.save(path)
                    return {task['task_id']:{'task_id':task['task_id'],'request_id':'receipt',
                            'media_id':'media','project_url':'https://flow.google.com/project/test'} for task in tasks}
                pipeline._browser_scene_images_batch=Mock(side_effect=generate)
                with patch('videostudio.providers.available_flow_batch_sizes',return_value=[1,10]):
                    pipeline._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',10)
                    saved=json.loads(checkpoint.read_text(encoding='utf8'))
                    self.assertEqual(saved['prompt'],'A @prop on a table')
                    self.assertEqual(saved['submitted_prompt'],scene_image_prompt('A prop on a table',wide=True))
                    pipeline._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',10)
                self.assertEqual(pipeline._browser_scene_images_batch.call_count,1)

    def test_normalized_checkpoint_reuses_image_without_new_generation(self):
        self.check_reuse()

    def test_changed_character_is_still_rejected(self):
        self.check_reuse(change_character=True)

    def test_changed_prompt_is_still_rejected(self):
        self.check_reuse(change_prompt=True)

    def check_reuse(self, change_character=False, change_prompt=False):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'images-0000.png'
            Image.new('RGB',(512,512),(90,100,110)).save(path)
            reference={'character_id':str(uuid.uuid4()),'name':'marie','project_url':'https://flow.google.com/project/test'}
            saved={'provider':'flow','prompt':'Portrait of marie','submitted_prompt':'Portrait of marie',
                   'sha256':digest(path),'character_mentions':[dict(reference)]}
            path.with_suffix('.checkpoint.json').write_text(json.dumps(saved),encoding='utf8')
            if change_character:reference={**reference,'character_id':str(uuid.uuid4())}
            scene={'visual_prompt':'Portrait of @marie'+(' outdoors' if change_prompt else ''),
                   'character_ids':['marie'],'duration':8}
            job={'id':str(uuid.uuid4()),'output':folder,'request':{'duration_seconds':8},
                 'checkpoints':{'speech':{'scenes':[scene],'duration_seconds':8}}}
            pipeline=Pipeline.__new__(Pipeline)
            pipeline._browser_scene_images_batch=Mock(side_effect=AssertionError('Must not regenerate'))
            if change_character or change_prompt:
                with self.assertRaises(PermanentError):
                    pipeline._flow_batch_images(job,lambda:None,{'marie':reference},[],'native_flow_characters',10)
            else:
                result=pipeline._flow_batch_images(job,lambda:None,{'marie':reference},[],'native_flow_characters',10)
                self.assertEqual(result['scenes'][0]['path'],str(path))
                self.assertEqual(digest(path),saved['sha256'])
            pipeline._browser_scene_images_batch.assert_not_called()
