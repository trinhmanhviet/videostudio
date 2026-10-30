"""Isolated gate fixture for test_extension_connection_e2e.cjs; never production."""
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.providers import Pipeline,image_graph,music_graph

folder=Path(sys.argv[1]).resolve()
voices=SimpleNamespace(root=folder,catalog=lambda:{'complete':True,'warnings':[]},selected=lambda value:{'id':value})
pipeline=Pipeline(voices)
pipeline.speech_cache=str(folder)
pipeline.accepted_music=lambda:True
store=Store(folder/'jobs.sqlite3',folder/'out')
app=create_app(store,pipeline,False)
info={node['class_type']:{} for node in [*image_graph('',1,'fixture').values(),*music_graph('',8,1,'fixture').values()]}
for kind,key,values in [
    ('UNETLoader','unet_name',['qwen_image_2.1_int8_convrot.safetensors']),
    ('CLIPLoader','clip_name',['qwen3vl_8b_int8_convrot.safetensors','t5gemma_b_b_ul2.safetensors']),
    ('VAELoader','vae_name',['qwen_image_2.1_vae_bf16.safetensors']),
    ('CheckpointLoaderSimple','ckpt_name',['stable_audio_3_medium_base.safetensors']),
]:info[kind]={'input':{'required':{key:[values]}}}
sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
print(json.dumps({'port':sock.getsockname()[1]}),flush=True)
with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='True')),patch('shutil.which',return_value='/fixture/tool'),patch('videostudio.providers.httpx.get',return_value=SimpleNamespace(status_code=200,json=lambda:info,raise_for_status=lambda:None)):
    uvicorn.Server(uvicorn.Config(app,log_level='error')).run(sockets=[sock])
