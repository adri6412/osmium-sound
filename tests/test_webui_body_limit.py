"""Request bodies in the web admin are capped before anything reads them.

A POST to the login page needs no account, and the body used to be read whole
into memory: two 300 MB ones took the process from 50 to 837 MB on a real box.
JSON calls get 1 MB; the routes that carry a file get more and are streamed
through to sources_server instead of being held here.
"""
import os
import unittest

os.environ.setdefault('HIFI_PROVISION_FAKE', '1')

import webui_server  # noqa: E402

HDR = {'Cookie': 'csrf=a', 'X-CSRF-Token': 'a', 'Content-Type': 'application/json'}


class BodyLimitTests(unittest.TestCase):
    def setUp(self):
        self.c = webui_server.app.test_client()

    def test_an_oversized_login_is_refused_before_it_is_read(self):
        r = self.c.post('/api/auth/login', data=b'0' * (webui_server._BODY_LIMIT + 1), headers=HDR)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()['code'], 'request.tooLarge')

    def test_an_ordinary_login_is_not_affected(self):
        r = self.c.post('/api/auth/login', data=b'{"username":"x","password":"y"}', headers=HDR)
        self.assertNotEqual(r.status_code, 413)

    def test_upload_routes_get_the_large_limit(self):
        body = b'0' * (webui_server._BODY_LIMIT * 3)
        for path in ('/api/system/restore', '/api/system/dsp_fir'):
            r = self.c.post(path, data=body,
                            headers={**HDR, 'Content-Type': 'multipart/form-data; boundary=x'})
            self.assertNotEqual(r.status_code, 413, path)

    def test_the_large_limit_is_still_a_limit(self):
        with webui_server.app.test_request_context(
                '/api/system/restore', method='POST',
                headers={'Content-Length': str(webui_server._UPLOAD_BODY_LIMIT + 1)}):
            webui_server._body_limit()
            self.assertEqual(webui_server.request.max_content_length,
                             webui_server._UPLOAD_BODY_LIMIT)


if __name__ == '__main__':
    unittest.main()
