import asyncio
import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from videostudio.cdp_flow import FlowImages
from videostudio.core import Store


class CharacterRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_reads_same_entity_and_only_commits_a_verified_name(self):
        for verified in (True,False):
            with self.subTest(verified=verified),tempfile.TemporaryDirectory() as folder:
                command=AsyncMock()
                bridge=type('Bridge',(),{'job_lock':asyncio.Lock(),'connect':AsyncMock(),
                    'cdp':type('CDP',(),{'command':command})()})()
                flow=FlowImages(bridge,Path(folder));task=str(uuid.uuid4());job=str(uuid.uuid4());entity=str(uuid.uuid4())
                receipt={'task_id':task,'job_id':job,'kind':'native_character','name':'marie','character_manifest_id':'marie',
                         'prompt_sha256':hashlib.sha256(b'portrait').hexdigest(),'character_id':entity,
                         'project_url':'https://flow.google.com/project/test','stage':'project_ready','character_create_stage':'saving'}
                flow._write_receipt(task,receipt)
                flow._target=AsyncMock(return_value='tab');flow._session=AsyncMock(return_value='session')
                flow._wait_page=AsyncMock();flow._wait_character_complete=AsyncMock();flow._return_to_project_root=AsyncMock()
                flow._eval=AsyncMock(side_effect=[[{'value':'prompt'},{'value':'marie'}],verified])
                flow._click_named=AsyncMock()
                if verified:
                    result=await flow.create_character(task,job,'marie','marie','portrait')
                    self.assertEqual(result['character_id'],entity)
                    self.assertEqual(flow._read_receipt(task)['stage'],'character_saved')
                else:
                    with self.assertRaises(RuntimeError):await flow.create_character(task,job,'marie','marie','portrait')
                    self.assertEqual(flow._read_receipt(task)['character_create_stage'],'saving')
                flow._click_named.assert_not_awaited()
                self.assertFalse(any(call.args[0]=='Input.insertText' for call in command.await_args_list))

    async def test_failed_reconnect_never_marks_unsaved_character_as_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=type('Bridge',(),{'job_lock':asyncio.Lock(),'connect':AsyncMock(side_effect=RuntimeError('offline'))})()
            flow=FlowImages(bridge,Path(folder));task=str(uuid.uuid4());job=str(uuid.uuid4())
            receipt={'task_id':task,'job_id':job,'kind':'native_character','name':'marie',
                     'character_manifest_id':'marie','prompt_sha256':hashlib.sha256(b'portrait').hexdigest(),
                     'character_id':str(uuid.uuid4()),'project_url':'https://flow.google.com/project/test',
                     'stage':'project_ready','character_create_stage':'saving'}
            flow._write_receipt(task,receipt)
            with self.assertRaises(RuntimeError):await flow.create_character(task,job,'marie','marie','portrait')
            self.assertEqual(flow._read_receipt(task)['character_create_stage'],'saving')


class ResetSafetyTests(unittest.TestCase):
    def test_reset_restores_files_and_checkpoints_if_transaction_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos')
            job,_=store.create({'idea':'test','voice_id':'test','duration_seconds':8},'job')
            with store.db() as c:
                for stage in ('script','speech','images'):c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],stage,'{}'))
                c.execute("UPDATE jobs SET state='failed' WHERE id=?",(job['id'],))
            image=Path(job['output'])/'images-0000.png';image.write_bytes(b'keep')
            with patch.object(store,'event',side_effect=RuntimeError('transaction failed')),self.assertRaises(RuntimeError):store.reset_stage_images(job['id'])
            self.assertEqual(image.read_bytes(),b'keep')
            self.assertIn('images',store.get(job['id'])['checkpoints'])

    def test_stale_job_snapshot_does_not_delete_running_job_files(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos')
            job,_=store.create({'idea':'test','voice_id':'test','duration_seconds':8},'job')
            with store.db() as c:
                for stage in ('script','speech'):c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],stage,'{}'))
                c.execute("UPDATE jobs SET state='failed' WHERE id=?",(job['id'],))
            stale=store.get(job['id']);picture=Path(job['output'])/'images-0000.png';picture.write_bytes(b'keep')
            with store.db() as c:c.execute("UPDATE jobs SET state='running' WHERE id=?",(job['id'],))
            with patch.object(store,'get',return_value=stale),self.assertRaises(ValueError):store.reset_stage_images(job['id'])
            self.assertEqual(picture.read_bytes(),b'keep')
