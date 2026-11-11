import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from videostudio.core import Store
from videostudio.workflow import default_workflow
from videostudio.workflow_api import register_workflow_routes

class WorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'jobs.db',Path(self.tmp.name)/'out');app=FastAPI()
        def same_origin(request):
            if request.headers.get('origin')!='http://testserver':raise HTTPException(403,'Origin rejected')
        register_workflow_routes(app,self.store,same_origin)
        self.client=TestClient(app);self.headers={'Origin':'http://testserver'}
    def test_save_load_stale_clone_delete_and_origin(self):
        graph=default_workflow()
        self.assertEqual(self.client.post('/api/workflows',json={'graph':graph,'revision':0}).status_code,403)
        response=self.client.post('/api/workflows',json={'graph':graph,'revision':0},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);saved=response.json()
        self.assertEqual(self.client.get('/api/workflows/'+saved['id']).json(),saved)
        self.assertEqual(self.client.post('/api/workflows',json={'graph':saved,'revision':0},headers=self.headers).status_code,409)
        listing=self.client.get('/api/workflows').json();self.assertEqual(len(listing['templates']),3)
        self.assertEqual(self.client.delete('/api/workflows/'+saved['id'],headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/workflows/'+saved['id']).status_code,404)
    def test_compile_returns_effective_request_and_execution_order(self):
        data={'graph':default_workflow(),'request':{'idea':'My story','voice_id':'preset:test','duration_seconds':30}}
        response=self.client.post('/api/workflows/compile',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);body=response.json()
        self.assertEqual(body['request']['workflow'],body['graph'])
        self.assertLess(body['order'].index('speech'),body['order'].index('images'))
        data['graph']['edges']=[]
        self.assertEqual(self.client.post('/api/workflows/compile',json=data,headers=self.headers).status_code,422)
if __name__=='__main__':unittest.main()
