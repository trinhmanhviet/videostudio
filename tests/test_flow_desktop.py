import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import urllib.parse
import uuid

import httpx

from FlowAPI.desktop import DesktopFlowClient, load_exported_cookies
from FlowAPI.protocol import FlowRPCError

PROJECT = '11111111-1111-4111-8111-111111111111'
IMAGE = '33333333-3333-4333-8333-333333333333'


def rpc_response(rpcid, payload):
    return ")]}'\n100\n" + json.dumps([['wrb.fr', rpcid, json.dumps(payload), None, None, None, 'generic']])


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cookies = self.root/'cookies.json'
        self.cookies.write_text(json.dumps([
            {'name': 'SID', 'value': 'fixture-cookie-secret', 'domain': '.google.com', 'path': '/'},
            {'name': 'flow', 'value': 'fixture-flow-cookie', 'domain': 'flow.google.com', 'path': '/'},
            {'name': 'expired', 'value': 'do-not-send', 'domain': '.google.com', 'expirationDate': time.time()-100},
            {'name': 'unrelated', 'value': 'do-not-send', 'domain': '.example.com'},
        ]))
        self.posts = []

    def client(self, handler=None):
        def serve(request):
            self.assertEqual(request.url.host, 'flow.google.com')
            if request.method == 'GET':
                return httpx.Response(200, text='window.WIZ_global_data='+json.dumps({'SNlM0e':'fixture-fresh-csrf','FdrFJe':-12345,'cfb2h':'fixture-build'})+';')
            self.posts.append(request)
            if handler:
                return handler(request)
            return httpx.Response(200, text=rpc_response('jHPbke', [PROJECT, ['Fixture']]))
        client = DesktopFlowClient(self.cookies, journal=self.root/'journal.sqlite3', transport=httpx.MockTransport(serve))
        self.addCleanup(client.close)
        return client

    def test_cookie_scope_and_expiry_preserved_and_no_unrelated_cookie_loaded(self):
        jar, count = load_exported_cookies(self.cookies)
        self.assertEqual(count, 2)
        self.assertEqual(set(jar.keys()), {'SID', 'flow'})
        self.assertEqual({cookie.domain for cookie in jar.jar}, {'.google.com', 'flow.google.com'})

    def test_bootstrap_uses_fresh_csrf_and_accepts_integer_session_id(self):
        client = self.client()
        self.assertTrue(client.bootstrap()['ready'])
        client.submit('create_project', {'name':'Fixture'}, str(uuid.uuid4()))
        form = urllib.parse.parse_qs(self.posts[0].content.decode())
        self.assertEqual(form['at'], ['fixture-fresh-csrf'])
        self.assertEqual(self.posts[0].url.params['f.sid'], '-12345')
        self.assertIn('fixture-cookie-secret', self.posts[0].headers['cookie'])
        self.assertNotIn('do-not-send', self.posts[0].headers['cookie'])

    def test_anonymous_bootstrap_never_sends_a_mutation(self):
        client = DesktopFlowClient(self.cookies, journal=self.root/'journal.sqlite3',
                                   transport=httpx.MockTransport(lambda request:httpx.Response(200,text='window.WIZ_global_data={"FdrFJe":"123","cfb2h":"build"};')))
        self.addCleanup(client.close)
        with self.assertRaises(FlowRPCError) as seen:
            client.submit('create_project', {'name':'Fixture'}, str(uuid.uuid4()))
        self.assertEqual(seen.exception.code, 'fresh_cookie_required')

    def test_completed_write_survives_restart_without_another_post(self):
        request_id = str(uuid.uuid4())
        first = self.client().submit('create_project', {'name':'Fixture'}, request_id)
        second = self.client().submit('create_project', {'name':'Fixture'}, request_id)
        self.assertEqual(first, second)
        self.assertEqual(len(self.posts), 1)
        with self.assertRaises(ValueError):
            self.client().submit('create_project', {'name':'Different'}, request_id)

    def test_lost_post_response_stays_uncertain_across_restart(self):
        def lose(request):
            raise httpx.ReadTimeout('fixture response lost')
        request_id = str(uuid.uuid4())
        with self.assertRaises(FlowRPCError) as first:
            self.client(lose).submit('create_project', {'name':'Fixture'}, request_id)
        self.assertTrue(first.exception.uncertain)
        with self.assertRaises(FlowRPCError) as second:
            self.client().submit('create_project', {'name':'Fixture'}, request_id)
        self.assertTrue(second.exception.uncertain)
        self.assertEqual(len(self.posts), 1)

    def test_generation_uses_one_proof_in_both_contexts_and_never_journals_secrets(self):
        proof='fixture-verification-secret-'*10
        calls=[]
        def verify(context):
            calls.append(context)
            return proof
        def image(request):
            form=urllib.parse.parse_qs(request.content.decode())
            payload=json.loads(json.loads(form['f.req'][0])[0][0][1])
            self.assertEqual(payload[1][0][7][10], [proof,1])
            self.assertEqual(payload[1][0][7][10], payload[3][10])
            data=[None]*14;data[7]='Fixture';data[13]='https://lh3.googleusercontent.com/fixture'
            return httpx.Response(200,text=rpc_response('ogiZ0b', [[[IMAGE,None,PROJECT,None,None,None,[data,None,[1024,768]]]], []]))
        request_id=str(uuid.uuid4())
        result=self.client(image).submit('generate_image', {'project_id':PROJECT,'prompt':'Fixture'}, request_id, verification_provider=verify)
        self.assertEqual(result['images'][0]['image_id'], IMAGE)
        again=self.client(image).submit('generate_image', {'project_id':PROJECT,'prompt':'Fixture'}, request_id, verification_provider=verify)
        self.assertEqual(again,result);self.assertEqual(len(calls),1)
        db=sqlite3.connect(self.root/'journal.sqlite3')
        try:
            saved='\n'.join(db.iterdump())
        finally:
            db.close()
        for secret in (proof,'fixture-cookie-secret','fixture-fresh-csrf'):
            self.assertNotIn(secret,saved)

    def test_generation_requires_verification_and_verification_failure_does_not_send(self):
        client=self.client()
        with self.assertRaises(FlowRPCError) as seen:
            client.submit('generate_image', {'project_id':PROJECT,'prompt':'Fixture'}, str(uuid.uuid4()))
        self.assertEqual(seen.exception.code, 'verification_provider_required')
        with self.assertRaises(FlowRPCError):
            client.submit('generate_image', {'project_id':PROJECT,'prompt':'Fixture'}, str(uuid.uuid4()), verification_provider=lambda context:None)
        self.assertEqual(len(self.posts),0)


if __name__ == '__main__':
    unittest.main()
