"""Tests for the Licenses & credits page: distro/gen-credits.py (the Debian
package list written at image build) and api_server.py's /credits.

Hermetic: a fake chroot in a temporary folder. When the build chroot
/srv/trixie is around, one extra test runs the generator on the real thing.

Run with:  python3 tests/test_credits.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location('gen_credits', os.path.join(ROOT, 'distro', 'gen-credits.py'))
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)

STATUS = """Package: squeezelite
Status: install ok installed
Priority: optional
Section: sound
Installed-Size: 300
Maintainer: Debian Multimedia Maintainers <debian-multimedia@lists.debian.org>
Architecture: amd64
Version: 2.0.0-1517+git20241227.262994a-1
Depends: libasound2t64 (>= 1.0.16)
Description: lightweight headless Squeezebox emulator
 Long description here.
Homepage: https://github.com/ralph-irving/squeezelite

Package: libfoo1
Status: install ok installed
Architecture: amd64
Source: foo (1.2-3)
Version: 1.2-3
Description: foo library

Package: oldstyle
Status: install ok installed
Architecture: all
Version: 0.1
Description: free-form copyright

Package: removed-pkg
Status: deinstall ok config-files
Architecture: all
Version: 9
Description: not installed any more

Package: nodoc
Status: install ok installed
Architecture: all
Version: 1
Description: no copyright file at all
"""

DEP5 = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: squeezelite

Files: *
Copyright: 2012-2015 Adrian Smith, 2015-2024 Ralph Irving
License: GPL-3.0+

Files: debian/*
Copyright: 2014 Chris Boot
License: GPL-3.0+

License: GPL-3.0+
 This program is free software: you can redistribute it and/or modify
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in /usr/share/common-licenses/GPL-3.
"""

DEP5_TWO = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/

Files: *
License: LGPL-2.1+

