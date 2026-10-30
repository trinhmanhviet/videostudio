"""Isolated bridge queue fixtures; never call a model or media provider."""
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.exchanges import Exchanges


REQUEST = {'idea': 'Fixture video', 'voice_id': 'test', 'duration_seconds': 8}


class ReadyFixture:
    def handlers(self): return {}
    def preflight(self): return {'ready': True, 'checks': []}


class BridgeQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict('os.environ', {'VS_LLM_TRANSPORT': 'extension', 'VS_STORYFORGE_ROOT': self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Store(Path(self.tmp.name)/'db', Path(self.tmp.name)/'out')
        self.client = TestClient(create_app(self.store, ReadyFixture(), False))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.ex = Exchanges(self.store)
        self.root = self.ex.scope()
        self.other = self.ex.scope()
        for root in (self.root, self.other):
            with self.store.db() as c:
                c.execute('INSERT INTO connector_status VALUES(?,?,?)', (root, json.dumps({'build':'videostudio-extension-0.3.0','stage':'active','connected':True,'enabled':True}), time.time()))

    def submit(self, key, root=None, data=None):
        return self.client.post('/api/jobs', headers={'Idempotency-Key': key, 'X-Connector-Scope': root or self.root}, json=data or REQUEST)

    def path(self, suffix, root=None):
        return '/api/connector/bridges/'+(root or self.root)+'/'+suffix

    def test_two_jobs_allocate_distinct_children_and_replay_same_child(self):
        first = self.submit('first')
        second = self.submit('second')
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        a, b = first.json(), second.json()
        self.assertNotEqual(a['connector_scope'], self.root)
        self.assertNotEqual(a['connector_scope'], b['connector_scope'])
        self.assertEqual(self.ex.for_job(a['id']), a['connector_scope'])
        replay = self.submit('first').json()
        self.assertFalse(replay['created'])
        self.assertEqual((replay['id'], replay['connector_scope']), (a['id'], a['connector_scope']))
        cards = self.client.get(self.path('sessions')).json()['items']
        self.assertEqual({c['scope'] for c in cards}, {a['connector_scope'], b['connector_scope']})
        self.assertEqual(set(cards[0]), {'scope', 'job_id', 'title', 'project', 'state', 'stage', 'error', 'cancel_requested', 'created'})
        self.assertEqual(self.client.get(self.path('sessions', self.other)).json()['items'], [])

    def test_wrong_bridge_replay_and_child_as_bridge_leave_no_orphan(self):
        a = self.submit('first').json()
        self.assertEqual(self.submit('first', self.other).status_code, 409)
        self.assertEqual(self.submit('nested', a['connector_scope']).status_code, 422)
        self.assertEqual(len(self.store.list()), 1)
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM connector_scopes').fetchone()[0], 3)

    def test_failed_legacy_root_does_not_block_new_children(self):
        old, _ = self.store.create(REQUEST, 'legacy', self.root)
        request_id = self.ex.enqueue(self.root, 'old failed request')
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='failed',error='fixture failure' WHERE id=?", (old['id'],))
        new = self.submit('new')
        self.assertEqual(new.status_code, 201, new.text)
        cards = self.client.get(self.path('sessions')).json()['items']
        self.assertEqual({c['job_id'] for c in cards}, {old['id'], new.json()['id']})
        self.assertEqual(self.client.get(self.path('pending')).json()['items'], [])
        self.assertEqual(self.ex.get(self.root, request_id)['response'], None)
        smoke_response = self.client.post('/api/connector/smoke/'+self.root)
        self.assertEqual(smoke_response.status_code, 200, smoke_response.text)
        pending_smoke=self.client.get(self.path('pending')).json()['items']
        self.assertEqual(len(pending_smoke),1)
        self.assertTrue(pending_smoke[0].get('is_smoke'))
        self.assertIsNone(pending_smoke[0]['job_id'])
        smoke = smoke_response.json()['exchange_id']
        items = self.client.get(self.path('pending')).json()['items']
        self.assertEqual([i['id'] for i in items], [smoke])
        self.assertEqual(items[0]['scope'], self.root)
        self.assertIsNone(items[0]['job_id'])

    def test_pre_provider_legacy_request_replays_without_allocating_a_child(self):
        old,_=self.store.create(REQUEST,'legacy-replay',self.root)
        with self.store.db() as c:
            request=json.loads(c.execute('SELECT request FROM jobs WHERE id=?',(old['id'],)).fetchone()[0])
            request.pop('text_provider',None)
            request.pop('flow_batch_size',None)
            c.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(request),old['id']))
        response=self.submit('legacy-replay')
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['id'],old['id'])
        self.assertEqual(response.json()['connector_scope'],self.root)
        self.assertFalse(response.json()['created'])
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM connector_bridge_memberships').fetchone()[0],0)

    def test_pending_filters_terminal_jobs_and_keeps_scoped_receipts(self):
        jobs = [self.submit(str(i)).json() for i in range(5)]
        for i, job in enumerate(jobs):
            self.ex.enqueue(job['connector_scope'], 'request '+str(i))
        unrelated = self.submit('other', self.other).json()
        self.ex.enqueue(unrelated['connector_scope'], 'unrelated')
        with self.store.db() as c:
            for state, job in zip(('failed', 'completed', 'cancelled', 'retrying', 'running'), jobs):
                c.execute('UPDATE jobs SET state=? WHERE id=?', (state, job['id']))
        items = self.client.get(self.path('pending')).json()['items']
        self.assertEqual({i['job_id'] for i in items}, {j['id'] for j in jobs[3:]})
        self.assertEqual(set(items[0]), {'scope', 'job_id', 'is_smoke', 'id', 'version', 'prompt', 'attachments'})
        self.assertFalse(items[0]['is_smoke'])
        item = items[0]
        base = f"/api/v1/projects/{item['scope']}/runs/{item['scope']}/chatgpt-exchanges/{item['id']}"
        self.assertEqual(self.client.post(base+'/response', json={'expected_version': item['version'], 'response_text': '{}'}).status_code, 200)
        self.assertTrue(self.client.get(base).json()['accepted'])
        self.assertEqual(len(self.client.get(self.path('pending')).json()['items']), 1)

    def test_cancel_is_same_origin_and_exact_bridge_only(self):
        a, b = [self.submit(k).json() for k in ('a', 'b')]
        self.ex.enqueue(a['connector_scope'], 'cancelled request')
        url = self.path('jobs/'+a['id']+'/cancel')
        self.assertEqual(self.client.post(url, headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)
        self.assertEqual(self.client.post(self.path('jobs/'+a['id']+'/cancel', self.other)).status_code, 404)
        result = self.client.post(url)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['scope'], a['connector_scope'])
        self.assertTrue(result.json()['cancel_requested'])
        self.assertEqual(result.json()['state'], 'cancelled')
        self.assertEqual(self.store.get(b['id'])['state'], 'queued')
        self.assertEqual(self.client.get(self.path('pending')).json()['items'], [])

    def test_child_acceptance_inherits_only_current_parent_smoke_and_heartbeat(self):
        child = self.submit('a').json()['connector_scope']
        smoke = self.ex.enqueue_smoke(self.root)
        self.ex.receive(self.root, smoke, 1, '{"connection_test":"videostudio","ok":true}')
        with self.store.db() as c:
            c.execute('INSERT OR REPLACE INTO connector_status VALUES(?,?,?)', (self.root, json.dumps({'build':'videostudio-extension-0.3.0','stage':'active','connected':True,'enabled':True}), time.time()))
        self.assertTrue(self.ex.accepted_extension(child))
        self.assertFalse(self.ex.accepted_extension(self.other))
        with self.store.db() as c:
            c.execute('UPDATE connector_status SET updated=? WHERE scope=?', (time.time()-120, self.root))
        self.assertFalse(self.ex.accepted_extension(child))

    def test_old_extension_cannot_allocate_children_but_keeps_legacy_receipts(self):
        legacy, _ = self.store.create(REQUEST, 'legacy', self.root)
        request_id = self.ex.enqueue(self.root, 'legacy request')
        with self.store.db() as c:
            c.execute('UPDATE connector_status SET status=? WHERE scope=?', (json.dumps({'build':'videostudio-extension-0.2.2','stage':'active','connected':True,'enabled':True}), self.root))
        response = self.submit('new')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('0.3.0', response.json()['detail'])
        self.assertEqual(len(self.store.list()), 1)
        replay = self.submit('legacy').json()
        self.assertEqual(replay['id'], legacy['id'])
        self.assertEqual(replay['connector_scope'], self.root)
        self.assertEqual(self.ex.get(self.root, request_id)['response'], None)

    def test_unknown_bridge_routes_return_404(self):
        for suffix in ('sessions', 'pending'):
            self.assertEqual(self.client.get(self.path(suffix, 'unknown')).status_code, 404)

    def test_concurrent_allocations_and_same_key_replay_are_atomic(self):
        def create(key):
            return self.store.create(REQUEST, key, connector_bridge=self.root)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, ['same', 'same', 'one', 'two']))
        self.assertEqual(sum(created for _, created in results), 3)
        self.assertEqual(results[0][0]['id'], results[1][0]['id'])
        cards = self.client.get(self.path('sessions')).json()['items']
        self.assertEqual(len(cards), 3)
        self.assertEqual(len({c['scope'] for c in cards}), 3)

    def test_allocation_failure_rolls_back_child_membership_and_job(self):
        with patch.object(Path, 'mkdir', side_effect=OSError('fixture disk unavailable')):
            with self.assertRaisesRegex(OSError, 'fixture disk unavailable'):
                self.store.create(REQUEST, 'no-orphan', connector_bridge=self.root)
        self.assertEqual(self.store.list(), [])
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM connector_scopes').fetchone()[0], 2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM connector_bridge_memberships').fetchone()[0], 0)


if __name__ == '__main__': unittest.main()
