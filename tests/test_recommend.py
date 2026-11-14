"""Tests for the Recommended feature's core (hifi_recommend.py).

Everything here is hermetic: an in-memory database, hand-made vectors, no
network and no embedding model. Covered:
  * the time decay (exact half-life, monotonic, frequency adds up);
  * what counts as a play;
  * the taste clusters (k follows the variety of the listening);
  * the ranking (relevance, diversity, per-artist cap, cluster quotas);
  * the exclusion of heard and dismissed albums;
  * the album key, the TF-IDF fallback and the WordPiece tokenizer.

Run with:  python3 tests/test_recommend.py
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import hifi_recommend as rec  # noqa: E402

DAY = 86400.0


def unit(v):
    return rec.l2_normalize(np.array(v, dtype=np.float32))


def blob(centre, n, spread=0.05, seed=0):
    rng = np.random.default_rng(seed)
    return rec.l2_normalize(np.array(centre, dtype=np.float32)
                            + rng.normal(0, spread, (n, len(centre))))


class DecayTestCase(unittest.TestCase):
    def test_half_life_is_exact(self):
        self.assertAlmostEqual(rec.decay_weight(0), 1.0)
        self.assertAlmostEqual(rec.decay_weight(rec.HALF_LIFE_DAYS), 0.5)
        self.assertAlmostEqual(rec.decay_weight(2 * rec.HALF_LIFE_DAYS), 0.25)
        self.assertAlmostEqual(rec.decay_weight(30, half_life=30), 0.5)

    def test_monotonic_and_positive(self):
        w = [rec.decay_weight(d) for d in (0, 1, 7, 30, 365, 3650)]
        self.assertEqual(w, sorted(w, reverse=True))
        self.assertTrue(all(x > 0 for x in w))

    def test_future_play_counts_as_today(self):
        self.assertEqual(rec.decay_weight(-5), 1.0)

    def test_frequency_and_recency_combine(self):
        now = 1_000 * DAY
        plays = ([{'ts': now, 'album_key': 'recent'}]
                 + [{'ts': now - 90 * DAY, 'album_key': 'old'}] * 3
                 + [{'ts': now - 900 * DAY, 'album_key': 'ancient'}] * 3)
        w = rec.play_weights(plays, now=now)
        self.assertAlmostEqual(w['recent'], 1.0)
        self.assertAlmostEqual(w['old'], 1.5)       # three half-weight plays
        self.assertLess(w['ancient'], 0.01)
        self.assertGreater(w['old'], w['recent'])


class PlayTrackerTestCase(unittest.TestCase):
    def feed(self, tr, samples):
        return [tr.feed(*s) for s in samples]

    def test_counts_once_after_thirty_seconds(self):
        tr = rec.PlayTracker()
        got = self.feed(tr, [('a', True, 300, t) for t in range(0, 121, 20)])
        self.assertEqual(got.count(True), 1)
        self.assertEqual(got.index(True), 2)        # 0 → 20 → 40 s heard

    def test_short_track_counts_at_half_length(self):
        tr = rec.PlayTracker()
        got = self.feed(tr, [('a', True, 40, t) for t in (0, 10, 20, 30)])
        self.assertEqual(got, [False, False, True, False])

    def test_skipped_track_is_not_a_play(self):
        tr = rec.PlayTracker()
        got = self.feed(tr, [('a', True, 300, 0), ('a', True, 300, 20),
                             ('b', True, 300, 25), ('b', True, 300, 45)])
        self.assertNotIn(True, got)

    def test_pause_and_stall_do_not_count(self):
        tr = rec.PlayTracker()
        got = self.feed(tr, [('a', True, 300, 0), ('a', False, 300, 20),
                             ('a', False, 300, 600), ('a', True, 300, 620),
                             ('a', True, 300, 5000)])     # collector stalled
        self.assertNotIn(True, got)
        # Only whole playing-to-playing intervals count: 0 → 20 ended paused.
        self.assertFalse(tr.feed('a', True, 300, 5020))   # 20 s heard
        self.assertTrue(tr.feed('a', True, 300, 5040))    # 40 s heard

    def test_same_track_again_after_another_counts_again(self):
        tr = rec.PlayTracker()
        seq = ([('a', True, 300, t) for t in (0, 20, 40)]
               + [('b', True, 300, t) for t in (60, 80, 100)]
               + [('a', True, 300, t) for t in (120, 140, 160)])
        self.assertEqual(self.feed(tr, seq).count(True), 3)


class KeyTestCase(unittest.TestCase):
    def test_editions_and_spelling_collapse(self):
        k = rec.album_key('Björk', 'Homogenic')
        self.assertEqual(k, rec.album_key('bjork', 'Homogenic (Deluxe Edition)'))
        self.assertEqual(k, rec.album_key('BJÖRK ', 'Homogenic [2015 Remaster]'))
        self.assertNotEqual(k, rec.album_key('Björk', 'Post'))

    def test_parenthesis_that_is_the_title_survives(self):
        self.assertNotEqual(rec.album_key('Sigur Rós', '( )'),
                            rec.album_key('Sigur Rós', 'Takk'))
        self.assertNotEqual(rec.album_key('X', 'Live (Paris)'),
                            rec.album_key('X', 'Live (Tokyo)'))


class ClusterTestCase(unittest.TestCase):
    def test_uniform_taste_is_one_cluster(self):
        X = blob([1, 0, 0, 0], 30)
        C, labels, cw = rec.taste_clusters(X, np.ones(30))
        self.assertEqual(C.shape[0], 1)
        self.assertAlmostEqual(float(cw.sum()), 1.0)

    def test_three_tastes_are_three_clusters(self):
        X = np.vstack([blob([1, 0, 0, 0], 12, seed=1),
                       blob([0, 1, 0, 0], 12, seed=2),
                       blob([0, 0, 1, 0], 12, seed=3)])
        C, labels, cw = rec.taste_clusters(X, np.ones(36))
        self.assertEqual(C.shape[0], 3)
        self.assertEqual(len({tuple(labels[i:i + 12]) for i in (0, 12, 24)}), 3)
        for i in (0, 12, 24):
            self.assertEqual(len(set(labels[i:i + 12])), 1)

    def test_k_is_bounded_by_the_amount_of_listening(self):
        X = np.vstack([blob(c, 2, seed=i) for i, c in enumerate(np.eye(6))])
        C, _, _ = rec.taste_clusters(X, np.ones(12))
        self.assertLessEqual(C.shape[0], 12 // rec.MIN_POINTS_PER_CLUSTER)
        many = np.vstack([blob(c, 8, seed=i) for i, c in enumerate(np.eye(8))])
        C, _, _ = rec.taste_clusters(many, np.ones(64))
        self.assertLessEqual(C.shape[0], rec.K_MAX)

    def test_cluster_weight_follows_play_weight(self):
        X = np.vstack([blob([1, 0, 0], 10, seed=1), blob([0, 1, 0], 10, seed=2)])
        w = np.array([9.0] * 10 + [1.0] * 10)
        C, labels, cw = rec.taste_clusters(X, w)
        self.assertEqual(C.shape[0], 2)
        self.assertAlmostEqual(float(cw[labels[0]]), 0.9, places=5)

    def test_deterministic(self):
        X = np.vstack([blob([1, 0, 0], 10, seed=1), blob([0, 1, 0], 10, seed=2)])
        a = rec.taste_clusters(X, np.ones(20))
        b = rec.taste_clusters(X, np.ones(20))
        self.assertTrue(np.array_equal(a[1], b[1]))


def cand(artist, album):
    return {'artist': artist, 'album': album}


class RankTestCase(unittest.TestCase):
    def test_closest_to_the_taste_comes_first(self):
        C = unit([1, 0, 0])[None, :]
        cands = [cand('Far', 'A'), cand('Near', 'B'), cand('Mid', 'C')]
        V = np.array([[0, 1, 0], [1, 0.05, 0], [1, 1, 0]], dtype=np.float32)
        got = rec.rank(V, cands, C, [1.0])
        self.assertEqual([i for i, _, _ in got], [1, 2, 0])
        self.assertGreater(got[0][1], got[1][1])

    def test_per_artist_cap(self):
        C = unit([1, 0])[None, :]
        cands = [cand('Same', f'Album {i}') for i in range(6)] + [cand('Other', 'X')]
        V = np.array([[1, 0.01 * i] for i in range(6)] + [[0.2, 1]], dtype=np.float32)
        got = rec.rank(V, cands, C, [1.0], max_per_artist=2)
        names = [cands[i]['artist'] for i, _, _ in got]
        self.assertEqual(names.count('Same'), 2)
        self.assertIn('Other', names)

    def test_mmr_prefers_something_different(self):
        C = unit([1, 1, 0])[None, :]
        cands = [cand('A', '1'), cand('B', '2'), cand('C', '3')]
        V = np.array([[1, 0.9, 0], [1, 0.88, 0], [0.8, 1, 0.3]], dtype=np.float32)
        plain = rec.rank(V, cands, C, [1.0], n=2, lam=1.0)
        diverse = rec.rank(V, cands, C, [1.0], n=2, lam=0.3)
        self.assertEqual([i for i, _, _ in plain], [0, 1])
        self.assertEqual([i for i, _, _ in diverse], [0, 2])

    def test_every_taste_cluster_is_served(self):
        C = np.vstack([unit([1, 0]), unit([0, 1])])
        cands = ([cand(f'Rock {i}', 'r') for i in range(10)]
                 + [cand(f'Jazz {i}', 'j') for i in range(10)])
        V = np.vstack([blob([1, 0], 10, 0.02, 1), blob([0, 1], 10, 0.2, 2)])
        got = rec.rank(V, cands, C, [0.5, 0.5], n=8)
        per = [c for _, _, c in got]
        self.assertEqual(per.count(0), 4)
        self.assertEqual(per.count(1), 4)

    def test_quota_relaxes_when_a_cluster_runs_dry(self):
        C = np.vstack([unit([1, 0]), unit([0, 1])])
        cands = [cand(f'Rock {i}', 'r') for i in range(6)] + [cand('Jazz', 'j')]
        V = np.vstack([blob([1, 0], 6, 0.02, 1), unit([0, 1])[None, :]])
        got = rec.rank(V, cands, C, [0.5, 0.5], n=6)
        self.assertEqual(len(got), 6)

    def test_heard_and_dismissed_are_excluded(self):
        C = unit([1, 0])[None, :]
        cands = [cand('Heard', 'Old Friend (Deluxe Edition)'),
                 cand('Dismissed', 'No Thanks'), cand('New', 'Fresh')]
        V = np.array([[1, 0], [1, 0.01], [0.5, 1]], dtype=np.float32)
        db = rec.open_db(':memory:')
        rec.record_play(db, 'heard', 'Old Friend', 'Track 1')
        rec.dismiss(db, rec.album_key('Dismissed', 'No Thanks'))
        exclude = rec.heard_keys(db) | rec.dismissed_keys(db)
        got = rec.rank(V, cands, C, [1.0], exclude=exclude)
        self.assertEqual([cands[i]['artist'] for i, _, _ in got], ['New'])

    def test_same_album_from_two_sources_appears_once(self):
        C = unit([1, 0])[None, :]
        cands = [cand('Band', 'Record'), cand('band', 'Record [Remastered]'),
                 cand('Else', 'Thing')]
        V = np.array([[1, 0], [1, 0], [0.9, 0.3]], dtype=np.float32)
        got = rec.rank(V, cands, C, [1.0])
        self.assertEqual(sorted(i for i, _, _ in got), [0, 2])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(rec.rank(np.zeros((0, 2)), [], unit([1, 0])[None, :], [1.0]), [])


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.db = rec.open_db(':memory:')

    def row(self, artist, album, **kw):
        base = {'artist': artist, 'album': album, 'source': 'library',
                'play_kind': 'album_id', 'play_id': '1', 'score': 0.5, 'cluster': 0}
        base.update(kw)
        return base

    def test_list_is_replaced_and_ordered(self):
        rec.write_recommendations(self.db, [self.row('A', '1'), self.row('B', '2')])
        rec.write_recommendations(self.db, [self.row('C', '3', source='qobuz',
                                                     play_kind='url',
                                                     play_id='qobuz://album:9')])
        got = rec.read_recommendations(self.db)
        self.assertEqual([(r['artist'], r['play_kind'], r['play_id']) for r in got],
                         [('C', 'url', 'qobuz://album:9')])

    def test_dismiss_removes_now_and_is_remembered(self):
        rec.write_recommendations(self.db, [self.row('A', '1'), self.row('B', '2')])
        rec.dismiss(self.db, rec.album_key('A', '1'))
        self.assertEqual([r['artist'] for r in rec.read_recommendations(self.db)], ['B'])
        self.assertIn(rec.album_key('a', '1 (Deluxe Edition)'), rec.dismissed_keys(self.db))

    def test_states(self):
        self.assertEqual(rec.history_state(self.db)['state'], 'few_plays')
        for i in range(rec.MIN_PLAYS):
            rec.record_play(self.db, 'A', 'B', f't{i}')
        st = rec.history_state(self.db)
        self.assertEqual((st['state'], st['plays'], st['needed']),
                         ('never_run', rec.MIN_PLAYS, rec.MIN_PLAYS))
        rec.write_recommendations(self.db, [self.row('C', '3')])
        self.assertEqual(rec.history_state(self.db)['state'], 'ok')


class VectorTestCase(unittest.TestCase):
    def test_tfidf_puts_like_with_like(self):
        X = rec.tfidf_vectors([
            'Pink Floyd; progressive rock, psychedelic rock; 1970s; England',
            'Genesis; progressive rock, art rock; 1970s; England',
            'Miles Davis; jazz, cool jazz, modal jazz; 1950s; United States',
            'John Coltrane; jazz, hard bop, modal jazz; 1960s; United States'])
        self.assertGreater(float(X[0] @ X[1]), float(X[0] @ X[2]))
        self.assertGreater(float(X[2] @ X[3]), float(X[1] @ X[3]))
        self.assertAlmostEqual(float(np.linalg.norm(X[0])), 1.0, places=5)

    def test_tfidf_survives_empty_input(self):
        X = rec.tfidf_vectors(['', ''])
        self.assertEqual(X.shape[0], 2)
        self.assertFalse(np.isnan(X).any())

    def test_wordpiece(self):
        vocab = ['[PAD]', '[UNK]', '[CLS]', '[SEP]', 'prog', '##ressive', 'rock',
                 ',', 'bjork', 'jazz']
        tok = rec.WordPiece(vocab)
        self.assertEqual(tok.encode('Progressive Rock, Björk'),
                         [2, 4, 5, 6, 7, 8, 3])
        self.assertEqual(tok.encode('zzz jazz'), [2, 1, 9, 3])
        self.assertEqual(len(tok.encode('rock ' * 500, max_len=16)), 16)
        ids, mask = tok.batch(['rock', 'progressive rock'])
        self.assertEqual(ids.shape, (2, 5))
        self.assertEqual(mask.tolist(), [[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]])


class FakeEmbedder:
    """Stands in for the ONNX model: counts what it is asked to embed."""

    def __init__(self):
        self.seen = []

    def embed(self, texts):
        self.seen.extend(texts)
        return rec.l2_normalize(np.array(
            [[len(t), t.count('a') + 1, 1.0] for t in texts], dtype=np.float32))


class VectorsForTestCase(unittest.TestCase):
    def test_without_the_model_it_falls_back_to_tfidf(self):
        db = rec.open_db(':memory:')
        X, mode = rec.vectors_for(db, ['jazz trio', 'jazz quartet'], None)
        self.assertEqual(mode, 'tfidf')
        self.assertEqual(X.shape[0], 2)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0], 0)

    def test_model_missing_means_no_embedder(self):
        self.assertIsNone(rec.Embedder.load('/nonexistent/hifi-recommend'))

    def test_each_text_is_embedded_once_ever(self):
        db = rec.open_db(':memory:')
        emb = FakeEmbedder()
        X, mode = rec.vectors_for(db, ['alpha', 'banana', 'alpha'], emb)
        self.assertEqual(mode, 'model')
        self.assertEqual(sorted(emb.seen), ['alpha', 'banana'])
        self.assertTrue(np.allclose(X[0], X[2]))
        Y, _ = rec.vectors_for(db, ['banana', 'cherry', 'alpha'], emb)
        self.assertEqual(sorted(emb.seen), ['alpha', 'banana', 'cherry'])
        self.assertTrue(np.allclose(Y[0], X[1]))
        self.assertTrue(np.allclose(Y[2], X[0]))


class SettingsTestCase(unittest.TestCase):
    def test_defaults_are_complete(self):
        s = rec.clean_settings(None)
        self.assertTrue(s['enabled'])
        self.assertEqual(s['schedule'], {'mode': 'daily', 'days': [], 'time': '18:00'})
        self.assertEqual(s['sources'], list(rec.SOURCES))

    def test_garbage_is_cleaned(self):
        s = rec.clean_settings({'enabled': 0, 'sources': ['tidal', 'napster'],
                                'schedule': {'mode': 'hourly', 'time': '25:99',
                                             'days': [1, 1, 9, 'x', True]},
                                'lastfm_key': ' ABCdef0123; rm '})
        self.assertFalse(s['enabled'])
        self.assertEqual(s['sources'], ['tidal'])
        self.assertEqual(s['schedule'], {'mode': 'daily', 'days': [1], 'time': '18:00'})
        self.assertEqual(s['lastfm_key'], 'ABCdef0123')

    def test_schedule_expression(self):
        mk = lambda **sch: {'schedule': sch}
        self.assertEqual(rec.schedule_oncalendar(mk(mode='daily', time='07:30')),
                         '*-*-* 07:30:00')
        self.assertEqual(rec.schedule_oncalendar(mk(mode='days', days=[5, 0], time='21:05')),
                         'Mon,Sat *-*-* 21:05:00')
        self.assertIsNone(rec.schedule_oncalendar(mk(mode='manual')))
        self.assertIsNone(rec.schedule_oncalendar(mk(mode='days', days=[])))
        self.assertIsNone(rec.schedule_oncalendar({'enabled': False}))

    def test_round_trip_on_disk(self):
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'recommend.json')
            self.assertEqual(rec.load_settings(path), rec.clean_settings({}))
            rec.save_settings({'enabled': False, 'lastfm_key': 'ab12'}, path)
            got = rec.load_settings(path)
            self.assertEqual((got['enabled'], got['lastfm_key']), (False, 'ab12'))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class StatusTestCase(unittest.TestCase):
    def status(self, mode='play', **track):
        base = {'artist': 'Pink Floyd', 'album': 'Animals', 'title': 'Dogs',
                'duration': '1024.5', 'url': 'file:///music/dogs.flac', 'id': 7}
        base.update(track)
        return {'mode': mode, 'playlist_cur_index': '2', 'playlist_loop': [base]}

    def test_album_track(self):
        p = rec.play_from_status(self.status())
        self.assertEqual((p['artist'], p['album'], p['title'], p['source']),
                         ('Pink Floyd', 'Animals', 'Dogs', 'library'))
        self.assertTrue(p['playing'])
        self.assertEqual(p['duration'], 1024.5)
        self.assertFalse(rec.play_from_status(self.status(mode='pause'))['playing'])

    def test_sources(self):
        for url, want in (('qobuz://123.flac', 'qobuz'), ('tidal://9.flc', 'tidal'),
                          ('spotify://track:abc', 'spotty'), ('deezer://1.mp3', 'deezer'),
                          ('cdplay://3', 'cd'), ('', '')):
            self.assertEqual(rec.source_of_url(url), want)

    def test_radio_and_stopped_are_not_plays(self):
        self.assertIsNone(rec.play_from_status(self.status(album='', url='http://radio/x')))
        self.assertIsNone(rec.play_from_status(self.status(mode='stop')))
        self.assertIsNone(rec.play_from_status({'mode': 'play', 'playlist_loop': []}))
        self.assertIsNone(rec.play_from_status(None))

    def test_same_file_at_another_queue_position_is_another_listen(self):
        a = rec.play_from_status(self.status())
        b = rec.play_from_status(dict(self.status(), playlist_cur_index='5'))
        self.assertNotEqual(a['track'], b['track'])


class ScreenSettingsTestCase(unittest.TestCase):
    def test_dropin(self):
        self.assertIsNone(rec.schedule_dropin({'enabled': False}))
        self.assertIsNone(rec.schedule_dropin({'schedule': {'mode': 'manual'}}))
        text = rec.schedule_dropin({'schedule': {'mode': 'days', 'days': [0, 5], 'time': '21:05'}})
        self.assertIn('[Timer]\nOnCalendar=\nOnCalendar=Mon,Sat *-*-* 21:05:00\n', text)

    def test_key_never_shown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pub = rec.public_settings({'lastfm_key': 'abcdef0123'}, d)
            self.assertNotIn('lastfm_key', pub)
            self.assertNotIn('abcdef0123', repr(pub))
            self.assertEqual(pub['lastfm'], 'own')
            self.assertEqual(rec.public_settings({}, d)['lastfm'], 'none')
            with open(os.path.join(d, rec.LASTFM_KEY_FILE), 'w') as f:
                f.write('00ff')
            self.assertEqual(rec.public_settings({}, d)['lastfm'], 'project')

    def test_merge_keeps_what_was_not_sent(self):
        cur = {'enabled': True, 'lastfm_key': 'abc123', 'sources': ['library', 'tidal'],
               'schedule': {'mode': 'daily', 'time': '07:30'}}
        got = rec.merge_settings(cur, {'enabled': False})
        self.assertEqual((got['enabled'], got['lastfm_key'], got['sources'], got['schedule']['time']),
                         (False, 'abc123', ['library', 'tidal'], '07:30'))
        self.assertEqual(rec.merge_settings(cur, {'lastfm_key': ''})['lastfm_key'], '')
        self.assertEqual(rec.merge_settings(cur, {'lastfm_key': None})['lastfm_key'], 'abc123')
        self.assertEqual(rec.merge_settings(cur, 'junk'), rec.clean_settings(cur))


class FakeHttp:
    """hifi_metadata.HttpClient's get_json, answered from canned replies."""

    def __init__(self, known=(), offline=False):
        self.known = {rec.norm_text(k): v for k, v in dict(known).items()}
        self.offline = offline
        self.urls = []

    def get_json(self, url, group='mb', **kw):
        import urllib.parse
        self.urls.append(url)
        if self.offline:
            raise OSError('no route')
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if group == 'mb':
            name = q['query'][0][len('artist:"'):-1]
            k = self.known.get(rec.norm_text(name))
            if not k:
                return {'artists': []}
            return {'artists': [{'id': '00000000-0000-0000-0000-%012d' % k['n'],
                                 'name': name, 'country': k.get('country', ''),
                                 'type': 'Group', 'life-span': {'begin': k.get('begin', '')},
                                 'tags': [{'name': t, 'count': 5} for t in k.get('mbtags', [])]}]}
        if group == 'wikidata':
            n = int(q['query'][0].split('wdt:P434 "')[1][24:36])
            k = next(v for v in self.known.values() if v['n'] == n)
            return {'results': {'bindings': [{
                'genres': {'value': '|'.join(k.get('genres', []))},
                'infl': {'value': '|'.join(k.get('influences', []))},
                'd': {'value': k.get('about', '')}}]}}
        if group == 'lastfm':
            k = self.known.get(rec.norm_text(q['artist'][0])) or {}
            if q['method'][0] == 'artist.gettoptags':
                return {'toptags': {'tag': [{'name': t, 'count': 50} for t in k.get('lfm', [])]}}
            return {'similarartists': {'artist': [{'name': s} for s in k.get('similar', [])]}}
        raise AssertionError(group)


