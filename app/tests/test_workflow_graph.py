import copy
import tempfile
import unittest
from pathlib import Path
from videostudio.core import Store
from videostudio.workflow import WorkflowService, compile_workflow, default_workflow, validate_workflow
BASE = {'idea': 'A science story', 'voice_id': 'preset:test', 'duration_seconds': 30}
class WorkflowTests(unittest.TestCase):
    def test_native_reference_node_rejects_providers_without_that_capability(self):
        graph=default_workflow()
        next(n for n in graph['nodes'] if n['type']=='images')['config']['provider']='comfy'
        with self.assertRaisesRegex(ValueError,'Flow'):
            compile_workflow(graph,BASE)
    def test_default_compiles_supported_settings_and_graph(self):
        req = compile_workflow(default_workflow('science'), BASE)
        self.assertEqual(req['edit_preset'], 'science')
        self.assertEqual(req['workflow']['schema_version'], 1)
        self.assertEqual(req['workflow_mode'], 'research')
        self.assertEqual(req['image_provider'], 'flow')
        self.assertTrue(req['music_enabled'])
        self.assertNotIn('workflow', BASE)
    def test_optional_removal_compiles_real_runtime_switches(self):
        graph = default_workflow()
        absent = {'research', 'references', 'captions', 'music', 'sfx'}
        graph['nodes'] = [n for n in graph['nodes'] if n['type'] not in absent]
        graph['edges'] = [e for e in graph['edges'] if e['source'] not in absent and e['target'] not in absent]
        graph['edges'].append({'id': 'direct', 'source': 'input', 'source_port': 'brief', 'target': 'script', 'target_port': 'brief'})
        req = compile_workflow(graph, BASE)
        self.assertEqual(req['workflow_mode'], 'provided_narration')
        for key in ('references_enabled', 'captions_enabled', 'music_enabled', 'sfx_enabled'): self.assertIs(req[key], False)
    def test_disabled_node_and_configuration_overrides(self):
        graph = default_workflow()
        for node in graph['nodes']:
            if node['type'] == 'music': node['config']['enabled'] = False
            if node['type'] == 'speech': node['config'] = {'voice_id': 'preset:new', 'pitch': 2}
            if node['type'] == 'images': node['config'] = {'provider': 'comfy', 'batch_size': 1}
            if node['type'] == 'references': node['config']['enabled'] = False
        req = compile_workflow(graph, BASE)
        self.assertFalse(req['music_enabled'])
        self.assertEqual(req['voice_id'], 'preset:new')
        self.assertEqual(req['image_provider'], 'comfy')
        self.assertEqual(req['pitch'], 2)
    def test_rejects_invalid_graphs_instead_of_ignoring_edges(self):
        for mutate, message in [
            (lambda g: g['nodes'].append(copy.deepcopy(g['nodes'][0])), 'Duplicate'),
            (lambda g: g['edges'].pop(next(i for i,e in enumerate(g['edges']) if e['target']=='output')), 'required'),
            (lambda g: g['edges'][0].update(source_port='unknown'), 'port'),
            (lambda g: g['nodes'][0]['config'].update(command='execute'), 'config'),
            (lambda g: next(n for n in g['nodes'] if n['type']=='images')['config'].update(provider='fake'), 'provider'),
            (lambda g: g['edges'].append({'id':'bad', 'source':'output','source_port':'video','target':'input','target_port':'brief'}), 'port'),
        ]:
            with self.subTest(message=message):
                graph = default_workflow(); mutate(graph)
                with self.assertRaisesRegex(ValueError, message): validate_workflow(graph)
    def test_rejects_fan_in_and_disconnected_optional_nodes(self):
        graph = default_workflow(); graph['edges'].append({**graph['edges'][0], 'id':'second'})
        with self.assertRaisesRegex(ValueError, 'Duplicate|already connected'): validate_workflow(graph)
        graph = default_workflow(); graph['edges'] = [e for e in graph['edges'] if e['source'] != 'music']
        with self.assertRaisesRegex(ValueError, 'output|connected'): validate_workflow(graph)
    def test_conflicting_text_providers_rejected(self):
        graph = default_workflow(); next(n for n in graph['nodes'] if n['type']=='script')['config']['provider']='gemini'
        next(n for n in graph['nodes'] if n['type']=='research')['config']['provider']='chatgpt'
        with self.assertRaisesRegex(ValueError, 'same text provider'): compile_workflow(graph, BASE)
    def test_cycles_rejected_before_execution(self):
        graph=default_workflow()
        graph['edges'][0].update(source='research')
        with self.assertRaisesRegex(ValueError, 'cycle'):validate_workflow(graph)
    def test_provided_narration_mode_is_preserved(self):
        req=compile_workflow(default_workflow(),{**BASE,'workflow_mode':'provided_narration'})
        self.assertEqual(req['workflow_mode'],'provided_narration')
    def test_malformed_client_values_raise_validation_errors(self):
        for mutate in (
            lambda g:g.update(schema_version=True),
            lambda g:g['nodes'][0].update(type=[]),
            lambda g:g['edges'][0].update(source=[]),
            lambda g:g['edges'][0].update(source_port=[]),
            lambda g:g['nodes'][0].update(x=float('nan')),
            lambda g:g.update(viewport={'zoom':0}),
        ):
            graph=default_workflow();mutate(graph)
            with self.assertRaises(ValueError):validate_workflow(graph)
    def test_revisions_clone_import_export_and_delete_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'jobs.db', Path(tmp)/'out'); service = WorkflowService(store)
            saved = service.save(default_workflow(), 0); self.assertEqual(saved['revision'], 1)
            saved['name'] = 'My flow'; newer = service.save(saved, 1); self.assertEqual(newer['revision'], 2)
            with self.assertRaisesRegex(ValueError, 'Stale'): service.save(saved, 1)
            self.assertEqual(WorkflowService(store).get(saved['id'])['name'], 'My flow')
            clone = copy.deepcopy(newer); clone['id']=''; clone['revision']=0; clone = service.save(clone, 0)
            self.assertNotEqual(clone['id'], saved['id']); self.assertEqual(len(service.list()['items']), 2)
            self.assertEqual(len(service.revisions(saved['id'])), 2); service.delete(saved['id'])
            with self.assertRaises(KeyError): service.get(saved['id'])
if __name__ == '__main__': unittest.main()
