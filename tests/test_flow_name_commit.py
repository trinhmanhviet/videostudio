import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock
from videostudio.cdp_flow import FlowImages


class CharacterNameCommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_save_before_reload_and_never_creates_another_character(self):
        with tempfile.TemporaryDirectory() as folder:
            persisted='Unnamed';draft='Unnamed';pending=False;settles=0;aborted=False
            async def command(method,params=None,**kwargs):
                nonlocal draft,pending,aborted
                if method=='Input.insertText':draft=params['text']
                if method=='Page.navigate' and pending:
                    aborted=True;pending=False;draft=persisted
                return {}
            bridge=type('Bridge',(),{'cdp':type('CDP',(),{'command':AsyncMock(side_effect=command)})()})()
            flow=FlowImages(bridge,Path(folder))
            flow._wait_page=AsyncMock();flow._wait_character_complete=AsyncMock();flow._click_point=AsyncMock();flow._return_to_project_root=AsyncMock()
            async def click(session,label,**kwargs):
                nonlocal pending
                self.assertEqual(label,'Xong');pending=True
            flow._click_named=AsyncMock(side_effect=click)
            async def evaluate(session,expression):
                nonlocal settles,persisted,pending
                if 'VS_CHARACTER_SAVE_SETTLED' in expression:
                    settles+=1
                    if settles>=2:persisted=draft;pending=False
                    return not pending
                if '.map(' in expression:
                    return [{'value':'search','x':1,'y':1,'hint':'search'},{'value':persisted,'x':2,'y':2,'hint':'character name'}]
                return persisted=='marie'
            flow._eval=AsyncMock(side_effect=evaluate)
            task=str(uuid.uuid4());receipt={'task_id':task,'character_id':str(uuid.uuid4()),'project_url':'https://flow.google.com/project/test','character_create_stage':'saving'}
            await flow._resume_character_save('session',task,receipt,'marie','portrait',30)
            self.assertFalse(aborted,'Navigation must not abort a name save still in progress')
            self.assertEqual(flow._read_receipt(task)['stage'],'character_saved')
            flow._click_named.assert_awaited_once()
