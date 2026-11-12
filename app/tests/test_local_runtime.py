import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videostudio import paths
from videostudio.providers import Pipeline


class LocalRuntimeTests(unittest.TestCase):
    def test_runtime_is_owned_by_videostudio_data(self):
        self.assertEqual(paths.RUNTIME_ROOT, paths.DATA_ROOT / 'runtime')
        self.assertEqual(paths.VOICE_ROOT, Path(os.getenv('VS_VOICE_ROOT', str(paths.DATA_ROOT))))

    def test_speech_runtime_does_not_follow_a_legacy_voice_inventory_root(self):
        with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'is_dir', return_value=True), patch.dict(os.environ, {}, clear=True):
            pipeline=Pipeline(SimpleNamespace(root=Path('X:/retired-project')))
        self.assertEqual(Path(pipeline.speech_python), paths.RUNTIME_ROOT/'media/.venv/Scripts/python.exe')
        self.assertEqual(Path(pipeline.speech_cache), paths.RUNTIME_ROOT/'media/model-cache')

    def test_production_sources_have_no_absolute_storyforge_dependency(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('videostudio/api.py','videostudio/providers.py','scripts/start_comfy_recovery.py',
                     'memestudio/engine/make_voice.py','compose.yaml'):
            source=(root/name).read_text(encoding='utf8').lower().replace('\\','/')
            self.assertFalse('d:/projects/storyforge' in source,name)
            self.assertFalse('vs_storyforge_root' in source,name)
