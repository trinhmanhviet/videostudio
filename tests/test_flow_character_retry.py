import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock,AsyncMock
import httpx
from videostudio.providers import Pipeline,UncertainDeliveryError
from videostudio.core import PermanentError,Cancelled
from videostudio.cdp_flow import FlowImages,FlowTaskError


class CharacterRetryTests(unittest.TestCase):
    def test_cancel_during_confirmation_wait_never_submits_another_request(self):
        p=self.pipeline();p._flow_post=Mock(return_value=httpx.Response(409,json={'code':'character_save_pending','error':'pending'}))
        p._wait_for_character_recheck=lambda seconds,check:check()
        check=Mock(side_effect=[None,Cancelled()])
        with self.assertRaises(Cancelled):p._browser_flow_character({'id':str(uuid.uuid4())},{'character_id':'worker'},'portrait',check,task_id=str(uuid.uuid4()))
        self.assertEqual(p._flow_post.call_count,1)

    def pipeline(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline._wait_for_character_recheck=Mock()
        return pipeline

    def test_delayed_confirmation_rechecks_same_character_without_new_creation(self):
        p=self.pipeline();task=str(uuid.uuid4());entity=str(uuid.uuid4())
        p._flow_post=Mock(side_effect=[httpx.Response(409,json={'code':'character_save_pending','error':'Waiting for persisted name'}),
            httpx.Response(200,json={'data':{'task_id':task,'character_id':entity,'name':'worker','project_url':'https://flow.google.com/project/test'}})])
        result=p._browser_flow_character({'id':str(uuid.uuid4())},{'character_id':'worker'},'portrait',lambda:None,task_id=task)
        self.assertEqual(result['character_id'],entity)
        self.assertNotIn('resume_only',p._flow_post.call_args_list[0].args[1])
        self.assertTrue(p._flow_post.call_args_list[1].args[1]['resume_only'])
        self.assertTrue(all(call.args[1]['task_id']==task for call in p._flow_post.call_args_list))
        p._wait_for_character_recheck.assert_called_once()

    def test_pending_name_has_bounded_budget_per_character(self):
        p=self.pipeline();p._flow_post=Mock(return_value=httpx.Response(409,json={'code':'character_save_pending','error':'pending'}))
        with self.assertRaises(UncertainDeliveryError):p._browser_flow_character({'id':str(uuid.uuid4())},{'character_id':'worker'},'portrait',lambda:None,task_id=str(uuid.uuid4()))
        self.assertEqual(p._flow_post.call_count,5)
        self.assertEqual(p._wait_for_character_recheck.call_count,4)

    def test_auth_and_uncertain_delivery_do_not_enter_name_retry_loop(self):
        for code,error in [('needs_auth',PermanentError),('uncertain',UncertainDeliveryError)]:
            p=self.pipeline();p._flow_post=Mock(return_value=httpx.Response(409,json={'code':code,'error':'blocked'}))
            with self.assertRaises(error):p._browser_flow_character({'id':str(uuid.uuid4())},{'character_id':'worker'},'portrait',lambda:None,task_id=str(uuid.uuid4()))
            self.assertEqual(p._flow_post.call_count,1);p._wait_for_character_recheck.assert_not_called()


class ResumeOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_receipt_never_falls_back_to_creating_character(self):
        with tempfile.TemporaryDirectory() as folder:
            flow=FlowImages(object(),Path(folder));flow._create_character_unreserved=AsyncMock()
            with self.assertRaises(FlowTaskError):await flow.create_character(str(uuid.uuid4()),str(uuid.uuid4()),'worker','worker','portrait',resume_only=True)
            flow._create_character_unreserved.assert_not_awaited()
