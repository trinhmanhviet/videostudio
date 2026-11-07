import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

ROOT = Path(__file__).resolve().parents[1]


class ComedyStoryTests(unittest.TestCase):
    def setUp(self):
        roster=patch('videostudio.character_store.load_roster',return_value=[])
        self.roster_mock=roster.start();self.addCleanup(roster.stop)
    def test_unified_story_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.comedy_story'))

    def fixture(self, folder):
        from videostudio.core import Store
        sample=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
        request={'idea':'Bạn tôi khoe sách tự viết, vợ anh ấy chỉ ra anh chỉ gõ tên. Giữ nguyên câu chốt này.',
                 'voice_id':'test','duration_seconds':20,'workflow_mode':'meme','meme_engine':'hyperframes'}
        store=Store(Path(folder)/'db',Path(folder)/'videos');job,_=store.create(request,'story')
        story={'input_kind':'story','logline':'Tự nhận công viết sách của vợ','theme':'Sĩ diện',
               'central_error':'Nhận công người khác','conflict':'Vợ phát hiện','structure':'reversal',
               'techniques':['t15'],'climax_type':'dialogue_reversal','ending':'Tôi chỉ viết tên.',
               'characters':{cid:{'motivation':'Được công nhận','flaw':'Sĩ diện','belief':'Tôi luôn đúng',
                                  'reasoning':'Biện hộ','dialogue':'Ngắn gọn','reaction':'Chữa thẹn','relations':{}} for cid in sample['cast']},
               'props':{},'callbacks':{'book':{'setup_event':'e1','payoff_event':'e2','required':True}},
               'events':[{'id':'e1','summary':'Khoe sách','causes':[],'role':'setup'},
                         {'id':'e2','summary':'Vợ bóc mẽ','causes':['e1'],'role':'ending'}],
               'source_contract':{'facts':['Bạn tôi khoe sách','Vợ anh chỉ ra anh chỉ gõ tên'],'ending':'Tôi chỉ viết tên.'},
               'candidates':[],'selected_candidate':None}
        calls=[]
        def answer(prompt, check):
            calls.append(prompt)
            if '[COMEDY_ARCHITECT' in prompt:return copy.deepcopy(story)
            if '[COMEDY_OUTLINE' in prompt:return {k:copy.deepcopy(sample[k]) for k in ('title','payoff','cast','scenes')}
            if '[COMEDY_WRITE' in prompt:
                rows=[dict(copy.deepcopy(b),event_id='e1' if i<4 else 'e2') for i,b in enumerate(sample['beats'])]
                rows[0]['callbacks']={'book':'setup'};rows[-1]['callbacks']={'book':'payoff'}
                return {'part':1,'beats':rows,'summary':'Đã khoe và bị vợ bóc mẽ','prop_updates':[]}
            if '[COMEDY_CRITIC' in prompt:
                return {'scores':{k:8 for k in ('causal_logic','setup_payoff','novelty','voice','ending','renderability')},
                        'issues':[],'fidelity':'preserved','ending_preserved':True}
            self.fail('Unknown internal phase')
        pipeline=SimpleNamespace(store=store,llm_json=Mock(side_effect=answer))
        return pipeline,job,calls,answer

    def test_story_is_reviewed_and_resume_does_not_call_ai_again(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,_=self.fixture(folder)
            result=write_story(p,j,lambda:None)
            self.assertEqual(result['comedy']['status'],'approved')
            self.assertEqual(result['comedy']['continuity']['callbacks']['book'],'paid')
            self.assertEqual(len(result['comedy']['narrative_map']),8)
            self.assertEqual(result,write_story(p,j,lambda:None));self.assertEqual(len(calls),4)
            self.assertTrue(all(c['voice']=='test' for c in result['animation_script']['cast'].values()))

    def test_roster_snapshot_does_not_change_a_resumed_story(self):
        from videostudio.comedy_story import write_story
        self.roster_mock.return_value=[{'id':'toi','name':'Tôi','aliases':[],'costume':'ao_phong_xanh','acc':[],'default_face':'noi'}]
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,_=self.fixture(folder);first=write_story(p,j,lambda:None);count=len(calls)
            self.roster_mock.return_value=[{'id':'toi','name':'Khác','aliases':[],'costume':'vest_den','acc':[]}]
            self.assertEqual(first,write_story(p,j,lambda:None));self.assertEqual(len(calls),count)

    def test_semantic_plan_objects_keep_their_content_instead_of_causing_retry_loops(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,answer=self.fixture(folder)
            def structured(prompt,check):
                raw=answer(prompt,check)
                if '[COMEDY_ARCHITECT' in prompt:
                    raw['structure']={'kind':'reversal','stages':['setup','payoff']}
                    raw['ending']={'line':'Tôi chỉ viết tên.','type':'dialogue'}
                return raw
            p.llm_json.side_effect=structured;result=write_story(p,j,lambda:None)
            self.assertIn('reversal',result['comedy']['story']['structure'])
            self.assertIn('Tôi chỉ viết tên.',result['comedy']['story']['ending'])
            self.assertEqual(sum('[COMEDY_ARCHITECT' in c for c in calls),1)

    def test_a_saved_reply_rejected_by_old_validator_is_reused_without_resubmission(self):
        from videostudio.comedy_story import _step,_hash,_prose,VERSION
        from videostudio.core import digest
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,_,_=self.fixture(folder);target=Path(j['output']);prompt='cached semantic plan'
            identity=_hash({'version':VERSION,'prompt':prompt})
            raw=target/f'architect-{identity[:16]}-raw-0.json'
            raw.write_text(json.dumps({'kind':'reversal'}),encoding='utf8')
            raw.with_suffix('.rejected.json').write_text(json.dumps({'sha256':digest(raw),'error':'Old string-only rule'}),encoding='utf8')
            p.llm_json.side_effect=AssertionError('Must reuse the real saved reply')
            result=_step(p,j,lambda:None,target,'architect',prompt,lambda value:_prose(value,'structure'))
            self.assertIn('reversal',result);p.llm_json.assert_not_called()

    def test_retry_of_exhausted_structural_replies_sends_actual_previous_json_to_repair(self):
        from videostudio.comedy_story import _step,_hash,_text,VERSION,VALIDATOR_VERSION
        from videostudio.core import digest
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,_,_=self.fixture(folder);target=Path(j['output']);prompt='repair bad structure'
            identity=_hash({'version':VERSION,'prompt':prompt})
            for i in range(3):
                raw=target/f'writer-{identity[:16]}-raw-{i}.json';raw.write_text(json.dumps({'wrong':'keep this actual content'}),encoding='utf8')
                raw.with_suffix('.rejected.json').write_text(json.dumps({'sha256':digest(raw),'error':'text missing','validator_version':VALIDATOR_VERSION}),encoding='utf8')
            p.llm_json=Mock(return_value={'text':'fixed'})
            result=_step(p,j,lambda:None,target,'writer',prompt,lambda r:_text(r.get('text'),'text'))
            self.assertEqual(result,'fixed');self.assertEqual(p.llm_json.call_count,1)
            self.assertIn('keep this actual content',p.llm_json.call_args.args[0])

    def test_timeout_in_critic_keeps_written_story(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,answer=self.fixture(folder);once=False
            def flaky(prompt,check):
                nonlocal once
                if '[COMEDY_CRITIC' in prompt and not once:once=True;raise TimeoutError('offline')
                return answer(prompt,check)
            p.llm_json.side_effect=flaky
            with self.assertRaises(TimeoutError):write_story(p,j,lambda:None)
            result=write_story(p,j,lambda:None)
            self.assertEqual(result['comedy']['status'],'approved')
            self.assertEqual(sum('[COMEDY_WRITE' in c for c in calls),1)

    def test_single_beat_repair_does_not_rewrite_other_lines(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,answer=self.fixture(folder);rounds=0
            sample=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
            def needs_repair(prompt,check):
                nonlocal rounds
                if '[COMEDY_CRITIC' in prompt:
                    reply=answer(prompt,check);rounds+=1
                    if rounds==1:reply['issues']=[{'severity':'major','description':'Câu đầu dài','event_ids':['e1'],'beat_indices':[0]}]
                    return reply
                if '[COMEDY_REPAIR' in prompt:
                    calls.append(prompt)
                    return {'replacements':[{'index':0,'beat':dict(sample['beats'][0],text='Bạn tôi khoe sách.')} ]}
                reply=answer(prompt,check)
                if '[COMEDY_ARCHITECT' in prompt:reply['props']={'book':{'owner':'toi','location':'hand','condition':'closed'}}
                if '[COMEDY_OUTLINE' in prompt:
                    reply['props']={'book':{'asset':None,'label':'Sách'}}
                    reply['initial_props']={'book':{'owner':'toi','location':'hand','condition':'closed'}}
                if '[COMEDY_WRITE' in prompt:reply['beats'][0]['props']={'book':{'placement':'held','owner':'toi'}}
                return reply
            p.llm_json.side_effect=needs_repair;result=write_story(p,j,lambda:None)
            self.assertEqual(result['animation_script']['beats'][0]['text'],'Bạn tôi khoe sách.')
            self.assertEqual(result['animation_script']['beats'][1]['text'],sample['beats'][1]['text'])
            self.assertEqual(result['animation_script']['beats'][0]['props']['book']['owner'],'toi')
            self.assertEqual(sum('[COMEDY_WRITE' in c for c in calls),1)

    def test_legacy_prefix_continues_only_missing_part_and_runs_whole_critic(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            # 100 s at the uncalibrated 4.6 syllables/s budgets ~135 words per part, which the 76-word fixture part still meets.
            p,j,calls,answer=self.fixture(folder);j['request']['duration_seconds']=100
            sample=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
            prefix={'meta':{k:sample[k] for k in ('title','payoff','cast','scenes')},'total_parts':3,
                    'outline_parts':[{'summary':f'Sự kiện {i}','ending':'Câu chốt'} for i in range(3)],
                    'parts':[{'beats':sample['beats'],'summary':f'Đã xong {i}'} for i in range(2)]}
            def continuation(prompt,check):
                if '[COMEDY_WRITE' in prompt:
                    self.assertIn('part=3/3',prompt);calls.append(prompt)
                    return {'part':3,'beats':[dict(b,event_id='legacy_3') for b in sample['beats']],
                            'summary':'Đã kết thúc','prop_updates':[]}
                return answer(prompt,check)
            p.llm_json.side_effect=continuation
            result=write_story(p,j,lambda:None,legacy_prefix=prefix)
            self.assertEqual(len(result['animation_script']['beats']),24)
            self.assertEqual(result['animation_script']['beats'][0]['text'],sample['beats'][0]['text'])
            self.assertEqual(sum('[COMEDY_WRITE' in c for c in calls),1)
            self.assertFalse(any('[COMEDY_ARCHITECT' in c for c in calls))

    def test_unknown_prop_state_cannot_teleport_between_parts(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{'a':{}},'callbacks':{}}
        state={'completed_events':[],'callbacks':{},'summary':'','props':{'box':{'owner':'a','location':'desk','condition':'closed'}}}
        updates=[{'id':'box','event_id':'e1','beat_index':0,'before':{'owner':'a','location':'road','condition':'closed'},
                  'after':{'owner':'a','location':'hand','condition':'open'}}]
        with self.assertRaisesRegex(ValueError,'previous state'):
            _ledger(story,state,[{'id':'e1'}],[{'event_id':'e1'}],updates,'Đang mở hộp')

    def test_layout_resolves_initial_prop_state_before_writing_not_the_final_story_state(self):
        from videostudio.comedy_story import write_story
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,answer=self.fixture(folder)
            def initial_state(prompt,check):
                raw=answer(prompt,check)
                if '[COMEDY_ARCHITECT' in prompt:raw['props']={'book':{'owner':'toi','location':'hand','condition':'Đã mở ở cuối truyện'}}
                if '[COMEDY_OUTLINE' in prompt:
                    raw['props']={'book':{'asset':None,'label':'Sách'}}
                    raw['initial_props']={'book':{'owner':'toi','location':'hand','condition':'Chưa mở'}}
                if '[COMEDY_WRITE' in prompt:
                    self.assertIn('Chưa mở',prompt)
                    raw['beats'][0]['props']={'book':{'placement':'held','owner':'toi'}}
                return raw
            p.llm_json.side_effect=initial_state;result=write_story(p,j,lambda:None)
            self.assertEqual(result['comedy']['story']['props']['book']['condition'],'Chưa mở')
            self.assertEqual(result['comedy']['continuity']['props']['book']['condition'],'Chưa mở')

    def test_callback_event_coverage_alone_is_not_a_payoff_receipt(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{},'callbacks':{'key':{'setup_event':'e1','payoff_event':'e2','required':True}}}
        state={'completed_events':[],'callbacks':{'key':'pending'},'props':{},'summary':''}
        with self.assertRaises(ValueError):_ledger(story,state,[{'id':'e1'},{'id':'e2'}],[{'event_id':'e1'},{'event_id':'e2'}],[],'Xong')

    def test_explicit_setup_can_move_within_the_story_but_payoff_still_requires_it(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{},'events':[{'id':'e1'},{'id':'e2'},{'id':'e3'}],
               'callbacks':{'key':{'setup_event':'e1','payoff_event':'e3','required':True}}}
        state={'completed_events':[],'callbacks':{'key':'pending'},'props':{},'summary':''}
        rows=[{'event_id':'e1'},{'event_id':'e2','callbacks':{'key':'setup'}},{'event_id':'e3','callbacks':{'key':'payoff'}}]
        result=_ledger(story,state,story['events'],rows,[],'Có setup trước payoff')
        self.assertEqual(result['callbacks']['key'],'paid')
        self.assertEqual(result['callback_events']['key']['setup'],'e2')
        with self.assertRaises(ValueError):_ledger(story,state,story['events'],[{'event_id':'e1'},{'event_id':'e2'},{'event_id':'e3','callbacks':{'key':'payoff'}}],[],'Thiếu setup')

    def test_compiler_distinguishes_spoken_punchline_and_logical_scenery_state(self):
        from videostudio.comedy_story import _compile_rows,_ledger
        sample=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
        sample['props']={'garden':{'asset':None,'label':'Vườn rau'}}
        row=dict(sample['beats'][0],text='Rau nhà tôi trồng bằng cần câu.',punch='Rau nhà tôi trồng bằng cần câu.',event_id='e1')
        after={'owner':None,'location':'garden','condition':'Đang trồng rau'}
        updates=[{'id':'garden','event_id':'e1','beat_index':0,'after':after}]
        rows=_compile_rows([row],sample,updates)
        self.assertIsInstance(rows[0]['punch'],dict)
        self.assertEqual(rows[0]['notes'][0]['prop'],'garden')
        story={'characters':{},'callbacks':{}}
        state={'props':{'garden':dict(after,condition='Đất trống')},'callbacks':{},'completed_events':[],'summary':''}
        self.assertEqual(_ledger(story,state,[{'id':'e1'}],rows,updates,'Trồng rau')['props']['garden']['condition'],'Đang trồng rau')

    def test_visible_holder_change_requires_the_same_prop_ledger_update(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{'a':{},'b':{}},'callbacks':{}}
        state={'completed_events':[],'callbacks':{},'summary':'','props':{'book':{'owner':'a','location':'hand','condition':'closed'}},
               'visual_props':{'book':{'placement':'held','owner':'a'}}}
        rows=[{'event_id':'e1','props':{'book':{'placement':'held','owner':'b'}}}]
        with self.assertRaisesRegex(ValueError,'matching prop_update'):_ledger(story,state,[{'id':'e1'}],rows,[],'Đổi chủ')
        updates=[{'id':'book','event_id':'e1','beat_index':0,'before':state['props']['book'],
                  'after':{'owner':'b','location':'hand','condition':'closed'}}]
        result=_ledger(story,state,[{'id':'e1'}],rows,updates,'Đổi chủ')
        self.assertEqual(result['props']['book']['owner'],'b')
        after_only=[{k:v for k,v in updates[0].items() if k!='before'}]
        result=_ledger(story,state,[{'id':'e1'}],rows,after_only,'Đổi chủ')
        self.assertEqual(result['props']['book']['owner'],'b')

    def test_duration_profile_uses_only_verified_wavs_of_the_selected_voice(self):
        from videostudio.comedy_story import _speech_profile
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,_,_=self.fixture(folder)
            with p.store.db() as c:
                c.execute("UPDATE jobs SET state='completed' WHERE id=?",(j['id'],))
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],'speech',json.dumps({'utterances':[{'narration':'một hai ba bốn năm','duration':1}]})))
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],'verify',json.dumps({'verified':True})))
            measured=_speech_profile(p.store,'test',speed=1);self.assertTrue(measured['calibrated_from_verified_wav'])
            self.assertEqual(measured['syllables_per_second'],5)
            # A 1.0x job is rescaled to the meme atempo instead of mixed in raw.
            self.assertAlmostEqual(_speech_profile(p.store,'test',speed=1.15)['syllables_per_second'],5.75)
            other=_speech_profile(p.store,'other',speed=1.15)
            self.assertFalse(other['calibrated_from_verified_wav'])
            self.assertAlmostEqual(other['syllables_per_second'],4.6)
            self.assertEqual(other['speech_share'],.88)

    def test_duration_profile_measures_speech_share_of_rendered_meme_videos(self):
        from videostudio.comedy_story import _speech_profile
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,_,_=self.fixture(folder)
            with p.store.db() as c:
                c.execute("UPDATE jobs SET state='completed' WHERE id=?",(j['id'],))
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],'speech',json.dumps({'utterances':[{'narration':'một hai ba bốn năm sáu','duration':1.15}],
                          'speed':1.15,'meme_engine':'hyperframes','duration_seconds':1.25})))
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],'verify',json.dumps({'verified':True})))
            measured=_speech_profile(p.store,'test',speed=1.15)
            self.assertAlmostEqual(measured['syllables_per_second'],5.217,places=3)
            self.assertEqual(measured['speech_share'],.92)

    def test_history_context_is_compact_and_keeps_status_without_repeating_old_scripts(self):
        from videostudio.comedy_story import _history
        records=[{'job':str(i),'status':'rejected','rendered':True,'published':False,'human_feedback':None,
                  'metadata':{'idea':'old '*30000,'ending':'end '*1000,'logline':'Plot','characters':{'a':'x'*10000},'events':['x'*50000]}} for i in range(12)]
        context=_history(records)
        self.assertLess(len(json.dumps(context)),20000)
        self.assertEqual(context[0]['status'],'rejected');self.assertTrue(context[0]['rendered'])
        self.assertNotIn('events',context[0]['metadata'])

    def test_missing_optional_owner_is_normalized_and_never_raises_keyerror(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{},'callbacks':{}}
        before={'owner':None,'location':'desk','condition':'closed'}
        state={'completed_events':[],'callbacks':{},'summary':'','props':{'book':before}}
        rows=[{'event_id':'e1','props':{'book':{'placement':'table','owner':None}}}]
        after={'location':'desk','condition':'open'}
        update={'id':'book','event_id':'e1','beat_index':0,'before':before,'after':after}
        result=_ledger(story,state,[{'id':'e1'}],rows,[update],'Mở sách')
        self.assertIsNone(result['props']['book']['owner'])

    def test_ai_prop_id_lists_are_schema_errors_and_updates_cannot_go_back_in_time(self):
        from videostudio.comedy_story import _ledger
        story={'characters':{'a':{}},'callbacks':{}}
        a={'owner':'a','location':'desk','condition':'closed'};b=dict(a,location='bin');d=dict(a,location='hand')
        state={'completed_events':[],'callbacks':{},'summary':'','props':{'box':a}}
        rows=[{'event_id':'e1','props':{'box':{'placement':'held','owner':'a'}}},{'event_id':'e2','props':{'box':{'placement':'table','owner':None}}}]
        with self.assertRaises(ValueError):_ledger(story,state,[{'id':'e1'},{'id':'e2'}],rows,[{'id':[]}],'Xong')
        updates=[{'id':'box','event_id':'e2','before':a,'after':b,'beat_index':1},
                 {'id':'box','event_id':'e1','before':b,'after':d,'beat_index':0}]
        with self.assertRaises(ValueError):_ledger(story,state,[{'id':'e1'},{'id':'e2'}],rows,updates,'Xong')

    def test_blocking_review_is_saved_rejected_without_silent_approval(self):
        from videostudio.comedy_story import write_story
        from videostudio.core import PermanentError
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p,j,calls,answer=self.fixture(folder)
            def blocked(prompt,check):
                result=answer(prompt,check)
                if '[COMEDY_CRITIC' in prompt:result['fidelity']='uncertain'
                return result
            p.llm_json.side_effect=blocked
            with self.assertRaises(PermanentError):write_story(p,j,lambda:None)
            report=json.loads((Path(j['output'])/'comedy/quality.json').read_text(encoding='utf8'))
            self.assertEqual(report['status'],'rejected')
            self.assertNotIn('script',j['checkpoints'])
