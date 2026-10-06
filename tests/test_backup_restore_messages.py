"""Backup/restore and first-boot setup: what reaches the owner, and in which
language.

- Lyrion plugins that sign in to a streaming service (TIDAL, Qobuz, Spotty…)
  keep that login in their prefs: an unencrypted backup must leave those files
  out, like every other secret, while older backups that carried them still
  restore.
- Every hifi_backup.BackupError has an i18n code, and the backup worker writes
  codes that /api/backup/status translates for whoever asks; a restore job
  speaks the language of the request that started it.
- A restore that replaces webui.db logs the web admin out: the device reboots
  by itself (not during first-boot setup, where the wizard does it).
- Finishing first-boot setup from a restore keeps the display mode the backup
  put back, instead of forcing the screen on.
- The admin page never asks for a translation key the catalogues lack, and
  webui_server.py compiles without escape-sequence warnings.

Run with:  python3 -m unittest tests.test_backup_restore_messages
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('HIFI_PROVISION_FAKE', '1')

import hifi_backup as hb  # noqa: E402
import hifi_i18n  # noqa: E402
import sources_server as ss  # noqa: E402
import webui_server as w  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
PLUGIN = "/var/lib/squeezeboxserver/prefs/plugin/"


def _write(root, logical, content=b"x"):
    path = os.path.join(root, logical.lstrip("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hifi-msg-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class LyrionPluginLoginTests(_Tmp):
    def setUp(self):
        super().setUp()
        _write(self.tmp, PLUGIN + "tidal.prefs", b"_version: 1\nquality: HI_RES\n")
        _write(self.tmp, PLUGIN + "newservice.prefs",
               b"accounts:\n  42:\n    refreshToken: abc\n    name: me\n")
        _write(self.tmp, PLUGIN + "material-skin.prefs", b"_version: 1\ntheme: dark\n")
        _write(self.tmp, PLUGIN + "emptylogin.prefs", b"token: ''\npassword: ~\n")
        _write(self.tmp, "/var/lib/squeezeboxserver/prefs/server.prefs", b"playlistdir: /music\n")

    def _names(self, encrypted):
        dest = os.path.join(self.tmp, "out.tar.gz")
        manifest = hb.build_archive(dest, ["lyrion"], self.tmp, encrypted=encrypted)
        with tarfile.open(dest) as tar:
            names = set(tar.getnames())
        return names, manifest["notes"]

    def test_unencrypted_backup_leaves_the_logins_out(self):
        names, notes = self._names(False)
        p = PLUGIN.lstrip("/")
        self.assertNotIn(p + "tidal.prefs", names)        # a known login holder
        self.assertNotIn(p + "newservice.prefs", names)   # a nested token
        self.assertIn(p + "material-skin.prefs", names)   # plain settings stay
        self.assertIn(p + "emptylogin.prefs", names)      # nothing to hide in it
        self.assertIn("var/lib/squeezeboxserver/prefs/server.prefs", names)
        self.assertEqual(sum("lyrion-login-left-out" in n for n in notes), 2)

    def test_encrypted_backup_keeps_them(self):
        names, _ = self._names(True)
        p = PLUGIN.lstrip("/")
        for name in ("tidal.prefs", "newservice.prefs", "material-skin.prefs"):
            self.assertIn(p + name, names)

    def test_an_older_backup_that_carried_them_still_restores(self):
        dest = hb.restore_dest_for_member(PLUGIN.lstrip("/") + "tidal.prefs", ["lyrion"], self.tmp)
        self.assertEqual(dest, os.path.join(self.tmp, PLUGIN.lstrip("/"), "tidal.prefs"))


class BackupErrorCodeTests(_Tmp):
    def test_every_backup_error_has_a_translated_code(self):
        with open(os.path.join(REPO, "hifi_backup.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        raises = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "BackupError"]
        self.assertTrue(raises)
        for call in raises:
            code = next((k.value.value for k in call.keywords if k.arg == "code"), None)
            self.assertTrue(code, f"BackupError without a code at line {call.lineno}")
            entry = hifi_i18n.MESSAGES.get(code)
            self.assertTrue(entry and entry.get("en") and entry.get("it"), code)

    def test_garbage_and_missing_passphrase_carry_their_codes(self):
        junk = _write(self.tmp, "/junk.tar.gz", b"not a tarball")
        with self.assertRaises(hb.BackupError) as cm:
            hb.open_backup(junk, self.tmp)
        self.assertEqual(cm.exception.code, "restore.archiveInvalid")

        wrapper = os.path.join(self.tmp, "enc.tar.gz")
        _write(self.tmp, "/x.enc", b"ciphertext")
        hb.wrap_encrypted(wrapper, {"enc": {}}, os.path.join(self.tmp, "x.enc"))
        with self.assertRaises(hb.BackupError) as cm:
            hb.open_backup(wrapper, tempfile.mkdtemp(dir=self.tmp))
        self.assertEqual(cm.exception.code, "restore.passphraseRequired")


class BackupWorkerStatusTests(_Tmp):
    def _worker(self):
        path = os.path.join(REPO, "distro/config/includes.chroot/usr/local/sbin/hifi-backup-run.py")
        spec = importlib.util.spec_from_file_location("hifi_backup_run_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        out, err = sys.stdout, sys.stderr
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.stdout, sys.stderr = out, err
        return mod

    def test_worker_writes_codes_and_the_endpoint_translates_them(self):
        status = os.path.join(self.tmp, "status.json")
        mod = self._worker()
        mod.STATUS = status
        mod.write_status("done", 100, "backup.completed", {"count": 7}, id="g")
        with open(status) as f:
            raw = json.load(f)
        self.assertEqual(raw["code"], "backup.completed")
        self.assertEqual(raw["message"], "Backup completed: 7 file(s).")
        with patch.object(hb, "STATUS_FILE", status):
            c = ss.app.test_client()
            it = c.get("/api/backup/status", headers={"X-UI-Lang": "it"}).get_json()
            en = c.get("/api/backup/status", headers={"X-UI-Lang": "en"}).get_json()
        self.assertEqual(it["message"], "Backup completato: 7 file.")
        self.assertEqual(en["message"], "Backup completed: 7 file(s).")
        self.assertEqual(it["id"], "g")

    def test_no_italian_left_in_the_worker_status_calls(self):
        with open(os.path.join(REPO, "distro/config/includes.chroot/usr/local/sbin/hifi-backup-run.py")) as f:
            src = f.read()
        for m in re.finditer(r'(?<!def )\b(?:write_status|fail)\(([^)]*)\)', src):
            args = m.group(1)
            if args.startswith("code") or args.startswith('"error"'):
                continue   # the helpers' own bodies
            self.assertRegex(args, r'"backup\.\w+"|e\.code', m.group(0))


class RestoreJobTests(_Tmp):
    def setUp(self):
        super().setUp()
        self.statuses = []
        self.reboots = []
        patches = [
            patch.object(ss, "_write_restore_status",
                         lambda state, progress, message, **kw: self.statuses.append((state, message, kw))),
            patch.object(ss, "_snapshot_before_restore", lambda protect=(): "snap"),
            patch.object(ss, "RESTORE_REBOOT_DELAY", 0),
            patch.object(ss, "_reboot_after_restore", lambda: self.reboots.append(True)),
            patch.object(ss, "PROVISIONING_MARKER", os.path.join(self.tmp, "provisioning-pending")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # _run_restore_async is called on this very thread here
        self.addCleanup(lambda: ss._job_lang.__dict__.pop("lang", None))

    def _run(self, login_replaced, lang="it"):
        def fake_restore(path, passphrase, categories, report=None):
            report("restoring", 50, ss._ht("restore.preparing", ss._hlang()))
            return {"success": True, "message": "ok", "restored": 3,
                    "categories": ["accounts"], "login_replaced": login_replaced}, 200
        with patch.object(ss, "_restore_from_path", fake_restore):
            self.assertTrue(ss._RESTORE_LOCK.acquire(timeout=30))
            ss._run_restore_async("x", "", None, lang=lang)
        # the Timer runs on a thread of its own
        for _ in range(100):
            if not login_replaced or self.reboots:
                break
            import time
            time.sleep(0.02)
        return self.statuses[-1]

    def test_messages_follow_the_language_of_the_request(self):
        self._run(False, lang="it")
        self.assertIn(("restoring", "Preparazione…", {}), self.statuses)
        self.assertEqual(self.statuses[0][1], hifi_i18n.t("restore.preparing", "it"))

    def test_a_replaced_login_reboots_the_device(self):
        state, message, extra = self._run(True)
        self.assertEqual(state, "done")
        self.assertTrue(extra["reboot"])
        self.assertIn(hifi_i18n.t("restore.rebootingLoginReplaced", "it"), message)
        self.assertEqual(self.reboots, [True])

    def test_no_reboot_without_a_replaced_login(self):
        state, _message, extra = self._run(False)
        self.assertEqual(state, "done")
        self.assertFalse(extra["reboot"])
        self.assertEqual(self.reboots, [])

    def test_no_reboot_during_first_boot_setup(self):
        _write(self.tmp, "/provisioning-pending", b"")
        _state, _message, extra = self._run(True)
        self.assertFalse(extra["reboot"])
        self.assertEqual(self.reboots, [])


class FinalizeDisplayModeTests(_Tmp):
    def setUp(self):
        super().setUp()
        self.modes = []
        self.proxied = []
        marker = os.path.join(self.tmp, "provisioning-pending")
        _write(self.tmp, "/provisioning-pending", b"")
        for name, value in (("STATE_DIR", self.tmp), ("MARKER", marker),
                            ("PROVISION_STATE", os.path.join(self.tmp, "provisioning-state.json")),
                            ("DISPLAY_MODE_FILE", os.path.join(self.tmp, "display-mode"))):
            p = patch.object(w, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, fn in (("_set_display_mode", lambda mode, live: self.modes.append((mode, live))),
                         ("_do_finalize", lambda: None),
                         ("_proxy", lambda *a, **kw: (self.proxied.append(a[1]) or {}, 200))):
            p = patch.object(w, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def _finalize(self, **body):
        r = w.app.test_client().post("/api/provision/finalize", json=body)
        self.assertEqual(r.status_code, 200, r.get_json())
        return self.modes[-1]

    def test_restore_keeps_the_restored_headless_mode(self):
        w._save_prov_state({"stage": "network-ok"})
        _write(self.tmp, "/display-mode", b"headless\n")
        self.assertEqual(self._finalize(reboot=True), ("headless", True))
        self.assertIn("/reboot", self.proxied)

    def test_restore_without_a_saved_mode_is_the_screen(self):
        w._save_prov_state({})
        self.assertEqual(self._finalize(reboot=True), ("gui", True))

    def test_the_claimed_mode_wins_otherwise(self):
        _write(self.tmp, "/display-mode", b"headless\n")
        w._save_prov_state({"mode": "gui", "claimed_by": "web"})
        self.assertEqual(self._finalize(), ("gui", True))

    def test_server_only_is_a_headless_screen(self):
        # hifi-display-mode.sh knows only gui|headless: 'off' used to be
        # refused there, leaving the setup screen on.
        w._save_prov_state({"mode": "off", "claimed_by": "web"})
        self.assertEqual(self._finalize(), ("headless", True))


class AdminI18nKeyTests(unittest.TestCase):
    """Every literal t('a.b') in admin-webui/src exists in both catalogues —
    a missing one shows the raw key on the page."""

    def _flat(self, d, prefix=""):
        out = set()
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            out |= self._flat(v, key) if isinstance(v, dict) else {key}
        return out

    def test_literal_keys_exist_in_both_languages(self):
        src = os.path.join(REPO, "admin-webui", "src")
        cats = {}
        for lang in ("en", "it"):
            with open(os.path.join(src, "i18n", "locales", f"{lang}.json"), encoding="utf-8") as f:
                cats[lang] = self._flat(json.load(f))
        call = re.compile(r"""\b\$?t\(\s*['"]([A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)+)['"]""")
        missing = []
        for base, _dirs, files in os.walk(src):
            for name in files:
                if not name.endswith((".vue", ".js")):
                    continue
                with open(os.path.join(base, name), encoding="utf-8") as f:
                    text = f.read()
                for key in set(call.findall(text)):
                    for lang, keys in cats.items():
                        if key not in keys and not any(k.startswith(key + ".") for k in keys):
                            missing.append(f"{name}: {key} ({lang})")
        self.assertEqual(missing, [])


class EscapeSequenceTests(unittest.TestCase):
    def test_webui_server_compiles_without_warnings(self):
        with open(os.path.join(REPO, "webui_server.py"), encoding="utf-8") as f:
            src = f.read()
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(src, "webui_server.py", "exec")


if __name__ == "__main__":
    unittest.main()
