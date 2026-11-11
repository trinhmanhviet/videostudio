import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from videostudio.providers import Pipeline
from videostudio.core import digest


class FlowProgressTests(unittest.TestCase):
    def test_retry_progress_counts_cached_and_new_images_across_all_scenes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pipeline=Pipeline.__new__(Pipeline);pipeline.store=Mock()
            scenes=[{'visual_prompt':f'Scene {i}','duration':1} for i in range(8)]
            job={'id':str(uuid.uuid4()),'output':folder,'request':{'duration_seconds':8},'checkpoints':{'speech':{'scenes':scenes,'duration_seconds':8}}}
            def picture(path):
                image=Image.new('RGB',(512,512),'black');image.paste('white',(0,0,256,512));image.save(path)
            for i in range(2):
                path=root/f'images-{i:04}.png';picture(path)
                path.with_suffix('.checkpoint.json').write_text(json.dumps({'provider':'flow','prompt':f'Scene {i}','sha256':digest(path),'character_mentions':[]}))
            def generate(job,tasks,check,timeout):
                for task in tasks:picture(task['output_path'])
                return {t['task_id']:{'task_id':t['task_id'],'media_id':f'media-{t["ordinal"]}','request_id':'receipt','project_url':'https://flow.google.com/project/test'} for t in tasks}
            pipeline._browser_scene_images_batch=Mock(side_effect=generate)
            with patch('videostudio.providers.available_flow_batch_sizes',return_value=[1,3]):
                pipeline._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',3)
            messages=[call.args[2] for call in pipeline.store.log.call_args_list]
            self.assertTrue(messages[0].startswith('Đã tải 2/8 ảnh'),messages)
            self.assertTrue(any(text.startswith('Đã tải 5/8 ảnh') for text in messages),messages)
            self.assertTrue(messages[-1].startswith('Đã tải 8/8 ảnh'),messages)
            ordinals=[[t['ordinal'] for t in call.args[1]] for call in pipeline._browser_scene_images_batch.call_args_list]
            self.assertEqual(ordinals,[[2,3,4],[5,6,7]])
            pipeline.store.log.reset_mock();pipeline._browser_scene_images_batch.reset_mock()
            pipeline._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',3)
            self.assertTrue(pipeline.store.log.call_args.args[2].startswith('Đã tải 8/8 ảnh'))
            pipeline._browser_scene_images_batch.assert_not_called()
