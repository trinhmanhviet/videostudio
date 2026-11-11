import importlib.util
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_scene_editor import ready_job, picture


class EditPlanAPITests(unittest.TestCase):
    def test_routes_conflicts_origin_asset_upload_and_export(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.edit_plan_api'), 'Edit plan routes missing')
        from videostudio.edit_plan_api import register_edit_plan_routes
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t); app = FastAPI()
            def origin(request):
                if request.headers.get('origin') == 'https://foreign.test': raise HTTPException(403, 'Foreign origin')
            register_edit_plan_routes(app, store, origin, lambda j: {'id': j['id'], 'state': j['state']})
            with TestClient(app) as client:
                prefix = '/api/jobs/' + job['id'] + '/edit-plan'
                self.assertEqual(len(client.get('/api/edit-presets').json()['items']), 3)
                view = client.get(prefix).json()
                self.assertEqual(client.put(prefix, json={'revision': view['revision'], 'plan': view['plan']}, headers={'origin': 'https://foreign.test'}).status_code, 403)
                result = client.put(prefix, json={'revision': view['revision'], 'plan': view['plan']})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(client.put(prefix, json={'revision': view['revision'], 'plan': view['plan']}).status_code, 409)
                uploaded = client.post(prefix + '/assets?name=green.png', content=picture('green'))
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                self.assertEqual(client.get(uploaded.json()['asset']['url']).status_code, 200)
                self.assertEqual(client.get(prefix + '/assets/foreign-id').status_code, 422)
                exported = client.post(prefix + '/export', json={'revision': result.json()['revision']}, headers={'Idempotency-Key': 'api-export'})
                self.assertEqual(exported.status_code, 200, exported.text)
                self.assertEqual(exported.json()['state'], 'queued')


if __name__ == '__main__': unittest.main()
