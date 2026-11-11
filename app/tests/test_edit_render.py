import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image
from videostudio.core import digest
from videostudio.media import asset, probe, run
from test_scene_editor import ready_job


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class EditRenderTests(unittest.TestCase):
    def test_text_respects_track_order_relative_to_a_higher_image_layer(self):
        from videostudio.edit_plan import EditPlanService
        from videostudio.edit_render import render_edit_plan
        from test_scene_editor import picture
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder);service=EditPlanService(store);view=service.view(job['id']);plan=copy.deepcopy(view['plan'])
            overlay=service.import_asset(job['id'],picture('green'),'green.png')['asset']
            plan['duration']=.6;plan['canvas']={'width':160,'height':284,'fps':12};plan['captions']['enabled']=False;plan['music']=[];plan['sfx']=[]
            plan['clips']=[next(c for c in plan['clips'] if c['kind']=='image'),next(c for c in plan['clips'] if c['kind']=='text')]
            for clip in plan['clips']:clip.update(start=0,end=.6,transition={'type':'none','duration':0})
            plan['clips'][1].update(text='TEXT',x=.5,y=.5,size=36,background=None,color='#FFFFFF')
            plan['tracks'].append({'id':'top','kind':'image','name':'Top','muted':False,'visible':True,'locked':False})
            plan['clips'].append({'id':'top-image','track_id':'top','kind':'image','asset_id':overlay['id'],'start':0,'end':.6,'fit':'cover','enabled':True})
            saved=service.save(job['id'],0,plan);first=render_edit_plan(service.export(job['id'],saved['revision'],'text-below'),lambda:None)
            raw=run(['ffmpeg','-v','error','-ss','0.3','-i',first['video'],'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],lambda:None)
            self.assertEqual(sum(min(raw[i:i+3])>220 for i in range(0,len(raw),3)),0)
            changed=copy.deepcopy(saved['plan']);top=changed['tracks'].pop();changed['tracks'].insert(1,top)
            newer=service.save(job['id'],saved['revision'],changed);second=render_edit_plan(service.export(job['id'],newer['revision'],'text-above'),lambda:None)
            raw=run(['ffmpeg','-v','error','-ss','0.3','-i',second['video'],'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],lambda:None)
            self.assertGreater(sum(min(raw[i:i+3])>220 for i in range(0,len(raw),3)),10)
            corner=(10*160+10)*3;self.assertGreater(raw[corner+1],raw[corner]+20)

    def test_manual_quiet_soundtrack_exports_without_a_false_silence_failure(self):
        from videostudio.edit_plan import EditPlanService
        from videostudio.edit_render import render_edit_plan,verify_edit_render
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder);service=EditPlanService(store);view=service.view(job['id']);plan=copy.deepcopy(view['plan'])
            plan['canvas']={'width':160,'height':284,'fps':12};plan['duration']=.6;plan['captions']['enabled']=False
            plan['clips']=[next(c for c in plan['clips'] if c['kind']=='image')];plan['clips'][0].update(start=0,end=.6)
            plan['sfx']=[]
            for clip in plan['music']:clip.update(start=0,end=.6,volume=.0001,fade_in=0,fade_out=0)
            saved=service.save(job['id'],0,plan);child=service.export(job['id'],saved['revision'],'quiet-manual')
            child['checkpoints']['render']=render_edit_plan(child,lambda:None)
            result=verify_edit_render(child,lambda:None)
            self.assertTrue(result['verified']);self.assertFalse(result['audio_quality']['non_silence_check_required'])

    def test_synthetic_layer_motion_text_transition_timing_and_cross_export_cache(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.edit_render'), 'Edit renderer missing')
        from videostudio.edit_plan import EditPlanService
        from videostudio.edit_render import render_edit_plan
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            # Detailed source makes crop/camera motion observable; refresh fixture attestation.
            source = Path(job['checkpoints']['images']['scenes'][0]['path'])
            with Image.open(source) as im:
                for y in range(im.height):
                    for x in range(im.width): im.putpixel((x, y), (255 if x < 40 else 20, y * 2, 0))
                im.save(source)
            with store.db() as c:
                images = copy.deepcopy(job['checkpoints']['images']); images['assets'][0] = asset(source)
                c.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?', (json.dumps(images), job['id'], 'images'))
            service = EditPlanService(store); view = service.view(job['id']); plan = copy.deepcopy(view['plan'])
            plan['canvas'] = {'width': 160, 'height': 284, 'fps': 12}; plan['duration'] = 1.6
            plan['captions']['enabled'] = False
            plan['clips'] = [c for c in plan['clips'] if c['kind'] in ('image', 'text')]
            plan['clips'][0].update(start=0, end=.8, motion={'type': 'pan_right', 'amount': .2}, crop={'x': 0, 'y': 0, 'width': .9, 'height': 1}, transition={'type': 'fade', 'duration': .15})
            plan['clips'][1].update(start=.8, end=1.6, transition={'type': 'dissolve', 'duration': .2})
            title = next(c for c in plan['clips'] if c['kind'] == 'text'); title.update(start=0, end=1.6, text='Measured edit', size=22, y=.2)
            # Import a real video and layer it over the images.
            video = Path(t) / 'layer.mp4'
            run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=green:s=80x80:r=12:d=1.6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video], lambda: None)
            imported = service.import_asset(job['id'], video.read_bytes(), 'layer.mp4')['asset']
            plan['tracks'].insert(1, {'id': 'layer', 'kind': 'video', 'name': 'Layer', 'muted': False, 'visible': True, 'locked': False})
            plan['clips'].append({'id': 'video-layer', 'track_id': 'layer', 'kind': 'video', 'asset_id': imported['id'], 'source_start': 0, 'start': 0, 'end': 1.6, 'enabled': True, 'width': .3, 'height': .2, 'x': .75, 'y': .6, 'opacity': .8, 'motion': {'type': 'zoom_in', 'amount': .1}, 'transition': {'type': 'slide_left', 'duration': .2}})
            for collection in ('music', 'sfx'):
                for c in plan[collection]: c.update(start=0, end=1.6, fade_in=.1, fade_out=.1)
            if not plan['sfx']:
                plan['sfx'] = [{'id': 'accent', 'track_id': 'sfx', 'kind': 'audio', 'asset_id': 'sfx-chime', 'start': .2, 'end': .7, 'source_start': 0, 'volume': .2, 'enabled': True}]
            changed = service.save(job['id'], view['revision'], plan)
            originals = {a['path']: digest(a['path']) for stage in job['checkpoints'].values() for a in stage.get('assets', [])}
            # Source image was intentionally changed before taking the immutable baseline.
            originals[str(source.resolve())] = digest(source)
            child = service.export(job['id'], changed['revision'], 'render-first')
            first = render_edit_plan(child, lambda: None)
            from videostudio.providers import Pipeline
            pipeline=Pipeline.__new__(Pipeline);pipeline.ffmpeg='ffmpeg';pipeline.ffprobe='ffprobe'
            child['checkpoints']['render']=first
            verified=pipeline.verify(child,lambda:None)
            self.assertTrue(verified['verified'])
            self.assertAlmostEqual(verified['duration_seconds'],1.6,delta=.2)
            self.assertTrue(Path(first['video']).is_file())
            self.assertEqual(first['visual_cache']['misses'], 3)
            self.assertAlmostEqual(float(probe(first['video'])['format']['duration']), 1.6, delta=.15)
            run(['ffmpeg', '-v', 'error', '-xerror', '-i', first['video'], '-f', 'null', '-'], lambda: None)
            raw = run(['ffmpeg', '-v', 'error', '-ss', '0.5', '-i', first['video'], '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], lambda: None)
            self.assertEqual(len(raw), 160 * 284 * 3)
            # Video layer is visible at its actual timeline/canvas position.
            pixel = raw[(170 * 160 + 120)*3:(170 * 160 + 120)*3+3]
            self.assertGreater(pixel[1], pixel[0] + 20)
            cache_paths = list(Path(first['visual_cache']['directory']).glob('*.mp4'))
            mtimes = {str(p): p.stat().st_mtime_ns for p in cache_paths}
            plan2 = copy.deepcopy(changed['plan']); next(c for c in plan2['clips'] if c['kind'] == 'text')['text'] = 'Different label'
            saved2 = service.save(job['id'], changed['revision'], plan2)
            child2 = service.export(job['id'], saved2['revision'], 'render-second')
            second = render_edit_plan(child2, lambda: None)
            self.assertEqual(second['visual_cache']['hits'], 3)
            self.assertEqual(second['visual_cache']['misses'], 0)
            self.assertTrue(second['audio']['reused'])
            self.assertEqual({str(p): p.stat().st_mtime_ns for p in cache_paths}, mtimes)
            self.assertNotEqual(digest(first['video']), digest(second['video']))
            plan3 = copy.deepcopy(saved2['plan']); plan3['clips'][0]['motion'] = {'type': 'zoom_out', 'amount': .3}
            saved3 = service.save(job['id'], saved2['revision'], plan3)
            third = render_edit_plan(service.export(job['id'], saved3['revision'], 'render-third'), lambda: None)
            self.assertEqual(third['visual_cache']['misses'], 1)
            self.assertEqual(third['visual_cache']['hits'], 2)
            self.assertEqual({path: digest(path) for path in originals}, originals)

    def test_windowed_composition_keeps_timeline_and_dissolve_visible_across_boundary(self):
        from videostudio.edit_plan import EditPlanService
        from videostudio.edit_render import render_edit_plan
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t); service = EditPlanService(store); view = service.view(job['id'])
            plan = copy.deepcopy(view['plan']); plan['duration'] = 1.6; plan['canvas'] = {'width': 80, 'height': 144, 'fps': 10}
            plan['captions']['enabled'] = False; plan['music'] = []; plan['sfx'] = []
            plan['clips'] = [c for c in plan['clips'] if c['kind'] == 'image']
            plan['clips'][0].update(start=0, end=.8, motion={'type': 'none', 'amount': 0}, transition={'type': 'none', 'duration': 0})
            plan['clips'][1].update(start=.8, end=1.6, motion={'type': 'none', 'amount': 0}, transition={'type': 'dissolve', 'duration': .4})
            changed = service.save(job['id'], view['revision'], plan)
            child = service.export(job['id'], changed['revision'], 'windowed')
            with patch('videostudio.edit_render.COMPOSITE_WINDOW_SECONDS', .6): result = render_edit_plan(child, lambda: None)
            self.assertEqual(result['composite_segments'], 3)
            self.assertAlmostEqual(float(probe(result['video'])['format']['duration']), 1.6, delta=.15)
            frame = run(['ffmpeg', '-v', 'error', '-ss', '1.0', '-i', result['video'], '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], lambda: None)
            pixel = frame[(80*70+40)*3:(80*70+40)*3+3]
            self.assertGreater(pixel[0], 40)  # red outgoing scene still underneath
            self.assertGreater(pixel[2], 40)  # incoming blue scene has started


if __name__ == '__main__': unittest.main()
