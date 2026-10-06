"""Tags are never written into the track itself.

A change that no longer fits the padding makes the writer move the whole
audio inside the file; a power cut or a dropped NAS halfway left a damaged
track. Each track is now copied next to itself, the copy gets the tags and is
checked, and only then replaces the original -- one track at a time, with no
copy left behind.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import hifi_tags as ht
from tests.test_tags import HAVE_MUTAGEN, flac_bytes


class SafeWriteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='tags-safe-')
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.track = os.path.join(self.dir, '01 - Song.flac')
        with open(self.track, 'wb') as f:
            f.write(b'ORIGINAL' * 1000)
        os.chmod(self.track, 0o664)
        self.signature = mock.patch.object(ht, '_audio_signature', return_value=('same',))
        self.signature.start()
        self.addCleanup(self.signature.stop)

    def leftovers(self):
        return [n for n in os.listdir(self.dir) if ht.SAFE_COPY_MARK in n]

    def test_the_copy_is_written_and_takes_the_originals_place(self):
        seen = []

        def fake_write(path, fmt, set_, remove):
            seen.append(path)
            with open(path, 'ab') as f:
                f.write(b'+TAGS')
        with mock.patch.object(ht, 'write_file', side_effect=fake_write):
            ht.write_file_safely(self.track, 'flac', {'TITLE': ['x']}, set())
        self.assertEqual(seen, [ht.safe_copy_path(self.track)])     # never the original
        with open(self.track, 'rb') as f:
            self.assertTrue(f.read().endswith(b'+TAGS'))
        self.assertEqual(os.stat(self.track).st_mode & 0o777, 0o664)
        self.assertEqual(self.leftovers(), [])

    def test_the_copy_keeps_name_extension_and_is_hidden(self):
        tmp = ht.safe_copy_path(self.track)
        self.assertEqual(os.path.dirname(tmp), self.dir)
        self.assertTrue(os.path.basename(tmp).startswith('.'))
        self.assertTrue(tmp.endswith('.flac'))

    def test_a_failed_write_leaves_the_original_untouched(self):
        with mock.patch.object(ht, 'write_file', side_effect=ht.FileTagError('boom')):
            with self.assertRaises(ht.FileTagError):
                ht.write_file_safely(self.track, 'flac', {'TITLE': ['x']}, set())
        with open(self.track, 'rb') as f:
            self.assertEqual(f.read(), b'ORIGINAL' * 1000)
        self.assertEqual(self.leftovers(), [])

    def test_changed_audio_is_refused(self):
        self.signature.stop()
        sigs = iter([('before',), ('after',)])
        with mock.patch.object(ht, '_audio_signature', side_effect=lambda p: next(sigs)), \
                mock.patch.object(ht, 'write_file'):
            with self.assertRaises(ht.FileTagError):
                ht.write_file_safely(self.track, 'flac', {'TITLE': ['x']}, set())
        self.signature.start()
        with open(self.track, 'rb') as f:
            self.assertEqual(f.read(), b'ORIGINAL' * 1000)
        self.assertEqual(self.leftovers(), [])

    def test_not_enough_room_for_the_copy_writes_nothing(self):
        usage = shutil.disk_usage(self.dir)._replace(free=100)
        with mock.patch.object(ht.shutil, 'disk_usage', return_value=usage), \
                mock.patch.object(ht, 'write_file') as write:
            with self.assertRaises(ht.FileTagError):
                ht.write_file_safely(self.track, 'flac', {'TITLE': ['x']}, set())
        write.assert_not_called()
        self.assertEqual(self.leftovers(), [])

    def test_a_stale_copy_from_an_interrupted_job_is_replaced(self):
        with open(ht.safe_copy_path(self.track), 'wb') as f:
            f.write(b'half a copy')
        with mock.patch.object(ht, 'write_file'):
            ht.write_file_safely(self.track, 'flac', {'TITLE': ['x']}, set())
        with open(self.track, 'rb') as f:
            self.assertEqual(f.read(), b'ORIGINAL' * 1000)
        self.assertEqual(self.leftovers(), [])

    @unittest.skipUnless(HAVE_MUTAGEN, 'python3-mutagen is not importable')
    def test_a_real_flac_without_padding(self):
        # no padding at all: the writer has to move the audio -- the case
        # that used to put the track at risk
        with open(self.track, 'wb') as f:
            f.write(flac_bytes([('TITLE', 'Old')], padding=0))
        self.signature.stop()
        try:
            ht.write_file_safely(self.track, 'flac', {'TITLE': ['New ' * 400]}, set())
        finally:
            self.signature.start()
        self.assertEqual(ht.read_file(self.track, 'flac')['tags']['TITLE'], ['New ' * 400])
        self.assertEqual(self.leftovers(), [])


class RecoveryTests(unittest.TestCase):
    def test_an_interrupted_job_loses_its_working_copy(self):
        d = tempfile.mkdtemp(prefix='tags-rec-')
        self.addCleanup(shutil.rmtree, d, True)
        track = os.path.join(d, 'a.flac')
        open(track, 'wb').close()
        tmp = ht.safe_copy_path(track)
        open(tmp, 'wb').close()
        jobs = os.path.join(d, 'jobs')
        os.makedirs(jobs)
        ht._write_json(os.path.join(jobs, '20261006-220000-abc123.json'),
                       {'version': 1, 'job_id': '20261006-220000-abc123', 'when': 1, 'seq': 1, 'state': 'running',
                        'files': [{'path': track}], 'errors': []})
        svc = ht.TagService.__new__(ht.TagService)
        svc.jobs_dir = jobs
        svc._recovered = False
        svc._recover()
        self.assertFalse(os.path.exists(tmp))
        self.assertTrue(os.path.exists(track))


if __name__ == '__main__':
    unittest.main()
