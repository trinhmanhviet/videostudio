import json
import tempfile
import unittest
import wave
from unittest.mock import patch
from pathlib import Path

from videostudio.core import Store
from videostudio.voice_timing import reading_profiles


class VoiceTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'jobs.sqlite3',self.root/'out')
        self.number=0

    def tearDown(self):
        self.tmp.cleanup()

    def job(self,voice,words,seconds,speed=1,verified=True,state='completed',**speech_extra):
        self.number+=1
        job,_=self.store.create(dict(idea='Fixture narration',voice_id=voice,duration_seconds=60),str(self.number))
        speech=dict(utterances=[{'narration':' '.join(['tiếng']*words),'duration':seconds}],speed=speed,**speech_extra)
        with self.store.db() as db:
            db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(state,self.number,job['id']))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'speech',json.dumps(speech)))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],'verify',json.dumps({'verified':verified})))
        return job

    def test_each_voice_uses_its_own_measured_rate(self):
        self.job('fast',60,10)
        self.job('slow',20,10)
        profiles=reading_profiles(self.store,[{'id':'fast'},{'id':'slow'},{'id':'new'}])
        self.assertEqual(profiles['fast']['syllables_per_second'],6)
        self.assertEqual(profiles['slow']['syllables_per_second'],2)
        self.assertEqual(profiles['new'],dict(syllables_per_second=4.2,samples=0,source='default',speed=1))

    def test_speed_is_normalized_before_median_and_only_recent_eight_count(self):
        self.job('voice',100,10)
        for _ in range(8):self.job('voice',46,10,speed=1.15)
        profile=reading_profiles(self.store,[{'id':'voice'}])['voice']
        self.assertEqual(profile['syllables_per_second'],4)
        self.assertEqual(profile['samples'],8)

    def test_unverified_failed_and_malformed_durations_do_not_calibrate(self):
        self.job('voice',100,10,verified=False)
        self.job('voice',100,10,state='failed')
        self.job('voice',100,-1)
        self.job('voice',100,1)
        self.job('voice',100,10,speed=True)
        self.assertEqual(reading_profiles(self.store,[{'id':'voice'}])['voice']['source'],'default')

    def preview(self,text,seconds,**request):
        folder=self.root/'preview';folder.mkdir(exist_ok=True)
        path=folder/'preview.wav'
        with wave.open(str(path),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
            wav.writeframes(b'\0\0'*int(seconds*8000))
        (folder/'request.json').write_text(json.dumps(dict(text=text,**request)),encoding='utf8')
        return str(path)

    def test_clone_preview_requires_matching_reference_hash_and_known_text(self):
        sample=self.preview('một hai ba bốn năm sáu bảy tám chín mười',2.5,reference={'sha256':'current-hash'})
        voice={'id':'clone:a','kind':'clone','sha256':'current-hash','sample_path':sample}
        profile=reading_profiles(self.store,[voice])[voice['id']]
        self.assertEqual(profile['source'],'preview')
        self.assertEqual(profile['syllables_per_second'],4)
        voice['sha256']='different-reference'
        self.assertEqual(reading_profiles(self.store,[voice])[voice['id']]['source'],'default')

    def test_preset_preview_matches_voice_id_and_jobs_take_precedence(self):
        sample=self.preview('một hai ba bốn năm sáu bảy tám chín mười',2,voice_id='preset')
        voice={'id':'preset','kind':'preset','sample_path':sample}
        self.assertEqual(reading_profiles(self.store,[voice])['preset']['syllables_per_second'],5)
        self.job('preset',30,10)
        self.assertEqual(reading_profiles(self.store,[voice])['preset']['syllables_per_second'],3)
        voice['id']='other'
        self.assertEqual(reading_profiles(self.store,[voice])['other']['source'],'default')

    def test_explicit_clone_identity_mismatch_is_not_used(self):
        self.job('clone:a',30,10,voice_sha256='old-reference')
        voice={'id':'clone:a','kind':'clone','sha256':'new-reference'}
        self.assertEqual(reading_profiles(self.store,[voice])['clone:a']['source'],'default')

    def test_clone_job_without_reference_identity_uses_correlated_preview(self):
        self.job('clone:a',100,10)
        sample=self.preview('một hai ba bốn năm sáu bảy tám chín mười',5,reference={'sha256':'current'})
        voice={'id':'clone:a','kind':'clone','sha256':'current','sample_path':sample}
        profile=reading_profiles(self.store,[voice])['clone:a']
        self.assertEqual(profile['source'],'preview')
        self.assertEqual(profile['syllables_per_second'],2)

    def test_new_clone_checkpoint_with_matching_identity_self_calibrates(self):
        self.job('clone:a',50,10,speed=1.25,voice_id='clone:a',voice_sha256='current')
        voice={'id':'clone:a','kind':'clone','sha256':'current'}
        profile=reading_profiles(self.store,[voice])['clone:a']
        self.assertEqual(profile['source'],'verified_jobs')
        self.assertEqual(profile['syllables_per_second'],4)
        self.assertEqual(profile['samples'],1)

    def test_conflicting_checkpoint_voice_id_is_ignored_even_when_hash_matches(self):
        self.job('clone:a',50,10,voice_id='clone:b',voice_sha256='current')
        voice={'id':'clone:a','kind':'clone','sha256':'current'}
        self.assertEqual(reading_profiles(self.store,[voice])['clone:a']['source'],'default')

    def test_voice_api_exposes_estimate_metadata_without_private_paths(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        class Pipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        self.job('voice',40,10)
        catalog={'voices':[{'id':'voice','name':'Voice','kind':'preset','reference_path':'private-reference.wav','sha256':'private-sha'}],
                 'unmapped_sample_files':[],'complete':True,'warnings':[]}
        with patch('videostudio.api.Voices.catalog',return_value=catalog):
            with TestClient(create_app(self.store,Pipeline(),False)) as client:
                response=client.get('/api/voices')
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body['voices'][0]['reading_profile']['syllables_per_second'],4)
        self.assertEqual(body['voices'][0]['reading_profile']['source'],'verified_jobs')
        self.assertNotIn('private-reference',response.text)
        self.assertNotIn('private-sha',response.text)


if __name__=='__main__':unittest.main()
