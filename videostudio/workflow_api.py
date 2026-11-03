"""Same-origin workflow library and graph compiler routes."""
from fastapi import HTTPException, Request
from .workflow import WorkflowService, compile_workflow, execution_order

def register_workflow_routes(app,store,same_origin):
    service=WorkflowService(store)
    app.state.workflows=service
    def call(fn,*args):
        try:return fn(*args)
        except KeyError:raise HTTPException(404,'Workflow not found')
        except ValueError as exc:raise HTTPException(409 if str(exc).startswith('Stale') else 422,str(exc))
    @app.get('/api/workflows')
    def workflows():return service.list()
    @app.post('/api/workflows/compile')
    def compile_graph(data:dict,request:Request):
        same_origin(request)
        compiled=call(compile_workflow,data.get('graph'),data.get('request',{}))
        # Request-level validation remains core's responsibility; the compiler
        # itself never calls it, avoiding recursion when core compiles graphs.
        from .core import validate_request
        compiled=call(validate_request,compiled)
        return {'request':compiled,'graph':compiled['workflow'],'order':execution_order(compiled['workflow'])}
    @app.post('/api/workflows')
    def save(data:dict,request:Request):
        same_origin(request)
        return call(service.save,data.get('graph'),data.get('revision'))
    @app.get('/api/workflows/{workflow_id}')
    def view(workflow_id:str):return call(service.get,workflow_id)
    @app.get('/api/workflows/{workflow_id}/revisions')
    def revisions(workflow_id:str):return {'items':call(service.revisions,workflow_id)}
    @app.delete('/api/workflows/{workflow_id}')
    def delete(workflow_id:str,request:Request):
        same_origin(request)
        return call(service.delete,workflow_id)
    return service