KNOWN = {
    'Pink Floyd': {'n': 1, 'country': 'GB', 'begin': '1965', 'mbtags': ['progressive rock'],
                   'genres': ['psychedelic rock', 'art rock'], 'about': 'English rock band',
                   'lfm': ['seen live', 'classic rock'], 'similar': ['Camel', 'Genesis']},
    'Genesis': {'n': 2, 'country': 'GB', 'begin': '1967', 'mbtags': ['progressive rock'],
                'genres': ['art rock'], 'about': 'English rock band'},
    'Camel': {'n': 3, 'country': 'GB', 'begin': '1971', 'mbtags': ['progressive rock'],
              'genres': ['art rock']},
    'Miles Davis': {'n': 4, 'country': 'US', 'mbtags': ['jazz', 'cool jazz'],
                    'genres': ['modal jazz'], 'about': 'American jazz trumpeter'},
    'John Coltrane': {'n': 5, 'country': 'US', 'mbtags': ['jazz', 'hard bop'],
                      'genres': ['modal jazz'], 'about': 'American jazz saxophonist'},
}


class ProfileTestCase(unittest.TestCase):
    def test_sources_are_merged(self):
        p, found = rec.fetch_profile('Pink Floyd', FakeHttp(KNOWN), key='abc')
        self.assertTrue(found)
        self.assertEqual(p['country'], 'GB')
        self.assertEqual(p['decade'], '1960s')
        self.assertEqual(p['genres'], ['psychedelic rock', 'art rock'])
        self.assertEqual(p['tags'], ['progressive rock', 'classic rock'])   # no "seen live"
        self.assertEqual(p['related'][:2], ['Camel', 'Genesis'])
        self.assertEqual(p['about'], 'English rock band')

    def test_no_key_no_lastfm(self):
        http = FakeHttp(KNOWN)
        p, _ = rec.fetch_profile('Pink Floyd', http)
        self.assertFalse(any('audioscrobbler' in u for u in http.urls))
        self.assertEqual(p['tags'], ['progressive rock'])

    def test_noncommercial_switch_removes_those_sources(self):
        old = rec.NONCOMMERCIAL_SOURCES
        rec.NONCOMMERCIAL_SOURCES = False
        try:
            self.assertEqual(rec.lastfm_key({'lastfm_key': 'abc'}), '')
            p, found = rec.fetch_profile('Pink Floyd', FakeHttp(KNOWN))
            self.assertEqual(p['tags'], [])
            self.assertEqual(p['genres'], ['psychedelic rock', 'art rock'])   # CC0 stays
            self.assertTrue(found)
        finally:
            rec.NONCOMMERCIAL_SOURCES = old

    def test_key_order_user_then_project_then_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(rec.lastfm_key({}, d), '')
            with open(os.path.join(d, rec.LASTFM_KEY_FILE), 'w') as f:
                f.write('00ff00ff\n')
            self.assertEqual(rec.lastfm_key({}, d), '00ff00ff')
            self.assertEqual(rec.lastfm_key({'lastfm_key': 'aa11'}, d), 'aa11')

    def test_enrich_caches_limits_and_remembers_unknowns(self):
        db = rec.open_db(':memory:')
        http = FakeHttp(KNOWN)
        have, n = rec.enrich(db, ['Pink Floyd', 'Nobody Band', 'Genesis'], http, limit=2, now=1000)
        self.assertEqual((sorted(have), n), (['pink floyd'], 2))
        calls = len(http.urls)
        have, n = rec.enrich(db, ['Pink Floyd', 'Nobody Band', 'Genesis'], http, now=2000)
        self.assertEqual((sorted(have), n), (['genesis', 'pink floyd'], 1))
        self.assertEqual(len(http.urls), calls + 2)      # only Genesis: MB + Wikidata
        late = 2000 + (rec.PROFILE_RETRY_DAYS + 1) * DAY
        _, n = rec.enrich(db, ['Nobody Band'], http, now=late)
        self.assertEqual(n, 1)                           # unknown: asked again later

    def test_offline_stops_at_once_and_keeps_the_key_out_of_the_log(self):
        db = rec.open_db(':memory:')
        http = FakeHttp(KNOWN, offline=True)

        class Log:
            lines = []

            def info(self, fmt, *a):
                self.lines.append(fmt % a)
        have, n = rec.enrich(db, ['Pink Floyd', 'Genesis'], http, key='SECRETKEY', log=Log())
        self.assertEqual((have, n, len(http.urls)), ({}, 0, 1))
        self.assertNotIn('SECRETKEY', ' '.join(Log.lines))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM artist_info').fetchone()[0], 0)

    def test_describe(self):
        p, _ = rec.fetch_profile('Pink Floyd', FakeHttp(KNOWN), key='k')
        text = rec.describe('Pink Floyd', p, genres=['Rock'], year=1977)
        self.assertEqual(text, 'Pink Floyd; rock, psychedelic rock, art rock, progressive rock, '
                               'classic rock; 1960s; GB; related: Camel, Genesis; English rock band')
        self.assertEqual(rec.describe('Unknown', None, ['Folk'], 1999), 'Unknown; folk; 1990s')
        self.assertEqual(rec.describe('Unknown'), 'Unknown')


