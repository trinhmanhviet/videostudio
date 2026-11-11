import json, tempfile, unittest
from pathlib import Path

from videostudio.core import Store
from videostudio.providers import image_seed

REQUEST = {'idea': 'test', 'voice_id': 'test', 'duration_seconds': 8}
OLD = ['images-0000.png', 'images-0000.checkpoint.json', 'images-0000-receipt.json', 'images-hybrid-0001-receipt.json',
       'images-hybrid-0001.conditioning.json', 'images-vq-s1-abc.png', 'images-vq-s1-abc-receipt.json', 'images-vq-s1-abc.review.json']


class ResetImagesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'db', Path(self.folder.name) / 'videos')
        self.job, _ = self.store.create(REQUEST, 'job')
        self.out = Path(self.job['output'])
        with self.store.db() as c:
            for stage in ('script', 'speech', 'images'):
                c.execute('INSERT INTO checkpoints VALUES(?,?,?)', (self.job['id'], stage, '{}'))
            c.execute("UPDATE jobs SET state='completed' WHERE id=?", (self.job['id'],))

    def tearDown(self):
        self.folder.cleanup()

    def test_reset_moves_old_receipts_so_comfy_really_runs_again(self):
        for name in OLD:
            (self.out / name).write_text('old')
        self.store.reset_stage_images(self.job['id'], image_provider='comfy')
        self.assertEqual(sorted(p.name for p in self.out.glob('images-*')), [])
        backups = list((self.out / '.reset-backup').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(sorted(p.name for p in backups[0].iterdir()), sorted(OLD))

    def test_failed_reset_puts_receipts_back(self):
        receipt = self.out / 'images-0000-receipt.json'
        receipt.write_text('old')
        original = self.store.event
        self.store.event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('transaction failed'))
        with self.assertRaises(RuntimeError):
            self.store.reset_stage_images(self.job['id'], image_provider='comfy')
        self.store.event = original
        self.assertEqual(receipt.read_text(), 'old')

    def test_every_reset_gets_new_seeds_that_stay_stable_on_resume(self):
        first = self.store.get(self.job['id'])
        base = int(self.job['id'].replace('-', '')[:8], 16)
        self.assertEqual(image_seed(first, 3), base + 3)
        self.store.reset_stage_images(self.job['id'], image_provider='comfy')
        second = self.store.get(self.job['id'])
        self.assertNotEqual(image_seed(second, 3), image_seed(first, 3))
        self.assertEqual(image_seed(self.store.get(self.job['id']), 3), image_seed(second, 3))
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='completed' WHERE id=?", (self.job['id'],))
        self.store.reset_stage_images(self.job['id'], image_provider='comfy')
        third = self.store.get(self.job['id'])
        self.assertEqual(len({image_seed(j, 3) for j in (first, second, third)}), 3)
        self.assertEqual(image_seed({'id': self.job['id']}, 3), base + 3)


if __name__ == '__main__':
    unittest.main()
