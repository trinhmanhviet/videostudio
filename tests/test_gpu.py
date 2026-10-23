import tempfile,json,unittest,httpx
from pathlib import Path
from videostudio.gpu import headroom,record_owned
class GpuOwnershipTests(unittest.TestCase):
    def setup(self,path):path.write_text(json.dumps({'baseline_attested_empty_gpu':True,'baseline_order':10,'prompt_ids':['owned']}))
    def client(self,history):return httpx.Client(base_url='http://test/',transport=httpx.MockTransport(lambda request:httpx.Response(200,json=history)))
    def test_owned_allocations_can_be_counted_without_unload(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state';self.setup(p)
            with self.client({'owned':{'prompt':[10]}}) as c:
                value,owned=headroom(c,[{'vram_free':100,'torch_vram_total':900}],p)
            self.assertTrue(owned);self.assertEqual(value,1000)
    def test_foreign_prompt_revokes_counting(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state';self.setup(p)
            with self.client({'owned':{'prompt':[10]},'foreign':{'prompt':[11]}}) as c:value,owned=headroom(c,[{'vram_free':100,'torch_vram_total':900}],p)
            self.assertFalse(owned);self.assertEqual(value,100)
    def test_restart_missing_baseline_revokes_counting(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state';self.setup(p)
            with self.client({}) as c:value,owned=headroom(c,[{'vram_free':100,'torch_vram_total':900}],p)
            self.assertFalse(owned)
if __name__=='__main__':unittest.main()
