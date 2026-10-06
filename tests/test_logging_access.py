"""Werkzeug's per-request lines: the ones for requests that went fine are
dropped, errors are kept. They reach the rotated log through stderr, filed
under ERROR, and the kiosk's polling used to fill it in a day or two."""
import logging
import unittest

import hifi_logging


def record(code):
    return logging.LogRecord('werkzeug', logging.INFO, __file__, 1, '"%s" %s %s',
                             ('GET /api/sources HTTP/1.1', code, '-'), None)


class QuietAccessLogTests(unittest.TestCase):
    def setUp(self):
        self.f = hifi_logging._QuietAccessLog()

    def test_successes_and_redirects_are_dropped(self):
        for code in ('200', '204', '302', '304'):
            self.assertFalse(self.f.filter(record(code)), code)

    def test_errors_are_kept(self):
        for code in ('400', '401', '404', '413', '500', '502'):
            self.assertTrue(self.f.filter(record(code)), code)

    def test_anything_else_from_werkzeug_is_kept(self):
        other = logging.LogRecord('werkzeug', logging.ERROR, __file__, 1,
                                  'Error on request:', (), None)
        self.assertTrue(self.f.filter(other))
        bad = logging.LogRecord('werkzeug', logging.INFO, __file__, 1, '"%s" %s %s',
                                ('GET / HTTP/1.1', '-', '-'), None)
        self.assertTrue(self.f.filter(bad))


if __name__ == '__main__':
    unittest.main()
