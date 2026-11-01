import tempfile
import json
import unittest
from pathlib import Path
from videostudio.core import Store
from videostudio.output_layout import final_video_path, publish_video


class OutputLayoutTests(unittest.TestCase):
    def test_jobs_share_project_folder_but_keep_separate_data_and_videos(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db.sqlite3',Path(folder)/'videos')
            request={'idea':'Một video','voice_id':'test','duration_seconds':8,'project':'vuan1'}
            jobs=[store.create(request,str(i))[0] for i in range(2)]
            for job in jobs:
                self.assertEqual(Path(job['output']),store.outputs/'vuan1'/'data'/job['id'])
                source=Path(job['output'])/'video.mp4';source.write_bytes(b'fixture video')
                result=publish_video(job,{'video':str(source),'assets':[]})
                self.assertEqual(Path(result['video']).parent,store.outputs/'vuan1')
                self.assertTrue(Path(result['video']).is_file())
                self.assertFalse(source.exists())
            self.assertNotEqual(final_video_path(jobs[0]),final_video_path(jobs[1]))
            self.assertEqual(store.create(request,'0')[0]['id'],jobs[0]['id'])

    def test_new_render_never_overwrites_existing_finished_video(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos')
            job,_=store.create({'idea':'test','project':'vuan1','voice_id':'test','duration_seconds':8},'one')
            paths=[]
            for content in (b'first',b'second'):
                source=Path(job['output'])/'video.mp4';source.write_bytes(content)
                paths.append(Path(publish_video(job,{'video':str(source),'assets':[]})['video']))
            self.assertNotEqual(*paths)
            self.assertEqual(paths[0].read_bytes(),b'first')
            self.assertEqual(paths[1].read_bytes(),b'second')

    def test_old_output_paths_stay_compatible(self):
        self.assertEqual(final_video_path({'id':'old','output':'old-folder'}),Path('old-folder/video.mp4'))

    def test_public_video_route_and_deletion_preserve_other_project_exports(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        from videostudio.project_lifecycle import OutputRemoval
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db.sqlite3',Path(folder)/'videos')
            request={'idea':'Test','voice_id':'test','duration_seconds':8,'project':'vuan1'}
            jobs=[store.create(request,str(i))[0] for i in range(2)]
            for job in jobs:
                source=Path(job['output'])/'video.mp4';source.write_bytes(b'video fixture')
                result=publish_video(job,{'video':str(source),'assets':[]})
                with store.db() as c:
                    c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'render',json.dumps(result)))
                    c.execute("UPDATE jobs SET state='completed' WHERE id=?",(job['id'],))
                if job['id']==jobs[0]['id']:
                    source.write_bytes(b'another export')
                    publish_video(job,{'video':str(source),'assets':[]})
            app=create_app(store=store,worker_enabled=False)
            with TestClient(app) as client:
                response=client.get('/api/jobs/'+jobs[0]['id']+'/files/video.mp4')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.content,b'video fixture')
                self.assertEqual(client.get('/api/jobs/'+jobs[0]['id']+'/files/other.mp4').status_code,404)
            with store.db() as c:
                removal=OutputRemoval(store,c,[jobs[0]]);removal.stage()
            self.assertFalse(removal.purge())
            self.assertFalse(final_video_path(jobs[0]).exists())
            self.assertEqual(list((store.outputs/'vuan1').glob('video-'+jobs[0]['id']+'*.mp4')),[])
            self.assertTrue(final_video_path(jobs[1]).is_file())
            self.assertTrue(Path(jobs[1]['output']).is_dir())
