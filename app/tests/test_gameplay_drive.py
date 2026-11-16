import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from videostudio import gameplay_drive
from videostudio.drive_storage import DriveError, folder_id_from_link
from videostudio.gameplay_drive import GameplayFolder
from videostudio.story_library import StoryLibrary

FOLDER = 'F' * 25


def make_library(tmp):
    library = StoryLibrary(Path(tmp, 'lib'), Path(tmp, 'game'))
    library.probe_video = lambda path: {'duration': 60.0, 'width': 1920, 'height': 1080, 'fps': 60, 'has_audio': False}
    library.thumbnail = lambda clip_id: None
    return library


def add_clip(library, tmp, name, folder=FOLDER, used=False):
    path = Path(tmp, 'cache', name)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(name.encode())
    return library.add_gameplay_cached(path, name, hashlib.sha256(name.encode()).hexdigest(), 'id-' + name, 'u', folder=folder, used=used)['id']


def playlist(library, book_id):
    return [c['name'] for c in library.gameplay(book_id)['items']]


class UsedClipTests(unittest.TestCase):
    def test_used_clips_leave_playlists_and_the_cursor_keeps_its_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = make_library(tmp)
            book = library.create_book('A')['id']
            c1, c2, c3 = (add_clip(library, tmp, n) for n in ('a.mp4', 'b.mp4', 'c.mp4'))
            own = add_clip(library, tmp, 'own.mp4', folder=None)
            library.advance_cursor(book, 1, 5.0, 'job')  # in the middle of b.mp4
            self.assertEqual(library.mark_used([c1, own]), [c1])  # a clip not from the folder is never "used"
            self.assertEqual(playlist(library, book), ['b.mp4', 'c.mp4', 'own.mp4'])
            self.assertEqual((library.cursor(book)['clip'], library.cursor(book)['offset']), (0, 5.0))
            self.assertEqual(library.mark_used([c1]), [])
            library.mark_used([c2])  # the clip under the cursor: the next clip starts from its beginning
            self.assertEqual((library.cursor(book)['clip'], library.cursor(book)['offset']), (0, 0.0))
            self.assertEqual(playlist(library, library.create_book('B')['id']), ['c.mp4', 'own.mp4'])
            self.assertEqual(library.folder_counts(FOLDER), {'new': 1, 'used': 2, 'to_move': 2})

            library.set_reuse(True)
            self.assertEqual(playlist(library, book), ['c.mp4', 'own.mp4', 'a.mp4', 'b.mp4'])
            self.assertEqual(len(playlist(library, library.create_book('C')['id'])), 4)
            library.set_reuse(False)
            self.assertEqual(playlist(library, book), ['c.mp4', 'own.mp4'])

    def test_when_every_new_clip_is_used_the_video_still_gets_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = make_library(tmp)
            book = library.create_book('A')['id']
            c1, c2 = (add_clip(library, tmp, n) for n in ('a.mp4', 'b.mp4'))
            self.assertEqual(library.playable(book)[1], False)
            library.mark_used([c1, c2])
            items, fell_back = library.playable(book)
            self.assertTrue(fell_back)
            self.assertEqual([c['name'] for c in items], ['a.mp4', 'b.mp4'])
            library.import_files(book, [{'name': '1.txt', 'text': 'Trời mưa.'}], split=False)
            chapter_id = library.chapters(book)['items'][0]['id']
            snapshot = library.freeze(book, [chapter_id], 'idem-1')
            self.assertTrue(snapshot['gameplay_fallback'])
            self.assertEqual(len(snapshot['gameplay']), 2)
            # The used copies on this machine are removed; the clips stay usable (downloaded again from Drive).
            self.assertEqual(library.drop_used_cache(), len('a.mp4') + len('b.mp4'))
            self.assertFalse(Path(tmp, 'cache', 'a.mp4').exists())
            self.assertTrue(all(c['available'] for c in library.playable(book)[0]))


