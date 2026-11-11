import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from videostudio.providers import Pipeline,image_graph,music_graph


class ProductionGateTests(unittest.TestCase):
    def test_authenticated_socket_and_past_smoke_do_not_release_full_pipeline(self):
        with tempfile.TemporaryDirectory() as t:
            voices=SimpleNamespace(root=Path(t),catalog=lambda:{'complete':True,'warnings':[]})
            p=Pipeline(voices);p.speech_cache=t;p.accepted_music=lambda:True;p.accepted_cdp=lambda:True
            info={n['class_type']:{} for n in list(image_graph('',1,'x').values())+list(music_graph('',8,1,'x').values())}
            for kind,key,values in [('UNETLoader','unet_name',['qwen_image_2.1_int8_convrot.safetensors']),('CLIPLoader','clip_name',['qwen3vl_8b_int8_convrot.safetensors','t5gemma_b_b_ul2.safetensors']),('VAELoader','vae_name',['qwen_image_2.1_vae_bf16.safetensors']),('CheckpointLoaderSimple','ckpt_name',['stable_audio_3_medium_base.safetensors'])]:info[kind]={'input':{'required':{key:[values]}}}
            def get(url,**kwargs):
                data={'ready':True,'connected':True} if url.endswith('/api/status') else info
                return SimpleNamespace(status_code=200,json=lambda:data,raise_for_status=lambda:None)
            with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp','VS_ENGINEERING_SCOPE':''}),patch('httpx.get',side_effect=get),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='True')):
                pf=p.preflight();checks={c['name']:c['ok'] for c in pf['checks']}
                self.assertTrue(pf['ready'])
                self.assertTrue(checks['cdp_transport']);self.assertTrue(checks['cdp_smoke'])
                self.assertTrue(checks['production_acceptance'])

if __name__=='__main__':unittest.main()
