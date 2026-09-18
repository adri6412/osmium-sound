#!/usr/bin/env python3
"""prune-ota-r2.py: only the newest release of each channel stays on R2.

A fake bucket, no network. What matters: a release a device may still be
told to download is never deleted — the one a manifest names (on Pages or in
the bucket's mirror), the one being published, one another run is uploading
right now — and nothing is deleted at all when a channel's tag is unknown.
"""
import datetime
import importlib.util
import io
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'prune', os.path.join(HERE, '..', '.github', 'scripts', 'prune-ota-r2.py'))
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)

NOW = datetime.datetime(2026, 9, 18, 12, 0, tzinfo=datetime.timezone.utc)
OLD = NOW - datetime.timedelta(days=5)
FILES = ('hifi-image-{t}.raucb', 'hifi-os-{t}.tar.gz', 'hifi-os-{t}.tar.gz.sha256.sig')


class NoSuchKey(Exception):
    pass


class FakeS3:
    def __init__(self, tags, mirrors, recent=()):
        self.objects = {}
        for t in tags:
            for f in FILES:
                self.objects[f'ota/{t}/{f.format(t=t)}'] = NOW - datetime.timedelta(minutes=10) if t in recent else OLD
        for ch, t in mirrors.items():
            self.objects[f'ota/latest-{ch}.json'] = OLD
        self.mirrors = mirrors
        self.deleted = []

    def get_object(self, Bucket, Key):
        ch = Key[len('ota/latest-'):-len('.json')]
        if ch not in self.mirrors:
            raise NoSuchKey('NoSuchKey')
        return {'Body': io.BytesIO(json.dumps({'tag_name': self.mirrors[ch]}).encode())}

    def get_paginator(self, _):
        fake = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {'Contents': [{'Key': k, 'LastModified': m}
                                    for k, m in sorted(fake.objects.items()) if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, Bucket, Delete):
        for o in Delete['Objects']:
            self.deleted.append(o['Key'])
            del self.objects[o['Key']]
        return {}

    def tags(self):
        return sorted({k.split('/')[1] for k in self.objects if k.count('/') == 2})


def run(s3, *argv):
    os.environ.pop('GITHUB_STEP_SUMMARY', None)
    return prune.main(list(argv), s3=s3, now=NOW)


class Prune(unittest.TestCase):
    def test_keeps_the_newest_of_each_channel_only(self):
        s3 = FakeS3(['v2.5.23', 'v2.5.24', 'v2.5.25-dev.1', 'v2.5.25-dev.2',
                     'v2.5.25-dev.3-alpha1', 'v2.5.25-dev.3-alpha2'],
                    {'prod': 'v2.5.24', 'dev': 'v2.5.25-dev.2', 'alpha': 'v2.5.25-dev.3-alpha2'})
        self.assertEqual(run(s3), 0)
        self.assertEqual(s3.tags(), ['v2.5.24', 'v2.5.25-dev.2', 'v2.5.25-dev.3-alpha2'])
        self.assertIn('ota/latest-prod.json', s3.objects)  # manifests are never touched

    def test_both_pages_and_the_mirror_are_kept_when_they_disagree(self):
        s3 = FakeS3(['v2.5.23', 'v2.5.24', 'v2.5.25-dev.2', 'v2.5.25-dev.3-alpha2'],
                    {'prod': 'v2.5.23', 'dev': 'v2.5.25-dev.2', 'alpha': 'v2.5.25-dev.3-alpha2'})
        run(s3, '--channel-tag', 'prod=v2.5.24')
        self.assertIn('v2.5.23', s3.tags())
        self.assertIn('v2.5.24', s3.tags())

    def test_the_release_being_published_stays(self):
        s3 = FakeS3(['v2.5.24', 'v2.5.25', 'v2.5.25-dev.2', 'v2.5.25-dev.3-alpha2'],
                    {'prod': 'v2.5.24', 'dev': 'v2.5.25-dev.2', 'alpha': 'v2.5.25-dev.3-alpha2'})
        run(s3, '--keep', 'v2.5.25', '--grace-hours', '0')
        self.assertIn('v2.5.25', s3.tags())

    def test_an_upload_in_progress_is_left_alone(self):
        s3 = FakeS3(['v2.5.24', 'v2.5.25-dev.2', 'v2.5.25-dev.3-alpha2', 'v2.5.25-dev.3-alpha3'],
                    {'prod': 'v2.5.24', 'dev': 'v2.5.25-dev.2', 'alpha': 'v2.5.25-dev.3-alpha2'},
                    recent=['v2.5.25-dev.3-alpha3'])
        run(s3)
        self.assertIn('v2.5.25-dev.3-alpha3', s3.tags())
        run(s3, '--grace-hours', '0')
        self.assertNotIn('v2.5.25-dev.3-alpha3', s3.tags())

    def test_an_unknown_channel_deletes_nothing(self):
        s3 = FakeS3(['v2.5.23', 'v2.5.24', 'v2.5.25-dev.2'], {'prod': 'v2.5.24', 'dev': 'v2.5.25-dev.2'})
        self.assertEqual(run(s3), 0)
        self.assertEqual(s3.deleted, [])
        run(s3, '--channel-tag', 'alpha=v2.5.25-dev.2')
        self.assertEqual(s3.tags(), ['v2.5.24', 'v2.5.25-dev.2'])

    def test_dry_run_deletes_nothing(self):
        s3 = FakeS3(['v2.5.23', 'v2.5.24'], {'prod': 'v2.5.24', 'dev': 'v2.5.24', 'alpha': 'v2.5.24'})
        run(s3, '--dry-run')
        self.assertEqual(s3.deleted, [])

    def test_only_release_folders_are_considered(self):
        s3 = FakeS3(['v2.5.23', 'v2.5.24'], {'prod': 'v2.5.24', 'dev': 'v2.5.24', 'alpha': 'v2.5.24'})
        s3.objects['ota/ci-test/x'] = OLD
        run(s3)
        self.assertIn('ota/ci-test/x', s3.objects)
        self.assertNotIn('v2.5.23', s3.tags())


if __name__ == '__main__':
    unittest.main()
