"""ensure_playlistdir() must not undo what Lyrion had in memory.

Lyrion writes a changed pref to server.prefs 10 seconds later (Slim::Utils::
Prefs::Namespace::save) and flushes everything when it stops. In the setup
wizard the skin step sets skin=material live, and the next step (the plugins,
which the owner can skip in a second) starts with ensure_playlistdir(). It
used to read server.prefs first, then stop Lyrion — which flushed skin=material
to disk — and then write its older copy back: the web player came up in the
default skin, "the wizard no longer turns on Material". It must read the file
again once Lyrion is down.

Run with:  python tests/test_playlistdir_keeps_live_prefs.py
"""
import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import sources_server as ss  # noqa: E402


class PlaylistdirKeepsLivePrefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.prefs = os.path.join(self.tmp, 'server.prefs')
        # on disk: what Lyrion last flushed — no playlist folder, default skin
        with open(self.prefs, 'w') as f:
            yaml.safe_dump({'skin': 'Default', 'language': 'EN'}, f)
        self._saved = {}

        def run(cmd, timeout=None):
            # "systemctl stop": Lyrion flushes what it had in memory
            if 'stop' in cmd:
                with open(self.prefs) as f:
                    data = yaml.safe_load(f) or {}
                data['skin'] = 'material'
                with open(self.prefs, 'w') as f:
                    yaml.safe_dump(data, f)
            return 0, '', ''

        def provision(data):
            if data.get('playlistdir'):
                return data, False
            data = dict(data)
            data['playlistdir'] = '/music/Playlists'
            return data, True

        self._patch('_find_prefs', lambda: self.prefs)
        self._patch('_run', run)
        self._patch('_systemctl_lyrion', lambda action: None)
        self._patch('_provision_playlistdir', provision)
        self._patch('_squeezebox_ids', lambda: (None, None))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(ss, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(ss, name)
        setattr(ss, name, value)

    def test_the_skin_set_live_survives_the_playlist_folder(self):
        self.assertTrue(ss.ensure_playlistdir())
        with open(self.prefs) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['playlistdir'], '/music/Playlists')
        self.assertEqual(data['skin'], 'material', 'the stale copy put the default skin back')
        self.assertEqual(data['language'], 'EN')


if __name__ == '__main__':
    unittest.main(verbosity=2)