class FakeDrive:
    def __init__(self, tmp):
        self.files = {FOLDER: [{'id': 'v1', 'name': 'one.mp4', 'size': 3}, {'id': 'v2', 'name': 'two.mp4', 'size': 3},
                               {'id': 'doc', 'name': 'ghi chu.txt', 'size': 3}],
                      'USED': [{'id': 'old', 'name': 'old.mp4', 'size': 3}]}
        self.downloads, self.moves, self.fail, self.used_exists = [], [], None, True

    def find_folder(self, folder_id, account=None):
        return account or 'me@example.com', {'id': folder_id, 'name': 'Gameplay'}

    def accounts(self):
        return [{'id': 'me@example.com', 'disabled': 0}, {'id': 'two@example.com', 'disabled': 0}]

    def list_folders(self, account, parent='root'):
        return {'root': [{'id': FOLDER, 'name': 'Gameplay'}], 'shared': [{'id': 'S' * 20, 'name': 'Của bạn bè'}]}.get(parent, [])

    def list_videos(self, account, folder_id):
        return [f for f in self.files.get(folder_id, []) if f['name'].endswith('.mp4')]

    def child_folder(self, account, parent, name, create=True):
        return 'USED' if self.used_exists or create else None

    def download(self, file_id, target, check=lambda: None, account=None, progress=None):
        self.downloads.append(file_id)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(file_id.encode())
        return hashlib.sha256(file_id.encode()).hexdigest(), len(file_id)

    def move(self, account, file_id, from_folder, to_folder):
        if self.fail:
            raise self.fail
        self.moves.append((file_id, from_folder, to_folder))
        return True

    def trash(self, account, file_id):
        if self.fail:
            raise self.fail
        self.trashed = getattr(self, 'trashed', []) + [(account, file_id)]
        return True

    def metadata(self, file_id):
        return 'two@example.com', {'id': file_id}


class FolderSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [mock.patch.object(gameplay_drive, 'CACHE', Path(self.tmp, 'cache')), mock.patch.object(gameplay_drive, 'cache_trim', lambda keep=(): None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.library = make_library(self.tmp)
        self.book = self.library.create_book('A')['id']
        self.drive = FakeDrive(self.tmp)
        self.folder = GameplayFolder(store=None, library=self.library, drive=self.drive)

    def test_browse_folders_then_pick_one(self):
        root = self.folder.browse()
        self.assertEqual((root['account'], root['folders'][0]['name'], root['videos']), ('me@example.com', 'Gameplay', 0))
        inside = self.folder.browse('two@example.com', FOLDER)
        self.assertEqual((inside['account'], inside['videos'], inside['folders']), ('two@example.com', 2, []))
        self.assertEqual(self.folder.browse('nobody', 'shared')['account'], 'me@example.com')
        with self.assertRaises(ValueError):
            self.folder.browse(None, "x' or name contains '")
        status = self.folder.configure({'link': FOLDER, 'account': 'two@example.com'})
        self.assertEqual(status['folder']['account'], 'two@example.com')

    def test_folder_link(self):
        self.assertEqual(folder_id_from_link(f'https://drive.google.com/drive/folders/{FOLDER}?usp=sharing'), FOLDER)
        with self.assertRaises(ValueError):
            folder_id_from_link('https://example.com/drive/folders/' + FOLDER)

    def test_sync_fetches_new_videos_once_and_used_ones_move_into_used(self):
        status = self.folder.configure({'link': f'https://drive.google.com/drive/folders/{FOLDER}'})
        self.assertEqual(status['folder']['name'], 'Gameplay')
        status = self.folder.sync()
        self.assertEqual((status['task']['state'], status['task']['added'], status['new']), ('done', 2, 2))
        self.assertEqual(playlist(self.library, self.book), ['one.mp4', 'two.mp4'])
        self.folder.sync()
        self.assertEqual(self.drive.downloads, ['v1', 'v2'])  # nothing fetched twice

        clips = self.library.gameplay(self.book)['items']
        segments = [{'id': clips[0]['id'], 'start': 0.0, 'length': 60.0}, {'id': clips[1]['id'], 'start': 0.0, 'length': 20.0}]
        log = []
        self.assertEqual(self.folder.after_plan(segments, clips, log.append), [clips[0]['id']])
        self.assertEqual(self.drive.moves, [('v1', FOLDER, 'USED')])
        self.assertEqual(playlist(self.library, self.book), ['two.mp4'])
        self.assertIn('Used', log[0])

    def test_a_refused_move_is_retried_on_the_next_sync(self):
        self.folder.configure({'link': FOLDER})
        self.folder.sync()
        clips = self.library.gameplay(self.book)['items']
        self.drive.fail = DriveError('Drive chưa cho phép chuyển clip vào Used')
        log = []
        self.folder.after_plan([{'id': clips[0]['id'], 'start': 0.0, 'length': 60.0}], clips, log.append)
        self.assertIn('chưa chuyển được', log[0])
        self.assertEqual(self.folder.status()['to_move'], 1)
        self.assertIn('chưa cho phép', self.folder.status()['folder']['error'])
        self.drive.fail = None
        self.folder.sync()
        self.assertEqual(self.drive.moves, [('v1', FOLDER, 'USED')])
        self.assertEqual(self.folder.status()['to_move'], 0)

    def test_reuse_also_fetches_what_is_already_in_used(self):
        self.folder.configure({'link': FOLDER, 'reuse': True})
        self.folder.sync()
        self.assertEqual(sorted(playlist(self.library, self.book)), ['old.mp4', 'one.mp4', 'two.mp4'])
        self.assertEqual(self.folder.status()['used'], 1)
        self.assertEqual(self.folder.status()['to_move'], 0)  # already in Used
        with self.assertRaises(ValueError):
            self.folder.configure({'reuse': 'có'})


if __name__ == '__main__':
    unittest.main()


class DeleteClipTests(unittest.TestCase):
    """The owner deletes a clip from its thumbnail: gone from every book, from this computer and into Drive's trash."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cache = mock.patch.object(gameplay_drive, 'CACHE', Path(self.tmp, 'cache'))
        cache.start()
        self.addCleanup(cache.stop)
        self.library = make_library(self.tmp)
        self.book = self.library.create_book('A')['id']
        self.drive = FakeDrive(self.tmp)
        self.folder = GameplayFolder(store=None, library=self.library, drive=self.drive)
        self.folder.configure({'link': FOLDER, 'account': 'me@example.com'})

    def test_folder_clip_is_deleted_here_and_trashed_on_drive_and_never_fetched_again(self):
        clip = add_clip(self.library, self.tmp, 'one.mp4')
        keep = add_clip(self.library, self.tmp, 'two.mp4')
        result = self.folder.delete_clip(clip, set())
        self.assertEqual((result['local'], result['drive']), (True, 'trashed'))
        self.assertFalse(Path(self.tmp, 'cache', 'one.mp4').exists())
        self.assertTrue(Path(self.tmp, 'cache', 'two.mp4').exists())
        self.assertEqual(self.drive.trashed, [('me@example.com', 'id-one.mp4')])
        self.assertEqual(playlist(self.library, self.book), ['two.mp4'])
        self.assertIn('id-one.mp4', self.library.drive_clip_ids())
        self.assertEqual(self.folder.playback(keep), ('file', Path(self.tmp, 'cache', 'two.mp4')))
        with self.assertRaises(KeyError):
            self.folder.playback(clip)

    def test_clip_from_a_link_is_trashed_with_the_account_that_sees_it(self):
        clip = add_clip(self.library, self.tmp, 'link.mp4', folder=None)
        self.folder.delete_clip(clip, set())
        self.assertEqual(self.drive.trashed, [('two@example.com', 'id-link.mp4')])

    def test_drive_refusal_still_deletes_here_and_says_why(self):
        clip = add_clip(self.library, self.tmp, 'one.mp4')
        self.drive.fail = DriveError('Drive không cho chuyển vào thùng rác (mã 403)')
        result = self.folder.delete_clip(clip, set())
        self.assertEqual(result['drive'], 'failed')
        self.assertIn('403', result['error'])
        self.assertEqual(playlist(self.library, self.book), [])

    def test_clip_a_queued_video_uses_is_refused_untouched(self):
        from videostudio.story_library import ConflictError
        clip = add_clip(self.library, self.tmp, 'one.mp4')
        with self.assertRaises(ConflictError):
            self.folder.delete_clip(clip, {clip})
        self.assertTrue(Path(self.tmp, 'cache', 'one.mp4').exists())
        self.assertFalse(getattr(self.drive, 'trashed', []))
        self.assertEqual(playlist(self.library, self.book), ['one.mp4'])

    def test_file_outside_the_tool_folders_is_never_deleted(self):
        outside = Path(self.tmp, 'mine', 'own.mp4')
        outside.parent.mkdir()
        outside.write_bytes(b'x')
        import hashlib
        clip = self.library.add_gameplay_cached(outside, 'own.mp4', hashlib.sha256(b'own').hexdigest(), 'id-own', 'u', folder=FOLDER)['id']
        self.assertFalse(self.folder.delete_clip(clip, set())['local'])
        self.assertTrue(outside.exists())

    def test_uncached_drive_clip_plays_from_drive(self):
        clip = add_clip(self.library, self.tmp, 'one.mp4')
        Path(self.tmp, 'cache', 'one.mp4').unlink()
        self.assertEqual(self.folder.playback(clip), ('drive', 'me@example.com', 'id-one.mp4'))
