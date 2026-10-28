import json
import tempfile
import time
import unittest
from pathlib import Path
from videostudio.core import Store, PermanentError
from videostudio.exchanges import Exchanges


class ExtensionAcceptanceTests(unittest.TestCase):
    def test_each_smoke_request_has_a_new_exchange_id_in_same_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'jobs.sqlite3', Path(tmp) / 'out')
            ex = Exchanges(store)
            scope = ex.scope()
            first = ex.enqueue_smoke(scope)
            with self.assertRaisesRegex(PermanentError,'still pending'):
                ex.enqueue_smoke(scope)
            ex.receive(scope, first, 1, '{"connection_test":"videostudio","ok":true}')
            second = ex.enqueue_smoke(scope)
            self.assertNotEqual(first, second)
            self.assertEqual(ex.pending(scope)['items'][0]['id'], second)

    def test_scope_requires_exact_smoke_reply_and_fresh_active_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'jobs.sqlite3', Path(tmp) / 'out')
            ex = Exchanges(store)
            scope = ex.scope()
            self.assertFalse(ex.accepted_extension(scope))
            request_id = ex.enqueue_smoke(scope)
            ex.receive(scope, request_id, 1, '{"connection_test":"videostudio","ok":true}')
            self.assertFalse(ex.accepted_extension(scope))
            with store.db() as db:
                db.execute('INSERT OR REPLACE INTO connector_status VALUES(?,?,?)', (scope, json.dumps({'build':'videostudio-extension-0.1.0','stage':'active','connected':True,'enabled':True}), time.time()))
            self.assertTrue(ex.accepted_extension(scope))
            with store.db() as db:
                db.execute('UPDATE connector_status SET updated=? WHERE scope=?', (time.time() - 120, scope))
            self.assertFalse(ex.accepted_extension(scope))


if __name__ == '__main__':
    unittest.main()
