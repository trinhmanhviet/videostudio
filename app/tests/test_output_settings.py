import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import output_settings
from videostudio.core import Store
from videostudio.output_layout import allocate_output


class OutputSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old, self.new = root / 'E' / 'Videos', root / 'D' / 'Videos'
        self.store = Store(root / 'jobs.sqlite3', self.old)
        self.settings = patch.object(output_settings, 'SETTINGS', root / 'output-root.json')
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.tmp.cleanup()

    def test_changing_folder_moves_new_videos_and_keeps_old_ones_owned(self):
        with self.store.db() as c:
            first = allocate_output(self.store, c, {'project': 'Truyện A'}, 'job-1')
        self.assertEqual(first.parent.parent.parent, self.old)
        output_settings.save(self.store, str(self.new))
        with self.store.db() as c:
            second = allocate_output(self.store, c, {'project': 'Truyện A'}, 'job-2')
            third = allocate_output(self.store, c, {'project': 'Truyện A'}, 'job-3')
        self.assertEqual(second.parent.parent.parent, self.new)
        self.assertEqual(second.parent.parent, third.parent.parent)  # same project folder under the new root
        self.assertEqual(self.store.root_containing(first), self.old.resolve())
        self.assertEqual(self.store.root_containing(second), self.new.resolve())
        self.assertIsNone(self.store.root_containing(Path(self.tmp.name) / 'elsewhere' / 'x.mp4'))
        self.assertEqual(output_settings.configured_root(), self.new)

    def test_invalid_folders_are_refused(self):
        for bad in ('', 'Videos', 'C:\\'):
            with self.assertRaises(ValueError):
                output_settings.validate(bad)
        with self.assertRaises(ValueError):
            output_settings.validate(str(output_settings.DATA_ROOT / 'videos'))


if __name__ == '__main__':
    unittest.main()
