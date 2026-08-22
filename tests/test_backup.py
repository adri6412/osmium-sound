"""Unit tests for the backup/restore core.

These run against a fake root (a temp directory), so they exercise the real
enumeration, allow-list and rotation code without needing an appliance. Archive
member names are root-relative by construction, which is what makes that
substitution honest rather than a stub.
"""
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest

import yaml

import hifi_backup as hb


def _write(root, logical, content=b"x"):
    path = os.path.join(root, logical.lstrip("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


class FakeRootTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hifi-backup-test-")
        self.addCleanup(shutil.rmtree, self.root, True)


class CategorySelectionTests(unittest.TestCase):
    def test_secret_categories_need_a_passphrase(self):
        chosen = hb.selected_categories(hb.ALL_CATEGORIES, encrypted=False)
        for cat in hb.SECRET_CATEGORIES:
            self.assertNotIn(cat, chosen)
        self.assertIn("core", chosen)

    def test_secret_categories_allowed_when_encrypted(self):
        chosen = hb.selected_categories(hb.ALL_CATEGORIES, encrypted=True)
        for cat in hb.SECRET_CATEGORIES:
            self.assertIn(cat, chosen)

    def test_unknown_categories_are_dropped(self):
        self.assertEqual(hb.selected_categories(["core", "nope"], encrypted=False),
                         ["core"])

    def test_unattended_set_has_no_secrets(self):
        for cat in hb.UNATTENDED_CATEGORIES:
            self.assertFalse(hb.CATEGORIES[cat]["secret"])

    def test_sources_survives_an_unencrypted_backup(self):
        # Losing the source list from every plain backup would be a regression
        # against the behaviour this feature replaces.
        self.assertIn("sources", hb.selected_categories(hb.ALL_CATEGORIES, False))


class DenyListTests(FakeRootTestCase):
    def test_denied_files_are_never_enumerated(self):
        _write(self.root, "/etc/hifi-player/dsp.json", b"{}")
        for denied in ("/etc/hifi-player/OS_VERSION",
                       "/etc/hifi-player/SYSTEM_VERSION",
                       "/etc/hifi-player/ota-pubkey.pem",
                       "/etc/hifi-player/webui-secret.key"):
            _write(self.root, denied, b"secret")
        logicals = [lg for lg, _ in hb.iter_members(hb.ALL_CATEGORIES, self.root)]
        for denied in hb.DENY_FILES:
            self.assertNotIn(denied, logicals)
        self.assertIn("/etc/hifi-player/dsp.json", logicals)

    def test_denied_files_are_never_restored(self):
        for denied in hb.DENY_FILES:
            self.assertIsNone(
                hb.restore_dest_for_member(denied.lstrip("/"),
                                           hb.ALL_CATEGORIES, self.root),
                f"{denied} must not be restorable")

    def test_backups_dir_is_not_backed_up(self):
        self.assertTrue(hb.is_denied("/var/lib/hifi-player/backups/2026/x"))

    def test_ssh_host_keys_are_denied(self):
        self.assertTrue(hb.is_denied("/etc/ssh/ssh_host_ed25519_key"))


class RestoreMappingTests(FakeRootTestCase):
    def test_allowed_exact_file(self):
        dest = hb.restore_dest_for_member("etc/hifi-player/dsp.json",
                                          ["core"], self.root)
        self.assertEqual(dest, os.path.join(self.root, "etc/hifi-player/dsp.json"))

    def test_allowed_under_directory(self):
        dest = hb.restore_dest_for_member("etc/camilladsp/filters/room.wav",
                                          ["core"], self.root)
        self.assertIsNotNone(dest)

    def test_directory_itself_is_not_a_target(self):
        self.assertIsNone(hb.restore_dest_for_member("etc/camilladsp/filters",
                                                     ["core"], self.root))

    def test_traversal_is_rejected(self):
        for name in ("../../etc/shadow",
                     "etc/hifi-player/../../root/.ssh/authorized_keys",
                     "/etc/shadow",
                     "etc/camilladsp/filters/../../../etc/passwd"):
            self.assertIsNone(
                hb.restore_dest_for_member(name, hb.ALL_CATEGORIES, self.root),
                f"{name} must not map to a destination")

    def test_category_not_selected_is_rejected(self):
        # Wi-Fi profiles are in the manifest, but only when 'network' was asked
        # for — restoring a category the user did not pick must not happen.
        name = "etc/NetworkManager/system-connections/home.nmconnection"
        self.assertIsNone(hb.restore_dest_for_member(name, ["core"], self.root))
        self.assertIsNotNone(hb.restore_dest_for_member(name, ["network"], self.root))

    def test_legacy_archive_maps_to_core_and_sources(self):
        self.assertEqual(hb.categories_in_manifest(None), ("core", "sources"))
        self.assertEqual(hb.categories_in_manifest({}), ("core", "sources"))


class BuildArchiveTests(FakeRootTestCase):
    def test_members_and_checksums(self):
        _write(self.root, "/etc/hifi-player/dsp.json", b'{"enabled":true}')
        _write(self.root, "/etc/camilladsp/filters/room.wav", b"RIFF")
        dest = os.path.join(self.root, "out.tar.gz")
        manifest = hb.build_archive(dest, ["core"], self.root)
        members = manifest["members"]

        self.assertIn("etc/hifi-player/dsp.json", members)
        self.assertIn("etc/camilladsp/filters/room.wav", members)
        with tarfile.open(dest) as tar:
            names = tar.getnames()
            self.assertCountEqual(names, list(members) + [hb.MANIFEST_MEMBER])
            data = tar.extractfile("etc/hifi-player/dsp.json").read()
        import hashlib
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         members["etc/hifi-player/dsp.json"])

    def test_manifest_is_the_last_member(self):
        # It is the completeness marker: a truncated archive must not have it.
        _write(self.root, "/etc/hifi-player/dsp.json", b"{}")
        dest = os.path.join(self.root, "out.tar.gz")
        hb.build_archive(dest, ["core"], self.root)
        with tarfile.open(dest) as tar:
            self.assertEqual(tar.getnames()[-1], hb.MANIFEST_MEMBER)

    def test_embedded_manifest_is_readable(self):
        _write(self.root, "/etc/hifi-player/dsp.json", b"{}")
        dest = os.path.join(self.root, "out.tar.gz")
        hb.build_archive(dest, ["core"], self.root, extra={"trigger": "manual"})
        with tarfile.open(dest) as tar:
            manifest = hb.read_embedded_manifest(tar)
        self.assertEqual(manifest["schema"], hb.SCHEMA)
        self.assertEqual(manifest["categories"], ["core"])
        self.assertEqual(manifest["trigger"], "manual")

    def test_manifest_member_is_not_a_restore_target(self):
        self.assertIsNone(hb.restore_dest_for_member(
            hb.MANIFEST_MEMBER, hb.ALL_CATEGORIES, self.root))

    def test_no_partial_file_is_left_behind(self):
        _write(self.root, "/etc/hifi-player/dsp.json", b"{}")
        dest = os.path.join(self.root, "out.tar.gz")
        hb.build_archive(dest, ["core"], self.root)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_symlinks_are_not_followed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink support")
        target = _write(self.root, "/etc/passwd-ish", b"root:x:0:0")
        link = os.path.join(self.root, "etc/hifi-player/dsp.json")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        logicals = [lg for lg, _ in hb.iter_members(["core"], self.root)]
        self.assertNotIn("/etc/hifi-player/dsp.json", logicals)

    def test_lyrion_cache_is_excluded(self):
        _write(self.root, "/var/lib/squeezeboxserver/prefs/server.prefs", b"a: 1\n")
        _write(self.root, "/var/lib/squeezeboxserver/cache/library.db", b"HUGE")
        logicals = [lg for lg, _ in hb.iter_members(["lyrion"], self.root)]
        self.assertIn("/var/lib/squeezeboxserver/prefs/server.prefs", logicals)
        self.assertFalse([lg for lg in logicals
                          if "/cache/" in lg and "InstalledPlugins" not in lg])

    def test_lyrion_installed_plugins_are_kept(self):
        _write(self.root,
               "/var/lib/squeezeboxserver/cache/InstalledPlugins/Plugins/Material.zip",
               b"plugin data")
        _write(self.root, "/var/lib/squeezeboxserver/cache/library.db", b"HUGE")
        logicals = [lg for lg, _ in hb.iter_members(["lyrion"], self.root)]
        self.assertIn(
            "/var/lib/squeezeboxserver/cache/InstalledPlugins/Plugins/Material.zip",
            logicals)
        self.assertNotIn("/var/lib/squeezeboxserver/cache/library.db", logicals)

    def test_server_uuid_is_stripped(self):
        _write(self.root, "/var/lib/squeezeboxserver/prefs/server.prefs",
               b"server_uuid: 8f14e45f-ceea-4e58-a1b2-abcdef123456\nplaylistdir: /music\n")
        dest = os.path.join(self.root, "out.tar.gz")
        notes = hb.build_archive(dest, ["lyrion"], self.root)["notes"]
        with tarfile.open(dest) as tar:
            raw = tar.extractfile(
                "var/lib/squeezeboxserver/prefs/server.prefs").read()
        data = yaml.safe_load(raw)
        self.assertNotIn("server_uuid", data)
        self.assertEqual(data["playlistdir"], "/music")
        self.assertTrue(any("stripped-server-uuid" in n for n in notes))


class SourcesRedactionTests(FakeRootTestCase):
    STATE = {"sources": [{"type": "smb", "server": "nas", "share": "music",
                          "username": "u", "password": "hunter2"}]}

    def test_password_stripped_when_not_encrypted(self):
        _write(self.root, "/etc/hifi-sources.json",
               json.dumps(self.STATE).encode())
        dest = os.path.join(self.root, "out.tar.gz")
        notes = hb.build_archive(dest, ["sources"], self.root,
                                 encrypted=False)["notes"]
        with tarfile.open(dest) as tar:
            data = json.loads(tar.extractfile("etc/hifi-sources.json").read())
        self.assertEqual(data["sources"][0]["password"], "")
        self.assertEqual(data["sources"][0]["server"], "nas")
        self.assertIn("sources:redacted", notes)

    def test_password_kept_when_encrypted(self):
        _write(self.root, "/etc/hifi-sources.json",
               json.dumps(self.STATE).encode())
        dest = os.path.join(self.root, "out.tar.gz")
        hb.build_archive(dest, ["sources"], self.root, encrypted=True)
        with tarfile.open(dest) as tar:
            data = json.loads(tar.extractfile("etc/hifi-sources.json").read())
        self.assertEqual(data["sources"][0]["password"], "hunter2")

    def test_merge_reinstates_local_password(self):
        redacted = json.dumps({"sources": [dict(self.STATE["sources"][0],
                                                password="")]}).encode()
        merged = json.loads(hb.merge_sources_state(
            redacted, json.dumps(self.STATE).encode()))
        self.assertEqual(merged["sources"][0]["password"], "hunter2")

    def test_merge_leaves_unknown_sources_alone(self):
        redacted = json.dumps({"sources": [{"type": "smb", "server": "other",
                                            "share": "x", "password": ""}]}).encode()
        merged = json.loads(hb.merge_sources_state(
            redacted, json.dumps(self.STATE).encode()))
        self.assertEqual(merged["sources"][0]["password"], "")


class NetworkFilterTests(FakeRootTestCase):
    def test_only_wifi_profiles_are_archived(self):
        _write(self.root, "/etc/NetworkManager/system-connections/wifi.nmconnection",
               b"[connection]\ntype=wifi\n[wifi-security]\npsk=secret\n")
        _write(self.root, "/etc/NetworkManager/system-connections/wired.nmconnection",
               b"[connection]\ntype=ethernet\n")
        dest = os.path.join(self.root, "out.tar.gz")
        members = hb.build_archive(dest, ["network"], self.root,
                                   encrypted=True)["members"]
        self.assertTrue(any("wifi.nmconnection" in m for m in members))
        self.assertFalse(any("wired.nmconnection" in m for m in members))


class GenerationTests(FakeRootTestCase):
    def _make_gen(self, gen_id, complete=True):
        gdir = os.path.join(self.root, gen_id)
        os.makedirs(gdir, exist_ok=True)
        with open(os.path.join(gdir, hb.ARCHIVE_NAME), "wb") as f:
            f.write(b"archive")
        if complete:
            with open(os.path.join(gdir, hb.MANIFEST_NAME), "w") as f:
                json.dump({"schema": hb.SCHEMA, "created": gen_id,
                           "categories": ["core"]}, f)
        return gdir

    def test_incomplete_generation_is_not_listed(self):
        self._make_gen("20260101-000000", complete=True)
        self._make_gen("20260102-000000", complete=False)
        ids = [g["id"] for g in hb.list_generations(self.root)]
        self.assertEqual(ids, ["20260101-000000"])

    def test_incomplete_generation_is_pruned(self):
        gdir = self._make_gen("20260102-000000", complete=False)
        self.assertEqual(hb.prune_incomplete(self.root), 1)
        self.assertFalse(os.path.exists(gdir))

    def test_prune_keeps_complete_generations(self):
        gdir = self._make_gen("20260101-000000", complete=True)
        hb.prune_incomplete(self.root)
        self.assertTrue(os.path.exists(gdir))

    def test_rotation_keeps_newest_n(self):
        for day in range(1, 8):
            self._make_gen(f"2026010{day}-000000")
        dropped = hb.rotate(self.root, keep=3)
        ids = [g["id"] for g in hb.list_generations(self.root)]
        self.assertEqual(ids, ["20260107-000000", "20260106-000000",
                               "20260105-000000"])
        self.assertEqual(len(dropped), 4)

    def test_newest_first_ordering(self):
        self._make_gen("20260101-000000")
        self._make_gen("20260301-120000")
        self._make_gen("20260201-000000")
        ids = [g["id"] for g in hb.list_generations(self.root)]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_generation_id_validation(self):
        for bad in ("", "..", "../etc", "foo", "2026/01", "a" * 40):
            self.assertFalse(hb.valid_gen_id(bad), bad)
        self.assertTrue(hb.valid_gen_id("20260101-000000"))

    def test_free_space_guard(self):
        self.assertFalse(hb.free_space_ok(self.root, 1 << 62))
        self.assertTrue(hb.free_space_ok(self.root, 1))


def _have_openssl():
    try:
        return subprocess.run(["openssl", "version"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


@unittest.skipUnless(_have_openssl(), "openssl not available")
class EncryptionTests(FakeRootTestCase):
    def _plain(self):
        path = os.path.join(self.root, "plain.tar.gz")
        with open(path, "wb") as f:
            f.write(b"payload" * 1000)
        return path

    def test_roundtrip(self):
        plain = self._plain()
        enc = os.path.join(self.root, "cipher.enc")
        meta = hb.encrypt_archive(plain, enc, "correct horse")
        with open(enc, "rb") as f:
            self.assertNotIn(b"payload", f.read())

        out = os.path.join(self.root, "back.tar.gz")
        hb.decrypt_archive(enc, out, "correct horse", meta)
        with open(out, "rb") as f, open(plain, "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_wrong_passphrase_writes_nothing(self):
        plain = self._plain()
        enc = os.path.join(self.root, "cipher.enc")
        meta = hb.encrypt_archive(plain, enc, "correct horse")
        out = os.path.join(self.root, "back.tar.gz")
        with self.assertRaises(hb.BackupError):
            hb.decrypt_archive(enc, out, "wrong horse", meta)
        self.assertFalse(os.path.exists(out),
                         "a failed decrypt must not leave an output file")

    def test_tampered_ciphertext_is_rejected_before_decryption(self):
        plain = self._plain()
        enc = os.path.join(self.root, "cipher.enc")
        meta = hb.encrypt_archive(plain, enc, "pw")
        with open(enc, "r+b") as f:
            f.seek(32)
            f.write(b"\x00\x01\x02\x03")
        out = os.path.join(self.root, "back.tar.gz")
        with self.assertRaises(hb.BackupError):
            hb.decrypt_archive(enc, out, "pw", meta)
        self.assertFalse(os.path.exists(out))


class OpenBackupTests(FakeRootTestCase):
    """The two shapes a downloaded backup can have, opened by the same door."""

    def _build(self, encrypted):
        _write(self.root, "/etc/hifi-player/dsp.json", b'{"enabled":true}')
        plain = os.path.join(self.root, "backup.tar.gz")
        manifest = hb.build_archive(plain, ["core"], self.root,
                                    encrypted=encrypted,
                                    extra={"created": "20260101-000000"})
        return plain, manifest

    def test_plain_archive_opens_with_its_manifest(self):
        plain, _ = self._build(False)
        work = tempfile.mkdtemp(dir=self.root)
        tar, manifest = hb.open_backup(plain, work)
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())
        self.assertEqual(manifest["categories"], ["core"])

    def test_legacy_archive_without_manifest_still_opens(self):
        legacy = os.path.join(self.root, "legacy.tar.gz")
        with tarfile.open(legacy, "w:gz") as tar:
            info = tarfile.TarInfo("etc/hifi-player/dsp.json")
            info.size = 2
            tar.addfile(info, __import__("io").BytesIO(b"{}"))
        work = tempfile.mkdtemp(dir=self.root)
        tar, manifest = hb.open_backup(legacy, work)
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())
        self.assertIsNone(manifest)
        self.assertEqual(hb.categories_in_manifest(manifest), ("core", "sources"))

    def test_garbage_is_rejected(self):
        junk = os.path.join(self.root, "junk.tar.gz")
        with open(junk, "wb") as f:
            f.write(b"not a tarball at all")
        with self.assertRaises(hb.BackupError):
            hb.open_backup(junk, self.root)

    @unittest.skipUnless(_have_openssl(), "openssl not available")
    def test_encrypted_wrapper_roundtrip(self):
        plain, manifest = self._build(True)
        enc = os.path.join(self.root, hb.ENC_NAME)
        manifest["enc"] = hb.encrypt_archive(plain, enc, "pw")
        wrapper = os.path.join(self.root, "download.tar.gz")
        hb.wrap_encrypted(wrapper, manifest, enc)

        # The wrapper must not leak the paths it protects.
        with tarfile.open(wrapper) as tar:
            self.assertCountEqual(tar.getnames(), [hb.MANIFEST_NAME, hb.ENC_NAME])

        work = tempfile.mkdtemp(dir=self.root)
        tar, got = hb.open_backup(wrapper, work, "pw")
        with tar:
            self.assertIn("etc/hifi-player/dsp.json", tar.getnames())
        self.assertEqual(got["categories"], ["core"])

    @unittest.skipUnless(_have_openssl(), "openssl not available")
    def test_encrypted_wrapper_needs_the_passphrase(self):
        plain, manifest = self._build(True)
        enc = os.path.join(self.root, hb.ENC_NAME)
        manifest["enc"] = hb.encrypt_archive(plain, enc, "pw")
        wrapper = os.path.join(self.root, "download.tar.gz")
        hb.wrap_encrypted(wrapper, manifest, enc)

        with self.assertRaises(hb.BackupError):
            hb.open_backup(wrapper, tempfile.mkdtemp(dir=self.root))
        with self.assertRaises(hb.BackupError):
            hb.open_backup(wrapper, tempfile.mkdtemp(dir=self.root), "wrong")


if __name__ == "__main__":
    unittest.main()
