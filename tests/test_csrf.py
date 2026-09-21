"""The double-submit CSRF token in webui_server.py: who gets one, and who is
turned away without one.

The token is unguessable and lives in a cookie the page echoes back in a
header, so only a page served by this appliance can mutate anything. The part
that is easy to get wrong — and that these tests pin — is WHERE a token is
born. Handing a fresh one to every request that arrives without the cookie
reads as the forgiving thing to do, and it is what produced an intermittent
"Missing or invalid CSRF token" in the web admin: a cold page load fires a
burst of parallel calls (the route guard, the update poll, the ~30 loaders in
Settings, one skin.json and several images per VU meter card), each of them
came back with a DIFFERENT token, and the last reply to land redefined the
cookie under requests whose header had already been read. So:

  * a page load mints one (it precedes every subresource of its own page, so
    it cannot race anything) — including the 304 a browser gets for an
    index.html it already has, which carries no Content-Type to judge by;
  * /api/csrf mints one on demand, for a page that arrived without it;
  * nothing else does — not an API read, not a VU skin image, not an asset;
  * and the guard itself still refuses a mutation whose header and cookie
    disagree, while leaving the captive flows and the token-authenticated
    forwards alone.

Run with:  python tests/test_csrf.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import webui_server  # noqa: E402

# What a browser actually sends for each kind of request.
DOCUMENT = {'Sec-Fetch-Dest': 'document',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
IFRAME = {'Sec-Fetch-Dest': 'iframe', 'Accept': 'text/html,*/*;q=0.8'}
XHR = {'Sec-Fetch-Dest': 'empty', 'Accept': '*/*'}
IMAGE = {'Sec-Fetch-Dest': 'image', 'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'}
SCRIPT = {'Sec-Fetch-Dest': 'script', 'Accept': '*/*'}
# A browser too old to say what it is asking for (pre Chrome 76 / Firefox 90).
OLD_DOCUMENT = {'Accept': 'text/html,application/xhtml+xml'}
OLD_XHR = {'Accept': '*/*'}

# Not loopback: 127.0.0.1 is exempt from the check (api_server's
# server-to-server provisioning calls come from there).
LAN = {'REMOTE_ADDR': '192.168.1.40'}


def minted(resp):
    """The token this reply hands out, if any."""
    for header in resp.headers.getlist('Set-Cookie'):
        if header.startswith('csrf='):
            return header.split(';')[0][len('csrf='):]
    return None


class CsrfMintingTestCase(unittest.TestCase):
    """Where a token is born. Every client here starts with an empty cookie
    jar, which is the only state that matters: a request that already carries
    the cookie is never handed another one."""

    def get(self, path, headers):
        # A client of its own each time == a browser that has no token yet.
        return webui_server.app.test_client().get(path, headers=headers)

    def test_page_load_mints(self):
        for path in ('/', '/settings', '/library'):
            with self.subTest(path=path):
                self.assertTrue(minted(self.get(path, DOCUMENT)))

    def test_page_inside_a_frame_mints(self):
        # Lyrion's Material skin opens the admin in an iframe: that page needs
        # a token as much as a top-level one, and precedes its own subresources
        # just the same.
        self.assertTrue(minted(self.get('/', IFRAME)))

    def test_old_browser_mints_on_its_document(self):
        self.assertTrue(minted(self.get('/', OLD_DOCUMENT)))
        self.assertIsNone(minted(self.get('/api/auth/status', OLD_XHR)))

    def test_bootstrap_endpoint_mints(self):
        # The recovery path for a page that arrived without one (an index.html
        # answered 304 from the browser cache after the cookie was dropped).
        resp = self.get('/api/csrf', XHR)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(minted(resp))

    def test_nothing_else_mints(self):
        for name, path, headers in (
            ('api read', '/api/auth/status', XHR),
            ('vu skin geometry', '/api/system/vu_skin/classic/skin.json', XHR),
            ('vu skin image', '/api/system/vu_skin/classic/under.png', IMAGE),
            ('spa asset', '/assets/index.js', SCRIPT),
        ):
            with self.subTest(name):
                self.assertIsNone(minted(self.get(path, headers)))

    def test_a_client_that_has_one_keeps_it(self):
        client = webui_server.app.test_client()
        token = minted(client.get('/', headers=DOCUMENT))
        self.assertTrue(token)
        for path, headers in (('/', DOCUMENT), ('/api/csrf', XHR),
                              ('/api/auth/status', XHR)):
            with self.subTest(path=path):
                self.assertIsNone(minted(client.get(path, headers=headers)))
        self.assertEqual(client.get_cookie('csrf').value, token)


class CsrfGuardTestCase(unittest.TestCase):
    """What the guard lets through. The admin's own endpoints need the token;
    the captive flows and the token-authenticated forwards are exempt by
    design (see _guard in webui_server.py)."""

    def setUp(self):
        self.client = webui_server.app.test_client()
        self.token = minted(self.client.get('/api/csrf', headers=XHR, environ_base=LAN))
        self.assertTrue(self.token)

    def post(self, path, token=None):
        headers = {'X-CSRF-Token': token} if token else {}
        return self.client.post(path, json={'username': 'x', 'password': 'y'},
                                headers=headers, environ_base=LAN)

    def refused(self, resp):
        return resp.status_code == 403 and (resp.get_json() or {}).get('code') == 'auth.csrfInvalid'

    def test_matching_token_passes_the_guard(self):
        # 401 = it reached the login route and the credentials were wrong,
        # which is exactly what "the guard let it through" looks like here.
        self.assertFalse(self.refused(self.post('/api/auth/login', self.token)))

    def test_wrong_or_missing_header_is_refused(self):
        self.assertTrue(self.refused(self.post('/api/auth/login', 'not-the-token')))
        self.assertTrue(self.refused(self.post('/api/auth/login')))

    def test_a_refusal_does_not_hand_out_a_token(self):
        # The page that lost its cookie asks /api/csrf for one; a mutation is
        # not a place to mint, or the burst that broke the admin comes back.
        resp = webui_server.app.test_client().post('/api/auth/login', json={},
                                                   environ_base=LAN)
        self.assertTrue(self.refused(resp))
        self.assertIsNone(minted(resp))

    def test_captive_flows_stay_exempt(self):
        # Pre-auth and gated by physical/RF proximity + PSK instead: no token
        # exists yet while the setup hotspot is up.
        for path in ('/api/provision/claim_mode', '/api/netrecovery/status'):
            with self.subTest(path=path):
                resp = webui_server.app.test_client().post(path, json={},
                                                           environ_base=LAN)
                self.assertNotEqual(resp.status_code, 403)

    def test_sources_forwards_stay_exempt(self):
        # Authenticated by the pairing bearer token, not by cookies.
        for prefix in webui_server._SOURCES_FWD_PREFIXES:
            with self.subTest(prefix=prefix):
                resp = webui_server.app.test_client().post(prefix + '/nowhere',
                                                           json={}, environ_base=LAN)
                self.assertNotEqual(resp.status_code, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
