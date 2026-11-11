import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from videostudio.core import Store


ROOT = Path(__file__).resolve().parents[1]


class ComedyFoundationTests(unittest.TestCase):
    def memory_module(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.comedy_memory'),
                             'Comedy memory API must exist')
        from videostudio import comedy_memory
        return comedy_memory

    def test_playbook_has_all_techniques_and_valid_combinations(self):
        playbook = self.memory_module().load_playbook()
        self.assertEqual(playbook['version'], 1)
        techniques = playbook['techniques']
        self.assertEqual(len(techniques), 32)
        ids = {item['id'] for item in techniques}
        self.assertEqual(len(ids), 32)
        required = {'id', 'name', 'mechanism', 'when', 'setup', 'escalation',
                    'payoff', 'combines_with', 'mistakes', 'avoid_when'}
        for item in techniques:
            self.assertTrue(required <= item.keys())
            for key in required - {'combines_with'}:
                self.assertTrue(item[key], (item['id'], key))
            self.assertTrue(set(item['combines_with']) <= ids)
        self.assertEqual(len({item['id'] for item in playbook['endings']}), 9)
        self.assertEqual(list(playbook['critic']['weights'].values()), [20, 25, 15, 15, 15, 10])
        self.assertEqual(playbook['critic']['max_repairs'], 2)
        self.assertEqual(playbook['selection']['mode'], 'story_driven')
        playbook['techniques'].clear()
        self.assertEqual(len(self.memory_module().load_playbook()['techniques']), 32)

    def test_benchmark_covers_twenty_distinct_categories_with_human_review(self):
        path = ROOT / 'tests/fixtures/comedy-benchmark.json'
        self.assertTrue(path.is_file(), 'Offline benchmark fixture must exist')
        benchmark = json.loads(path.read_text(encoding='utf-8'))
        cases = benchmark['cases']
        self.assertGreaterEqual(len({case['category'] for case in cases}), 20)
        for case in cases:
            self.assertTrue(case['input'])
            self.assertTrue(case['constraints'])
            self.assertTrue(case['rubric']['objective'])
            self.assertTrue(case['rubric']['subjective'])
            self.assertIsNone(case['human_feedback']['rating'])
            self.assertEqual(case['human_feedback']['note'], '')

    def test_record_is_idempotent_and_uses_existing_database(self):
        memory = self.memory_module()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'jobs.db', directory)
            first = memory.record(store, 'j1', {'idea': 'Bản đồ thất lạc', 'props': ['map']}, 'draft')
            second = memory.record(store, {'id': 'j1', 'state': 'completed'}, {'idea': 'Bản đồ thất lạc'}, 'draft')
            self.assertEqual(first, second)
            self.assertEqual(second['metadata']['props'], ['map'])
            self.assertFalse(second['published'])
            self.assertFalse(second['rendered'])
            self.assertEqual(len(memory.recent(store)), 1)
            self.assertEqual(sorted(path.name for path in Path(directory).glob('*.db')), ['jobs.db'])

    def test_statuses_are_explicit_and_recent_distinguishes_rejected_drafts(self):
        memory = self.memory_module()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'jobs.db', directory)
            for index, status in enumerate(('draft', 'reviewed', 'approved', 'rendered', 'published', 'rejected')):
                item = memory.record(store, f'j{index}', {'ending': 'dialogue'}, status)
                self.assertEqual(item['status'], status)
                self.assertEqual(item['published'], status == 'published')
                self.assertEqual(item['rendered'], status in ('rendered', 'published'))
            self.assertEqual(len(memory.recent(store, limit=2)), 2)
            self.assertEqual(memory.recent(store, limit=0), [])
            with self.assertRaises(ValueError):
                memory.record(store, 'bad', {}, 'completed')

    def test_replay_does_not_demote_accepted_work_or_overwrite_human_feedback(self):
        memory = self.memory_module()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'jobs.db', directory)
            memory.record(store, 'j1', {'idea': 'Old'}, 'published')
            reviewed = memory.feedback(store, 'j1', 4, 'Có bất ngờ')
            self.assertEqual(reviewed['human_feedback']['rating'], 4)
            memory.record(store, 'j1', {'critic': {'score': 99}, 'human_feedback': None}, 'draft')
            summary = memory.recent(store)[0]
            self.assertEqual(summary['status'], 'published')
            self.assertEqual(summary['human_feedback']['note'], 'Có bất ngờ')
            self.assertEqual(summary['metadata']['idea'], 'Old')
            self.assertNotIn('critic', summary['metadata'])
            memory.record(store, 'j2', {}, 'approved')
            self.assertEqual(memory.record(store, 'j2', {}, 'draft')['status'], 'approved')
            memory.record(store, 'j3', {}, 'rejected')
            self.assertEqual(memory.record(store, 'j3', {}, 'draft')['status'], 'rejected')

    def test_stale_draft_cannot_replace_final_story_and_rejection_keeps_render_fact(self):
        memory=self.memory_module()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'jobs.db',directory)
            memory.record(store,'j1',{'idea':'Final','ending':'Final ending'},'published')
            result=memory.record(store,'j1',{'idea':'Stale','ending':'Stale ending'},'draft')
            self.assertEqual(result['metadata']['ending'],'Final ending')
            memory.record(store,'j2',{},'rendered')
            self.assertTrue(memory.record(store,'j2',{},'rejected')['rendered'])

    def test_invalid_inputs_do_not_create_or_corrupt_entries(self):
        memory = self.memory_module()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'jobs.db', directory)
            self.assertEqual(memory.recent(store), [])
            with self.assertRaises(ValueError):
                memory.record(store, '', {}, 'draft')
            with self.assertRaises(ValueError):
                memory.record(store, 'j1', {'score': float('nan')}, 'draft')
            with self.assertRaises(ValueError):
                memory.feedback(store, 'unknown', 3, 'Missing job')
            memory.record(store, 'j1', {}, 'draft')
            with self.assertRaises(ValueError):
                memory.feedback(store, 'j1', True)
            with self.assertRaises(ValueError):
                memory.feedback(store, 'j1', 6)
            self.assertIsNone(memory.feedback(store, 'j1', None, 'Chỉ nhận xét')['human_feedback']['rating'])


if __name__ == '__main__':
    unittest.main()
