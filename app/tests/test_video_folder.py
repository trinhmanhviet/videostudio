import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.output_layout import final_video_path

class Pipeline:
    def handlers(self):return {}
    def preflight(self):return {'ready':False,'checks':[]}

class VideoFolderTests(unittest.TestCase):
    def test_opens_only_existing_job_video_folder_and_rejects_foreign_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'jobs.sqlite3',Path(tmp)/'out')
            job,_=store.create({'idea':'Test','voice_id':'voice','duration_seconds':30},'test')
            video=final_video_path(job);video.parent.mkdir(parents=True,exist_ok=True)
            with TestClient(create_app(store,Pipeline(),False),base_url='http://localhost:8877') as client,patch('os.startfile',create=True) as launch:
                url='/api/jobs/'+job['id']+'/open-folder'
                self.assertEqual(client.post(url,json={}).status_code,409)
                video.write_bytes(b'fixture')
                self.assertEqual(client.post(url,json={},headers={'Origin':'https://foreign.invalid'}).status_code,403)
                self.assertEqual(client.post(url,json={'path':'C:/Windows'}).status_code,422)
                launch.assert_not_called()
                self.assertEqual(client.post(url,json={}).status_code,200)
                launch.assert_called_once_with(str(video.parent.resolve()))
