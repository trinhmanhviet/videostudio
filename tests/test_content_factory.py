"""Factory orchestration uses fixtures only; no providers, browser or GPU."""
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from videostudio.core import Store, digest
from videostudio.content_factory import ContentFactory
from videostudio.content_factory_api import register_content_factory_routes


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'jobs.sqlite3', self.root / 'out')
        self.calls = []
        def submit(request, key, scope):
            self.calls.append((request, key, scope))
            job, _ = self.store.create(request, key)
            return {'job': job}
        self.submit = submit
        self.factory = ContentFactory(self.store, submit, video_probe=lambda path: {
            'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}], 'format': {'duration': '30'}})

    def tearDown(self):
        self.tmp.cleanup()

    def batch(self, **changes):
        body = {'project': 'Test', 'style': 'news', 'input_mode': 'script',
                'defaults': {'voice_id': 'voice', 'duration_seconds': 30},
                'items': [{'content': 'First narration'}, {'content': 'Second narration'}]}
        body.update(changes)
        return self.factory.create_batch(body, 'batch-key', 'bridge')

    def test_batch_persists_normalized_requests_without_allocating_jobs(self):
        batch = self.batch()
        self.assertEqual(len(self.store.list()), 0)
        self.assertEqual(len(batch['items']), 2)
        self.assertEqual(batch['items'][0]['request']['workflow_mode'], 'provided_narration')
        self.assertEqual(batch['items'][0]['request']['project'], 'Test')
        self.assertEqual(self.batch()['id'], batch['id'])
        with self.assertRaises(ValueError):
            self.batch(items=[{'content': 'Different'}])
        restored = ContentFactory(self.store, self.submit)
        self.assertEqual(restored.queue()['items'][0]['id'], batch['items'][0]['id'])

    def test_batch_page_sends_one_project_per_video_with_its_own_style_in_order(self):
        # The batch page posts each row as its own single-item batch.
        rows = [('Bố đi chợ', 'meme', 'idea', 45), ('Hồ sơ khu phố cũ', 'case', 'script', 360), ('Ông chú công nghệ', 'meme', 'script', 60)]
        for index, (name, style, mode, seconds) in enumerate(rows):
            self.factory.create_batch({'project': name, 'style': style, 'input_mode': mode,
                                       'defaults': {'voice_id': 'voice', 'duration_seconds': seconds},
                                       'items': [{'text': 'Nội dung ' + name, 'title': name}]}, f'row-{index}', 'bridge')
        items = self.factory.queue()['items']
        self.assertEqual([i['project'] for i in items], [r[0] for r in rows])
        self.assertEqual([i['request']['workflow_mode'] for i in items], ['meme', 'provided_narration', 'meme'])
        self.assertEqual([i['request'].get('meme_input_mode') for i in items], ['idea', None, 'script'])
        self.assertEqual([i['request']['duration_seconds'] for i in items], [45, 360, 60])

    def test_only_one_job_is_dispatched_and_pause_survives_restart(self):
        batch = self.batch()
        self.assertTrue(self.factory.tick())
        self.assertEqual(len(self.store.list()), 1)
        self.assertFalse(self.factory.tick())
        self.factory.set_paused(True)
        job_id = self.store.list()[0]['id']
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='failed', error='Render failed' WHERE id=?", (job_id,))
        restored = ContentFactory(self.store, self.submit)
        self.assertFalse(restored.tick())
        self.assertTrue(restored.queue()['paused'])
        restored.set_paused(False)
        self.assertTrue(restored.tick())
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(restored.get_batch(batch['id'])['items'][0]['state'], 'failed')

    def test_admission_wait_is_bounded_and_does_not_allocate_or_fail_items(self):
        batch = self.batch()
        def blocked(*args):
            self.calls.append(args)
            raise HTTPException(503, {'message': 'Production preflight blocked', 'checks': [{'name': 'Chrome', 'detail': 'Login required'}]})
        self.factory.submit_job = blocked
        self.assertFalse(self.factory.tick())
        self.assertFalse(self.factory.tick())
        self.assertEqual(len(self.calls), 1)
        item = self.factory.get_batch(batch['id'])['items'][0]
        self.assertEqual(item['state'], 'waiting')
        self.assertIn('Production preflight blocked', item['message'])
        self.assertEqual(self.store.list(), [])

    def test_crash_after_create_recovers_receipt_before_dispatching_next(self):
        batch = self.batch()
        item = batch['items'][0]
        # A process died after admission committed Store.create and before linking.
        job, _ = self.store.create(item['request'], item['idempotency_key'])
        with self.store.db() as db:
            db.execute("UPDATE factory_items SET state='dispatching', lease_until=0 WHERE id=?", (item['id'],))
        recovered = ContentFactory(self.store, self.submit)
        self.assertFalse(recovered.tick())
        self.assertEqual(recovered.get_batch(batch['id'])['items'][0]['job_id'], job['id'])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.calls, [])

    def test_pending_order_and_actions_do_not_mutate_an_active_job(self):
        batch = self.batch()
        first, second = batch['items']
        self.factory.reorder([second['id'], first['id']])
        self.factory.tick()
        self.assertEqual(self.calls[0][0]['idea'], 'Second narration')
        with self.assertRaises(ValueError):
            self.factory.reorder([second['id'], first['id']])
        with self.assertRaises(ValueError):
            self.factory.item_action(second['id'], 'skip')
        self.factory.item_action(first['id'], 'cancel')
        self.assertEqual(self.factory.get_batch(batch['id'])['items'][1]['state'], 'cancelled')

    def test_invalid_batch_never_partially_inserts(self):
        for changes in ({'items': []}, {'style': 'bad'}, {'input_mode': 'bad'},
                        {'items': [{'content': 'x', 'overrides': {'duration_seconds': 1}}]},
                        {'items': [{'content': 'x', 'overrides': {'project': 'Other'}}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.batch(**changes)
        self.assertEqual(self.factory.list_batches()['items'], [])

    def verified_job(self):
        job, _ = self.store.create({'idea': 'Verified', 'voice_id': 'voice', 'duration_seconds': 30, 'project': 'Test'}, 'verified')
        from videostudio.output_layout import final_video_path
        video = final_video_path(job)
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b'fixture-verified-video')
        asset = {'path': str(video.resolve()), 'sha256': digest(video)}
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='completed' WHERE id=?", (job['id'],))
            for stage, value in [('render', {'video': str(video), 'assets': [asset]}),
                                 ('verify', {'verified': True, 'duration_seconds': 30, 'assets': [asset]})]:
                db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (job['id'], stage, json.dumps(value)))
        return self.store.get(job['id']), video

    def test_library_approval_binds_hash_and_rejects_changed_asset(self):
        job, video = self.verified_job()
        library = self.factory.videos(page_size=10)
        self.assertEqual(library['total'], 1)
        version = library['items'][0]['versions'][0]
        approval = self.factory.approve(job['id'], version['id'], version['sha256'])
        self.assertEqual(approval['sha256'], digest(video))
        self.assertEqual(self.factory.approved_version(job['id'])['path'], str(video.resolve()))
        video.write_bytes(b'changed')
        self.assertIsNone(self.factory.approved_version(job['id']))
        with self.assertRaises(ValueError):
            self.factory.get_video_version(job['id'], version['id'])

    def test_library_excludes_unverified_and_pagination_is_bounded(self):
        self.store.create({'idea': 'Queued', 'voice_id': 'voice', 'duration_seconds': 30}, 'queued')
        self.assertEqual(self.factory.videos()['total'], 0)
        with self.assertRaises(ValueError):
            self.factory.videos(page_size=100)

    def test_manual_jobs_have_priority_over_pending_factory_requests(self):
        self.batch()
        self.store.create({'idea': 'Manual', 'voice_id': 'voice', 'duration_seconds': 30}, 'manual')
        self.assertFalse(self.factory.tick())
        self.assertEqual(self.calls, [])

    def test_overlapping_dispatches_share_a_database_lease(self):
        self.batch()
        started, release = threading.Event(), threading.Event()
        def slow_submit(*args):
            started.set()
            release.wait(3)
            return self.submit(*args)
        self.factory.submit_job = slow_submit
        thread = threading.Thread(target=self.factory.tick)
        thread.start()
        self.assertTrue(started.wait(2))
        try:
            self.assertFalse(ContentFactory(self.store, self.submit).tick())
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(len(self.store.list()), 1)

    def test_response_lost_after_create_is_reconciled_without_another_job(self):
        batch = self.batch()
        def lost(*args):
            self.submit(*args)
            raise TimeoutError('Response lost')
        self.factory.submit_job = lost
        self.assertFalse(self.factory.tick())
        item = self.factory.get_batch(batch['id'])['items'][0]
        self.assertIsNotNone(item['job_id'])
        self.assertEqual(item['state'], 'queued')
        self.assertFalse(self.factory.tick())
        self.assertEqual(len(self.store.list()), 1)

    def test_availability_validation_is_atomic_and_replay_does_not_require_new_availability(self):
        def unavailable(request):
            raise ValueError('Voice not available')
        self.factory.validate_submission = unavailable
        with self.assertRaises(ValueError):
            self.batch()
        self.assertEqual(self.factory.list_batches()['items'], [])
        self.factory.validate_submission = None
        batch = self.batch()
        self.factory.validate_submission = unavailable
        self.assertEqual(self.batch()['id'], batch['id'])

    def test_old_approval_stays_pinned_after_a_new_verified_export(self):
        job, video = self.verified_job()
        version = self.factory.get_video_version(job['id'])
        self.factory.approve(job['id'], version['id'], version['sha256'])
        newer = video.with_name(video.stem + '-2.mp4')
        newer.write_bytes(b'fixture-second-video')
        asset = {'path': str(newer.resolve()), 'sha256': digest(newer)}
        with self.store.db() as db:
            for stage, value in [('render', {'video': str(newer), 'assets': [asset]}),
                                 ('verify', {'verified': True, 'duration_seconds': 30, 'assets': [asset]})]:
                db.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?', (json.dumps(value), job['id'], stage))
        self.assertEqual(self.factory.get_video_version(job['id'])['path'], str(newer.resolve()))
        self.assertEqual(self.factory.approved_version(job['id'])['path'], str(video.resolve()))
        captions = Path(job['output']) / 'subtitles.srt'
        captions.write_text('Captions for new render', encoding='utf8')
        with self.store.db() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (job['id'], 'subtitles', json.dumps({
                'assets': [{'path': str(captions), 'sha256': digest(captions)}]})))
        with self.factory.pack(job['id'], version['id']) as packed, zipfile.ZipFile(packed) as archive:
            self.assertEqual(archive.read(video.name), b'fixture-verified-video')
            self.assertNotIn(newer.name, archive.namelist())
            self.assertNotIn(captions.name, archive.namelist())
            self.assertEqual(json.loads(archive.read('video-metadata.json'))['captions']['status'], 'unavailable_for_older_version')

    def test_pack_only_reads_owned_attested_captions_and_reports_changed_assets(self):
        job, _ = self.verified_job()
        root = Path(job['output'])
        captions = root / 'subtitles.srt'
        captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello', encoding='utf8')
        secret = self.root / 'outside.srt'
        secret.write_text('outside', encoding='utf8')
        with self.store.db() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (job['id'], 'subtitles', json.dumps({'assets': [
                {'path': str(captions), 'sha256': digest(captions)},
                {'path': str(secret), 'sha256': digest(secret)}]})))
        with self.factory.pack(job['id'], include=('captions', 'sidecar')) as packed, zipfile.ZipFile(packed) as archive:
            self.assertIn('subtitles.srt', archive.namelist())
            self.assertNotIn('outside.srt', archive.namelist())
        captions.write_text('changed', encoding='utf8')
        with self.assertRaises(ValueError):
            self.factory.pack(job['id'], include=('captions',))

    def test_other_job_named_video_and_unverified_streams_are_never_exported(self):
        job, video = self.verified_job()
        unrelated = video.parent / 'video-unrelated.mp4'
        unrelated.write_bytes(b'unrelated')
        self.assertEqual(len(self.factory.videos()['items'][0]['versions']), 1)
        self.factory.video_probe = lambda path: {'streams': [{'codec_type': 'video'}], 'format': {'duration': '30'}}
        with self.store.db() as db:
            db.execute('DELETE FROM factory_video_versions')
        self.assertEqual(self.factory.videos()['total'], 0)

    def test_api_validates_origin_headers_and_pack_selectors(self):
        app = FastAPI()
        def same_origin(request):
            if request.headers.get('origin') not in (None, 'http://testserver'):
                raise HTTPException(403, 'Cross-origin writes denied')
        register_content_factory_routes(app, self.store, same_origin, lambda job: job, self.submit,
            video_probe=self.factory.video_probe)
        with TestClient(app) as client:
            body = {'style': 'case', 'input_mode': 'script', 'project': 'API',
                    'defaults': {'voice_id': 'voice', 'duration_seconds': 30}, 'items': [{'text': 'Narration'}]}
            self.assertEqual(client.post('/api/factory/batches', json=body).status_code, 422)
            self.assertEqual(client.post('/api/factory/batches', json=body,
                headers={'Idempotency-Key': 'api', 'Origin': 'https://foreign'}).status_code, 403)
            response = client.post('/api/factory/batches', json=body, headers={'Idempotency-Key': 'api'})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['items'][0]['request']['workflow_mode'], 'provided_narration')
            self.assertEqual(client.get('/api/factory/queue').status_code, 200)
            self.assertEqual(client.post('/api/factory/queue/pause', json={'paused': 'yes'}).status_code, 422)
            job, _ = self.verified_job()
            versions = client.get('/api/factory/videos').json()['items'][0]['versions']
            selected = versions[0]
            self.assertEqual(client.post(f"/api/factory/videos/{job['id']}/approve", json={
                'version_id': selected['id'], 'sha256': selected['sha256']}).status_code, 200)
            self.assertEqual(client.get(selected['url']).content, b'fixture-verified-video')
            self.assertEqual(client.get(f"/api/factory/videos/{job['id']}/pack?include=../../secret").status_code, 422)

    def test_retry_existing_job_calls_normal_retry_boundary_without_creating_a_job(self):
        batch = self.batch()
        self.factory.tick()
        item = self.factory.get_batch(batch['id'])['items'][0]
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='failed',error='Temporary error' WHERE id=?", (item['job_id'],))
        retried = []
        def retry_job(job_id, scope):
            retried.append((job_id, scope))
            with self.store.db() as db:
                db.execute("UPDATE jobs SET state='queued',error=NULL WHERE id=?", (job_id,))
        self.factory.retry_job = retry_job
        result = self.factory.item_action(item['id'], 'retry', 'bridge-now')
        self.assertEqual(retried, [(item['job_id'], 'bridge-now')])
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(len(self.store.list()), 1)

    def test_legacy_verified_job_uses_attested_default_video_without_render_video_field(self):
        job, video = self.verified_job()
        with self.store.db() as db:
            db.execute("UPDATE checkpoints SET value=? WHERE job=? AND stage='render'", (
                json.dumps({'assets': [{'path': str(video), 'sha256': digest(video)}]}), job['id']))
        self.assertEqual(self.factory.get_video_version(job['id'])['path'], str(video.resolve()))

    def test_export_rehashes_a_cached_version_even_if_size_and_mtime_are_preserved(self):
        job, video = self.verified_job()
        version = self.factory.videos()['items'][0]['versions'][0]
        self.factory.approve(job['id'], version['id'], version['sha256'])
        previous = video.stat()
        video.write_bytes(b'x' * previous.st_size)
        os.utime(video, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        with self.assertRaises(ValueError):
            self.factory.get_video_version(job['id'], version['id'])
        self.assertIsNone(self.factory.approved_version(job['id']))

    def test_meme_script_keeps_raw_source_and_explicit_input_classification(self):
        source = 'Nam: Bạn có thấy cái ví của tôi không?\nLan: Nó ở trong túi của bạn.'
        batch = self.batch(style='meme', input_mode='script', items=[{'text': source}])
        request = batch['items'][0]['request']
        self.assertEqual(request['idea'], source)
        self.assertEqual(request['workflow_mode'], 'meme')
        self.assertEqual(request['meme_input_mode'], 'script')
        self.assertEqual(request['meme_engine'], 'hyperframes')

    def test_research_case_style_remains_metadata_and_uses_normal_provider_validation(self):
        batch = self.batch(style='case', input_mode='idea', items=[{'text': 'A factual case',
            'overrides': {'text_provider': 'gemini', 'image_provider': 'comfy'}}])
        request = batch['items'][0]['request']
        self.assertEqual(request['workflow_mode'], 'research')
        self.assertNotIn('style', request)
        self.assertEqual(request['text_provider'], 'gemini')
        self.assertEqual(request['image_provider'], 'comfy')

    def test_explicit_retry_can_reauthorize_an_unlinked_item_to_a_new_bridge(self):
        batch = self.batch()
        first = batch['items'][0]
        with self.store.db() as db:
            db.execute("UPDATE factory_items SET state='failed',message='Unknown connector bridge' WHERE id=?", (first['id'],))
        self.factory.item_action(first['id'], 'retry', 'new-bridge')
        self.factory.tick()
        self.assertEqual(self.calls[0][2], 'new-bridge')
        self.assertEqual(self.calls[0][1], first['idempotency_key'])
        self.assertEqual(self.calls[0][0], first['request'])

    def test_historical_filename_and_old_inspection_cache_do_not_prove_verification(self):
        job, video = self.verified_job()
        unrelated = video.with_name(video.stem + '-99.mp4')
        unrelated.write_bytes(b'never-verified-historical-export')
        stat = unrelated.stat()
        checksum = digest(unrelated)
        import hashlib
        version_id = hashlib.sha256((str(unrelated.resolve()) + '\0' + checksum).encode()).hexdigest()[:32]
        with self.store.db() as db:
            db.execute('INSERT INTO factory_video_versions VALUES(?,?,?,?,?,?,?,?,?)', (
                job['id'], version_id, str(unrelated.resolve()), checksum, 30,
                stat.st_size, stat.st_mtime_ns, stat.st_mtime, stat.st_mtime))
        versions = self.factory.videos()['items'][0]['versions']
        self.assertEqual([version['path'] for version in versions], [str(video.resolve())])
        with self.assertRaises(ValueError):
            self.factory.approve(job['id'], version_id, checksum)

    def test_remember_verified_preserves_attested_history_across_restart_and_rerender(self):
        job, video = self.verified_job()
        self.factory.remember_verified(job['id'])
        newer = video.with_name(video.stem + '-2.mp4')
        newer.write_bytes(b'next-verified-render')
        asset = {'path': str(newer.resolve()), 'sha256': digest(newer)}
        with self.store.db() as db:
            for stage, value in [('render', {'video': str(newer), 'assets': [asset]}),
                                 ('verify', {'verified': True, 'assets': [asset]})]:
                db.execute('UPDATE checkpoints SET value=? WHERE job=? AND stage=?',
                           (json.dumps(value), job['id'], stage))
        restored = ContentFactory(self.store, self.submit, video_probe=self.factory.video_probe)
        self.assertEqual({version['path'] for version in restored.videos()['items'][0]['versions']},
                         {str(video.resolve()), str(newer.resolve())})

    def test_cancelled_checkpoint_retry_explicitly_requests_continuation(self):
        batch = self.batch()
        self.factory.tick()
        item = self.factory.get_batch(batch['id'])['items'][0]
        self.factory.item_action(item['id'], 'cancel')
        calls = []
        def retry(job_id, scope, resume_cancelled=False):
            calls.append((job_id, scope, resume_cancelled))
            with self.store.db() as db:
                db.execute("UPDATE jobs SET state='queued',cancel=0 WHERE id=?", (job_id,))
        self.factory.retry_job = retry
        result = self.factory.item_action(item['id'], 'retry', 'current-bridge')
        self.assertEqual(calls, [(item['job_id'], 'current-bridge', True)])
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(len(self.store.list()), 1)


if __name__ == '__main__':
    unittest.main()
