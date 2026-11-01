import asyncio,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,AsyncMock,patch
from PIL import Image
from videostudio.cdp_flow import FlowImages,FlowTaskError
from videostudio.comfy_references import reference_graph
from videostudio.hybrid_images import run


class ReferenceGraphTests(unittest.TestCase):
    def test_old_batch_requires_unique_job_prompt_and_explicit_failure(self):
        import hashlib
        task={'task_id':'one','job_id':'job','prompt':'A unique full scene description','prompt_sha256':hashlib.sha256(b'A unique full scene description').hexdigest(),'character_mentions':[]}
        receipt={**task,'stage':'waiting_result'}
        tile={'tile_id':'failed','complete':False,'text':'Generation failed. A unique full scene description'}
        self.assertEqual(FlowImages._legacy_failed_tasks([task],[tile],[receipt]),{'one':'failed'})
        self.assertEqual(FlowImages._legacy_failed_tasks([task],[tile],[receipt,{**receipt,'task_id':'other'}]),{})
        self.assertEqual(FlowImages._legacy_failed_tasks([task],[{**tile,'text':'Still generating'}],[receipt]),{})

    def test_only_new_terminal_cards_with_unambiguous_full_prompt_are_blocked(self):
        tasks=[{'task_id':'one','prompt':'The unique long description of this scene'}]
        failure={'tile_id':'new-card','text':'Generation failed. The unique long description of this scene','complete':False}
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks,[failure],[]),{'one':'new-card'})
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks,[failure],['new-card']),{})
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks,[failure],None),{})
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks,[{**failure,'text':'Still generating'}],[]),{})
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks,[{**failure,'complete':True}],[]),{})
        self.assertEqual(FlowImages._confirmed_failed_tasks(tasks+[{'task_id':'two','prompt':tasks[0]['prompt']}],[failure],[]),{})

    def test_reference_tensors_feed_encoder_vae_and_sampler(self):
        graph=reference_graph('same person',1,'test',['a.png','b.png'])
        self.assertEqual(graph['4']['inputs']['images.image_1'],['10',0])
        self.assertEqual(graph['4']['inputs']['images.image_2'],['11',0])
        self.assertEqual(graph['4']['inputs']['vae'],['3',0])
        self.assertEqual(graph['6']['inputs']['latent_image'],['4',2])
        self.assertEqual(graph['10']['inputs']['image'],'a.png')


class PortraitDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_uses_saved_entity_and_cache_never_generates(self):
        with tempfile.TemporaryDirectory() as folder:
            import io,base64
            buffer=io.BytesIO();Image.effect_noise((512,768),60).convert('RGB').save(buffer,format='PNG')
            command=AsyncMock(return_value={'result':{'value':base64.b64encode(buffer.getvalue()).decode()}})
            bridge=type('Bridge',(),{'job_lock':asyncio.Lock(),'connect':AsyncMock(),'cdp':type('CDP',(),{'command':command})(),'images':object()})()
            flow=FlowImages(bridge,Path(folder));task=str(uuid.uuid4());job=str(uuid.uuid4());entity=str(uuid.uuid4())
            flow._write_receipt(task,{'task_id':task,'job_id':job,'character_id':entity,'stage':'character_saved','project_url':'https://flow.google.com/project/test'})
            flow._target=AsyncMock(return_value='tab');flow._session=AsyncMock(return_value='session');flow._wait_page=AsyncMock();flow._wait_character_complete=AsyncMock();flow._return_to_project_root=AsyncMock();flow._eval=AsyncMock(return_value={'src':'https://flow.google.com/displayed-portrait'})
            flow._click_point=AsyncMock()
            first=await flow.download_character_reference(task,job,entity)
            second=await flow.download_character_reference(task,job,entity)
            self.assertEqual(first['sha256'],second['sha256']);self.assertTrue(Path(first['file_path']).is_file())
            flow._click_point.assert_not_awaited()
            self.assertFalse(any(c.args[0]=='Input.insertText' for c in command.await_args_list))
            with self.assertRaises(FlowTaskError):await flow.download_character_reference(task,job,str(uuid.uuid4()))


