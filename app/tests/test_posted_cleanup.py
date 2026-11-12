import json,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from videostudio.core import Store
from videostudio.exchanges import Exchanges
from videostudio.media import asset
from videostudio.output_layout import final_video_path
from videostudio.posted_cleanup import PostedCleanup


class PostedCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'jobs.sqlite3',self.root/'videos')
        self.exchanges=Exchanges(self.store)
        self.service=PostedCleanup(self.store)

    def tearDown(self):self.tmp.cleanup()

    def job(self,state='completed',project='Project'):
        job,_=self.store.create(dict(idea='Private full narration',voice_id='voice',duration_seconds=30,project=project),str(time.time_ns()))
        video=final_video_path(job);video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'video')
        video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\nHello\n')
        (Path(job['output'])/'private.json').write_text('private job content')
        with self.store.db() as db:
            db.execute('UPDATE jobs SET state=? WHERE id=?',(state,job['id']))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'render',json.dumps({'video':str(video),'assets':[asset(video)]})))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'verify',json.dumps({'verified':True})))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'speech',json.dumps({'utterances':[{'narration':'one two three four five six seven eight nine ten','duration':2}],'voice_id':'voice'})))
        return self.store.get(job['id']),video

    def body(self,**changes):
        result=dict(confirm=True,title='Posted title',platform='youtube',channel_name='My channel',post_url='https://www.youtube.com/watch?v=fixture',published_at=datetime.now(timezone.utc).isoformat())
        result.update(changes);return result

    def test_cleanup_preserves_log_and_other_job_but_removes_job_media_and_heavy_rows(self):
        job,video=self.job();other,other_video=self.job()
        result=self.service.posted_cleanup(job['id'],self.body(),'cleanup-one')
        self.assertEqual(result['entry']['cleanup_state'],'completed')
        self.assertFalse(video.exists());self.assertFalse(video.with_suffix('.srt').exists())
        self.assertFalse(Path(job['output']).exists());self.assertTrue(other_video.exists())
        with self.assertRaises(KeyError):self.store.get(job['id'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM checkpoints WHERE job=?',(job['id'],)).fetchone()[0],0)
        restored=PostedCleanup(self.store)
        self.assertEqual(restored.history(q='posted')['items'][0]['job_id'],job['id'])
        self.assertNotIn('Private full narration',json.dumps(result))
        self.assertNotIn(str(video),json.dumps(result))

    def test_lost_reply_repeat_is_idempotent_after_job_is_gone(self):
        job,_=self.job();body=self.body()
        with self.store.db() as db:source_idem=db.execute('SELECT idem FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
        first=self.service.posted_cleanup(job['id'],body,'one')
        again=self.service.posted_cleanup(job['id'],body,'one')
        self.assertEqual(first['entry']['id'],again['entry']['id'])
        self.assertEqual(self.service.history()['total'],1)
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(title='Different'),'one')
        with self.assertRaises(ValueError):self.store.create(job['request'],source_idem)

    def test_blocks_running_and_live_schedule_even_if_user_confirms(self):
        job,video=self.job('running')
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(video.exists());self.assertEqual(self.service.history()['total'],0)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='completed' WHERE id=?",(job['id'],))
            db.execute('CREATE TABLE publishing_schedules(id TEXT,job_id TEXT,state TEXT)')
            db.execute("INSERT INTO publishing_schedules VALUES('schedule',?,'needs_attention')",(job['id'],))
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(video.exists())

    def test_confirmation_and_urls_are_validated_before_any_cleanup(self):
        job,video=self.job()
        for changes in ({'confirm':False},{'post_url':'javascript:alert(1)'},{'post_url':'https://user:secret@example.com/x'},{'published_at':'2026-11-12T08:00:00'}):
            with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(**changes),'one')
        self.assertTrue(video.exists())

    def test_shared_asset_reference_blocks_cleanup(self):
        job,video=self.job();other,_=self.job()
        with self.store.db() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(other['id'],'images',json.dumps({'assets':[asset(Path(job['output'])/'private.json')]})))
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(video.exists());self.assertEqual(self.service.history()['total'],0)

    def test_shared_checks_resolve_repeated_other_file_once_per_validation_pass(self):
        job,_=self.job();other,_=self.job()
        candidate=Path(other['output'])/'keep.dat';candidate.write_text('shared checks only')
        with self.store.db() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(other['id'],'images',json.dumps({'assets':[{'path':str(candidate)}]*100})))
        original=Path.resolve;calls=[]
        def resolve(path,*args,**kwargs):
            if path==candidate:calls.append(path)
            return original(path,*args,**kwargs)
        with patch.object(Path,'resolve',autospec=True,side_effect=resolve):
            self.service.posted_cleanup(job['id'],self.body(),'deduplicated-check')
        self.assertLessEqual(len(calls),4)
        self.assertTrue(candidate.exists())

    def test_pending_locked_file_can_be_cleaned_after_restart_without_job(self):
        job,video=self.job()
        with patch.object(self.service,'_purge_path',side_effect=PermissionError('busy')):
            result=self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(result['cleanup_pending']);self.assertFalse(video.exists())
        restored=PostedCleanup(self.store)
        result=restored.retry_cleanup(result['entry']['id'])
        self.assertFalse(result['cleanup_pending'])
        self.assertFalse(list(self.store.outputs.glob('.deleted-*')))

    def test_job_timing_survives_cleanup_without_retaining_narration(self):
        from videostudio.voice_timing import reading_profiles
        job,_=self.job()
        self.service.posted_cleanup(job['id'],self.body(),'one')
        profile=reading_profiles(self.store,[{'id':'voice'}])['voice']
        self.assertEqual(profile['syllables_per_second'],5)
        self.assertEqual(profile['source'],'verified_jobs')

    def test_uncommitted_filesystem_move_is_restored_on_recovery(self):
        job,video=self.job()
        journal=self.service.journal_root/'crash.json'
        quarantine=self.store.outputs/('.deleted-'+'a'*32)
        self.service.journal_root.mkdir(parents=True,exist_ok=True)
        journal.write_text(json.dumps({'entry_id':'not-committed','moves':[[str(video),str(quarantine)]]}))
        video.rename(quarantine)
        self.service.recover()
        self.assertTrue(video.exists());self.assertFalse(quarantine.exists())


    def editor_fixtures(self,job):
        with self.store.db() as db:
            db.executescript("CREATE TABLE edit_plan_heads(job TEXT PRIMARY KEY,revision INTEGER,value TEXT); CREATE TABLE edit_plan_assets(job TEXT,id TEXT,value TEXT); CREATE TABLE scene_editor_heads(job TEXT PRIMARY KEY,mode TEXT,version INTEGER); CREATE TABLE scene_exports(child TEXT PRIMARY KEY,parent TEXT); CREATE TABLE edit_plan_exports(child TEXT PRIMARY KEY,parent TEXT)")
            db.execute('INSERT INTO edit_plan_heads VALUES(?,0,?)',(job['id'],json.dumps({'clips':[{'text':'private editorial content'}]})))
        folder=self.root/'editor-imports'/job['id'];folder.mkdir(parents=True)
        imported=folder/'media.mp4';imported.write_bytes(b'private imported media')
        with self.store.db() as db:db.execute('INSERT INTO edit_plan_assets VALUES(?,?,?)',(job['id'],'import-one',json.dumps({'path':str(imported)})))
        return imported

    def test_owned_external_editor_media_and_metadata_are_removed(self):
        job,_=self.job();imported=self.editor_fixtures(job)
        result=self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertFalse(imported.exists())
        self.assertEqual(result['entry']['cleanup_state'],'completed')
        with self.store.db() as db:
            for table in ('edit_plan_heads','edit_plan_assets'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table+' WHERE job=?',(job['id'],)).fetchone()[0],0)

    def test_shared_external_import_blocks_cleanup(self):
        job,video=self.job();other,_=self.job();imported=self.editor_fixtures(job)
        with self.store.db() as db:db.execute('INSERT INTO edit_plan_assets VALUES(?,?,?)',(other['id'],'shared',json.dumps({'path':str(imported)})))
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(imported.exists());self.assertTrue(video.exists())

    def test_completed_task_owned_external_media_are_removed(self):
        job,_=self.job();task='a'*32
        with self.store.db() as db:
            db.execute('CREATE TABLE scene_image_tasks(id TEXT PRIMARY KEY,job TEXT,state TEXT,result TEXT)')
            db.execute('INSERT INTO scene_image_tasks VALUES(?,?,?,NULL)',(task,job['id'],'completed'))
        files=[self.root/'scene-image-candidates'/(task+'.png'),self.root/'chatgpt-images'/(task+'.png'),self.root/'chatgpt-images'/'comfy-tasks'/task/'request.json']
        for file in files:file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'private')
        with patch('videostudio.posted_cleanup.DATA_ROOT',self.root):
            self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(all(not file.exists() for file in files))

    def test_uncertain_image_task_blocks_cleanup(self):
        job,video=self.job()
        with self.store.db() as db:
            db.execute('CREATE TABLE scene_image_tasks(id TEXT PRIMARY KEY,job TEXT,state TEXT,result TEXT)')
            db.execute('INSERT INTO scene_image_tasks VALUES(?,?,?,NULL)',('a'*32,job['id'],'uncertain'))
        with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(video.exists())

    def test_cleaned_child_no_longer_blocks_parent_cleanup(self):
        parent,_=self.job();child,_=self.job();self.editor_fixtures(parent)
        with self.store.db() as db:db.execute('INSERT INTO scene_exports VALUES(?,?)',(child['id'],parent['id']))
        self.service.posted_cleanup(child['id'],self.body(),'child')
        self.service.posted_cleanup(parent['id'],self.body(),'parent')
        self.assertEqual(self.service.history()['total'],2)

    def test_edit_plan_child_blocks_parent_cleanup(self):
        parent,video=self.job();child,_=self.job();self.editor_fixtures(parent)
        with self.store.db() as db:db.execute('INSERT INTO edit_plan_exports VALUES(?,?)',(child['id'],parent['id']))
        with self.assertRaises(ValueError):self.service.posted_cleanup(parent['id'],self.body(),'parent')
        self.assertTrue(video.exists())

    def test_database_fault_restores_outputs_and_external_media(self):
        job,video=self.job();imported=self.editor_fixtures(job)
        with patch.object(self.service,'_purge_job',side_effect=RuntimeError('database fault')):
            with self.assertRaises(RuntimeError):self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertTrue(imported.exists());self.assertTrue(video.exists());self.assertTrue(Path(job['output']).exists())
        self.assertEqual(self.service.history()['total'],0)

    def test_recovery_waits_for_active_cleanup_transaction(self):
        import threading
        job,video=self.job();identifier='active';quarantine=self.store.outputs/('.deleted-'+'b'*32)
        journal=self.service._write_journal(identifier,[(video,quarantine)])
        started=threading.Event();done=threading.Event();errors=[]
        def recover():
            started.set()
            try:self.service.recover()
            except BaseException as error:errors.append(error)
            finally:done.set()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');video.rename(quarantine)
            thread=threading.Thread(target=recover);thread.start();self.assertTrue(started.wait(1))
            blocked=not done.wait(.15)
        thread.join(3)
        self.assertTrue(blocked,'recovery must wait for the active SQLite write transaction')
        self.assertFalse(errors);self.assertTrue(video.exists());self.assertFalse(journal.exists())


    def test_external_moves_restore_after_uncommitted_crash(self):
        job,_=self.job();imported=self.editor_fixtures(job);folder=imported.parent
        quarantine=self.root/('.deleted-'+'c'*32)
        self.service._write_journal('crash-external',[(folder,quarantine)],job['id'],[])
        folder.rename(quarantine);self.service.recover()
        self.assertTrue(imported.exists());self.assertFalse(quarantine.exists())

    def test_failed_rollback_cannot_be_bypassed_by_second_cleanup(self):
        job,video=self.job();imported=self.editor_fixtures(job);folder=imported.parent
        rename=Path.rename
        def locked_restore(source,target):
            if source.name.startswith('.deleted-') and Path(target)==folder:raise PermissionError('still locked')
            return rename(source,target)
        with patch.object(Path,'rename',locked_restore):
            with patch.object(self.service,'_purge_job',side_effect=RuntimeError('database fault')):
                with self.assertRaises(RuntimeError):self.service.posted_cleanup(job['id'],self.body(),'first')
            with self.assertLogs('videostudio.posted_cleanup',level='ERROR'):
                with self.assertRaises(ValueError):self.service.posted_cleanup(job['id'],self.body(),'second')
        self.assertTrue(video.exists());self.assertEqual(self.service.history()['total'],0)
        self.service.recover();self.assertTrue(imported.exists())

    def test_external_recovery_manifest_cannot_move_shared_voice_resources(self):
        job,_=self.job();voice=self.root/'Voices'/'voice.wav';voice.parent.mkdir();voice.write_bytes(b'voice')
        quarantine=self.root/('.deleted-'+'d'*32);quarantine.write_bytes(b'quarantined')
        self.service._write_journal('bad-external',[(voice,quarantine)],job['id'],[])
        with self.assertLogs('videostudio.posted_cleanup',level='ERROR'):self.service.recover()
        self.assertEqual(voice.read_bytes(),b'voice');self.assertTrue(quarantine.exists())


    def test_bridge_root_and_smoke_survive_without_private_job_exchanges(self):
        job,_=self.job();scope='root-bridge'
        with self.store.db() as db:
            db.execute('INSERT INTO connector_scopes VALUES(?,?,?)',(scope,job['id'],time.time()))
            for identifier in ('smoke','private-script'):
                db.execute('INSERT INTO connector_exchanges(id,scope,request_key,prompt,response,created) VALUES(?,?,?,?,?,?)',(identifier,scope,identifier,'private prompt' if identifier=='private-script' else 'connection test','private response',time.time()))
            db.execute('INSERT INTO connector_smokes VALUES(?,?,?)',(scope,'smoke',time.time()))
        self.service.posted_cleanup(job['id'],self.body(),'one')
        self.assertEqual(self.exchanges.bridge_root(scope),scope)
        with self.store.db() as db:
            self.assertIsNone(db.execute('SELECT job FROM connector_scopes WHERE id=?',(scope,)).fetchone()[0])
            self.assertEqual([row[0] for row in db.execute('SELECT id FROM connector_exchanges WHERE scope=?',(scope,))],['smoke'])


    def test_busy_cleanup_does_not_starve_other_pending_entries(self):
        first,_=self.job();second,_=self.job()
        with patch.object(self.service,'_purge_path',side_effect=PermissionError('busy')):
            one=self.service.posted_cleanup(first['id'],self.body(),'first')
            two=self.service.posted_cleanup(second['id'],self.body(),'second')
        with self.store.db() as db:
            db.execute('UPDATE publication_history SET next_at=0')
            first_paths={row[0] for row in db.execute('SELECT path FROM publication_cleanup_files WHERE entry_id=?',(one['entry']['id'],))}
        purge=self.service._purge_path
        def busy_first(path):
            if str(path) in first_paths:raise PermissionError('busy')
            return purge(path)
        with patch.object(self.service,'_purge_path',busy_first):
            self.assertTrue(self.service.tick());self.assertTrue(self.service.tick())
        self.assertEqual(self.service.entry(two['entry']['id'])['cleanup_state'],'completed')
        self.assertFalse(self.service.retry_cleanup(one['entry']['id'])['cleanup_pending'])


if __name__=='__main__':unittest.main()
