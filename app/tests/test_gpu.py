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


class DeviceFreeTests(unittest.TestCase):
    def test_a_pool_only_figure_is_checked_against_the_driver(self):
        from videostudio.gpu import device_free
        GB = 1024 ** 3
        live = {'vram_total': 24 * GB, 'vram_free': 110 * 2 ** 20, 'torch_vram_total': 134 * 2 ** 20, 'torch_vram_free': 110 * 2 ** 20}
        self.assertEqual(device_free([live], driver=lambda: 22 * GB), 22 * GB)          # the card is really empty
        self.assertEqual(device_free([live], driver=lambda: 50 * 2 ** 20), live['vram_free'])   # really full: still low
        self.assertEqual(device_free([live], driver=lambda: None), live['vram_free'])  # no driver figure: as before
        whole = {'vram_total': 24 * GB, 'vram_free': GB, 'torch_vram_total': 20 * GB, 'torch_vram_free': GB}
        self.assertEqual(device_free([whole], driver=lambda: 22 * GB), GB)             # a normal report is trusted as is
        self.assertEqual(device_free([{'vram_free': 100, 'torch_vram_total': 900}], driver=lambda: 22 * GB), 100)
