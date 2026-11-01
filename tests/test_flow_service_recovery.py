import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import httpx
from videostudio.providers import Pipeline
from videostudio.service_recovery import ensure_flow_service


class FlowServiceRecoveryTests(unittest.TestCase):
    def test_absent_daemon_uses_start_script_without_restart_or_force(self):
        with tempfile.TemporaryDirectory() as folder:
            response=Mock();response.json.return_value={'service':'videostudio-dedicated-cdp','connected':True}
            process=Mock();process.poll.return_value=0;process.returncode=0
            with patch('videostudio.service_recovery.__file__',str(Path(folder)/'videostudio/service_recovery.py')),patch('videostudio.service_recovery.httpx.get',side_effect=[httpx.ConnectTimeout('absent'),response]),patch('videostudio.service_recovery.subprocess.Popen',return_value=process) as start:
                ensure_flow_service('http://127.0.0.1:8879',lambda:None)
            args=start.call_args.args[0]
            self.assertTrue(args[-1].endswith('start_browser.ps1'))
            self.assertNotIn('-Force',args);self.assertNotIn('-RestartOwnDaemon',args)

    def test_foreign_service_is_never_restarted(self):
        response=Mock();response.json.return_value={'service':'foreign'}
        with patch('videostudio.service_recovery.httpx.get',return_value=response),patch('videostudio.service_recovery.subprocess.Popen') as start:
            with self.assertRaises(RuntimeError):ensure_flow_service('http://127.0.0.1:8879',lambda:None)
        start.assert_not_called()

    def test_external_url_never_starts_any_service(self):
        with patch('videostudio.service_recovery.subprocess.Popen') as start:
            with self.assertRaises(RuntimeError):ensure_flow_service('https://example.com',lambda:None)
        start.assert_not_called()

    def test_connection_refused_recovers_and_reuses_exact_payload(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline.store=None
        body={'task_id':'unchanged','job_id':'same-job','prompt':'same prompt'}
        response=Mock()
        with patch('videostudio.providers.httpx.post',side_effect=[httpx.ConnectTimeout('absent'),response]) as post,patch('videostudio.service_recovery.ensure_flow_service') as recover:
            result=pipeline._flow_post('http://127.0.0.1:8879/api/flow/characters/create',body,lambda:None,1200)
        self.assertIs(result,response);recover.assert_called_once()
        self.assertEqual(post.call_args_list[0],post.call_args_list[1])

    def test_read_timeout_never_restarts_or_resubmits(self):
        pipeline=Pipeline.__new__(Pipeline);pipeline.store=None
        with patch('videostudio.providers.httpx.post',side_effect=httpx.ReadTimeout('unknown')) as post,patch('videostudio.service_recovery.ensure_flow_service') as recover:
            with self.assertRaises(httpx.ReadTimeout):pipeline._flow_post('http://127.0.0.1:8879/api/flow/images/generate',{},lambda:None,1200)
        self.assertEqual(post.call_count,1);recover.assert_not_called()
