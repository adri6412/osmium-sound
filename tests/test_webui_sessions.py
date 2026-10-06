"""Logins in the web admin are revocable, and root-level changes ask for the
admin password again.

The session cookie is signed, not stored, so clearing it at logout only
forgot it in that browser: a copy taken earlier stayed good for seven days,
and with it /api/system/shell_account could create a sudo login and
/api/system/ssh switch SSH on without anybody typing a password.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('HIFI_PROVISION_FAKE', '1')

import webui_server as w  # noqa: E402

CSRF = {'Cookie': 'csrf=a', 'X-CSRF-Token': 'a'}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='webui-sess-')
        for name, value in (('STATE_DIR', self.tmp),
                            ('DB_PATH', os.path.join(self.tmp, 'webui.db')),
                            ('MARKER', os.path.join(self.tmp, 'provisioning-pending'))):
            p = patch.object(w, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        w.app.secret_key = 'test-secret'
        w._init_db()
        w._create_user('admin', 'correct-horse')
        with w._auth_fail_lock:
            w._auth_fail_log.clear()
        # the throttle test leaves this address locked out for a minute
        self.addCleanup(w._auth_fail_log.clear)
        self.proxied = []
        p = patch.object(w, '_proxy', side_effect=lambda base, path, method='GET', body=None, timeout=15:
                         (self.proxied.append((path, body)) or {'success': True}, 200))
        p.start()
        self.addCleanup(p.stop)

    def login(self):
        c = w.app.test_client()
        r = c.post('/api/auth/login', json={'username': 'admin', 'password': 'correct-horse'},
                   headers=CSRF)
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def status(self, client):
        return client.get('/api/auth/status').get_json()['logged_in']

    def test_a_copied_cookie_dies_with_the_logout(self):
        c = self.login()
        thief = w.app.test_client()
        thief.set_cookie('session', c.get_cookie('session').value)
        self.assertTrue(self.status(thief))
        c.post('/api/auth/logout', headers=CSRF)
        self.assertFalse(self.status(c))
        self.assertFalse(self.status(thief))

    def test_a_cookie_from_before_this_change_is_logged_out(self):
        c = w.app.test_client()
        with c.session_transaction() as s:
            s['auth'] = True
            s['sv'] = w._session_version()
        self.assertFalse(self.status(c))

    def test_a_password_change_keeps_only_this_session(self):
        a, b = self.login(), self.login()
        r = a.post('/api/auth/change-password', headers=CSRF,
                   json={'current_password': 'correct-horse', 'new_password': 'battery-staple'})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertTrue(self.status(a))
        self.assertFalse(self.status(b))

    def test_shell_account_needs_the_admin_password(self):
        c = self.login()
        r = c.post('/api/system/shell_account', headers=CSRF,
                   json={'username': 'admin', 'password': 'ssh-password'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.proxied, [])
        r = c.post('/api/system/shell_account', headers=CSRF,
                   json={'username': 'admin', 'password': 'ssh-password',
                         'admin_password': 'correct-horse'})
        self.assertEqual(r.status_code, 200, r.get_json())
        # the admin password is checked here and never travels further
        self.assertEqual(self.proxied, [('/shell_account', {'username': 'admin',
                                                            'password': 'ssh-password'})])

    def test_turning_ssh_on_needs_it_turning_it_off_does_not(self):
        c = self.login()
        self.assertEqual(c.post('/api/system/ssh', headers=CSRF, json={'enable': True}).status_code, 403)
        self.assertEqual(c.post('/api/system/ssh', headers=CSRF, json={'enable': False}).status_code, 200)
        r = c.post('/api/system/ssh', headers=CSRF,
                   json={'enable': True, 'admin_password': 'correct-horse'})
        self.assertEqual(r.status_code, 200)

    def test_wrong_passwords_share_the_login_throttle(self):
        c = self.login()
        for _ in range(w._AUTH_FAIL_MAX):
            c.post('/api/system/ssh', headers=CSRF, json={'enable': True, 'admin_password': 'x'})
        r = c.post('/api/system/ssh', headers=CSRF,
                   json={'enable': True, 'admin_password': 'correct-horse'})
        self.assertEqual(r.status_code, 429)


if __name__ == '__main__':
    unittest.main()
