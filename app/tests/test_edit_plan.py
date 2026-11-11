import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from videostudio.core import digest
from test_scene_editor import ready_job, picture


class EditPlanTests(unittest.TestCase):
    def test_flow_bottom_crop_does_not_apply_to_comfy_fallback_scenes(self):
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder)
            images=copy.deepcopy(job['checkpoints']['images']);images['image_provider']='flow'
            images['scenes'][0]['image_provider']='comfy';images['scenes'][1]['image_provider']='flow'
            with store.db() as c:c.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?',(json.dumps(images),job['id'],'images'))
            plan=self.service(store).view(job['id'])['plan'];clips=[c for c in plan['clips'] if c['kind']=='image']
            self.assertNotIn('crop',clips[0]);self.assertEqual(clips[1]['crop'],{'x':0,'y':0,'width':1,'height':.94})

    def test_automatic_defaults_freeze_sources_without_overwriting_a_saved_user_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder);service=self.service(store);view=service.view(job['id']);plan=copy.deepcopy(view['plan'])
            next(c for c in plan['clips'] if c['kind']=='text')['text']='Keep this manual draft'
            saved=service.save(job['id'],0,plan);before=store.get(job['id'])['checkpoints']
            path=service.automatic_snapshot(job)
            self.assertTrue(path.is_file());self.assertEqual(service.view(job['id'])['revision'],saved['revision'])
            self.assertEqual(next(c for c in service.view(job['id'])['plan']['clips'] if c['kind']=='text')['text'],'Keep this manual draft')
            self.assertEqual(before,store.get(job['id'])['checkpoints'])

    def test_serving_one_asset_does_not_rehash_every_other_source(self):
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder);service=self.service(store);view=service.view(job['id'])
            selected=next(a for a in view['assets'] if a['kind']=='image')
            with patch('videostudio.edit_plan.digest',wraps=digest) as hashes:
                path=service.asset_file(job['id'],selected['id'])
            self.assertEqual({str(Path(call.args[0]).resolve()) for call in hashes.call_args_list},{str(path.resolve())})

    def test_real_speech_scene_metadata_without_a_file_path_remains_editable(self):
        with tempfile.TemporaryDirectory() as folder:
            store,job=ready_job(folder)
            speech=copy.deepcopy(job['checkpoints']['speech'])
            speech['scenes']=[{'scene_id':'scene-0','scene_index':0,'start':0,'end':3.5,'duration':3.5},
                              {'scene_id':'scene-1','scene_index':1,'start':3.5,'end':7,'duration':3.5}]
            with store.db() as c:c.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?',(json.dumps(speech),job['id'],'speech'))
            view=self.service(store).view(job['id'])
            self.assertTrue(view['editable']);self.assertEqual(len([c for c in view['plan']['clips'] if c['kind']=='image']),2)

    def service(self, store):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.edit_plan'), 'Edit plan service missing')
        from videostudio.edit_plan import EditPlanService
        return EditPlanService(store)

    def test_open_generates_persistent_scoped_plan_without_changing_checkpoints(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            before = copy.deepcopy(job['checkpoints'])
            service = self.service(store)
            view = service.view(job['id'])
            self.assertTrue(view['editable'])
            self.assertTrue(view['can_export'])
            self.assertEqual(view['plan']['schema_version'], 1)
            self.assertEqual({p['id'] for p in view['presets']}, {'documentary', 'science', 'everyday'})
            self.assertEqual(len([c for c in view['plan']['clips'] if c['kind'] == 'image']), 2)
            self.assertEqual(view['plan']['duration'], 8)
            self.assertNotIn('path', json.dumps(view['assets']))
            self.assertEqual(service.view(job['id'])['plan'], view['plan'])
            self.assertEqual(before, store.get(job['id'])['checkpoints'])
            self.assertEqual(json.loads((Path(job['output']) / 'edit_plan.json').read_text()), view['plan'])

    def test_atomic_revision_rejects_stale_and_invalid_edits_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            service = self.service(store)
            view = service.view(job['id'])
            plan = copy.deepcopy(view['plan'])
            plan['clips'][0]['motion'] = {'type': 'zoom_in', 'amount': .1}
            changed = service.save(job['id'], view['revision'], plan)
            self.assertEqual(changed['revision'], view['revision'] + 1)
            with self.assertRaisesRegex(ValueError, 'Stale'):
                service.save(job['id'], view['revision'], plan)
            for mutate in (
                lambda p: p['clips'][0].update(asset_id='../../secret'),
                lambda p: p['clips'][0].update(start=float('nan')),
                lambda p: p['clips'][0].update(filter='movie=secret'),
                lambda p: p['clips'][0].update(motion={'type': 'evil', 'amount': .1}),
                lambda p: p.update(preset_id=[]),
                lambda p: p['clips'][0].update(asset_id=[]),
                lambda p: p['clips'][0].update(track_id=[]),
                lambda p: p['tracks'].append(copy.deepcopy(p['tracks'][0])),
            ):
                bad = copy.deepcopy(changed['plan']); mutate(bad)
                with self.assertRaises(ValueError): service.save(job['id'], changed['revision'], bad)
                self.assertEqual(service.view(job['id'])['plan'], changed['plan'])
            self.assertTrue((Path(job['output']) / 'edit-plan-revisions' / '00000000.json').is_file())

    def test_import_scope_hash_checks_and_waveform(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            service = self.service(store)
            first = service.view(job['id'])
            imported = service.import_asset(job['id'], picture('green'), '../../unsafe.png')
            media = imported['asset']
            self.assertEqual(media['kind'], 'image')
            self.assertNotIn('..', media['name'])
            path = service.asset_file(job['id'], media['id'])
            self.assertTrue(path.is_file())
            with self.assertRaises(ValueError): service.asset_file(job['id'], '../../unsafe.png')
            for raw, name in ((b'not an audio file', 'broken.mp3'), (b'invalid video', 'broken.mp4')):
                with self.assertRaises(ValueError): service.import_asset(job['id'], raw, name)
            audio = next(a for a in first['assets'] if a['kind'] == 'audio' and a['source'] == 'speech')
            waveform = service.waveform(job['id'], audio['id'])
            self.assertTrue(waveform['bins'])
            self.assertTrue(all(0 <= x <= 1 for x in waveform['bins']))
            music = next(a for a in first['assets'] if a['kind'] == 'audio' and a['source'] == 'music')
            self.assertEqual(service.waveform(job['id'], music['id'])['asset_id'], music['id'])
            path.write_bytes(b'tampered')
            with self.assertRaises(ValueError): service.asset_file(job['id'], media['id'])

    def test_export_freezes_snapshot_and_is_idempotent_across_later_edits(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            service = self.service(store); view = service.view(job['id'])
            before = copy.deepcopy(job['checkpoints'])
            child = service.export(job['id'], view['revision'], 'export-once')
            snapshot = Path(child['checkpoints']['images']['edit_plan_snapshot'])
            frozen = snapshot.read_bytes()
            self.assertEqual(child['stage'], 'render')
            self.assertEqual(child['state'], 'queued')
            self.assertEqual(child['checkpoints']['speech'], before['speech'])
            updated = service.preset(job['id'], view['revision'], 'science')
            self.assertEqual(service.export(job['id'], view['revision'], 'export-once')['id'], child['id'])
            self.assertEqual(snapshot.read_bytes(), frozen)
            self.assertEqual(store.get(job['id'])['checkpoints'], before)
            with self.assertRaisesRegex(ValueError, 'already used'):
                service.export(job['id'], updated['revision'], 'export-once')
            child_view = service.view(child['id'])
            self.assertFalse(child_view['editable'])
            with self.assertRaises(ValueError): service.save(child['id'], child_view['revision'], child_view['plan'])

    def test_captions_emphasis_cannot_invent_utterance_times(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t); service = self.service(store); view = service.view(job['id'])
            plan = copy.deepcopy(view['plan'])
            plan['captions']['emphasis'] = [{'utterance_index': 0, 'start': 0, 'end': 4, 'text': 'cau'}]
            with self.assertRaisesRegex(ValueError, 'utterance'): service.save(job['id'], view['revision'], plan)
            plan['captions']['emphasis'][0]['end'] = 3.5
            self.assertTrue(service.save(job['id'], view['revision'], plan)['plan']['captions']['emphasis'])

    def test_chapter_labels_workflow_toggles_and_safe_optional_preset_default(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t)
            speech = copy.deepcopy(job['checkpoints']['speech'])
            for i, utterance in enumerate(speech['utterances']): utterance['chapter_index'] = i + 1
            with store.db() as c:
                c.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?', (json.dumps(speech), job['id'], 'speech'))
                c.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?', (json.dumps({'title': 'A measured title', 'chapters': [{'index': 1, 'title': 'Beginning'}, {'index': 2, 'title': 'Change'}], 'assets': []}), job['id'], 'script'))
                c.execute('UPDATE jobs SET request=? WHERE id=?', (json.dumps(dict(job['request'], edit_preset='unknown-optional-value', music_enabled=False, sfx_enabled=False, captions_enabled=False)), job['id']))
            service = self.service(store); view = service.view(job['id'])
            self.assertEqual(view['plan']['preset_id'], 'documentary')
            self.assertEqual(view['plan']['music'], [])
            self.assertEqual(view['plan']['sfx'], [])
            self.assertFalse(view['plan']['captions']['enabled'])
            labels = [c for c in view['plan']['clips'] if c['kind'] == 'text']
            self.assertTrue(any(c['text'] == 'Change' and c['start'] == 3.5 for c in labels))

    def test_preset_switch_changes_only_default_accents_and_clamps_short_transitions(self):
        with tempfile.TemporaryDirectory() as t:
            store, job = ready_job(t); service = self.service(store); view = service.view(job['id'])
            plan = copy.deepcopy(view['plan']); plan['clips'][0]['end'] = .1; plan['clips'][0]['transition'] = {'type': 'none', 'duration': 0}
            view = service.save(job['id'], view['revision'], plan)
            science = service.preset(job['id'], view['revision'], 'science')
            self.assertLessEqual(science['plan']['clips'][0]['transition']['duration'], .1)
            self.assertTrue(any(c['asset_id'] == 'sfx-chime' for c in science['plan']['sfx']))


if __name__ == '__main__': unittest.main()
