"""Small input and housekeeping fixes in sources_server.py and api_server.py.

  * SMB passwords with a comma or a leading '-' are accepted (they only go
    into the credentials file); server/share/user stay strict.
  * The playlist separator rewrite leaves double-byte encodings alone, and a
    pass over the playlist folder is bounded (depth, mounts, unchanged
    folders, network shares).
  * Pairing tokens: an unused one is handed out again, use is recorded,
    browser-session tokens expire, the list is capped.
  * Wi-Fi passwords starting with '-' are accepted.
  * The timezone list holds zones only, and set_timezone takes nothing else.
  * A device name the player name cannot follow is refused up front, and a
    player rename that fails is not reported as success.
  * /etc/hosts and the CamillaDSP config are written atomically.

Run with:  TMPDIR=<somewhere> python3 -m unittest tests.test_low_fixes_srv_api
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import api_server  # noqa: E402
import sources_server as ss  # noqa: E402


def _iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


# ── 1. SMB password ──────────────────────────────────────────────────────
class SmbPasswordTests(unittest.TestCase):
    def test_comma_and_leading_dash_are_a_password(self):
        for pw in ("a,b", "-secret", "--x,y=z", "p@ss word", ""):
            self.assertTrue(ss._password_ok(pw), pw)

    def test_line_breaks_would_break_the_credentials_file(self):
        for pw in ("a\nusername=root", "a\rb", "a\x00b", "a\x7fb"):
            self.assertFalse(ss._password_ok(pw), repr(pw))

    def test_the_other_fields_stay_strict(self):
        self.assertFalse(ss._field_ok("user,uid=0"))
        self.assertFalse(ss._field_ok("-oexec"))

    def test_shares_and_test_routes_take_such_a_password(self):
        client = ss.app.test_client()
        with patch.object(ss, "_smb_reachable", lambda server: False):
            r = client.post("/api/sources/smb/shares",
                            json={"server": "nas", "username": "me", "password": "-a,b"})
            self.assertEqual(r.get_json().get("code"), "msg.smbUnreachable")
            r = client.post("/api/sources/smb/test",
                            json={"server": "nas", "share": "music",
                                  "username": "me", "password": "-a,b"})
            self.assertEqual(r.get_json().get("code"), "msg.smbUnreachable")
            r = client.post("/api/sources/smb/test",
                            json={"server": "nas", "share": "music",
                                  "username": "-me", "password": "x"})
            self.assertEqual(r.get_json().get("code"), "msg.smbFieldsRequired")

    def test_mount_takes_it_too(self):
        src = {"server": "nas", "share": "music", "mountpoint": "/nonexistent/x",
               "username": "me", "password": "-a,b"}
        ok, msg, _ = ss._mount_smb_locked(dict(src, mountpoint="/"))
        # Past the field check: it stops at the mountpoint check instead.
        self.assertFalse(ok)
        self.assertNotEqual(msg, ss._ht('mount.invalidFields', ss._hlang()))
        bad = dict(src, password="a\nb", mountpoint="/")
        ok, msg, _ = ss._mount_smb_locked(bad)
        self.assertEqual(msg, ss._ht('mount.invalidFields', ss._hlang()))


# ── 2. Playlist normaliser ──────────────────────────────────────────────
class PlaylistEncodingTests(unittest.TestCase):
    def norm(self, raw):
        return ss._normalize_playlist_bytes(raw, False)

    def test_shift_jis_trail_bytes_are_not_separators(self):
        raw = "Music\\表示\\ソング.flac\n".encode("shift_jis")
        out, changed = self.norm(raw)
        self.assertFalse(changed)
        self.assertEqual(out, raw)

    def test_big5_is_left_alone(self):
        raw = "D:\\音樂\\許.flac\n".encode("big5")
        out, changed = self.norm(raw)
        self.assertFalse(changed)
        self.assertEqual(out, raw)

    def test_utf8_with_accents_is_still_fixed(self):
        out, changed = self.norm("Music\\Café\\a.flac\n".encode("utf-8"))
        self.assertTrue(changed)
        self.assertEqual(out, "Music/Café/a.flac\n".encode("utf-8"))

    def test_cp1252_with_separators_after_ascii_is_still_fixed(self):
        out, changed = self.norm(b"Music\\Bj\xf6rk\\a.flac\n")
        self.assertTrue(changed)
        self.assertEqual(out, b"Music/Bj\xf6rk/a.flac\n")

    def test_utf16_is_left_alone(self):
        raw = "Music\\a.flac\n".encode("utf-16")
        out, changed = self.norm(raw)
        self.assertFalse(changed)
        self.assertEqual(out, raw)


class PlaylistWalkTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="hifi-pl-walk-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        ss._playlist_seen.clear()
        ss._playlist_dirs.clear()
        self.addCleanup(ss._playlist_dirs.clear)
        self.addCleanup(ss._playlist_seen.clear)

    def write(self, rel, raw=b"Music\\a.flac\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        self.age(path)
        return path

    def age(self, path, seconds=3600):
        old = time.time() - seconds
        os.utime(path, (old, old))

    def age_dirs(self):
        for dirpath, _d, _f in os.walk(self.root):
            self.age(dirpath)

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_depth_is_bounded(self):
        near = self.write("a/b/near.m3u")
        deep = self.write("/".join("d%d" % i for i in range(ss.NORMALIZE_MAX_DEPTH + 1)) + "/deep.m3u")
        self.age_dirs()
        ss._normalize_playlists(self.root)
        self.assertEqual(self.read(near), b"Music/a.flac\n")
        self.assertEqual(self.read(deep), b"Music\\a.flac\n")

    def test_a_mount_inside_the_folder_is_not_entered(self):
        inside = self.write("nas/list.m3u")
        mine = self.write("mine.m3u")
        self.age_dirs()
        table = {os.path.join(self.root, "nas"): [("cifs", "rw")]}
        with patch.object(ss, "_mount_table", lambda: table):
            ss._normalize_playlists(self.root)
        self.assertEqual(self.read(inside), b"Music\\a.flac\n")
        self.assertEqual(self.read(mine), b"Music/a.flac\n")

    def test_an_unchanged_folder_is_not_listed_again(self):
        self.write("sub/one.m3u", b"/music/a.flac\n")
        self.age_dirs()
        ss._normalize_playlists(self.root)
        listed = []
        real_scandir = os.scandir

        def counting(path):
            listed.append(path)
            return real_scandir(path)
        with patch.object(ss.os, "scandir", counting):
            ss._normalize_playlists(self.root)
        self.assertEqual(listed, [])
        # A playlist rewritten in place (folder mtime unchanged) is still seen.
        path = os.path.join(self.root, "sub", "one.m3u")
        with open(path, "wb") as f:
            f.write(b"Music\\b.flac\n")
        self.age(path, 1800)
        with patch.object(ss.os, "scandir", counting):
            ss._normalize_playlists(self.root)
        self.assertEqual(listed, [])
        self.assertEqual(self.read(path), b"Music/b.flac\n")

    def test_a_new_file_shows_up(self):
        self.write("one.m3u", b"/music/a.flac\n")
        self.age_dirs()
        ss._normalize_playlists(self.root)
        new = self.write("two.m3u")
        ss._normalize_playlists(self.root)       # folder mtime moved
        self.assertEqual(self.read(new), b"Music/a.flac\n")

    def test_file_budget(self):
        paths = [self.write("p%02d.m3u" % i) for i in range(5)]
        self.age_dirs()
        with patch.object(ss, "NORMALIZE_MAX_FILES", 2):
            ss._normalize_playlists(self.root)
        fixed = [p for p in paths if self.read(p) == b"Music/a.flac\n"]
        self.assertEqual(len(fixed), 2)

    def test_a_folder_on_a_share_is_looked_at_rarely(self):
        with patch.object(ss, "_on_network_fs", lambda p, table=None: True), \
             patch.object(ss, "_playlist_last_net_pass", 0.0):
            now = time.time()
            self.assertTrue(ss._playlist_pass_due("/mnt/nas/pl", now))
            self.assertFalse(ss._playlist_pass_due("/mnt/nas/pl", now + 60))
            self.assertTrue(ss._playlist_pass_due("/mnt/nas/pl",
                                                  now + ss.NORMALIZE_NET_INTERVAL_S + 1))
        with patch.object(ss, "_on_network_fs", lambda p, table=None: False):
            self.assertTrue(ss._playlist_pass_due("/data/playlists", time.time()))


# ── 3. Pairing tokens ───────────────────────────────────────────────────
class PairTokenTests(unittest.TestCase):
    LAN = {"REMOTE_ADDR": "192.168.1.50"}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hifi-pair-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = patch.object(ss, "PAIR_TOKENS_FILE", os.path.join(self.dir, "tokens.json"))
        p.start()
        self.addCleanup(p.stop)
        ss._auth_fail_log.clear()
        self.addCleanup(ss._auth_fail_log.clear)
        self.client = ss.app.test_client()

    def mint(self, **body):
        r = self.client.post("/api/pair/token", json=body)
        self.assertEqual(r.status_code, 200)
        return r.get_json()["token"]

    def use(self, token):
        return self.client.get("/api/sources/smb/discover", environ_base=self.LAN,
                               headers={"Authorization": "Bearer " + token}).status_code

    def stored(self):
        with open(ss.PAIR_TOKENS_FILE) as f:
            return json.load(f)

    def store(self, tokens):
        with open(ss.PAIR_TOKENS_FILE, "w") as f:
            json.dump(tokens, f)

    def test_minting_is_localhost_only(self):
        r = self.client.post("/api/pair/token", json={}, environ_base=self.LAN)
        self.assertEqual(r.status_code, 403)

    def test_an_unused_token_is_handed_out_again(self):
        a = self.mint()
        b = self.mint()
        self.assertEqual(a, b)
        self.assertEqual(len(self.stored()), 1)

    def test_once_a_phone_used_it_the_next_gets_its_own(self):
        a = self.mint()
        self.assertEqual(self.use(a), 200)
        self.assertIn("last_used", self.stored()[0])
        b = self.mint()
        self.assertNotEqual(a, b)
        self.assertEqual(self.use(a), 200)
        self.assertEqual(self.use(b), 200)

    def test_a_used_phone_token_does_not_expire(self):
        self.store([{"token": "old-phone", "created": _iso(400 * 86400),
                     "last_used": _iso(200 * 86400)}])
        self.assertEqual(self.use("old-phone"), 200)

    def test_last_use_is_not_rewritten_on_every_request(self):
        a = self.mint()
        self.use(a)
        first = self.stored()[0]["last_used"]
        time.sleep(0.01)
        self.use(a)
        self.assertEqual(self.stored()[0]["last_used"], first)

    def test_browser_tokens_are_reused_and_kept_apart(self):
        app = self.mint()
        b1 = self.mint(purpose="browser")
        self.use(b1)                       # a browser token in use is still reused
        b2 = self.mint(purpose="browser")
        self.assertEqual(b1, b2)
        self.assertNotEqual(app, b1)
        self.assertEqual(self.mint(), app)

    def test_browser_tokens_expire(self):
        self.store([{"token": "stale", "created": _iso(40 * 86400), "purpose": "browser"},
                    {"token": "phone", "created": _iso(40 * 86400)}])
        self.assertEqual(self.use("stale"), 401)
        self.assertEqual([t["token"] for t in self.stored()], ["phone"])
        self.assertEqual(self.use("phone"), 200)

    def test_an_old_browser_token_is_not_reused(self):
        self.store([{"token": "week-old", "purpose": "browser",
                     "created": _iso(ss.PAIR_BROWSER_REUSE_S + 60)}])
        self.assertNotEqual(self.mint(purpose="browser"), "week-old")

    def test_the_list_is_capped_idle_ones_first(self):
        tokens = [{"token": "t%02d" % i, "created": _iso(100 * 86400),
                   "last_used": _iso((40 - i) * 86400)} for i in range(30)]
        tokens += [{"token": "br%d" % i, "created": _iso(3600), "purpose": "browser"}
                   for i in range(3)]
        self.store(tokens)
        self.mint()
        kept = [t["token"] for t in self.stored()]
        self.assertEqual(len(kept), ss.PAIR_TOKENS_MAX)
        self.assertIn("t29", kept)            # the most recently used phone
        self.assertNotIn("t00", kept)         # the one idle the longest
        self.assertFalse([k for k in kept if k.startswith("br")])

    def test_revoke_all_still_clears_everything(self):
        a = self.mint()
        self.client.post("/api/pair/tokens/revoke_all", json={})
        self.assertEqual(self.use(a), 401)
        self.assertNotEqual(self.mint(), a)

    def test_old_files_keep_working(self):
        # The format before this change: no purpose, no last_used.
        self.store([{"token": "legacy", "created": "2026-01-01T00:00:00+00:00"}])
        self.assertEqual(self.use("legacy"), 200)
        self.assertEqual(self.use("nope"), 401)


# ── 4. Wi-Fi password ───────────────────────────────────────────────────
class WifiPasswordTests(unittest.TestCase):
    def connect(self, ssid, password):
        joined = []

        def fake_join(s, p, dev, band=''):
            joined.append((s, p))
            import subprocess
            return subprocess.CompletedProcess([], 1, '', 'nope')
        with patch.object(api_server, '_wifi_join', fake_join), \
             patch.object(api_server, '_first_device_of_type', lambda t: 'wlan0'), \
             patch.object(api_server, '_ensure_networkmanager_state', lambda *a: None):
            result = api_server.wifi_connect(ssid, password)
        return result, joined

    def test_a_password_may_start_with_a_dash(self):
        result, joined = self.connect('HomeNet', '-Summer2024')
        self.assertEqual(joined, [('HomeNet', '-Summer2024')])
        self.assertNotEqual(result.get('code'), 'network.invalidField')

    def test_control_characters_are_still_refused(self):
        result, joined = self.connect('HomeNet', 'abc\ndef')
        self.assertEqual(result.get('code'), 'network.invalidField')
        self.assertEqual(joined, [])

    def test_an_ssid_still_may_not(self):
        result, joined = self.connect('-HomeNet', 'secret')
        self.assertEqual(result.get('code'), 'network.invalidField')
        self.assertEqual(joined, [])


# ── 5. Timezones ────────────────────────────────────────────────────────
class TimezoneListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="hifi-tz-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.zoneinfo = os.path.join(self.tmp, 'zoneinfo')
        for zone in ('Europe/Rome', 'UTC', 'posixrules', 'Factory', 'right/Europe/Rome'):
            self.put(zone, b'TZif2...')
        for name in ('leapseconds', 'SECURITY'):
            self.put(name, b'# text\n')
        self.put('zone1970.tab', b'# tab\n')
        self.put('leap-seconds.list', b'# list\n')
        # trixie: zoneinfo/localtime -> /etc/localtime, itself a TZif file.
        etc = os.path.join(self.tmp, 'etc')
        os.makedirs(etc)
        self.localtime = os.path.join(etc, 'localtime')
        os.symlink(os.path.join(self.zoneinfo, 'UTC'), self.localtime)
        os.symlink(self.localtime, os.path.join(self.zoneinfo, 'localtime'))
        for name, value in (('ZONEINFO_DIR', self.zoneinfo),
                            ('LOCALTIME_LINK', self.localtime),
                            ('TIMEZONE_FILE', os.path.join(etc, 'timezone'))):
            p = patch.object(api_server, name, value)
            p.start()
            self.addCleanup(p.stop)

    def put(self, rel, data):
        path = os.path.join(self.zoneinfo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)

    def test_only_zones_are_listed(self):
        self.assertEqual(api_server.list_timezones(), ['Europe/Rome', 'UTC'])

    def test_set_timezone_refuses_what_is_not_listed(self):
        with patch.object(api_server.subprocess, 'run') as run:
            for tz in ('localtime', 'leapseconds', 'posixrules', 'right/Europe/Rome',
                       'zone1970.tab', 'Factory'):
                result = api_server.set_timezone(tz)
                self.assertFalse(result['success'], tz)
                self.assertEqual(result['code'], 'timezone.invalid', tz)
            run.assert_not_called()
        self.assertEqual(os.readlink(self.localtime), os.path.join(self.zoneinfo, 'UTC'))


# ── 6. Device name ──────────────────────────────────────────────────────
class DeviceNameTests(unittest.TestCase):
    def setUp(self):
        self.applied = []
        self.player = {'success': True}
        for name, value in (('_apply_hostname', lambda n: self.applied.append(n) or
                             {'success': True, 'name': n}),
                            ('set_player_name', lambda n: dict(self.player, name=n))):
            p = patch.object(api_server, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_a_name_the_player_cannot_take_is_refused_up_front(self):
        result = api_server.set_device_name('A' * 25)
        self.assertFalse(result['success'])
        self.assertEqual(result['code'], 'device.invalidName')
        self.assertEqual(self.applied, [])

    def test_24_characters_go_through(self):
        result = api_server.set_device_name('Living-Room-Stereo-0001')
        self.assertTrue(result['success'], result)

    def test_a_failed_player_rename_is_not_success(self):
        self.player = {'success': False, 'code': 'lms.sqConfigMissing'}
        result = api_server.set_device_name('Kitchen')
        self.assertFalse(result['success'])
        self.assertEqual(result['code'], 'device.playerNameFailed')
        self.assertIn('Kitchen', result['message'])

    def test_the_message_exists_in_both_languages(self):
        from hifi_i18n import MESSAGES
        self.assertEqual(set(MESSAGES['device.playerNameFailed']), {'en', 'it'})
        self.assertIn('24', MESSAGES['device.invalidName']['en'])
        self.assertIn('24', MESSAGES['device.invalidName']['it'])

    def test_hostname_apply_still_takes_a_restored_long_name(self):
        self.assertTrue(api_server._valid_device_name('A' * 32))


# ── 7. Atomic writes ────────────────────────────────────────────────────
class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="hifi-atomic-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_mode_kept_symlink_followed_nothing_left_behind(self):
        real = os.path.join(self.dir, 'real-hosts')
        with open(real, 'w') as f:
            f.write('127.0.0.1\tlocalhost\n127.0.1.1\told\n')
        os.chmod(real, 0o644)
        link = os.path.join(self.dir, 'hosts')
        os.symlink(real, link)
        with patch.object(api_server, 'ETC_HOSTS', link):
            api_server._set_etc_hosts_hostname('newname')
        self.assertTrue(os.path.islink(link))
        with open(real) as f:
            self.assertEqual(f.read(), '127.0.0.1\tlocalhost\n127.0.1.1\tnewname\n')
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o644)
        self.assertEqual(sorted(os.listdir(self.dir)), ['hosts', 'real-hosts'])

    def test_a_failed_write_leaves_the_old_file(self):
        path = os.path.join(self.dir, 'config.yml')
        with open(path, 'w') as f:
            f.write('old')
        with patch.object(api_server.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                api_server._write_file_atomic(path, 'new')
        with open(path) as f:
            self.assertEqual(f.read(), 'old')
        self.assertEqual(os.listdir(self.dir), ['config.yml'])


if __name__ == '__main__':
    unittest.main()
