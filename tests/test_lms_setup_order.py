"""Order of the first-run Lyrion setup job (_lms_setup_apply in sources_server).

The playlist folder has to be written before the plugins go in: it stops and
starts Lyrion when it writes server.prefs, and after the plugin install that
stop landed two seconds into the server extracting the new plugins. When it
did restart Lyrion, the plugin install must wait for that start to finish,
since a server stopped before loading its prefs rewrites them on the way out.

Run with:  python tests/test_lms_setup_order.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import sources_server as ss  # noqa: E402


class LmsSetupOrderTests(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        self.calls = []
        self.restarted = True
        self._patch('_ensure_prefs', lambda: '/tmp/server.prefs')
        self._patch('ensure_playlistdir', lambda: (self.calls.append('playlistdir'), self.restarted)[1])
        self._patch('_lyrion_wait_up', lambda: (self.calls.append('wait'), True)[1])
        self._patch('_ensure_plugins_installed',
                    lambda names, builtins: (self.calls.append('plugins'), (list(names), []))[1])
        self._patch('_set_lms_pref', lambda name, value: (self.calls.append('pref:' + name), True)[1])
        self._patch('_lyrion_rescan', lambda: self.calls.append('rescan'))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(ss, name, value)

    def _patch(self, name, value):
        self._saved[name] = getattr(ss, name)
        setattr(ss, name, value)

    def test_playlist_folder_then_wait_then_plugins(self):
        ss._lms_setup_apply(['Spotty'], False, 'it')
        self.assertEqual(self.calls[:3], ['playlistdir', 'wait', 'plugins'])
        self.assertEqual(self.calls[-2:], ['pref:' + ss.LMS_WIZARD_DONE_PREF, 'rescan'])
        self.assertEqual(ss._lms_setup_status()['state'], 'done')

    def test_no_wait_when_the_folder_was_already_set(self):
        self.restarted = False
        ss._lms_setup_apply([], False, 'en')
        self.assertEqual(self.calls[:2], ['playlistdir', 'plugins'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
