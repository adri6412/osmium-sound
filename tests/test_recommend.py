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


if __name__ == '__main__':
    unittest.main()