class HybridRoutingTests(unittest.TestCase):
    def test_mixed_provider_checkpoint_survives_retry_and_keeps_render_source(self):
        from videostudio.providers import Pipeline
        with tempfile.TemporaryDirectory() as folder:
            p=Pipeline.__new__(Pipeline);job={'id':str(uuid.uuid4()),'output':folder,'request':{'duration_seconds':2},'checkpoints':{'speech':{'duration_seconds':2,'scenes':[{'visual_prompt':'scene 0','duration':1},{'visual_prompt':'scene 1','duration':1}]}}}
            def picture(path):
                image=Image.new('RGB',(512,512),'white');image.paste('black',(0,0,256,512));image.save(path)
            def flow(j,group,check,timeout):
                results={}
                for task in group:
                    if task['ordinal']==0:results[task['task_id']]={'task_id':task['task_id'],'status':'blocked','blocked_confirmed':True}
                    else:picture(task['output_path']);results[task['task_id']]={'task_id':task['task_id'],'media_id':'media','request_id':'flow'}
                return results
            def comfy(p,j,t,r,c):picture(t['output_path']);return {'task_id':t['task_id'],'provider':'comfy','hybrid_fallback':True}
            p._browser_scene_images_batch=Mock(side_effect=flow)
            with patch('videostudio.providers.available_flow_batch_sizes',return_value=[1,3]),patch('videostudio.hybrid_images.comfy_scene',side_effect=comfy) as generate:
                first=p._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',3)
                second=p._flow_batch_images(job,lambda:None,{},[],'legacy_text_only',3)
            self.assertEqual([s['image_provider'] for s in first['scenes']],['comfy','flow'])
            self.assertEqual(first['scenes'],second['scenes']);generate.assert_called_once();p._browser_scene_images_batch.assert_called_once()

    def test_partial_flow_success_is_kept_before_two_comfy_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            from videostudio.providers import Pipeline
            job={'id':str(uuid.uuid4()),'output':folder};pipeline=Mock();pipeline.store=None;pipeline._flow_cohorts=Pipeline._flow_cohorts
            tasks=[{'task_id':str(uuid.uuid4()),'prompt':f'scene {i}','original_prompt':f'scene {i}','ordinal':i,'character_mentions':[]} for i in range(10)]
            calls=[];completed=[]
            def flow(j,group,check,timeout):
                calls.append([t['ordinal'] for t in group])
                return {t['task_id']:({'task_id':t['task_id'],'status':'blocked','blocked_confirmed':True} if t['ordinal']==2 else {'task_id':t['task_id']}) for t in group}
            pipeline._browser_scene_images_batch=Mock(side_effect=flow)
            with patch('videostudio.hybrid_images.comfy_scene',side_effect=lambda p,j,t,r,c:{'task_id':t['task_id'],'provider':'comfy'}):
                run(pipeline,job,tasks,3,{},lambda t,r:completed.append((t['ordinal'],r.get('provider','flow'))),lambda:None)
            self.assertEqual(calls,[[0,1,2],[8],[9]])
            self.assertEqual(completed[:2],[(0,'flow'),(1,'flow')])
            self.assertEqual(completed[2:8],[(i,'comfy') for i in range(2,8)])

    def test_two_comfy_batches_then_single_flow_probe_with_persisted_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            job={'id':str(uuid.uuid4()),'output':folder};pipeline=Mock();pipeline.store=None
            tasks=[{'task_id':str(uuid.uuid4()),'prompt':f'scene {i}','original_prompt':f'scene {i}','ordinal':i,'character_mentions':[]} for i in range(10)]
            from videostudio.providers import Pipeline
            pipeline._flow_cohorts=Pipeline._flow_cohorts
            calls=[]
            def flow(job,cohort,check,timeout):
                calls.append([t['ordinal'] for t in cohort])
                return {t['task_id']:({'task_id':t['task_id'],'status':'blocked','blocked_confirmed':True} if len(calls)==1 else {'task_id':t['task_id']}) for t in cohort}
            pipeline._browser_scene_images_batch=Mock(side_effect=flow);done=[]
            def comfy(p,j,t,r,check):return {'task_id':t['task_id'],'provider':'comfy'}
            with patch('videostudio.hybrid_images.comfy_scene',side_effect=comfy):
                result=run(pipeline,job,tasks,3,{},lambda t,r:done.append((t['ordinal'],r.get('provider','flow'))),lambda:None)
            self.assertEqual(calls,[[0,1,2],[6],[7,8,9]])
            self.assertEqual(done[:6],[(i,'comfy') for i in range(6)])
            self.assertEqual(len(result),10);self.assertEqual(len(set(i for i,_ in done)),10)
            self.assertEqual(json.loads((Path(folder)/'image-routing.json').read_text())['mode'],'flow')

    def test_unknown_flow_result_never_switches_to_comfy(self):
        with tempfile.TemporaryDirectory() as folder:
            from videostudio.providers import Pipeline,UncertainDeliveryError
            pipeline=Mock();pipeline._flow_cohorts=Pipeline._flow_cohorts
            pipeline._browser_scene_images_batch.side_effect=UncertainDeliveryError('unknown')
            with patch('videostudio.hybrid_images.comfy_scene') as comfy,self.assertRaises(UncertainDeliveryError):
                run(pipeline,{'id':str(uuid.uuid4()),'output':folder},[{'task_id':str(uuid.uuid4()),'prompt':'p','ordinal':0}],3,{},Mock(),lambda:None)
            comfy.assert_not_called()
