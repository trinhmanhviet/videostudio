import asyncio,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import AsyncMock
from PIL import Image
from videostudio.cdp_flow import FlowImages,FlowTaskError

class DownloadFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def run_download(self,mode):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);task=str(uuid.uuid4());bridge=type('Bridge',(),{})()
        bridge.images=type('Images',(),{'download_behavior_uncertain':False})()
        async def command(method,params=None,**kwargs):
            if method=='Page.getFrameTree':return {'frameTree':{'frame':{'id':'frame'}}}
            return {}
        bridge.cdp=type('CDP',(),{})();bridge.cdp.command=AsyncMock(side_effect=command)
        flow=FlowImages(bridge,root);self.flow=flow
        flow._image=AsyncMock(return_value=[{'media_id':'right-scene','x':30,'y':30}])
        flow._click_media_control=AsyncMock();flow._dismiss_flow_popups=AsyncMock()
        def complete(size):
            guid=str(uuid.uuid4());folder=root/'downloads'/task;folder.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',size,'navy').save(folder/guid,format='PNG')
            flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'frame','guid':guid}})
            flow.on_event({'method':'Browser.downloadProgress','params':{'guid':guid,'state':'completed'}})
        async def click(session,name,**kwargs):
            if kwargs.get('download_frame'):flow.active_frame=kwargs['download_frame']
            if name=='2K':
                if mode=='missing-control':raise FlowTaskError('2K unavailable')
                if mode=='normal':complete((1080,1920))
                if mode=='pending-2k':
                    flow.on_event({'method':'Browser.downloadWillBegin','params':{'frameId':'frame','guid':str(uuid.uuid4())}})
                if mode=='wrong-card':flow._image.return_value=[{'media_id':'other-scene','x':30,'y':30}]
            if name=='1K' and mode!='both-fail':complete((576,1024))
        flow._click_named=AsyncMock(side_effect=click)
        result=await flow._download_2k(task,'target','session',{'stage':'image_ready'},'prompt',media_id='right-scene',timeout=0)
        return result
    async def test_timeout_uses_same_image_at_1k_without_generation(self):
        result=await self.run_download('timeout')
        self.assertEqual((result['width'],result['height']),(576,1024))
        self.assertEqual(result['download_resolution_requested'],'1K')
        self.assertEqual(result['media_id'],'right-scene')
        self.assertEqual([c.args[1] for c in self.flow._click_named.await_args_list],['Tải xuống','2K','Tải xuống','1K'])
    async def test_missing_2k_control_also_falls_back(self):
        result=await self.run_download('missing-control');self.assertEqual(result['height'],1024)
    async def test_pending_2k_does_not_block_completed_1k(self):
        result=await self.run_download('pending-2k');self.assertEqual(result['height'],1024)
    async def test_successful_2k_does_not_download_again(self):
        result=await self.run_download('normal');self.assertEqual(result['height'],1920)
        self.assertNotIn('1K',[c.args[1] for c in self.flow._click_named.await_args_list])
    async def test_wrong_card_never_becomes_fallback(self):
        with self.assertRaisesRegex(FlowTaskError,'missing or ambiguous'):await self.run_download('wrong-card')
    async def test_both_downloads_fail_without_generating_a_replacement(self):
        with self.assertRaisesRegex(FlowTaskError,'1K'):await self.run_download('both-fail')

if __name__=='__main__':unittest.main()