class FakeLyrion:
    """rpc(player, command) over a tiny library and two streaming plugins."""

    def __init__(self, albums, signed_in=('qobuz', 'tidal')):
        self.albums = albums             # (id, artist, album, genre)
        self.signed_in = signed_in
        self.qobuz_recent = ['halo']
        self.calls = []
        self.catalog = {
            'Camel': ['Mirage', 'Moonmadness'],
            'Pink Floyd': ['Animals', 'Meddle'],
            'Genesis': ['Foxtrot'],
        }

    def __call__(self, player, cmd):
        self.calls.append((player, list(cmd)))
        if cmd[0] == 'players':
            return {'players_loop': [{'playerid': 'aa:bb', 'ip': '127.0.0.1:4321'}]}
        if cmd[0] == 'genres':
            names = sorted({a[3] for a in self.albums})
            return {'genres_loop': [{'id': i, 'genre': g} for i, g in enumerate(names)]}
        if cmd[0] == 'albums':
            names = sorted({a[3] for a in self.albums})
            rows = self.albums
            for c in cmd:
                if str(c).startswith('genre_id:'):
                    rows = [a for a in rows if a[3] == names[int(str(c)[9:])]]
            return {'albums_loop': [{'id': a[0], 'artist': a[1], 'album': a[2], 'year': 1975,
                                     'artwork_track_id': 'art%s' % a[0]} for a in rows]}
        if cmd[0] == 'pref':
            return {'_p2': list(self.qobuz_recent)}
        if cmd[:2] == ['qobuz', 'recentsearches']:
            del self.qobuz_recent[int(cmd[2].split(':')[1])]
            return {}
        if cmd[0] in ('qobuz', 'tidal', 'spotty', 'deezer') and cmd[1] == 'items':
            return self.plugin(cmd[0], {str(c).split(':', 1)[0]: str(c).split(':', 1)[1]
                                        for c in cmd[4:]})
        raise AssertionError(cmd)

    def plugin(self, service, a):
        if service not in self.signed_in:
            return {'loop_loop': [{'id': '0', 'name': 'Please sign in', 'type': 'textarea'}]}
        item, term = a.get('item_id'), a.get('search')
        if service == 'qobuz':
            if item is None:
                return {'loop_loop': [{'id': '0', 'name': 'Cerca', 'type': 'link'}]}
            if item == '0':
                return {'loop_loop': [{'id': '0.0', 'name': 'New search', 'type': 'search'}]}
            if item == '0.0':
                self.qobuz_recent.append(term)
                self.term = term
                return {'loop_loop': [{'id': 'q.albums', 'name': 'Uscite',
                                       'image': 'html/images/albums.png'}]}
            return {'item_loop': [
                {'text': '%s\n%s (1974)' % (t, self.term), 'presetParams': None,
                 'icon': '/imageproxy/https%%3A%%2F%%2Fstatic.qobuz.com%%2Fcovers%%2Fab%%2Fq%dx_600.jpg/image.jpg' % i}
                for i, t in enumerate(self.catalog.get(self.term, []))]
                + [{'text': 'Tribute\nSomebody Else', 'icon': '/x/zz9_600.jpg'}]}
        if item is None:
            return {'loop_loop': [{'id': '6', 'name': 'Artisti', 'type': 'link'},
                                  {'id': '7', 'name': 'Cerca', 'type': 'search'}]}
        if item == '7':
            self.term = term
            return {'loop_loop': [{'id': 't.all', 'name': 'Tutto'}, {'id': 't.pl', 'name': 'Playlist'},
                                  {'id': 't.ar', 'name': 'Artisti'}, {'id': 't.al', 'name': 'Raccolte'}]}
        assert item == 't.al', item
        return {'item_loop': [
            {'text': '%s [E]\n%s' % (t, self.term),
             'presetParams': {'favorites_url': 'tidal://album:%d' % (100 + i), 'icon': 'http://img/%d.jpg' % i}}
            for i, t in enumerate(self.catalog.get(self.term, []))]}