Files: debian/*
License: MIT
"""

FREEFORM = """This package was debianized by Someone <someone@debian.org> on 2003.

Copyright (C) 2001 Example Inc.

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License.
"""


class FakeChroot:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='credits-')
        os.makedirs(os.path.join(self.dir, 'var', 'lib', 'dpkg'))
        with open(os.path.join(self.dir, 'var', 'lib', 'dpkg', 'status'), 'w') as f:
            f.write(STATUS)
        os.makedirs(os.path.join(self.dir, 'etc'))
        with open(os.path.join(self.dir, 'etc', 'os-release'), 'w') as f:
            f.write('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nVERSION_CODENAME=trixie\n')

    def doc(self, pkg, text):
        d = os.path.join(self.dir, 'usr', 'share', 'doc', pkg)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'copyright'), 'w') as f:
            f.write(text)

    def doc_link(self, pkg, target):
        d = os.path.join(self.dir, 'usr', 'share', 'doc')
        os.makedirs(d, exist_ok=True)
        os.symlink(target, os.path.join(d, pkg))


class TestParsing(unittest.TestCase):
    def test_status(self):
        pkgs = gc.parse_status(STATUS)
        names = [p['name'] for p in pkgs]
        self.assertEqual(names, ['squeezelite', 'libfoo1', 'oldstyle', 'nodoc'])   # the removed one is skipped
        sq = pkgs[0]
        self.assertEqual(sq['version'], '2.0.0-1517+git20241227.262994a-1')
        self.assertEqual(sq['homepage'], 'https://github.com/ralph-irving/squeezelite')
        self.assertEqual(pkgs[1]['source'], 'foo')     # version stripped

    def test_licenses(self):
        self.assertEqual(gc.licenses_from_copyright(DEP5), 'GPL-3.0+')
        self.assertEqual(gc.licenses_from_copyright(DEP5_TWO), 'LGPL-2.1+, MIT')
        self.assertEqual(gc.licenses_from_copyright(FREEFORM), 'GPL')
        self.assertEqual(gc.licenses_from_copyright(''), gc.UNKNOWN)
        self.assertEqual(gc.licenses_from_copyright('Copyright 2001 Nobody. All rights reserved.'), gc.UNKNOWN)
        both = FREEFORM + '\nParts are in the public domain.\n'
        self.assertEqual(gc.licenses_from_copyright(both), 'GPL, public-domain')


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.ch = FakeChroot()
        self.ch.doc('squeezelite', DEP5)
        self.ch.doc('foo', DEP5_TWO)             # libfoo1's docs live under the source name
        self.ch.doc_link('libfoo1', 'foo')
        self.ch.doc('oldstyle', FREEFORM)

    def test_build(self):
        data = gc.build(self.ch.dir)
        self.assertEqual(data['suite'], 'trixie')
        self.assertEqual(data['count'], 4)
        by = {p['name']: p for p in data['packages']}
        self.assertEqual(by['squeezelite']['license'], 'GPL-3.0+')
        self.assertEqual(by['libfoo1']['license'], 'LGPL-2.1+, MIT')   # through the symlink
        self.assertEqual(by['oldstyle']['license'], 'GPL')
        self.assertEqual(by['nodoc']['license'], gc.UNKNOWN)
        self.assertEqual([p['name'] for p in data['packages']], sorted(by))

    def test_main_writes_json(self):
        out = os.path.join(self.ch.dir, 'usr', 'lib', 'osmium', 'credits.json')
        self.assertEqual(gc.main(['x', self.ch.dir, out]), 0)
        with open(out) as f:
            data = json.load(f)
        self.assertEqual(data['count'], 4)
        self.assertFalse(os.path.exists(out + '.tmp'))
        self.assertEqual(gc.main(['x']), 2)

    @unittest.skipUnless(os.path.exists('/srv/trixie/var/lib/dpkg/status'), 'build chroot not here')
    def test_real_chroot(self):
        data = gc.build('/srv/trixie')
        self.assertGreater(data['count'], 100)
        known = sum(1 for p in data['packages'] if p['license'] != gc.UNKNOWN)
        self.assertGreater(known / data['count'], 0.9, 'most packages have a recognisable license')


class TestApi(unittest.TestCase):
    def setUp(self):
        import api_server
        self.api = api_server
        self.tmp = tempfile.mkdtemp(prefix='credits-api-')
        self._saved = {}
        self._patch('CREDITS_FILE', os.path.join(self.tmp, 'credits.json'))
        self._patch('THIRD_PARTY_FILE', os.path.join(self.tmp, 'third_party.json'))
        self._patch('_installed_ui_version', lambda: '2.5.25-dev.10-alpha1')
        self._patch('_lyrion_installed_version', lambda: '9.2.0')

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.api, k, v)

    def _patch(self, name, value):
        self._saved[name] = getattr(self.api, name)
        setattr(self.api, name, value)

    def test_without_files(self):
        c = self.api.get_credits()
        self.assertEqual(c['project']['license'], 'AGPL-3.0-only')
        self.assertEqual(c['project']['version'], '2.5.25-dev.10-alpha1')
        self.assertEqual(c['lyrion']['name'], 'Lyrion Music Server')
        self.assertEqual(c['lyrion']['version'], '9.2.0')
        self.assertEqual(c['notices'], [])
        self.assertEqual(c['packages'], [])
        self.assertFalse(c['packages_available'])

    def test_with_files(self):
        with open(self.api.CREDITS_FILE, 'w') as f:
            json.dump({'generated': '2026-10-01', 'suite': 'trixie', 'count': 1,
                       'packages': [{'name': 'squeezelite', 'version': '2.0.0', 'license': 'GPL-3.0+', 'homepage': ''}]}, f)
        with open(self.api.THIRD_PARTY_FILE, 'w') as f:
            json.dump([{'section': 'Bundled', 'entries': [{'name': 'Qt 6', 'license': 'LGPL-3.0'}]}], f)
        c = self.api.get_credits()
        self.assertTrue(c['packages_available'])
        self.assertEqual(c['packages'][0]['name'], 'squeezelite')
        self.assertEqual(c['suite'], 'trixie')
        self.assertEqual(c['packages_generated'], '2026-10-01')
        self.assertEqual(c['notices'][0]['entries'][0]['license'], 'LGPL-3.0')

    def test_broken_files(self):
        with open(self.api.CREDITS_FILE, 'w') as f:
            f.write('{ nope')
        with open(self.api.THIRD_PARTY_FILE, 'w') as f:
            f.write('"a string"')
        c = self.api.get_credits()
        self.assertEqual(c['packages'], [])
        self.assertEqual(c['notices'], [])


if __name__ == '__main__':
    unittest.main()
