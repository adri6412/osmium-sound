#!/usr/bin/env python3
"""Keep only the newest OTA release of each channel on file.osmiumsound.it.

Every release, stable or not, is uploaded to the R2 bucket behind
file.osmiumsound.it as ``ota/<tag>/<asset>`` (see build-ui-ota.yml), and the
manifests the devices read point there. Nothing ever needs an older one: a
device only ever installs the release its channel's manifest names, so every
``ota/<tag>/`` folder that no channel names any more is dead weight — about a
gigabyte each, against a 10 GB free tier.

Usage:
    prune-ota-r2.py [--channel-tag CH=TAG ...] [--keep TAG ...]
                    [--grace-hours N] [--dry-run]

What stays:
  * the tag named by each channel's manifest: ``--channel-tag`` (the workflow
    passes what gh-pages, i.e. the Pages manifest the devices read first,
    says) plus ``ota/latest-<channel>.json`` in the bucket, the mirror the
    devices read when Pages is down. Both, when they disagree: a device may be
    reading either one;
  * every ``--keep`` tag (the release being published right now);
  * any folder written in the last ``--grace-hours`` hours: a release of
    another channel may be uploading at this very moment, and its manifest
    does not name it yet.

If a channel's tag cannot be found in either place, nothing is deleted: not
knowing what a channel points at is no reason to take its files away.

Environment: R2_ENDPOINT, R2_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY.
"""
import argparse
import datetime
import json
import os
import re
import sys

CHANNELS = ('prod', 'dev', 'alpha')
# Release tags only (v2.5.24, v2.5.25-dev.3-alpha2, …): whatever else may one
# day live under ota/ is not this script's business.
TAG_RE = re.compile(r'^v\d+\.\d+\.\d+[0-9A-Za-z.-]*$')


def group_by_tag(objects):
    """{tag: [objects]} for the keys shaped ota/<tag>/<file>."""
    out = {}
    for o in objects:
        parts = o['Key'].split('/')
        if len(parts) >= 3 and parts[0] == 'ota' and TAG_RE.match(parts[1]):
            out.setdefault(parts[1], []).append(o)
    return out


def plan(objects, keep, grace_hours, now):
    """(to delete {tag: [keys]}, kept-for-grace [tags]) for the listed objects."""
    delete, recent = {}, []
    limit = now - datetime.timedelta(hours=grace_hours)
    for tag, objs in sorted(group_by_tag(objects).items()):
        if tag in keep:
            continue
        if max(o['LastModified'] for o in objs) > limit:
            recent.append(tag)
            continue
        delete[tag] = [o['Key'] for o in objs]
    return delete, recent


def mirror_tags(s3, bucket):
    """{channel: tag} from the ota/latest-<channel>.json mirrors in the bucket."""
    out = {}
    for ch in CHANNELS:
        try:
            body = s3.get_object(Bucket=bucket, Key=f'ota/latest-{ch}.json')['Body'].read()
            tag = json.loads(body).get('tag_name') or ''
        except Exception as e:  # missing mirror, or unreadable
            if 'NoSuchKey' not in repr(e) and '404' not in repr(e):
                raise
            continue
        if tag:
            out[ch] = tag
    return out


def list_ota(s3, bucket):
    objs = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='ota/'):
        objs.extend(page.get('Contents', []))
    return objs


def summary(lines):
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


def main(argv=None, s3=None, now=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel-tag', action='append', default=[], metavar='CH=TAG')
    ap.add_argument('--keep', action='append', default=[], metavar='TAG')
    ap.add_argument('--grace-hours', type=float, default=3)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    bucket = os.environ.get('R2_BUCKET', 'osmium-sound-iso-beta')
    if s3 is None:
        import boto3
        s3 = boto3.client('s3', endpoint_url=os.environ['R2_ENDPOINT'], region_name='auto')
    now = now or datetime.datetime.now(datetime.timezone.utc)

    named = {ch: set() for ch in CHANNELS}
    for kv in args.channel_tag:
        ch, _, tag = kv.partition('=')
        if ch in named and tag:
            named[ch].add(tag)
    for ch, tag in mirror_tags(s3, bucket).items():
        named[ch].add(tag)
    unknown = [ch for ch in CHANNELS if not named[ch]]
    if unknown:
        print(f"::warning::no manifest names a release for channel(s) {', '.join(unknown)}: "
              "nothing deleted")
        return 0

    keep = set(args.keep).union(*named.values())
    delete, recent = plan(list_ota(s3, bucket), keep, args.grace_hours, now)

    lines = ['### OTA releases on file.osmiumsound.it', '']
    for ch in CHANNELS:
        lines.append(f"- {ch}: {', '.join(sorted(named[ch]))}")
    for tag in recent:
        lines.append(f'- {tag}: written less than {args.grace_hours:g} h ago, left for the next run')
    verb = 'would delete' if args.dry_run else 'deleted'
    for tag, keys in delete.items():
        lines.append(f'- {tag}: {verb} ({len(keys)} files)')
        if args.dry_run:
            continue
        for i in range(0, len(keys), 1000):
            res = s3.delete_objects(Bucket=bucket, Delete={
                'Objects': [{'Key': k} for k in keys[i:i + 1000]], 'Quiet': True})
            if res.get('Errors'):
                print(f"::error::deleting ota/{tag}/ failed: {res['Errors'][:3]}")
                return 1
    if not delete:
        lines.append('- nothing to delete')
    print('\n'.join(lines))
    summary(lines)
    return 0


if __name__ == '__main__':
    sys.exit(main())
