import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import drive_storage
from videostudio.core import Store
from videostudio.drive_storage import DriveError, DriveStorage, file_id_from_link


class DriveStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'jobs.sqlite3', Path(self.tmp.name) / 'out')
        self.drive = DriveStorage(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_are_parsed_and_other_hosts_refused(self):
        file_id = '1AbCdEfGhIjKlMnOpQrStUvWxYz012345'
        for link in (f'https://drive.google.com/file/d/{file_id}/view?usp=sharing', f'https://drive.google.com/open?id={file_id}', file_id):
            self.assertEqual(file_id_from_link(link), file_id)
        with self.assertRaises(ValueError):
            file_id_from_link(f'https://www.youtube.com/watch?v={file_id}')

    def test_first_account_with_room_is_used_then_the_next(self):
        with self.store.db() as db:
            db.execute("INSERT INTO drive_accounts VALUES('a@x','a@x','t',0,0,0)")
            db.execute("INSERT INTO drive_accounts VALUES('b@x','b@x','t',1,0,0)")
        free = {'a@x': 10 * 2**30, 'b@x': 100 * 2**30}
        with patch.object(DriveStorage, 'quota', lambda self, account: {'free': free[account], 'limit': 1, 'usage': 0}):
            self.assertEqual(self.drive.pick_account(1 * 2**30), 'a@x')
            free['a@x'] = 2 * 2**30  # nearly full: keep the safety margin
            self.assertEqual(self.drive.pick_account(1 * 2**30), 'b@x')
            free['b@x'] = 0
            with self.assertRaises(DriveError):
                self.drive.pick_account(1 * 2**30)

    def test_cache_trim_removes_oldest_beyond_limit_but_keeps_files_in_use(self):
        cache = Path(self.tmp.name) / 'cache'
        cache.mkdir()
        files = []
        for index in range(3):
            path = cache / f'clip{index}.mp4'
            path.write_bytes(b'x' * 100)
            files.append(path)
        with patch.object(drive_storage, 'CACHE', cache), patch.object(drive_storage, 'CACHE_LIMIT', 150):
            drive_storage.cache_trim(keep=[files[0]])
        self.assertTrue(files[0].exists())
        self.assertEqual(sum(p.exists() for p in files), 1)


if __name__ == '__main__':
    unittest.main()