class ServiceSearchTestCase(unittest.TestCase):
    def test_tidal_gives_the_favourite_url(self):
        ly = FakeLyrion([])
        got = rec.ServiceSearch(ly, 'aa:bb', 'tidal').albums('Camel')
        self.assertEqual([(a['album'], a['play_id'], a['cover']) for a in got],
                         [('Mirage', 'tidal://album:100', 'http://img/0.jpg'),
                          ('Moonmadness', 'tidal://album:101', 'http://img/1.jpg')])

    def test_qobuz_url_from_cover_and_other_artists_dropped(self):
        ly = FakeLyrion([])
        got = rec.ServiceSearch(ly, 'aa:bb', 'qobuz').albums('Camel')
        self.assertEqual([(a['artist'], a['album'], a['play_id']) for a in got],
                         [('Camel', 'Mirage', 'qobuz://album:q0x.qbz'),
                          ('Camel', 'Moonmadness', 'qobuz://album:q1x.qbz')])

    def test_qobuz_recent_searches_are_left_as_found(self):
        ly = FakeLyrion([])
        s = rec.ServiceSearch(ly, 'aa:bb', 'qobuz')
        s.albums('Camel')
        self.assertEqual(ly.qobuz_recent, ['halo'])
        self.assertEqual(s.albums('halo'), [])           # the owner's own term: hands off
        self.assertEqual(ly.qobuz_recent, ['halo'])

    def test_not_signed_in_is_not_usable(self):
        s = rec.ServiceSearch(FakeLyrion([], signed_in=()), 'aa:bb', 'deezer')
        self.assertEqual(s.albums('Camel'), [])
        self.assertFalse(s.usable)

    def test_unstreamable_and_urlless_rows_are_dropped(self):
        f = rec._album_from_item
        self.assertIsNone(f('tidal', {'text': '* Gone\nBand', 'presetParams': {'favorites_url': 'tidal://album:1'}}))
        self.assertIsNone(f('spotty', {'text': 'Album\nBand'}))
        self.assertIsNone(f('tidal', {'text': 'No artist line', 'presetParams': {'favorites_url': 'x'}}))


