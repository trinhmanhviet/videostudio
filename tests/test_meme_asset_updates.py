"""Regression tests for content-aware meme assets and newest ZIP selection."""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.ingest_asset_zips import main as ingest
from videostudio.meme_catalog import Catalog, refresh_library


class AssetUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / 'pack'
        (self.pack / 'catalog').mkdir(parents=True)
        (self.pack / 'new').mkdir()
        self.sprite = self.pack / 'catalog' / 'sprite.png'
        self.background = self.pack / 'new' / 'bg_test.png'
        self.write_png(self.sprite, (255, 0, 0, 255))
        self.write_png(self.background, (255, 0, 0, 255))
        (self.pack / 'catalog' / 'panda.json').write_text(json.dumps({'version': 1, 'items': [
            {'id': 'test', 'kind': 'pose', 'file': 'sprite.png', 'size': [32, 32], 'scale': 1, 'tags': 'test'}
        ]}), encoding='utf-8')

    @staticmethod
    def write_png(path, color):
        # Uncompressed PNG keeps file length identical across color changes.
        Image.new('RGBA', (32, 32), color).save(path, compress_level=0)

    def replace_preserving_metadata(self, path):
        before = path.stat()
        self.write_png(path, (0, 0, 255, 255))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(path.stat().st_size, before.st_size)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_sprite_content_change_invalidates_new_catalog_and_keeps_snapshot_consistent(self):
        original = Catalog(self.pack)
        fingerprint = original.fingerprint()
        self.assertEqual(original.sprite('test').getpixel((0, 0)), (255, 0, 0, 255))
        self.replace_preserving_metadata(self.sprite)
        updated = Catalog(self.pack)
        self.assertEqual(updated.sprite('test').getpixel((0, 0)), (0, 0, 255, 255))
        self.assertNotEqual(updated.fingerprint(), fingerprint)
        self.assertEqual(original.sprite('test').getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(original.fingerprint(), fingerprint)

    def test_background_content_change_invalidates_new_catalog_and_keeps_snapshot_consistent(self):
        original = Catalog(self.pack)
        fingerprint = original.fingerprint()
        self.assertEqual(original.background('bg_test', (16, 16)).getpixel((0, 0)), (255, 0, 0))
        self.replace_preserving_metadata(self.background)
        updated = Catalog(self.pack)
        self.assertEqual(updated.background('bg_test', (16, 16)).getpixel((0, 0)), (0, 0, 255))
        self.assertNotEqual(updated.fingerprint(), fingerprint)
        self.assertEqual(original.background('bg_test', (16, 16)).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(original.fingerprint(), fingerprint)

    def test_lazy_images_belong_to_catalog_snapshot(self):
        original = Catalog(self.pack)
        self.replace_preserving_metadata(self.sprite)
        self.replace_preserving_metadata(self.background)
        self.assertEqual(original.sprite('test').getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(original.background('bg_test', (16, 16)).getpixel((0, 0)), (255, 0, 0))

    def test_unchanged_catalog_reuses_decoded_image_cache(self):
        first, second = Catalog(self.pack), Catalog(self.pack)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertIs(first.sprite('test'), second.sprite('test'))

    def test_refresh_library_detects_same_metadata_changes_and_old_timestamp_additions(self):
        source = self.pack / 'new' / 'prop_test.png'
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 55, 55), fill=(255, 0, 0, 255))
        image.save(source, compress_level=0)
        self.assertTrue(refresh_library(self.pack))
        self.assertFalse(refresh_library(self.pack))
        before = source.stat()
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 55, 55), fill=(0, 0, 255, 255))
        image.save(source, compress_level=0)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(source.stat().st_size, before.st_size)
        self.assertTrue(refresh_library(self.pack))
        self.assertEqual(Catalog(self.pack).sprite('test_2').getpixel((10, 10)), (0, 0, 255, 255))
        extra = self.pack / 'new' / 'prop_extra.png'
        extra.write_bytes(source.read_bytes())
        os.utime(extra, ns=(1_000_000_000, 1_000_000_000))
        self.assertTrue(refresh_library(self.pack))
        self.assertEqual(Catalog(self.pack).kind('extra'), 'prop')
        self.assertFalse(refresh_library(self.pack))


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
