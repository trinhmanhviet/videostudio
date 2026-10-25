import copy,importlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from videostudio.core import PermanentError,digest
from videostudio.providers import Pipeline

class VisualQualityTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict('os.environ',{'VS_VISUAL_REVIEW_SECRET':'fixture-signing-secret-never-use-production'})
        env.start();self.addCleanup(env.stop)
    def q(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.visual_quality'),'Visual contracts and image review gate not implemented')
        return importlib.import_module('videostudio.visual_quality')
    def contract(self,intent='reconstruction'):
        return {'scene_id':'scene-A','intent':intent,'context':{'era':'15th century','region':'Europe','setting':'forge'},'must_show':['articulated steel armor'],'avoid':['tactical vest','plastic face shield'],'references':[],'separate_subjects':False}
    def project(self):return {'schema_version':1,'style':'natural material textures','identities':[]}
    def test_scene_context_not_global_era(self):
        q=self.q(); a=self.contract();b=self.contract('contemporary');b['context']['era']='2020s';b['must_show']=['tactical vest'];b['avoid']=[]
        self.assertIn('15th century',q.compile_prompt('warrior',self.project(),a)['positive'])
        self.assertIn('2020s',q.compile_prompt('tactical vest',self.project(),b)['positive'])
    def test_prompt_conflict_blocks_before_gpu(self):
        q=self.q();self.assertTrue(q.prompt_issues('man wearing a tactical vest',self.contract()))
    def test_comparison_allows_modern_but_requires_separation(self):
        q=self.q(); c=self.contract('comparison');c['must_show']=['historical breastplate','modern tactical vest'];c['avoid']=[]
        with self.assertRaises(ValueError):q.compile_prompt('comparison',self.project(),c)
        c['separate_subjects']=True
        self.assertIn('separate',q.compile_prompt('comparison',self.project(),c)['positive'].lower())
    def test_reference_hash_is_verified(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'ref.png';p.write_bytes(b'pixels');c=self.contract();c['references']=[{'path':str(p),'sha256':digest(p),'note':'approved reference'}]
            q.compile_prompt('armor',self.project(),c)
            p.write_bytes(b'different')
            with self.assertRaises(ValueError):q.compile_prompt('armor',self.project(),c)
    def test_global_style_cannot_reintroduce_scene_prohibited_object(self):
        q=self.q();project=self.project();project['style']='a tactical vest in dramatic lighting'
        with self.assertRaises(ValueError):q.compile_prompt('armor',project,self.contract())
    def test_context_workflow_reference_changes_cache_key(self):
        q=self.q();c=self.contract();base=q.conditioning_key('p','n',c,{'cfg':1})
        for changed in (dict(c,context={'era':'16th century'}),dict(c,must_show=['mail'])):
            self.assertNotEqual(base,q.conditioning_key('p','n',changed,{'cfg':1}))
        self.assertNotEqual(base,q.conditioning_key('p','n',c,{'cfg':2}))
        self.assertNotEqual(base,q.conditioning_key('different','n',c,{'cfg':1}))
    def test_stable_ids_survive_reorder_and_visual_edits(self):
        q=self.q(); a={'narration':'first','visual_prompt':'old'};b={'narration':'second','visual_prompt':'b'}
        old=q.bind_scene_ids([a,b]);new=q.bind_scene_ids([b,dict(a,visual_prompt='new')])
        self.assertEqual(old[0]['scene_id'],new[1]['scene_id']);self.assertEqual(a['visual_prompt'],'old')
    def test_ambiguous_duplicate_requires_explicit_ids(self):
        q=self.q()
        with self.assertRaises(ValueError):q.bind_scene_ids([{'narration':'same'},{'narration':'same'}])
        self.assertEqual(len(q.bind_scene_ids([{'scene_id':'one','narration':'same'},{'scene_id':'two','narration':'same'}])),2)
    def test_missing_reviewer_is_needs_review_not_pass(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.png';p.write_bytes(b'pixels')
            r=q.review_image(p,self.contract(),'key',None,lambda:None)
            self.assertEqual(r['status'],'needs_review');self.assertFalse(q.receipt_passes(r,p,self.contract(),'key'))
    def test_malformed_or_uncertain_review_is_not_pass(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.png';p.write_bytes(b'pixels')
            for response in ({'status':'pass'}, {'status':'pass','observations':[],'issues':[],'uncertain':True,'reviewer':'vision-test'}, {'status':'pass','observations':['looks okay'],'issues':['plastic'],'uncertain':False,'reviewer':'vision-test'}):
                r=q.review_image(p,self.contract(),'key',lambda *args:response,lambda:None)
                self.assertNotEqual(r['status'],'pass')
    def test_bound_receipt_invalidates_when_image_contract_or_key_changes(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.png';p.write_bytes(b'pixels');c=self.contract()
            reviewer=lambda *args:{'status':'pass','observations':['visible steel shoulder plates'],'issues':[],'uncertain':False,'reviewer':'fixture-not-real-model'}
            r=q.review_image(p,c,'key',reviewer,lambda:None)
            self.assertTrue(q.receipt_passes(r,p,c,'key'))
            self.assertFalse(q.receipt_passes(r,p,dict(c,context={'era':'other'}),'key'))
            self.assertFalse(q.receipt_passes(r,p,c,'changed-key'))
            p.write_bytes(b'altered');self.assertFalse(q.receipt_passes(r,p,c,'key'))
    def test_changed_image_during_review_does_not_pass(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.png';p.write_bytes(b'pixels')
            def reviewer(*args):
                p.write_bytes(b'changed');return {'status':'pass','observations':['armor'],'issues':[],'uncertain':False,'reviewer':'fixture'}
            self.assertNotEqual(q.review_image(p,self.contract(),'key',reviewer,lambda:None)['status'],'pass')
    def test_receipt_cannot_be_forged_by_editing_fail_to_pass(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.png';p.write_bytes(b'pixels');c=self.contract()
            r=q.review_image(p,c,'key',lambda *args:{'status':'fail','observations':['plastic present'],'issues':['plastic'],'uncertain':False,'reviewer':'fixture'},lambda:None)
            r.update(status='pass',issues=[])
            self.assertFalse(q.receipt_passes(r,p,c,'key'))
    def test_missing_signing_key_cannot_approve(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_REVIEW_SECRET':''}):
            p=Path(t)/'a.png';p.write_bytes(b'pixels');c=self.contract()
            r=q.review_image(p,c,'key',lambda *args:{'status':'pass','observations':['armor'],'issues':[],'uncertain':False,'reviewer':'fixture'},lambda:None)
            self.assertFalse(q.receipt_passes(r,p,c,'key'))
            self.assertEqual(r['status'],'needs_review')
    def test_required_policy_survives_failed_stage_and_environment_change(self):
        q=self.q()
        with tempfile.TemporaryDirectory() as t:
            j=VisualPipelineGateTests().job(t)
            with patch.dict('os.environ',{'VS_VISUAL_QA':'required'}):
                with self.assertRaises(PermanentError):Pipeline.__new__(Pipeline).images(j,lambda:None)
            with patch.dict('os.environ',{'VS_VISUAL_QA':'legacy'}):self.assertEqual(q.gate_mode(j),'required')
    def test_regression_fixture_preserves_legitimate_modern_intent(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/visual-regression.json').read_text(encoding='utf8'))
        cases={c['case_id']:c for c in fixture['cases']}
        self.assertEqual(cases['armor-0174']['expected'],'fail');self.assertEqual(cases['modern-ppe-control']['expected'],'pass')
        self.assertEqual(cases['armor-0174']['image_sha256'],cases['modern-ppe-control']['image_sha256'])

class VisualPipelineGateTests(unittest.TestCase):
    def job(self,t):return {'id':'f9d386c3-ffef-4121-9e98-0b9caf4c4ddf','output':t,'request':{'duration_seconds':10},'checkpoints':{'speech':{'duration_seconds':9,'utterances':[{'narration':'a','visual_prompt':'b','duration':9}]}}}
    def test_required_missing_contracts_does_not_generate(self):
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required'}):
            p=Pipeline.__new__(Pipeline);p.comfy_asset=Mock(side_effect=AssertionError('must not generate'))
            with self.assertRaisesRegex(PermanentError,'Visual quality'):p.images(self.job(t),lambda:None)
            p.comfy_asset.assert_not_called()
    def test_render_cannot_accept_technical_only_checkpoint_when_required(self):
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required'}),patch('videostudio.providers.render') as renderer:
            p=Pipeline.__new__(Pipeline);p.ffmpeg='ffmpeg';p.ffprobe='ffprobe';j=self.job(t)
            j['checkpoints'].update(images={'scenes':[]},music={'path':'music.wav'},subtitles={'path':'subtitles.ass'})
            j['checkpoints']['speech']['path']='speech.wav'
            with self.assertRaisesRegex(PermanentError,'Visual quality'):p.render(j,lambda:None)
            renderer.assert_not_called()
    def test_invalid_gate_mode_is_not_legacy_bypass(self):
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'requird'}):
            p=Pipeline.__new__(Pipeline);p.comfy_asset=Mock(side_effect=AssertionError('must not generate'))
            with self.assertRaisesRegex(PermanentError,'Visual quality'):p.images(self.job(t),lambda:None)

class VisualGateRoundtripTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict('os.environ',{'VS_VISUAL_REVIEW_SECRET':'fixture-signing-secret-never-use-production'})
        env.start();self.addCleanup(env.stop)
    def test_required_cache_roundtrip_and_release_revalidates_pixels(self):
        from PIL import Image
        import videostudio.visual_quality as q
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required'}):
            p=Pipeline.__new__(Pipeline); j=VisualPipelineGateTests().job(t)
            u=q.bind_scene_ids(j['checkpoints']['speech']['utterances'])[0]
            c=VisualQualityTests().contract();c.update(scene_id=u['scene_id'],narration_sha256=q.text_hash(u['narration']))
            q.atomic_json(Path(t)/'visual-contracts.json',{'schema_version':1,'job_id':j['id'],'project':VisualQualityTests().project(),'scenes':[c]})
            calls=[]
            def generate(job,kind,graph,path,check):
                calls.append(graph);im=Image.new('RGB',(512,512),'black');im.paste('white',(0,0,256,512));im.save(path)
            p.comfy_asset=generate
            review_calls=[]
            def review(*args):
                review_calls.append(1);return {'status':'pass','reviewer':'synthetic-test-only','observations':['fixture image inspected'],'issues':[],'uncertain':False}
            p.visual_reviewer=review
            first=p.images(j,lambda:None);j['checkpoints']['images']=first
            self.assertEqual(q.require_release(j,lambda compiled,i:p._visual_workflow(j,compiled,i))['status'],'pass')
            p.images(j,lambda:None);self.assertEqual(len(calls),1);self.assertEqual(len(review_calls),1)
            Path(first['scenes'][0]['path']).write_bytes(b'changed')
            with self.assertRaises(PermanentError):q.require_release(j,lambda compiled,i:p._visual_workflow(j,compiled,i))
            with patch.dict('os.environ',{'VS_VISUAL_QA':'legacy'}):
                with self.assertRaises(PermanentError):q.require_release(j,lambda compiled,i:p._visual_workflow(j,compiled,i))
    def test_missing_signer_blocks_gpu_even_with_reviewer_callback(self):
        import videostudio.visual_quality as q
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required','VS_VISUAL_REVIEW_SECRET':''}):
            j=VisualPipelineGateTests().job(t);u=q.bind_scene_ids(j['checkpoints']['speech']['utterances'])[0]
            c=VisualQualityTests().contract();c.update(scene_id=u['scene_id'],narration_sha256=q.text_hash(u['narration']))
            q.atomic_json(Path(t)/'visual-contracts.json',{'schema_version':1,'job_id':j['id'],'project':VisualQualityTests().project(),'scenes':[c]})
            p=Pipeline.__new__(Pipeline);p.visual_reviewer=Mock();p.comfy_asset=Mock(side_effect=AssertionError('must not spend GPU'))
            with self.assertRaisesRegex(PermanentError,'signing'):p.images(j,lambda:None)
            p.comfy_asset.assert_not_called()
    def test_empty_contract_and_scene_set_cannot_be_accepted(self):
        import videostudio.visual_quality as q
        with tempfile.TemporaryDirectory() as t,patch.dict('os.environ',{'VS_VISUAL_QA':'required'}):
            j=VisualPipelineGateTests().job(t);j['checkpoints']['speech']['utterances']=[]
            j['checkpoints']['images']={'visual_qa_status':'pass','scenes':[]}
            q.atomic_json(Path(t)/'visual-contracts.json',{'schema_version':1,'job_id':j['id'],'project':VisualQualityTests().project(),'scenes':[]})
            with self.assertRaises(PermanentError):q.require_release(j,lambda c,i:{})
    def test_audit_has_no_generated_review_approvals(self):
        import videostudio.visual_audit as audit
        import videostudio.visual_quality as q
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source';source.mkdir();out=Path(t)/'audit'
            q.atomic_json(source/'final-script.json',{'scenes':[{'narration':'a','visual_prompt':'b'}]})
            before=digest(source/'final-script.json');result=audit.audit_existing(source,out)
            self.assertEqual(result['scenes'][0]['visual_qa_status'],'not_checked')
            self.assertEqual(before,digest(source/'final-script.json'))
            with self.assertRaises(ValueError):audit.audit_existing(source,source/'audit')

if __name__=='__main__':unittest.main()
