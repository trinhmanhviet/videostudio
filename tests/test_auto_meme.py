"""Local HTTP contract for the animated-meme API client (no real providers)."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from videostudio import auto_meme


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'video.mp4'
        self.calls = []
        self.state = 'completed'
        self.error = None
        self.drop_submit = False
        self.ready = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                owner.calls.append(('GET', self.path, None, dict(self.headers)))
                if self.path == '/api/connector/status':
                    value = {'items': [{'scope': 'root'}]}
                elif self.path == '/api/connector/bridges/root/status':
                    value = {'scope': 'root', 'bridge': 'root', 'ready': True}
                elif self.path == '/api/preflight?scope=root&workflow_mode=meme&meme_engine=hyperframes':
                    value = {'ready': owner.ready, 'checks': []}
                elif self.path == '/api/jobs/job-1':
                    value = {'id': 'job-1', 'status': owner.state, 'error': owner.error,
                             'output_url': '/api/jobs/job-1/files/video.mp4'}
                elif self.path == '/api/jobs/job-1/files/video.mp4':
                    self.send_response(200); self.end_headers(); self.wfile.write(b'mp4-data'); return
                else:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(value).encode())

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(('POST', self.path, payload, dict(self.headers)))
                if owner.drop_submit:
                    self.close_connection = True
                    return
                self.send_response(201); self.end_headers()
                self.wfile.write(json.dumps({'id': 'job-1', 'status': 'queued'}).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.args = ['--idea', 'A funny interview', '--out', str(self.out), '--server',
                     f'http://127.0.0.1:{self.server.server_port}', '--poll-seconds', '0.001']

    def run_cli(self, extra=()):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return auto_meme.main(self.args + list(extra))

    def test_submits_animated_request_and_downloads_completed_video(self):
        self.assertEqual(self.run_cli(), 0)
        post = next(c for c in self.calls if c[0] == 'POST')
        self.assertEqual(post[2]['meme_engine'], 'hyperframes')
        self.assertEqual(post[2]['workflow_mode'], 'meme')
        self.assertEqual(post[2]['voice_id'], auto_meme.DEFAULT_VOICE)
        self.assertEqual((post[2]['image_provider'], post[2]['flow_batch_size']), ('comfy', 1))
        self.assertEqual(post[2]['text_provider'], 'chatgpt')
        self.assertEqual(post[3]['X-Connector-Scope'], 'root')
        self.assertEqual(self.out.read_bytes(), b'mp4-data')
        receipt = json.loads(auto_meme.receipt_path(self.out).read_text())
        self.assertEqual(receipt['job_id'], 'job-1')
        self.assertTrue(receipt['request_hash'])
        self.assertNotIn('A funny interview', json.dumps(receipt))

    def test_receipt_resumes_pending_job_without_another_post(self):
        self.state = 'failed'; self.error = 'render failed'
        self.assertNotEqual(self.run_cli(), 0)
        self.assertFalse(self.out.exists())
        self.state = 'completed'
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(sum(c[0] == 'POST' for c in self.calls), 1)

    def test_lost_submission_response_reuses_idempotency_key(self):
        self.drop_submit = True
        self.assertNotEqual(self.run_cli(), 0)
        first = next(c for c in self.calls if c[0] == 'POST')
        self.drop_submit = False
        self.assertEqual(self.run_cli(), 0)
        posts = [c for c in self.calls if c[0] == 'POST']
        self.assertEqual(first[3]['Idempotency-Key'], posts[-1][3]['Idempotency-Key'])

    def test_arbitrary_existing_output_is_never_overwritten_or_submitted(self):
        self.out.write_bytes(b'keep me')
        self.assertNotEqual(self.run_cli(), 0)
        self.assertEqual(self.out.read_bytes(), b'keep me')
        self.assertEqual(self.calls, [])

    def test_matching_completed_output_is_reused_without_http(self):
        self.assertEqual(self.run_cli(), 0)
        self.calls.clear()
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.calls, [])
        self.out.write_bytes(b'external replacement')
        self.assertNotEqual(self.run_cli(), 0)
        self.assertEqual(self.calls, [])

    def test_changed_input_cannot_reuse_receipt(self):
        self.state = 'failed'
        self.assertNotEqual(self.run_cli(), 0)
        self.calls.clear()
        self.args[1] = 'Different story'
        self.assertNotEqual(self.run_cli(), 0)
        self.assertEqual(self.calls, [])

    def test_external_servers_are_rejected(self):
        self.args[-3] = 'https://example.com'
        self.assertNotEqual(self.run_cli(), 0)
        self.assertEqual(self.calls, [])

    def test_preflight_block_prevents_receipt_and_submission(self):
        self.ready = False
        self.assertNotEqual(self.run_cli(), 0)
        self.assertFalse(any(c[0] == 'POST' for c in self.calls))
        self.assertFalse(auto_meme.receipt_path(self.out).exists())

    def test_meme_duration_under_server_minimum_fails_before_http(self):
        self.assertNotEqual(self.run_cli(['--seconds', '10']), 0)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