LIBRARY = [(1, 'Pink Floyd', 'Animals', 'Rock'), (2, 'Pink Floyd', 'Meddle', 'Rock'),
           (3, 'Genesis', 'Foxtrot', 'Rock'), (4, 'Genesis', 'Selling England by the Pound', 'Rock'),
           (5, 'Miles Davis', 'Kind of Blue', 'Jazz'), (6, 'John Coltrane', 'Blue Train', 'Jazz'),
           (7, 'John Coltrane', 'Giant Steps', 'Jazz')]


class RunTestCase(unittest.TestCase):
    def setUp(self):
        self.db = rec.open_db(':memory:')
        self.now = 1_000 * DAY

    def listen(self, artist, album, n, days_ago=1):
        for i in range(n):
            rec.record_play(self.db, artist, album, 't%d' % i, 'library', self.now - days_ago * DAY)

    def test_thin_history_changes_nothing(self):
        rec.write_recommendations(self.db, [{'album': 'Old', 'artist': 'List', 'source': 'library',
                                             'play_kind': 'album_id', 'play_id': '9',
                                             'score': 1, 'cluster': 0}])
        self.listen('Pink Floyd', 'Animals', 3)
        got = rec.run(self.db, FakeLyrion(LIBRARY), now=self.now)
        self.assertEqual(got['outcome'], 'few_plays')
        self.assertEqual(len(rec.read_recommendations(self.db)), 1)

    def test_library_alone_is_a_profile(self):
        # No play counted yet: a rock shelf at home, and a streaming service
        # that has more by the same names.
        shelf = [(i, 'Pink Floyd' if i % 2 else 'Genesis', 'Album %d' % i, 'Rock')
                 for i in range(1, rec.MIN_LIBRARY_ALBUMS + 1)]
        self.assertEqual(rec.history_state(self.db, library=len(shelf))['state'], 'never_run')
        got = rec.run(self.db, FakeLyrion(shelf), http=None,
                      settings={'sources': ['qobuz']}, now=self.now)
        self.assertEqual((got['outcome'], got['plays'], got['library']), ('ok', 0, len(shelf)))
        rows = rec.read_recommendations(self.db)
        self.assertTrue(rows)
        self.assertEqual({r['source'] for r in rows}, {'qobuz'})
        self.assertLessEqual({r['artist'] for r in rows}, {'Pink Floyd', 'Genesis'})

    def test_library_weights(self):
        albums = [{'artist': 'Genesis'}] * 9 + [{'artist': 'Camel'}] + [{'artist': 'Various Artists'}] * 5
        w = rec.library_weights(albums)
        self.assertEqual(w, {'genesis': rec.LIBRARY_ALBUMS_CAP * rec.LIBRARY_ALBUM_WEIGHT,
                             'camel': rec.LIBRARY_ALBUM_WEIGHT})
        # a shelf never outweighs a handful of recent plays
        self.assertLess(max(w.values()), 2 * rec.decay_weight(0))

    def test_disabled(self):
        self.listen('Pink Floyd', 'Animals', 30)
        got = rec.run(self.db, FakeLyrion(LIBRARY), settings={'enabled': False}, now=self.now)
        self.assertEqual(got['outcome'], 'disabled')

    def test_offline_library_only_run(self):
        self.listen('Pink Floyd', 'Animals', 30)
        got = rec.run(self.db, FakeLyrion(LIBRARY), http=None,
                      settings={'sources': ['library']}, now=self.now)
        self.assertEqual((got['outcome'], got['mode'], got['fetched']), ('ok', 'tfidf', 0))
        rows = rec.read_recommendations(self.db)
        albums = [r['album'] for r in rows]
        self.assertNotIn('Animals', albums)                       # heard
        self.assertEqual(rows[0]['album'], 'Meddle')              # same artist, same genre
        self.assertEqual((rows[0]['source'], rows[0]['play_kind'], rows[0]['play_id'],
                          rows[0]['cover']), ('library', 'album_id', '2', 'art2'))
        # The jazz on the shelf is taste too (library_weights), but thirty
        # plays of rock say far more: every rock album scores above it. The
        # order of the list is MMR's, which mixes for variety.
        rock = [r['score'] for r in rows if r['album'] in ('Foxtrot', 'Selling England by the Pound')]
        jazz = [r['score'] for r in rows if r['album'] in ('Kind of Blue', 'Blue Train', 'Giant Steps')]
        self.assertTrue(rock and (not jazz or min(rock) > max(jazz)))

    def test_dismissed_album_stays_out_of_later_runs(self):
        self.listen('Pink Floyd', 'Animals', 30)
        rec.run(self.db, FakeLyrion(LIBRARY), settings={'sources': ['library']}, now=self.now)
        rec.dismiss(self.db, rec.album_key('Pink Floyd', 'Meddle'))
        rec.run(self.db, FakeLyrion(LIBRARY), settings={'sources': ['library']}, now=self.now + DAY)
        self.assertNotIn('Meddle', [r['album'] for r in rec.read_recommendations(self.db)])

    def test_streaming_brings_related_artists_and_stays_tidy(self):
        self.listen('Pink Floyd', 'Animals', 30)
        ly = FakeLyrion(LIBRARY, signed_in=('qobuz', 'tidal'))
        got = rec.run(self.db, ly, http=FakeHttp(KNOWN), now=self.now,
                      settings={'lastfm_key': 'abc', 'sources': list(rec.SOURCES)})
        self.assertEqual(got['outcome'], 'ok')
        rows = rec.read_recommendations(self.db)
        camel = [r for r in rows if r['artist'] == 'Camel']
        self.assertTrue(camel)
        self.assertTrue(all(r['play_kind'] == 'url' and r['source'] in ('qobuz', 'tidal')
                            for r in camel))
        self.assertLessEqual(len(camel), rec.MAX_PER_ARTIST)
        keys = [r['album_key'] for r in rows]
        self.assertEqual(len(keys), len(set(keys)))               # one Meddle, not three
        self.assertNotIn(rec.album_key('Pink Floyd', 'Animals'), keys)
        self.assertEqual(ly.qobuz_recent, ['halo'])
        self.assertLessEqual(got['searches'], 2 * rec.MAX_SEARCHES_PER_SERVICE)

    def test_run_bookkeeping(self):
        rid = rec.start_run(self.db, now=time_now())
        self.assertTrue(rec.history_state(self.db)['running'])
        rec.finish_run(self.db, rid, {'outcome': 'ok', 'mode': 'tfidf', 'items': 3})
        st = rec.history_state(self.db)
        self.assertFalse(st['running'])
        self.assertEqual(st['last_run']['outcome'], 'ok')

    def test_a_killed_run_does_not_look_running_forever(self):
        rec.start_run(self.db, now=time_now() - rec.RUN_TIMEOUT - 60)
        self.assertFalse(rec.history_state(self.db)['running'])


def time_now():
    import time
    return time.time()


if __name__ == '__main__':
    unittest.main()
