"""Scoped Voice Workspace routes; mutations share the app's same-origin guard."""
from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse
from .voice_studio import VoiceStudio


def register_voice_studio(app, store, pipeline, voices, same_origin):
    service=VoiceStudio(store,pipeline,voices)
    app.state.voice_studio=service

    def call(function,*args):
        try:return function(*args)
        except KeyError:raise HTTPException(404,'Không tìm thấy bản đọc hoặc mẫu tham chiếu trong thư viện này')
        except ValueError as error:raise HTTPException(409,str(error))
        except OSError:raise HTTPException(409,'Không đọc/ghi được tệp âm thanh; hãy thử lại')

    @app.get('/api/voice-studio/tasks')
    def history(page:int=1,page_size:int=10,saved:bool=False,x_voice_owner:str=Header(default='')):
        return call(service.shared_history,x_voice_owner,page,page_size,saved)

    @app.post('/api/voice-studio/tasks')
    def create(data:dict,request:Request,x_voice_owner:str=Header(default=''),idempotency_key:str=Header(default='')):
        same_origin(request)
        return call(service.create,x_voice_owner,data,idempotency_key)

    @app.get('/api/voice-studio/tasks/{identifier}')
    def get(identifier:str,x_voice_owner:str=Header(default='')):
        return call(service.shared_get,x_voice_owner,identifier)

    @app.patch('/api/voice-studio/tasks/{identifier}')
    def update(identifier:str,data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.update,x_voice_owner,identifier,data,data.get('version'))

    @app.post('/api/voice-studio/tasks/{identifier}/retry')
    def retry(identifier:str,data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.retry,x_voice_owner,identifier,data.get('version'))

    @app.post('/api/voice-studio/tasks/{identifier}/cancel')
    def cancel(identifier:str,data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.cancel,x_voice_owner,identifier,data.get('version'))

    @app.delete('/api/voice-studio/tasks/{identifier}')
    def delete(identifier:str,data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.delete,x_voice_owner,identifier,data.get('version'))

    @app.get('/api/voice-studio/tasks/{identifier}/audio/{extension}')
    def audio(identifier:str,extension:str,owner:str='',download:bool=False):
        path=call(service.shared_file,identifier,extension)
        task=call(service.shared_get,owner,identifier)
        # FileResponse sanitizes/encodes Content-Disposition. No filename is a path.
        return FileResponse(path,media_type='audio/wav' if extension=='wav' else 'audio/mpeg',
                            filename=(task['title']+'.'+extension) if download else None,
                            headers={'Cache-Control':'private, no-cache'})

    @app.post('/api/voice-studio/status')
    def status(data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.status,x_voice_owner,data)

    @app.get('/api/voice-studio/references')
    def references(x_voice_owner:str=Header(default='')):
        return call(service.references,x_voice_owner)

    @app.post('/api/voice-studio/references')
    def add_reference(data:dict,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.add_reference,x_voice_owner,data)

    @app.delete('/api/voice-studio/references/{identifier}')
    def delete_reference(identifier:str,request:Request,x_voice_owner:str=Header(default='')):
        same_origin(request)
        return call(service.delete_reference,x_voice_owner,identifier)

    @app.get('/api/voice-studio/references/{identifier}/audio')
    def reference_audio(identifier:str,owner:str=''):
        return FileResponse(call(service.reference_file,owner,identifier),media_type='audio/wav',headers={'Cache-Control':'private, no-cache'})

    return service
