import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from videostudio.core import Store, digest


class JobDetailsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'jobs.db', Path(self.tmp.name) / 'out')
        self.job, _ = self.store.create({'idea': 'Fixture', 'voice_id': 'fixture', 'duration_seconds': 8}, 'details')
        self.root = Path(self.job['output'])
        self.scenes = [{'narration': 'First', 'visual_prompt': 'red room', 'start': 0, 'end': 3, 'duration': 3},
                       {'narration': 'Second', 'visual_prompt': 'blue room', 'start': 3, 'end': 7, 'duration': 4}]
        with self.store.db() as c:
            c.execute('INSERT INTO checkpoints VALUES(?,?,?)', (self.job['id'], 'speech', json.dumps({'scenes': self.scenes, 'utterances': [], 'assets': []})))
            c.execute("UPDATE jobs SET state='failed',stage='images' WHERE id=?", (self.job['id'],))

    def service(self):
        from videostudio.job_details import JobDetails
        return JobDetails(self.store)

    def image(self, index=0, **overrides):
        path = self.root / f'images-{index:04}.png'
        Image.new('RGB', (64, 64), 'red').save(path)
        receipt = {'sha256': digest(path), 'prompt': self.scenes[index]['visual_prompt'], 'provider': 'comfy', **overrides}
        path.with_suffix('.checkpoint.json').write_text(json.dumps(receipt))
        return path

    def test_partial_images_are_read_only_and_do_not_create_checkpoint_or_editor_head(self):
        self.image()
        before = self.store.get(self.job['id'])
        view = self.service().snapshot(self.job['id'])
        self.assertFalse(view['editable'])
        self.assertEqual(view['image_count'], 1)
        self.assertEqual(len(view['scenes']), 2)
        self.assertTrue(view['scenes'][0]['image_url'].endswith('/details/images/0'))
        self.assertIsNone(view['scenes'][1]['image_url'])
        self.assertEqual(before, self.store.get(self.job['id']))
        self.assertNotIn(str(self.root), json.dumps(view))

    def test_stale_prompt_wrong_hash_and_invalid_image_are_missing(self):
        for overrides in ({'prompt': 'retired prompt'}, {'sha256': '0' * 64}):
            self.image(**overrides)
            self.assertEqual(self.service().snapshot(self.job['id'])['image_count'], 0)
        path = self.image()
        path.write_bytes(b'not an image')
        path.with_suffix('.checkpoint.json').write_text(json.dumps({'sha256': digest(path), 'prompt': 'red room'}))
        self.assertEqual(self.service().snapshot(self.job['id'])['image_count'], 0)

    def test_image_read_revalidates_receipt_and_bytes(self):
        path = self.image()
        service = self.service()
        self.assertEqual(service.image(self.job['id'], 0), path.resolve())
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError): service.image(self.job['id'], 0)
        for index in (-1, 2):
            with self.assertRaises(ValueError): service.image(self.job['id'], index)

    def test_grouped_utterances_preserve_scene_count_and_narration(self):
        utterances = [dict(self.scenes[0], scene_index=0, narration='One', end=1), dict(self.scenes[0], scene_index=0, narration='Two', start=1), dict(self.scenes[1], scene_index=1)]
        with self.store.db() as c:
            c.execute('UPDATE checkpoints SET value=? WHERE job=?', (json.dumps({'utterances': utterances}), self.job['id']))
        view = self.service().snapshot(self.job['id'])
        self.assertEqual(len(view['scenes']), 2)
        self.assertEqual(view['scenes'][0]['narration'], 'One Two')
        self.assertEqual(view['scenes'][0]['end'], 3)

    def test_retired_jobs_and_outside_output_are_rejected(self):
        self.image()
        with self.store.db() as c:
            c.execute('CREATE TABLE job_file_deletions(job TEXT)')
            c.execute('INSERT INTO job_file_deletions VALUES(?)', (self.job['id'],))
        with self.assertRaises(ValueError): self.service().snapshot(self.job['id'])
        with self.store.db() as c:
            c.execute('DELETE FROM job_file_deletions')
            c.execute('UPDATE jobs SET output=? WHERE id=?', (self.tmp.name, self.job['id']))
        with self.assertRaises(ValueError): self.service().snapshot(self.job['id'])

    def test_routes_serve_only_valid_scoped_images_without_mutation(self):
        from videostudio.job_details import register_job_details_routes
        self.image()
        app = FastAPI()
        register_job_details_routes(app, self.store, None, lambda request: None)
        client = TestClient(app)
        prefix = '/api/jobs/' + self.job['id'] + '/details'
        self.assertEqual(client.get(prefix).status_code, 200)
        self.assertEqual(client.get(prefix + '/images/0').headers['content-type'], 'image/png')
        self.assertEqual(client.get(prefix + '/images/1').status_code, 404)
        self.assertEqual(client.post(prefix, json={}).status_code, 405)
        self.assertNotIn(str(self.root), client.get(prefix).text)

    def test_meme_has_no_unsafe_scene_layout(self):
        with self.store.db() as c:
            req = dict(self.job['request'], workflow_mode='meme')
            c.execute('UPDATE jobs SET request=? WHERE id=?', (json.dumps(req), self.job['id']))
        view = self.service().snapshot(self.job['id'])
        self.assertEqual(view['scenes'], [])
        self.assertIn('/meme-editor?job=', view['editor_url'])

    def test_derived_video_can_read_attested_parent_audio_but_not_arbitrary_output_files(self):
        parent,_=self.store.create({'idea':'Parent','voice_id':'fixture','duration_seconds':8},'parent')
        audio=Path(parent['output'])/'music.wav';audio.write_bytes(b'owned-audio-fixture')
        saved={'assets':[{'path':str(audio),'sha256':digest(audio)}]}
        with self.store.db() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(parent['id'],'music',json.dumps(saved)))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(self.job['id'],'music',json.dumps(saved)))
        service=self.service();view=service.snapshot(self.job['id'])
        self.assertEqual(len(view['media']['music']),1)
        with self.store.db() as db:db.execute('DELETE FROM checkpoints WHERE job=? AND stage=?',(parent['id'],'music'))
        self.assertEqual(service.snapshot(self.job['id'])['media']['music'],[])

    def test_derived_video_counts_and_previews_attested_parent_images(self):
        parent,_=self.store.create({'idea':'Parent','voice_id':'fixture','duration_seconds':8},'image-parent')
        image=Path(parent['output'])/'images-0000.png';Image.new('RGB',(64,64),'blue').save(image)
        saved={'scenes':[{'path':str(image),'duration':3}],'assets':[{'path':str(image),'sha256':digest(image)}]}
        with self.store.db() as db:
            for jid in (parent['id'],self.job['id']):db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(jid,'images',json.dumps(saved)))
        service=self.service();self.assertEqual(service.snapshot(self.job['id'])['image_count'],1)
        self.assertEqual(service.image_bytes(self.job['id'],0),image.read_bytes())


if __name__ == '__main__': unittest.main()
