import unittest,tempfile,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from videostudio.core import Store
from videostudio.exchanges import Exchanges
from videostudio.providers import Pipeline,image_graph,music_graph
class EngineeringScopeTests(unittest.TestCase):
    def test_exception_is_exact_scope_only_not_global_release(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            class Voices:
                def __init__(self):self.root=root
                def catalog(self):return {'complete':True,'warnings':[]}
            p=Pipeline(Voices());p.speech_cache=t;p.accepted_music=lambda:True
            ex=Exchanges(Store(root/'db',root/'out'));scope=ex.scope();p.use_exchanges(ex)
            eid=ex.enqueue(scope,'smoke');ex.receive(scope,eid,1,'{"connection_test":"videostudio","ok":true}')
            info={n['class_type']:{} for n in list(image_graph('',1,'x').values())+list(music_graph('',8,1,'x').values())}
            for kind,key,values in [('UNETLoader','unet_name',['qwen_image_2.1_int8_convrot.safetensors']),('CLIPLoader','clip_name',['qwen3vl_8b_int8_convrot.safetensors','t5gemma_b_b_ul2.safetensors']),('VAELoader','vae_name',['qwen_image_2.1_vae_bf16.safetensors']),('CheckpointLoaderSimple','ckpt_name',['stable_audio_3_medium_base.safetensors'])]:info[kind]={'input':{'required':{key:[values]}}}
            response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:info)
            with patch.dict('os.environ',{'VS_ENGINEERING_SCOPE':scope,'VS_LLM_TRANSPORT':'chrome'}),patch('httpx.get',return_value=response),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='True')):
                self.assertFalse(p.preflight()['ready']);self.assertFalse(p.preflight('wrong')['ready']);self.assertTrue(p.preflight(scope)['ready']);self.assertTrue(p.preflight(scope)['engineering_only'])
if __name__=='__main__':unittest.main()
