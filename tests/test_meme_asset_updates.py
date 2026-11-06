"""Regression tests for newest ZIP selection when ingesting ChatGPT asset archives."""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.ingest_asset_zips import main as ingest


class ZipUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'downloads'
        self.dest = self.root / 'new'
        self.source.mkdir()
        self.dest.mkdir()

    def archive(self, name, timestamp, entries):
        path = self.source / name
        with zipfile.ZipFile(path, 'w') as bundle:
            for member, data in entries:
                bundle.writestr(member, data)
        os.utime(path, ns=(timestamp, timestamp))
        return path

    def run_ingest(self, replace=True):
        return ingest(['--src', str(self.source), '--dest', str(self.dest)] + (['--replace'] if replace else []))

    def test_newest_archive_wins_before_any_writes_and_replay_preserves_target(self):
        self.archive('R1_backgrounds.zip', 1_600_000_000_000_000_000, [('folder/bg_test.png', b'old')])
        self.archive('R2_backgrounds.zip', 1_600_000_100_000_000_000, [('folder/bg_test.png', b'new')])
        self.assertEqual(self.run_ingest(), 0)
        target = self.dest / 'bg_test.png'
        self.assertEqual(target.read_bytes(), b'new')
        self.assertFalse((self.dest / '_old_style').exists())
        before = target.stat().st_mtime_ns
        self.assertEqual(self.run_ingest(), 0)
        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertFalse((self.dest / '_old_style').exists())

    def test_existing_original_is_preserved_once_and_no_replace_skips(self):
        target = self.dest / 'bg_test.png'
        target.write_bytes(b'original')
        os.utime(target, ns=(1_500_000_000_000_000_000, 1_500_000_000_000_000_000))
        self.archive('R1_backgrounds.zip', 1_600_000_000_000_000_000, [('bg_test.png', b'old')])
        self.archive('R2_backgrounds.zip', 1_600_000_100_000_000_000, [('bg_test.png', b'new')])
        self.run_ingest(replace=False)
        self.assertEqual(target.read_bytes(), b'original')
        self.run_ingest()
        self.assertEqual(target.read_bytes(), b'new')
        self.assertEqual((self.dest / '_old_style' / 'bg_test.png').read_bytes(), b'original')
        self.run_ingest()
        self.assertEqual(len(list((self.dest / '_old_style').iterdir())), 1)

    def test_same_archive_duplicate_basename_uses_last_member_deterministically(self):
        self.archive('R1_backgrounds.zip', 1_600_000_000_000_000_000,
                     [('a/bg_test.png', b'first'), ('z/bg_test.png', b'last')])
        self.run_ingest()
        self.assertEqual((self.dest / 'bg_test.png').read_bytes(), b'last')


if __name__ == '__main__':
    unittest.main()
