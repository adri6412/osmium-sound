"""Tests for how api_server._fetch_release behaves under concurrency and
without internet: one fetch per channel at a time (the others wait for it
instead of queueing behind a lock and repeating it), failures remembered for a
minute, and no network chain at all when the sources' names do not resolve.

Run with:  python3 -m unittest tests.test_release_fetch
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import api_server  # noqa: E402


class ReleaseFetchTestCase(unittest.TestCase):

    def setUp(self):
        self._saved = {}
        api_server._RELEASE_CACHE.clear()
        api_server._RELEASE_FAILED.clear()
        api_server._RELEASE_INFLIGHT.clear()
        self.chain_calls = 0
        self.count_lock = threading.Lock()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(api_server, name, value)
        api_server._RELEASE_CACHE.clear()
        api_server._RELEASE_FAILED.clear()
        api_server._RELEASE_INFLIGHT.clear()

    def _patch(self, name, value):
        self._saved.setdefault(name, getattr(api_server, name))
        setattr(api_server, name, value)

    def _slow_chain(self, delay, result=None, error=None):
        def chain(channel):
            with self.count_lock:
                self.chain_calls += 1
            time.sleep(delay)
            if error is not None:
                raise error
            return result or {'tag_name': 'v9.9.9', 'assets': []}
        self._patch('_fetch_release_chain', chain)

    def _parallel(self, n, channel='prod'):
        results, errors = [], []
        def call():
            try:
                results.append(api_server._fetch_release(channel))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=call) for _ in range(n)]
        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(10)
        return time.monotonic() - t0, results, errors

    def test_parallel_callers_share_one_fetch(self):
        # The kiosk asks ui/system/os at once: they must finish in about the
        # time of one fetch, not three in a row.
        self._slow_chain(0.4)
        elapsed, results, errors = self._parallel(3)
        self.assertEqual(errors, [])
        self.assertEqual([r['tag_name'] for r in results], ['v9.9.9'] * 3)
        self.assertEqual(self.chain_calls, 1)
        self.assertLess(elapsed, 0.8)

    def test_parallel_failures_share_one_fetch_too(self):
        self._slow_chain(0.4, error=OSError('offline'))
        elapsed, results, errors = self._parallel(3)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 3)
        self.assertEqual(self.chain_calls, 1)
        self.assertLess(elapsed, 0.8)

    def test_failure_is_remembered_briefly(self):
        self._slow_chain(0, error=OSError('offline'))
        with self.assertRaises(OSError):
            api_server._fetch_release('prod')
        with self.assertRaises(OSError):
            api_server._fetch_release('prod')
        self.assertEqual(self.chain_calls, 1)
        # ... and only briefly.
        failed_at, err = api_server._RELEASE_FAILED['prod']
        api_server._RELEASE_FAILED['prod'] = (failed_at - api_server._RELEASE_FAILED_TTL - 1, err)
        with self.assertRaises(OSError):
            api_server._fetch_release('prod')
        self.assertEqual(self.chain_calls, 2)

    def test_last_good_release_outlives_a_failure(self):
        api_server._RELEASE_CACHE['prod'] = (time.time() - 3600, {'tag_name': 'v1.0.0'})
        self._slow_chain(0, error=OSError('offline'))
        self.assertEqual(api_server._fetch_release('prod')['tag_name'], 'v1.0.0')
        self.assertEqual(api_server._fetch_release('prod')['tag_name'], 'v1.0.0')
        self.assertEqual(self.chain_calls, 1)

    def test_success_clears_the_failure(self):
        self._slow_chain(0, error=OSError('offline'))
        with self.assertRaises(OSError):
            api_server._fetch_release('prod')
        api_server._RELEASE_FAILED['prod'] = (0, OSError('old'))
        self._slow_chain(0)
        self.assertEqual(api_server._fetch_release('prod')['tag_name'], 'v9.9.9')
        self.assertNotIn('prod', api_server._RELEASE_FAILED)

    def test_other_channels_are_not_blocked_by_a_fetch(self):
        # The lock is never held over I/O: a cached channel answers at once
        # while another channel is still fetching.
        api_server._RELEASE_CACHE['dev'] = (time.time(), {'tag_name': 'v2.0.0-dev.1'})
        self._slow_chain(0.5)
        th = threading.Thread(target=api_server._fetch_release, args=('prod',))
        th.start()
        time.sleep(0.05)
        t0 = time.monotonic()
        self.assertEqual(api_server._fetch_release('dev')['tag_name'], 'v2.0.0-dev.1')
        self.assertLess(time.monotonic() - t0, 0.2)
        th.join(5)

    def test_waiters_give_up_after_a_bound(self):
        self._patch('_RELEASE_WAIT', 0.2)
        self._slow_chain(1.0)
        th = threading.Thread(target=api_server._fetch_release, args=('prod',))
        th.start()
        time.sleep(0.05)
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            api_server._fetch_release('prod')
        self.assertLess(time.monotonic() - t0, 0.6)
        th.join(5)

    def test_no_dns_fails_fast_without_fetching(self):
        def no_urlopen(*a, **k):
            raise AssertionError('nothing to fetch when no source resolves')
        saved = api_server.urllib.request.urlopen
        api_server.urllib.request.urlopen = no_urlopen
        self._patch('_ota_resolvable_hosts', lambda hosts: set())
        try:
            t0 = time.monotonic()
            with self.assertRaises(OSError):
                api_server._fetch_release('prod')
            self.assertLess(time.monotonic() - t0, 0.5)
        finally:
            api_server.urllib.request.urlopen = saved

    def test_dns_lookups_are_bounded_and_parallel(self):
        def slow_lookup(name, timeout=5):
            time.sleep(timeout + 1 if name == 'stuck.example' else 0)
            return {'192.0.2.1'} if name != 'gone.example' else set()
        self._patch('_lookup_host', slow_lookup)
        self._patch('_RELEASE_DNS_TIMEOUT', 0.3)
        t0 = time.monotonic()
        got = api_server._ota_resolvable_hosts({'ok.example', 'gone.example', 'stuck.example', '192.0.2.9'})
        self.assertLess(time.monotonic() - t0, 0.8)
        self.assertEqual(got, {'ok.example', '192.0.2.9'})


if __name__ == '__main__':
    unittest.main()
