import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from fastapi.testclient import TestClient

from FlowAPI.bridge import FlowRequestBridge, secret_hash
from FlowAPI.protocol import FlowRPCError, RPCS, build_command, decode_result, parse_response
from FlowAPI.server import create_app

PROJECT = '11111111-1111-4111-8111-111111111111'
CHARACTER = '22222222-2222-4222-8222-222222222222'
IMAGE = '33333333-3333-4333-8333-333333333333'
ORIGIN = 'chrome-extension://' + 'a' * 32


def response(rpcid, payload, error=None):
    return ")]}'\n\n123\n" + json.dumps([['wrb.fr', rpcid, json.dumps(payload) if payload is not None else None, None, None, error, 'generic']]) + '\n25\n[["e",4]]'


def image_payload():
    data = [None] * 14
    data[7] = 'Synthetic fixture prompt'
    data[13] = 'https://lh3.googleusercontent.com/synthetic-fixture'
    media = [IMAGE, None, PROJECT, None, None, None, [data, None, [1024, 1792]]]
    return [[media], [[PROJECT, None]]]


class ProtocolTests(unittest.TestCase):
    def test_actual_har_outer_structure_decodes_media_not_status_section(self):
        decoded = decode_result('generate_image', parse_response(response('ogiZ0b', image_payload()), 'ogiZ0b'))
        self.assertEqual(decoded['images'][0]['image_id'], IMAGE)
        self.assertEqual(decoded['images'][0]['width'], 1024)

    def test_nested_character_response_is_not_flattened_into_wrong_ids(self):
        payload = [[PROJECT, CHARACTER, None, [1, 'Fixture character', []]]]
        self.assertEqual(decode_result('create_character', payload)['character_id'], CHARACTER)

    def test_rpc_rejection_with_http_200_is_never_an_empty_success(self):
        error = [7, None, [['type.googleapis.com/google.rpc.ErrorInfo', ['PUBLIC_ERROR_UNUSUAL_ACTIVITY']]]]
        with self.assertRaises(FlowRPCError) as seen:
            parse_response(response('ogiZ0b', None, error), 'ogiZ0b')
        self.assertEqual(seen.exception.code, 'PUBLIC_ERROR_UNUSUAL_ACTIVITY')

    def test_wrong_rpc_login_html_and_server_error_are_not_success(self):
        for body, status in [(response('other', image_payload()), 200), ('<html>Sign in</html>', 200), ('', 503)]:
            with self.assertRaises(FlowRPCError):
                parse_response(body, 'ogiZ0b', status)

    def test_same_request_freezes_seed_client_ids_and_native_references(self):
        request_id = str(uuid.uuid4())
        args = {'project_id': PROJECT, 'prompt': 'Fixture', 'references': [{'character_id': CHARACTER, 'name': 'Person'}]}
        first = build_command('generate_image', args, request_id)
        self.assertEqual(first, build_command('generate_image', args, request_id))
        self.assertEqual(first['payload'][1][0][10], [[CHARACTER]])
        self.assertEqual(first['payload'][1][0][4], 2)
        self.assertEqual(first['payload'][1][0][7][10], [])  # never fabricate/replay challenge tokens

    def test_portrait_targets_a_character_without_using_references_as_target(self):
        cmd = build_command('generate_image', {'project_id': PROJECT, 'target_character_id': CHARACTER, 'prompt': 'Fixture'}, str(uuid.uuid4()))
        self.assertTrue(cmd['source_path'].endswith('/character/' + CHARACTER))
        self.assertEqual(cmd['payload'][1][0][4], 3)
        self.assertEqual(cmd['payload'][4][1:], [None, [CHARACTER, [0]]])

    def test_malformed_or_multiple_images_do_not_get_assigned_arbitrarily(self):
        payload = image_payload()
        payload[0].append(payload[0][0])
        with self.assertRaises(FlowRPCError):
            decode_result('generate_image', payload)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'bridge.sqlite3'
        self.bridge = FlowRequestBridge(self.path)
        invitation = self.bridge.invitation()
        self.client = self.bridge.pair(invitation['code'], ORIGIN)
        self.info = {'enabled': True, 'tab_open': True, 'session_ready': True}
        self.bridge.poll(self.client['client_id'], self.info)

    def queue(self, operation='generate_image', arguments=None, request_id=None):
        return self.bridge.enqueue(self.client['client_id'], operation,
                                   arguments or {'project_id': PROJECT, 'prompt': 'Fixture'},
                                   request_id or str(uuid.uuid4()), confirm_generation=True)

    def test_restart_or_repeated_poll_cannot_dispatch_write_twice(self):
        receipt = self.queue()
        first = self.bridge.poll(self.client['client_id'], self.info)['command']
        restarted = FlowRequestBridge(self.path)
        self.assertIsNone(restarted.poll(self.client['client_id'], self.info)['command'])
        with restarted.db() as db:
            db.execute('UPDATE commands SET updated=? WHERE id=?', (time.time()-190, receipt['id']))
        self.assertIsNone(restarted.poll(self.client['client_id'], self.info)['command'])
        self.assertEqual(restarted.get(receipt['id'])['state'], 'uncertain')
        late = restarted.complete(self.client['client_id'], first['id'], first['dispatch'], {'http_status': 200, 'body': response('ogiZ0b', image_payload())})
        self.assertEqual(late['state'], 'completed')

    def test_same_id_returns_receipt_and_changed_content_is_rejected(self):
        first = self.queue()
        self.assertEqual(self.queue(request_id=first['id'])['id'], first['id'])
        with self.assertRaises(ValueError):
            self.queue(arguments={'project_id': PROJECT, 'prompt': 'Different'}, request_id=first['id'])

    def test_callback_must_match_client_and_dispatch_and_is_idempotent(self):
        self.queue();command = self.bridge.poll(self.client['client_id'], self.info)['command']
        result = {'http_status': 200, 'body': response('ogiZ0b', image_payload())}
        with self.assertRaises(PermissionError):
            self.bridge.complete(self.client['client_id'], command['id'], 'wrong', result)
        done = self.bridge.complete(self.client['client_id'], command['id'], command['dispatch'], result)
        self.assertEqual(done['state'], 'completed')
        self.assertEqual(self.bridge.complete(self.client['client_id'], command['id'], command['dispatch'], {'transport_error': 'network_uncertain'})['state'], 'completed')

    def test_old_queued_request_expires_without_sending(self):
        receipt = self.queue()
        with self.bridge.db() as db:
            db.execute('UPDATE commands SET created=? WHERE id=?', (time.time()-301, receipt['id']))
        self.assertIsNone(self.bridge.poll(self.client['client_id'], self.info)['command'])
        self.assertEqual(self.bridge.get(receipt['id'])['result']['code'], 'not_dispatched')

    def test_paused_extension_never_claims_new_commands(self):
        self.queue()
        self.assertIsNone(self.bridge.poll(self.client['client_id'], {**self.info, 'enabled': False})['command'])

    def test_pair_code_is_single_use_and_keys_are_origin_bound(self):
        invitation = self.bridge.invitation()
        paired = self.bridge.pair(invitation['code'], ORIGIN)
        with self.assertRaises(PermissionError):
            self.bridge.pair(invitation['code'], ORIGIN)
        with self.assertRaises(PermissionError):
            self.bridge.authenticate(paired['client_id'], paired['key'], 'chrome-extension://'+'b'*32)

    def test_generation_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            self.bridge.enqueue(self.client['client_id'], 'generate_image', {'project_id': PROJECT, 'prompt': 'Fixture'}, str(uuid.uuid4()))

    def test_verification_handoff_is_single_use_key_bound_and_not_in_sqlite(self):
        key='fixture-handoff-key';proof='fixture-proof-secret-'*10
        receipt=self.queue('prepare_generation',{'project_id':PROJECT,'handoff_hash':secret_hash(key)})
        command=self.bridge.poll(self.client['client_id'],self.info)['command']
        callback={'request_id':command['id'],'verification_token':proof,'user_agent':'fixture-UA'}
        self.bridge.complete(self.client['client_id'],command['id'],command['dispatch'],callback)
        self.assertNotIn(proof,json.dumps(self.bridge.get(receipt['id'])))
        with self.bridge.db() as db:
            saved='\n'.join(db.iterdump())
        self.assertNotIn(proof,saved);self.assertNotIn(key,saved)
        with self.assertRaises(PermissionError):self.bridge.consume_verification(receipt['id'],'wrong-key')
        value=self.bridge.consume_verification(receipt['id'],key)
        self.assertEqual(value['token'],proof)
        # Repeated acknowledgement cannot resurrect a consumed value.
        self.bridge.complete(self.client['client_id'],command['id'],command['dispatch'],callback)
        with self.assertRaises(ValueError):self.bridge.consume_verification(receipt['id'],key)

    def test_service_restart_loses_proof_without_dispatching_verification_again(self):
        key='fixture-handoff-key'
        receipt=self.queue('prepare_generation',{'project_id':PROJECT,'handoff_hash':secret_hash(key)})
        command=self.bridge.poll(self.client['client_id'],self.info)['command']
        self.bridge.complete(self.client['client_id'],command['id'],command['dispatch'],{'request_id':command['id'],'verification_token':'fixture-proof-secret-'*10,'user_agent':'fixture-UA'})
        restarted=FlowRequestBridge(self.path)
        with self.assertRaises(ValueError):restarted.consume_verification(receipt['id'],key)
        self.assertIsNone(restarted.poll(self.client['client_id'],self.info)['command'])

    def test_guarded_verification_is_an_unsent_failure_not_an_unknown_delivery(self):
        self.queue('prepare_generation',{'project_id':PROJECT,'handoff_hash':secret_hash('fixture-key')})
        command=self.bridge.poll(self.client['client_id'],self.info)['command']
        receipt=self.bridge.complete(self.client['client_id'],command['id'],command['dispatch'],{'transport_error':'verification_guarded'})
        self.assertEqual(receipt['state'],'failed')
        self.assertEqual(receipt['result']['code'],'verification_guarded')

    def test_guarded_client_is_rejected_before_a_request_enters_the_queue(self):
        self.bridge.poll(self.client['client_id'],{**self.info,'verification_guard_detected':True})
        with self.assertRaisesRegex(ValueError,'verification_guarded'):
            self.queue('prepare_generation',{'project_id':PROJECT,'handoff_hash':secret_hash('fixture-key')})
        self.assertIsNone(self.bridge.poll(self.client['client_id'],self.info)['command'])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(create_app(Path(self.tmp.name)/'db'), base_url='http://localhost:8878')
        self.addCleanup(self.client.close)

    def test_local_page_pair_poll_and_result_round_trip(self):
        code = self.client.post('/api/flow-request/invitation').json()['code']
        paired = self.client.post('/api/flow-request/pair', json={'code': code}, headers={'Origin': ORIGIN}).json()
        headers = {'Origin': ORIGIN, 'Authorization': 'Bearer '+paired['key'], 'X-Flow-Client': paired['client_id']}
        self.client.post('/api/flow-request/poll', json={'enabled': True, 'session_ready': True}, headers=headers).raise_for_status()
        request_id = str(uuid.uuid4())
        queued = self.client.post('/api/flow-request/commands', json={'id': request_id, 'client_id': paired['client_id'], 'operation': 'list_projects', 'arguments': {}})
        queued.raise_for_status()
        command = self.client.post('/api/flow-request/poll', json={'enabled': True, 'session_ready': True}, headers=headers).json()['command']
        done = self.client.post(f'/api/flow-request/commands/{request_id}/result', json={'dispatch': command['dispatch'], 'result': {'http_status': 200, 'body': response('UpteDb', [[[PROJECT, ['Fixture project']]]])}}, headers=headers)
        self.assertEqual(done.json()['state'], 'completed')
        self.assertEqual(self.client.get('/api/flow-request/commands/'+request_id).json()['result']['projects'][0]['project_id'], PROJECT)

    def test_websites_rebound_hosts_and_unpaired_extensions_cannot_control(self):
        for headers in ({'Origin': 'https://evil.invalid'}, {'Host': 'evil.invalid', 'Origin': 'http://evil.invalid'}):
            self.assertEqual(self.client.post('/api/flow-request/invitation', headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/api/flow-request/pair', json={'code': 'none'}).status_code, 403)
        self.assertEqual(self.client.post('/api/flow-request/poll', json={}, headers={'Origin': ORIGIN}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
