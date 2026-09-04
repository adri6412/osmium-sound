"""Unit tests for the guided "add a network folder" flow.

Everything here is parsing and mapping: the output of avahi-browse, nmblookup
and smbclient, and the translation of a raw NT_STATUS into a sentence someone
can act on. That mapping is the whole point of the redesign — a wrong bucket
sends the owner to fix the password when the share name is what is wrong —
so it is pinned down here rather than only tried by hand against one NAS.
"""
import subprocess
import unittest

import sources_server as ss


def _completed(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class ReasonMappingTests(unittest.TestCase):
    def test_credentials(self):
        for raw in ("Connection failed: NT_STATUS_LOGON_FAILURE",
                    "session setup failed: NT_STATUS_ACCESS_DENIED",
                    "mount error(13): Permission denied",
                    "NT_STATUS_WRONG_PASSWORD"):
            self.assertEqual(ss._smb_reason(raw), "msg.smbBadCredentials", raw)

    def test_share_name(self):
        for raw in ("tree connect failed: NT_STATUS_BAD_NETWORK_NAME",
                    "mount error(2): No such file or directory",
                    "NT_STATUS_OBJECT_NAME_NOT_FOUND"):
            self.assertEqual(ss._smb_reason(raw), "msg.smbNoSuchShare", raw)

    def test_unreachable(self):
        for raw in ("Error NT_STATUS_HOST_UNREACHABLE",
                    "Connection to nas failed: NT_STATUS_CONNECTION_REFUSED",
                    "mount error(112): Host is down",
                    "connection timed out"):
            self.assertEqual(ss._smb_reason(raw), "msg.smbUnreachable", raw)

    def test_expired_and_locked_are_not_a_plain_typo(self):
        # Both also carry ACCESS_DENIED on some servers; the more specific
        # bucket has to win, or the owner retypes a password that is correct.
        self.assertEqual(ss._smb_reason("NT_STATUS_PASSWORD_EXPIRED"),
                         "msg.smbPasswordExpired")
        self.assertEqual(ss._smb_reason("NT_STATUS_ACCOUNT_LOCKED_OUT"),
                         "msg.smbAccountLocked")

    def test_unknown_stays_unknown(self):
        # An unrecognised failure must fall through to the generic message
        # WITH its raw text as detail, never be forced into a wrong bucket.
        self.assertIsNone(ss._smb_reason("something nobody has seen before"))
        self.assertIsNone(ss._smb_reason(""))

    def test_every_code_is_translated_in_both_languages(self):
        codes = {
            "msg.smbBadCredentials", "msg.smbPasswordExpired", "msg.smbAccountLocked",
            "msg.smbNoSuchShare", "msg.smbUnreachable", "msg.smbProtocol",
            "msg.smbNeedsAuth", "msg.smbNoClient", "msg.smbListFailed",
            "msg.smbTestFailed"}
        for code in codes:
            for lang in ("en", "it"):
                self.assertIn(code, ss.SOURCES_I18N[lang], f"{code} missing in {lang}")


class AvahiTests(unittest.TestCase):
    SAMPLE = (
        "+;eth0;IPv4;My\\032NAS;_smb._tcp;local\n"
        "=;eth0;IPv4;My\\032NAS;_smb._tcp;local;nas.local;192.168.0.10;445;\n"
        "=;eth0;IPv6;My\\032NAS;_smb._tcp;local;nas.local;fe80::1;445;\n"
        "=;eth0;IPv4;iMac;_smb._tcp;local;imac.local;192.168.0.22;445;\n")

    def setUp(self):
        ss._smb_scan["hosts"] = []

    def test_unescape(self):
        self.assertEqual(ss._unescape_avahi("My\\032NAS"), "My NAS")
        self.assertEqual(ss._unescape_avahi("nas\\.local"), "nas.local")

    def test_parses_ipv4_records_only(self):
        # IPv6 is skipped: mount.cifs is given a bare host string, and a
        # link-local v6 address needs a scope the wizard has no way to ask for.
        orig_run, orig_have = ss._run, ss._have
        ss._run = lambda cmd, timeout=30: _completed(self.SAMPLE)
        ss._have = lambda cmd: True
        try:
            ss._smb_probe_mdns()
        finally:
            ss._run, ss._have = orig_run, orig_have
        found = {h["ip"]: h["name"] for h in ss._smb_scan["hosts"]}
        self.assertEqual(found, {"192.168.0.10": "My NAS", "192.168.0.22": "iMac"})

    def test_missing_tool_is_not_an_error(self):
        # avahi-utils only arrives with the next image: an older device must
        # still get the rest of the scan instead of a traceback.
        orig = ss._have
        ss._have = lambda cmd: False
        try:
            ss._smb_probe_mdns()
        finally:
            ss._have = orig
        self.assertEqual(ss._smb_scan["hosts"], [])


class NetbiosTests(unittest.TestCase):
    SAMPLE = (
        "querying * on 192.168.0.255\n"
        "192.168.0.10 *<00>\n"
        "Looking up status of 192.168.0.10\n"
        "\tNAS             <00> -         B <ACTIVE>\n"
        "\tNAS             <20> -         B <ACTIVE>\n"
        "\tWORKGROUP       <00> - <GROUP> B <ACTIVE>\n")

    def setUp(self):
        ss._smb_scan["hosts"] = []

    def test_takes_the_file_server_name(self):
        orig_run, orig_have = ss._run, ss._have
        ss._run = lambda cmd, timeout=30: _completed(self.SAMPLE)
        ss._have = lambda cmd: True
        try:
            ss._smb_probe_netbios()
        finally:
            ss._run, ss._have = orig_run, orig_have
        self.assertEqual(ss._smb_scan["hosts"],
                         [{"ip": "192.168.0.10", "name": "NAS", "sources": ["netbios"]}])


class ShareListTests(unittest.TestCase):
    GREPABLE = ("Disk|Music|The music\n"
                "Disk|Backup|\n"
                "Disk|IPC$|IPC Service\n"
                "Disk|C$|Default share\n"
                "IPC|IPC$|IPC Service (nas)\n"
                "Printer|HP_LaserJet|\n"
                "Server|NAS|\n")

    def _with_client(self, result):
        orig_have, orig_client = ss._have, ss._smbclient
        ss._have = lambda cmd: True
        ss._smbclient = lambda args, u, p, timeout=25: result
        try:
            return ss._smb_list_shares("nas", "", "")
        finally:
            ss._have, ss._smbclient = orig_have, orig_client

    def test_only_real_disk_shares_survive(self):
        shares, code, _detail = self._with_client(_completed(self.GREPABLE))
        self.assertIsNone(code)
        self.assertEqual([s["name"] for s in shares], ["Music", "Backup"])
        self.assertEqual(shares[0]["comment"], "The music")

    def test_anonymous_refusal_asks_for_a_password(self):
        # NOT a failure: it is the server asking who we are, and the wizard
        # has a step for that. Reporting it as an error was the old behaviour.
        shares, code, _d = self._with_client(
            _completed("", "session setup failed: NT_STATUS_LOGON_FAILURE", 1))
        self.assertEqual(code, "msg.smbNeedsAuth")
        self.assertEqual(shares, [])

    def test_wrong_password_with_a_username_stays_wrong_password(self):
        orig_have, orig_client = ss._have, ss._smbclient
        ss._have = lambda cmd: True
        ss._smbclient = lambda args, u, p, timeout=25: _completed(
            "", "NT_STATUS_LOGON_FAILURE", 1)
        try:
            _shares, code, _d = ss._smb_list_shares("nas", "bob", "nope")
        finally:
            ss._have, ss._smbclient = orig_have, orig_client
        self.assertEqual(code, "msg.smbBadCredentials")

    def test_without_smbclient_the_caller_is_told_to_type_it(self):
        orig = ss._have
        ss._have = lambda cmd: False
        try:
            _shares, code, _d = ss._smb_list_shares("nas", "", "")
        finally:
            ss._have = orig
        self.assertEqual(code, "msg.smbNoClient")


class ScanTargetTests(unittest.TestCase):
    def _targets(self, addr, prefixlen):
        orig = ss._run_json
        ss._run_json = lambda cmd, timeout=30: [
            {"link_type": "loopback", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
            {"link_type": "ether", "addr_info": [{"local": addr, "prefixlen": prefixlen}]},
        ]
        try:
            return ss._scan_targets()
        finally:
            ss._run_json = orig

    def test_own_addresses_are_never_probed(self):
        selves, targets = self._targets("192.168.0.5", 24)
        self.assertEqual(selves, {"192.168.0.5"})
        self.assertNotIn("192.168.0.5", targets)
        self.assertIn("192.168.0.10", targets)
        self.assertEqual(len(targets), 253)

    def test_a_wide_network_is_narrowed_to_our_own_24(self):
        # A /16 is 65k probes: that is a port scanner, not a setup wizard.
        _selves, targets = self._targets("10.0.5.7", 16)
        self.assertLessEqual(len(targets), ss._SMB_SCAN_MAX_HOSTS)
        self.assertIn("10.0.5.9", targets)
        self.assertNotIn("10.0.6.9", targets)

    def test_link_local_is_ignored(self):
        orig = ss._run_json
        ss._run_json = lambda cmd, timeout=30: [
            {"link_type": "ether", "addr_info": [{"local": "169.254.3.4", "prefixlen": 16}]}]
        try:
            selves, targets = ss._scan_targets()
        finally:
            ss._run_json = orig
        self.assertEqual((selves, targets), (set(), []))


if __name__ == "__main__":
    unittest.main()
