#!/usr/bin/env python3
"""Osmium Sound — "Recommended": albums the listener may like, computed offline.

A scheduled job (hifi-recommend.service, started by the timer the owner sets in
Settings, or by the "Compute now" button) turns the listening history into a
short list of playable albums and writes it to one SQLite table. The kiosk only
ever reads that table: nothing here runs while somebody browses.

Shape of the thing:
  * plays            — one row per listened track, written by api_server's
                       collector thread (PlayTracker decides what counts).
  * weights          — each play decays exponentially with its age, so last
                       month matters more than last year.
  * vectors          — one vector per artist/album, from a small sentence
                       embedding model when onnxruntime and the model file are
                       there, from plain TF-IDF over the same words otherwise.
  * taste clusters   — weighted k-means over what was played (k = 1..5), so
                       the list covers every corner of the listener's taste
                       and not just the average of them.
  * ranking          — cosine to the nearest cluster centre, then MMR and a
                       per-artist cap so the list is not twenty albums by one
                       band.
  * recommendations  — the output table, rewritten in one transaction.

🚨 Licensing switch. NONCOMMERCIAL_SOURCES gates every data source whose terms
allow non-commercial use only (MusicBrainz genre/tag associations, CC BY-NC-SA;
Last.fm). It is on because Osmium is distributed as open source only. For a
commercially licensed edition either obtain those licences or set it to False:
the pipeline then runs on the free sources alone (Wikidata, MusicBrainz core
data, Wikipedia text, the library's own tags).

Only numpy and the standard library are required; onnxruntime is optional.
"""
import hashlib
import math
import os
import re
import sqlite3
import time
import unicodedata

import numpy as np

NONCOMMERCIAL_SOURCES = True

DB_DIR = os.environ.get('HIFI_RECOMMEND_DIR', '/var/lib/hifi-player/recommend')
DB_NAME = 'recommend.db'

MODEL_DIR = os.environ.get('HIFI_RECOMMEND_MODEL_DIR',
                           '/usr/local/share/hifi-recommend')
MODEL_FILE = 'model.onnx'
VOCAB_FILE = 'vocab.txt'
MODEL_NAME = 'all-MiniLM-L6-v2-int8'   # part of the cache key: change with the model
EMBED_DIM = 384
EMBED_MAX_TOKENS = 64

HALF_LIFE_DAYS = 90.0     # a play counts half after this long
MIN_PLAYS = 20            # below this the history says too little: empty state
# The local library is taste too: an album someone bothered to own says what
# they like before a single play was counted. Each album gives its artist
# this much, up to LIBRARY_ALBUMS_CAP albums — a quarter of a play heard
# today, so a few real plays soon weigh more than a shelf.
LIBRARY_ALBUM_WEIGHT = 0.25
LIBRARY_ALBUMS_CAP = 4
MIN_LIBRARY_ALBUMS = 10   # a library this big is enough to start without plays
# What the owner marked on a streaming service is a shelf as well. A favourite
# album counts like an owned one (same weight, same cap, counted together);
# following an artist says a little more than keeping one of their albums.
FAVORITE_ARTIST_WEIGHT = 0.5
# A service's own listening history (Deezer has one) comes without dates:
# each track counts as a play one half-life old, a few per artist at most,
# since what was heard on this box is in our own log already.
SERVICE_PLAY_WEIGHT = 0.5
SERVICE_PLAYS_CAP = 10
MAX_RESULTS = 40
MAX_PER_ARTIST = 2
MMR_LAMBDA = 0.7          # 1 = pure relevance, 0 = pure diversity
LIBRARY_SHARE = 0.5       # of the list, when streaming albums compete for it
K_MIN, K_MAX = 2, 5
MIN_POINTS_PER_CLUSTER = 4
UNIFORM_COHESION = 0.95   # mean cosine to the one centre above which k = 1

RUN_TIMEOUT = 1800        # seconds; the same as the unit's TimeoutStartSec

PLAY_MIN_SECONDS = 30.0   # a track counts once heard this long…
PLAY_MIN_FRACTION = 0.5   # …or for half of its length, whichever comes first

SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    album_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS plays_album_key ON plays(album_key);
CREATE TABLE IF NOT EXISTS dismissed (
    album_key TEXT PRIMARY KEY,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    text_hash TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    vec BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
    rank INTEGER PRIMARY KEY,
    album TEXT NOT NULL,
    artist TEXT NOT NULL,
    cover TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    play_kind TEXT NOT NULL,
    play_id TEXT NOT NULL,
    score REAL NOT NULL,
    cluster INTEGER NOT NULL,
    album_key TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started REAL NOT NULL,
    finished REAL,
    outcome TEXT NOT NULL DEFAULT 'running',
    mode TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
"""


# ── Keys ─────────────────────────────────────────────────────────────────────

_EDITION = re.compile(
    r'\s*[\(\[][^\)\]]*(remaster|deluxe|edition|expanded|anniversary|bonus|'
    r'version|mono|stereo|reissue|hi-?res)[^\)\]]*[\)\]]', re.I)


def norm_text(s):
    """Lower-case, accent-free, punctuation-free: 'Björk!' and 'bjork' match."""
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


def album_key(artist, album):
    """What makes two albums "the same" for history and exclusion: the same
    artist and title once editions ("(Deluxe Edition)", "[2011 Remaster]") and
    spelling noise are gone, whichever source they come from."""
    title = _EDITION.sub('', str(album or ''))
    return norm_text(artist) + '|' + (norm_text(title) or norm_text(album))


# ── Database ─────────────────────────────────────────────────────────────────

def db_path():
    return os.path.join(DB_DIR, DB_NAME)


def open_db(path=None):
    path = path or db_path()
    if path != ':memory:':
        os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    if path != ':memory:':
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
    db.executescript(SCHEMA)
    return db


def record_play(db, artist, album, title, source='', ts=None):
    db.execute(
        'INSERT INTO plays (ts, artist, album, title, source, album_key) '
        'VALUES (?,?,?,?,?,?)',
        (time.time() if ts is None else ts, artist or '', album or '',
         title or '', source or '', album_key(artist, album)))
    db.commit()


def play_count(db):
    return db.execute('SELECT COUNT(*) FROM plays').fetchone()[0]


def heard_keys(db):
    return {r[0] for r in db.execute('SELECT DISTINCT album_key FROM plays')}


def dismissed_keys(db):
    return {r[0] for r in db.execute('SELECT album_key FROM dismissed')}


def dismiss(db, key, ts=None):
    """"Not interested": gone from the current list now and from every later
    run."""
    db.execute('INSERT OR REPLACE INTO dismissed (album_key, ts) VALUES (?,?)',
               (key, time.time() if ts is None else ts))
    db.execute('DELETE FROM recommendations WHERE album_key = ?', (key,))
    db.commit()


def write_recommendations(db, rows, now=None):
    """Replace the whole list in one transaction: a reader sees the old list
    or the new one, never half of each."""
    now = time.time() if now is None else now
    with db:
        db.execute('DELETE FROM recommendations')
        db.executemany(
            'INSERT INTO recommendations (rank, album, artist, cover, source, '
            'play_kind, play_id, score, cluster, album_key, created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            [(i, r['album'], r['artist'], r.get('cover', ''), r['source'],
              r['play_kind'], r['play_id'], float(r['score']),
              int(r['cluster']), album_key(r['artist'], r['album']), now)
             for i, r in enumerate(rows)])


def read_recommendations(db):
    return [dict(r) for r in
            db.execute('SELECT * FROM recommendations ORDER BY rank')]


# ── What counts as a play ────────────────────────────────────────────────────

class PlayTracker:
    """Turns periodic "what is playing" samples into plays.

    feed() takes the track identity (anything hashable, None when stopped),
    whether it is actually playing, its duration in seconds (0 if unknown) and
    the sample time. It returns True exactly once per listen: when the track
    has been heard for PLAY_MIN_SECONDS or PLAY_MIN_FRACTION of its length.
    Paused time does not count, and a gap between two samples longer than
    `max_gap` (the device slept, the collector stalled) is not counted as
    listening either.
    """

    def __init__(self, max_gap=90.0):
        self.max_gap = max_gap
        self.track = None
        self.heard = 0.0
        self.last = None
        self.counted = False

    def feed(self, track, playing, duration, now):
        if track != self.track:
            self.track, self.heard, self.counted = track, 0.0, False
            self.last = now if (track is not None and playing) else None
            return False
        if track is None or not playing:
            self.last = None
            return False
        if self.last is not None and 0 < now - self.last <= self.max_gap:
            self.heard += now - self.last
        self.last = now
        if self.counted:
            return False
        need = PLAY_MIN_SECONDS
        if duration and duration > 0:
            need = min(need, duration * PLAY_MIN_FRACTION)
        if self.heard >= need:
            self.counted = True
            return True
        return False


# ── Time decay ───────────────────────────────────────────────────────────────

def decay_weight(age_days, half_life=HALF_LIFE_DAYS):
    """Weight of one play that is `age_days` old: 1 today, 0.5 after one
    half-life, 0.25 after two. A play dated in the future counts as today."""
    return math.exp(-math.log(2.0) * max(0.0, age_days) / half_life)


def play_weights(plays, now=None, half_life=HALF_LIFE_DAYS, key='album_key'):
    """Sum of decayed plays per key: frequency and recency in one number.
    `plays` is an iterable of mappings with 'ts' and `key`."""
    now = time.time() if now is None else now
    out = {}
    for p in plays:
        w = decay_weight((now - p['ts']) / 86400.0, half_life)
        out[p[key]] = out.get(p[key], 0.0) + w
    return out


_NOT_AN_ARTIST = {'various artists', 'various', 'va', 'artisti vari', 'aa vv',
                  'verschiedene interpreten', 'unknown artist', 'no artist'}


def library_weights(albums):
    """Weight per artist key from the albums owned (see LIBRARY_ALBUM_WEIGHT).
    Compilations say nothing about one artist and are left out."""
    count = {}
    for a in albums:
        k = norm_text(a.get('artist') or '')
        if k and k not in _NOT_AN_ARTIST:
            count[k] = count.get(k, 0) + 1
    return {k: min(n, LIBRARY_ALBUMS_CAP) * LIBRARY_ALBUM_WEIGHT
            for k, n in count.items()}


def taste_weights(artists=(), history=()):
    """Weight per artist key from what a streaming account says beyond its
    favourite albums: the artists followed and the tracks in the service's
    listening history (one artist name per track)."""
    out = {}
    for k in {norm_text(a) for a in artists}:
        if k and k not in _NOT_AN_ARTIST:
            out[k] = FAVORITE_ARTIST_WEIGHT
    count = {}
    for a in history:
        k = norm_text(a)
        if k and k not in _NOT_AN_ARTIST:
            count[k] = count.get(k, 0) + 1
    for k, n in count.items():
        out[k] = out.get(k, 0.0) + min(n, SERVICE_PLAYS_CAP) * SERVICE_PLAY_WEIGHT
    return out


# ── Vectors ──────────────────────────────────────────────────────────────────

def l2_normalize(X):
    X = np.asarray(X, dtype=np.float32)
    n = np.linalg.norm(X, axis=-1, keepdims=True)
    return X / np.maximum(n, 1e-12)


_WORD = re.compile(r'[a-z0-9]+')


def tfidf_vectors(texts, max_features=2048):
    """The no-model fallback: one L2-normalised TF-IDF row per text over the
    words and two-word phrases all the texts share ("progressive rock" is a
    feature of its own). Rows of texts with no known word are all zero."""
    docs = []
    for t in texts:
        words = _WORD.findall(norm_text(t))
        docs.append(words + [a + ' ' + b for a, b in zip(words, words[1:])])
    df = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1
    # A term seen once tells nothing about similarity; keep the most shared.
    vocab = sorted((w for w, c in df.items() if c >= 2 or len(docs) < 2),
                   key=lambda w: (-df[w], w))[:max_features]
    index = {w: i for i, w in enumerate(vocab)}
    X = np.zeros((len(docs), max(1, len(vocab))), dtype=np.float32)
    n = len(docs)
    for r, d in enumerate(docs):
        for w in d:
            i = index.get(w)
            if i is not None:
                X[r, i] += 1.0
    if vocab:
        idf = np.array([math.log((1 + n) / (1 + df[w])) + 1.0 for w in vocab],
                       dtype=np.float32)
        X *= idf
    return l2_normalize(X)


class WordPiece:
    """BERT's uncased tokenizer (basic split + greedy WordPiece) in plain
    Python, so the embedding model needs no tokenizer package. `vocab` is the
    model's vocab.txt as a list of tokens or a path to it."""

    def __init__(self, vocab, max_chars_per_word=100):
        if isinstance(vocab, str):
            with open(vocab, encoding='utf-8') as f:
                vocab = [line.rstrip('\n') for line in f]
        self.ids = {t: i for i, t in enumerate(vocab)}
        self.max_chars = max_chars_per_word
        self.unk = self.ids.get('[UNK]', 0)
        self.cls = self.ids.get('[CLS]', 0)
        self.sep = self.ids.get('[SEP]', 0)
        self.pad = self.ids.get('[PAD]', 0)

    @staticmethod
    def _basic(text):
        text = unicodedata.normalize('NFD', str(text or '').lower())
        out, word = [], []
        for c in text:
            cat = unicodedata.category(c)
            if cat == 'Mn':
                continue
            if c.isspace() or cat.startswith('C'):
                if word:
                    out.append(''.join(word))
                    word = []
            elif cat.startswith('P') or cat.startswith('S'):
                if word:
                    out.append(''.join(word))
                    word = []
                out.append(c)
            else:
                word.append(c)
        if word:
            out.append(''.join(word))
        return out

    def _pieces(self, word):
        if len(word) > self.max_chars:
            return [self.unk]
        out, start = [], 0
        while start < len(word):
            end, cur = len(word), None
            while start < end:
                piece = word[start:end]
                if start:
                    piece = '##' + piece
                if piece in self.ids:
                    cur = self.ids[piece]
                    break
                end -= 1
            if cur is None:
                return [self.unk]
            out.append(cur)
            start = end
        return out

    def encode(self, text, max_len=64):
        ids = []
        for w in self._basic(text):
            ids.extend(self._pieces(w))
            if len(ids) >= max_len - 2:
                break
        return [self.cls] + ids[:max_len - 2] + [self.sep]

    def batch(self, texts, max_len=64):
        """(input_ids, attention_mask) padded to the longest text."""
        enc = [self.encode(t, max_len) for t in texts]
        width = max((len(e) for e in enc), default=2)
        ids = np.full((len(enc), width), self.pad, dtype=np.int64)
        mask = np.zeros((len(enc), width), dtype=np.int64)
        for r, e in enumerate(enc):
            ids[r, :len(e)] = e
            mask[r, :len(e)] = 1
        return ids, mask


def text_hash(text, model):
    return hashlib.sha256((model + '\0' + text).encode('utf-8')).hexdigest()


class Embedder:
    """The sentence-embedding model (all-MiniLM-L6-v2, int8 ONNX) on the CPU.

    Use Embedder.load(): it returns None when onnxruntime or the model files
    are not there, and the caller falls back to tfidf_vectors(). Two threads
    and short inputs keep an Atom responsive while the job runs.
    """

    def __init__(self, session, tokenizer):
        self.session = session
        self.tok = tokenizer
        self.inputs = {i.name for i in session.get_inputs()}

    @classmethod
    def load(cls, model_dir=None, threads=2):
        model_dir = model_dir or MODEL_DIR
        model = os.path.join(model_dir, MODEL_FILE)
        vocab = os.path.join(model_dir, VOCAB_FILE)
        if not (os.path.isfile(model) and os.path.isfile(vocab)):
            return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            session = ort.InferenceSession(
                model, sess_options=opts, providers=['CPUExecutionProvider'])
            return cls(session, WordPiece(vocab))
        except Exception:
            return None

    def embed(self, texts, batch=16, max_len=EMBED_MAX_TOKENS):
        """One L2-normalised row per text (mean of the token vectors)."""
        texts = list(texts)
        out = [None] * len(texts)
        # Similar lengths together: less padding, less work.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        for at in range(0, len(order), batch):
            idx = order[at:at + batch]
            ids, mask = self.tok.batch([texts[i] for i in idx], max_len)
            feed = {'input_ids': ids, 'attention_mask': mask}
            if 'token_type_ids' in self.inputs:
                feed['token_type_ids'] = np.zeros_like(ids)
            tokens = self.session.run(None, feed)[0]
            m = mask[:, :, None].astype(np.float32)
            pooled = (tokens * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1.0)
            for row, i in zip(l2_normalize(pooled), idx):
                out[i] = row
        if not out:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        return np.vstack(out).astype(np.float32)


def vectors_for(db, texts, embedder):
    """Vectors for `texts`, and how they were made ('model' or 'tfidf').

    With the model, each distinct text is embedded once ever: results are kept
    in the `embeddings` table by hash, so a later run only pays for what is
    new. Without it, TF-IDF over these same texts (they must all be passed
    together: history and candidates share one vocabulary)."""
    texts = list(texts)
    if embedder is None:
        return tfidf_vectors(texts), 'tfidf'
    hashes = [text_hash(t, MODEL_NAME) for t in texts]
    have = {}
    wanted = sorted(set(hashes))
    for at in range(0, len(wanted), 500):
        part = wanted[at:at + 500]
        for h, blob in db.execute(
                'SELECT text_hash, vec FROM embeddings WHERE model = ? AND '
                'text_hash IN (%s)' % ','.join('?' * len(part)),
                [MODEL_NAME] + part):
            have[h] = np.frombuffer(blob, dtype=np.float32)
    todo = {}
    for h, t in zip(hashes, texts):
        if h not in have:
            todo.setdefault(h, t)
    if todo:
        vecs = embedder.embed(list(todo.values()))
        with db:
            db.executemany(
                'INSERT OR REPLACE INTO embeddings (text_hash, model, vec) '
                'VALUES (?,?,?)',
                [(h, MODEL_NAME, v.astype(np.float32).tobytes())
                 for h, v in zip(todo, vecs)])
        have.update(zip(todo, vecs))
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32), 'model'
    return np.vstack([have[h] for h in hashes]).astype(np.float32), 'model'


# ── Taste clusters ───────────────────────────────────────────────────────────

def kmeans(X, weights, k, seed=0, iters=30):
    """Weighted spherical k-means on L2-normalised rows. Returns
    (centroids, labels). Deterministic for a given seed (k-means++ start)."""
    X = l2_normalize(X)
    w = np.asarray(weights, dtype=np.float64)
    n = X.shape[0]
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    centres = [X[int(np.argmax(w))]]
    for _ in range(1, k):
        d = 1.0 - np.max(X @ np.array(centres).T, axis=1)
        p = np.maximum(d, 0.0) * w
        if p.sum() <= 0:
            centres.append(X[int(rng.integers(n))])
        else:
            centres.append(X[int(rng.choice(n, p=p / p.sum()))])
    C = l2_normalize(np.array(centres))
    labels = np.zeros(n, dtype=np.int64)
    for it in range(iters):
        new = np.argmax(X @ C.T, axis=1)
        if it and np.array_equal(new, labels):
            break
        labels = new
        for c in range(k):
            m = labels == c
            if m.any():
                C[c] = (X[m] * w[m, None]).sum(axis=0)
        C = l2_normalize(C)
    return C, labels


def silhouette(X, labels):
    """Mean silhouette with cosine distance; 0 when there is one cluster."""
    X = l2_normalize(X)
    ids = np.unique(labels)
    if len(ids) < 2:
        return 0.0
    D = 1.0 - X @ X.T
    scores = []
    for i in range(X.shape[0]):
        own = labels == labels[i]
        if own.sum() <= 1:
            scores.append(0.0)
            continue
        a = D[i, own].sum() / (own.sum() - 1)
        b = min(D[i, labels == c].mean() for c in ids if c != labels[i])
        scores.append((b - a) / max(a, b, 1e-12))
    return float(np.mean(scores))


def taste_clusters(X, weights, seed=0):
    """Pick k by silhouette among K_MIN..K_MAX, as far as the amount of
    listening allows; a thin or uniform history gets a single cluster.
    Returns (centroids, labels, cluster_weights) with weights summing to 1."""
    X = l2_normalize(X)
    w = np.asarray(weights, dtype=np.float64)
    n = X.shape[0]
    best = kmeans(X, w, 1, seed)
    best_score = 0.05          # a split has to be at least this clear
    # Silhouette has no sense of scale: it would happily split a tight blob
    # along its noise. When everything already sits next to the one centre
    # there is a single taste and nothing to split.
    cohesion = float(np.average(X @ best[0][0], weights=w)) if w.sum() > 0 else 1.0
    k_top = 0 if cohesion >= UNIFORM_COHESION else min(K_MAX, n // MIN_POINTS_PER_CLUSTER)
    for k in range(K_MIN, k_top + 1):
        C, labels = kmeans(X, w, k, seed)
        if len(np.unique(labels)) < k:
            continue
        s = silhouette(X, labels)
        if s > best_score:
            best, best_score = (C, labels), s
    C, labels = best
    cw = np.array([w[labels == c].sum() for c in range(C.shape[0])])
    cw = cw / cw.sum() if cw.sum() > 0 else np.full(C.shape[0], 1 / C.shape[0])
    return C, labels, cw


# ── Ranking ──────────────────────────────────────────────────────────────────

def rank(cand_vecs, cands, centroids, cluster_weights, exclude=(),
         n=MAX_RESULTS, lam=MMR_LAMBDA, max_per_artist=MAX_PER_ARTIST,
         source_caps=None):
    """Choose up to `n` candidates.

    `cands` is a list of mappings with at least 'artist' and 'album', parallel
    to the rows of `cand_vecs`. A candidate's relevance is its cosine to the
    nearest taste centroid, which is also the cluster it is filed under.
    Selection is MMR (relevance against similarity to what is already chosen),
    with at most `max_per_artist` albums per artist and a quota per cluster in
    proportion to its weight, relaxed only when the other clusters run dry.
    `source_caps` ({source: most albums}) keeps one source from taking the
    whole list; like the cluster quota it gives way when the others run dry.
    Albums whose key is in `exclude` (heard, dismissed) and duplicates of the
    same album from two sources never get in.

    Returns [(candidate index, score, cluster)], best first.
    """
    if not len(cands) or centroids is None or not len(centroids):
        return []
    V = l2_normalize(cand_vecs)
    sims = V @ l2_normalize(centroids).T
    cluster = np.argmax(sims, axis=1)
    rel = sims[np.arange(len(cands)), cluster]
    keys = [album_key(c['artist'], c['album']) for c in cands]
    artists = [norm_text(c['artist']) for c in cands]
    exclude = set(exclude)

    quota = [max(1, int(round(n * float(cw)))) for cw in cluster_weights]
    taken_cluster = [0] * len(quota)
    taken_artist, taken_keys = {}, set()
    caps = dict(source_caps or {})
    sources = [c.get('source') for c in cands]
    taken_source = {}
    chosen, out = [], []
    alive = [i for i in range(len(cands))
             if keys[i] not in exclude and np.isfinite(rel[i])]
    max_sim = np.zeros(len(cands), dtype=np.float32)

    def pick(respect_quota, respect_caps=True):
        best, best_score = None, -1e9
        for i in alive:
            if keys[i] in taken_keys:
                continue
            if taken_artist.get(artists[i], 0) >= max_per_artist:
                continue
            if respect_quota and taken_cluster[cluster[i]] >= quota[cluster[i]]:
                continue
            if (respect_caps and sources[i] in caps
                    and taken_source.get(sources[i], 0) >= caps[sources[i]]):
                continue
            s = lam * rel[i] - (1.0 - lam) * max_sim[i]
            if s > best_score:
                best, best_score = i, s
        return best

    while len(out) < n:
        i = pick(True)
        if i is None:
            i = pick(False)
        if i is None:
            i = pick(False, False)
        if i is None:
            break
        out.append((i, float(rel[i]), int(cluster[i])))
        taken_source[sources[i]] = taken_source.get(sources[i], 0) + 1
        chosen.append(i)
        taken_keys.add(keys[i])
        taken_artist[artists[i]] = taken_artist.get(artists[i], 0) + 1
        taken_cluster[cluster[i]] += 1
        max_sim = np.maximum(max_sim, V @ V[i])
    return out


def source_caps(cands, n=MAX_RESULTS, library_share=None):
    """How many of the `n` places each source may take. With streaming
    candidates on the table the library keeps LIBRARY_SHARE of the list (the
    albums owned are, by construction, the closest to a taste read from the
    library, and would otherwise fill it all) and the services split the rest
    evenly. A single source has no cap."""
    share = LIBRARY_SHARE if library_share is None else library_share
    present = []
    for c in cands:
        if c.get('source') not in present:
            present.append(c.get('source'))
    streaming = [s for s in present if s != 'library']
    if not streaming or len(present) < 2:
        return {}
    caps, rest = {}, n
    if 'library' in present:
        caps['library'] = int(round(n * share))
        rest = n - caps['library']
    if len(streaming) > 1:
        for s in streaming:
            caps[s] = -(-rest // len(streaming))
    return caps


def history_state(db, min_plays=MIN_PLAYS, library=0):
    """What the screen should say before it shows a list. `library` is the
    number of albums in the local library: a big enough one stands in for a
    listening history that is still thin."""
    plays = play_count(db)
    last = db.execute(
        'SELECT started, finished, outcome, mode FROM runs '
        'ORDER BY id DESC LIMIT 1').fetchone()
    # A job that was killed never closes its row: past the unit's own time
    # limit a "running" row is a dead one.
    running = bool(last and last['outcome'] == 'running'
                   and time.time() - last['started'] < RUN_TIMEOUT)
    have = db.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0]
    # A list that exists is shown: a run may have started from the favourites
    # of a streaming account, which this cheap check does not go and read.
    if not have and plays < min_plays and (library or 0) < MIN_LIBRARY_ALBUMS:
        state = 'few_plays'
    elif not have:
        state = 'never_run' if not last or running else 'empty'
    else:
        state = 'ok'
    return {'state': state, 'plays': plays, 'needed': min_plays,
            'running': running,
            'last_run': dict(last) if last else None}


# ── Settings ─────────────────────────────────────────────────────────────────

SETTINGS_PATH = os.environ.get('HIFI_RECOMMEND_SETTINGS',
                               '/etc/hifi-player/recommend.json')
SOURCES = ('library', 'qobuz', 'tidal', 'spotty', 'deezer')
_DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
_TIME = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')

# The box is a hi-fi component, not a server: it is off at night. So the
# default is an hour when it is likely on, and the timer catches up at the
# next power-on when the hour was missed (Persistent=true in the unit).
DEFAULT_SETTINGS = {
    'enabled': True,
    'schedule': {'mode': 'daily', 'days': [], 'time': '18:00'},
    'sources': list(SOURCES),
    'lastfm_key': '',
}


def clean_settings(data):
    """Whatever came in, give back a complete and valid settings mapping."""
    data = data if isinstance(data, dict) else {}
    sch = data.get('schedule') if isinstance(data.get('schedule'), dict) else {}
    mode = sch.get('mode')
    if mode not in ('daily', 'days', 'manual'):
        mode = DEFAULT_SETTINGS['schedule']['mode']
    days = sorted({int(d) for d in (sch.get('days') or [])
                   if isinstance(d, int) and not isinstance(d, bool)
                   and 0 <= d <= 6})
    when = sch.get('time') if _TIME.match(str(sch.get('time') or '')) \
        else DEFAULT_SETTINGS['schedule']['time']
    if mode == 'days' and not days:
        mode = 'manual'            # "on chosen days" with no day chosen
    sources = data.get('sources')
    if not isinstance(sources, list):
        sources = list(SOURCES)
    return {
        'enabled': bool(data.get('enabled', True)),
        'schedule': {'mode': mode, 'days': days, 'time': when},
        'sources': [s for s in SOURCES if s in sources],
        'lastfm_key': re.sub(r'[^0-9a-fA-F]', '',
                             str(data.get('lastfm_key') or ''))[:64],
    }


def load_settings(path=None):
    import json
    try:
        with open(path or SETTINGS_PATH, encoding='utf-8') as f:
            return clean_settings(json.load(f))
    except (OSError, ValueError):
        return clean_settings({})


def save_settings(data, path=None):
    import json
    path = path or SETTINGS_PATH
    clean = clean_settings(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    # 0600: the file may hold the owner's own Last.fm key.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, path)
    return clean


def schedule_oncalendar(settings):
    """The systemd OnCalendar= expression for these settings, or None when
    nothing is to be scheduled (feature off, or "only when I ask")."""
    s = clean_settings(settings)
    sch = s['schedule']
    if not s['enabled'] or sch['mode'] == 'manual':
        return None
    when = '*-*-* %s:00' % sch['time']
    if sch['mode'] == 'days':
        return ','.join(_DAYS[d] for d in sch['days']) + ' ' + when
    return when


def schedule_dropin(settings):
    """The text of hifi-recommend.timer.d/schedule.conf for these settings,
    or None when the timer is to be switched off. The empty OnCalendar= first
    clears the unit's own default."""
    spec = schedule_oncalendar(settings)
    if not spec:
        return None
    return ('# Written by the API from Settings -> Recommended; do not edit.\n'
            '[Timer]\nOnCalendar=\nOnCalendar=%s\n' % spec)


def public_settings(settings, model_dir=None):
    """The settings as a screen may see them: the Last.fm key never leaves
    the device, only whether there is one and whose."""
    s = clean_settings(settings)
    own = bool(s.pop('lastfm_key'))
    s['lastfm'] = ('off' if not NONCOMMERCIAL_SOURCES else 'own' if own
                   else 'project' if lastfm_key({}, model_dir) else 'none')
    return s


def merge_settings(current, change):
    """Settings after a screen's change: what it did not send stays, and so
    does the Last.fm key unless it sent one ('' takes it away)."""
    current = clean_settings(current)
    change = change if isinstance(change, dict) else {}
    out = dict(current)
    for k in ('enabled', 'schedule', 'sources'):
        if k in change:
            out[k] = change[k]
    if isinstance(change.get('lastfm_key'), str):
        out['lastfm_key'] = change['lastfm_key']
    return clean_settings(out)


# ── Reading the player ───────────────────────────────────────────────────────

_SCHEME_SOURCE = {'file': 'library', 'spotify': 'spotty', 'cdplay': 'cd',
                  'cdda': 'cd'}


def source_of_url(url):
    """Where a track comes from, by its Lyrion URL: 'library', 'qobuz',
    'tidal', 'spotty', 'deezer', 'cd', or the bare scheme for anything else."""
    scheme = str(url or '').split(':', 1)[0].lower() if ':' in str(url or '') else ''
    return _SCHEME_SOURCE.get(scheme, scheme)


STATUS_TAGS = 'aldu'      # artist, album, duration, url


def play_from_status(st):
    """What PlayTracker and record_play need out of a Lyrion `status` reply
    (asked with tags STATUS_TAGS, one item at the current position).

    None when nothing is loaded, or when what plays is not an album track: a
    radio stream or a podcast has no artist/album pair and says nothing about
    which albums the listener likes."""
    if not isinstance(st, dict) or st.get('mode') not in ('play', 'pause'):
        return None
    loop = st.get('playlist_loop') or []
    if not loop or not isinstance(loop[0], dict):
        return None
    t = loop[0]
    artist = str(t.get('artist') or '').strip()
    album = str(t.get('album') or '').strip()
    if not artist or not album:
        return None
    url = str(t.get('url') or '')
    try:
        duration = float(t.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        'track': (url or str(t.get('id') or ''), str(st.get('playlist_cur_index', ''))),
        'playing': st.get('mode') == 'play',
        'duration': duration,
        'artist': artist, 'album': album,
        'title': str(t.get('title') or '').strip(),
        'source': source_of_url(url),
    }


# ── Artist profiles (enrichment) ─────────────────────────────────────────────
# One small record per artist — genres, tags, related names, country, decade,
# a one-line description — fetched once and kept for PROFILE_TTL_DAYS. Free
# sources always; non-commercial ones only behind NONCOMMERCIAL_SOURCES.
#   MusicBrainz search   id, country, start year (CC0)      + tags (NC) 🚨
#   Wikidata             genres, influences, description (CC0)
#   Last.fm              top tags, similar artists (NC) 🚨, needs an API key
# All calls go through hifi_metadata's throttled client (one request per
# second per service, shared User-Agent, short circuit when offline), and a
# run fetches at most MAX_NEW_PROFILES artists: the rest waits for the next.

PROFILE_TTL_DAYS = 90
PROFILE_RETRY_DAYS = 7        # an artist nobody knew: ask again after this
MAX_NEW_PROFILES = 120
MAX_TAGS = 8
MAX_RELATED = 8
LASTFM_BASE = 'https://ws.audioscrobbler.com/2.0/'
WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
MB_ARTIST_SEARCH = 'https://musicbrainz.org/ws/2/artist'
LASTFM_KEY_FILE = 'lastfm.key'

PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist_info (
    name_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    found INTEGER NOT NULL,
    fetched_at REAL NOT NULL
);
"""
SCHEMA += PROFILE_SCHEMA

# Tags that describe the tagger, not the music.
_JUNK_TAGS = {'seen live', 'favorites', 'favourites', 'favorite', 'albums i own',
              'spotify', 'all', 'beautiful', 'awesome', 'love', 'check out',
              'under 2000 listeners', 'vinyl', 'cd'}


def lastfm_key(settings, model_dir=None):
    """The owner's key if they set one, else the project key the build put
    next to the model, else '' (Last.fm is then skipped). Never logged."""
    if not NONCOMMERCIAL_SOURCES:
        return ''
    key = (settings or {}).get('lastfm_key') or ''
    if key:
        return key
    try:
        with open(os.path.join(model_dir or MODEL_DIR, LASTFM_KEY_FILE)) as f:
            return re.sub(r'[^0-9a-fA-F]', '', f.read())[:64]
    except OSError:
        return ''


def _clean_tags(tags, limit=MAX_TAGS):
    out = []
    for t in tags:
        t = ' '.join(str(t or '').lower().split())
        if t and t not in _JUNK_TAGS and t not in out and len(t) <= 40:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _qs(params):
    import urllib.parse
    return urllib.parse.urlencode(params)


def fetch_profile(name, http, key=''):
    """Ask the services about one artist. Returns (profile, found): `found`
    is False when nobody knew the name. Raises whatever the client raises on
    a dead network, so the caller can stop asking for this run."""
    prof = {'genres': [], 'tags': [], 'related': [], 'country': '',
            'decade': '', 'about': ''}
    mbid = ''
    query = 'artist:"%s"' % name.replace('\\', ' ').replace('"', ' ')
    mb = http.get_json(MB_ARTIST_SEARCH + '?' + _qs(
        {'query': query, 'limit': 3, 'fmt': 'json'}), group='mb')
    for a in (mb or {}).get('artists') or []:
        if norm_text(a.get('name')) != norm_text(name):
            continue
        mbid = a.get('id') or ''
        prof['country'] = a.get('country') or (a.get('area') or {}).get('name') or ''
        begin = str((a.get('life-span') or {}).get('begin') or '')[:4]
        if begin.isdigit() and a.get('type') != 'Person':
            prof['decade'] = begin[:3] + '0s'     # a band's start; a person's birth says little
        prof['about'] = a.get('disambiguation') or ''
        if NONCOMMERCIAL_SOURCES:
            tags = sorted(a.get('tags') or [], key=lambda t: -int(t.get('count') or 0))
            prof['tags'] = _clean_tags(t.get('name') for t in tags)
        break
    if mbid and re.match(r'^[0-9a-f-]{36}$', mbid):
        sparql = (
            'SELECT ?d (GROUP_CONCAT(DISTINCT ?g;separator="|") AS ?genres) '
            '(GROUP_CONCAT(DISTINCT ?i;separator="|") AS ?infl) WHERE { '
            '?a wdt:P434 "%s". '
            'OPTIONAL{?a schema:description ?d FILTER(LANG(?d)="en")} '
            'OPTIONAL{?a wdt:P136 ?gg. ?gg rdfs:label ?g FILTER(LANG(?g)="en")} '
            'OPTIONAL{?a wdt:P737 ?ii. ?ii rdfs:label ?i FILTER(LANG(?i)="en")} '
            '} GROUP BY ?d LIMIT 1' % mbid)
        try:
            wd = http.get_json(WIKIDATA_SPARQL + '?' + _qs(
                {'format': 'json', 'query': sparql}), group='wikidata')
            for b in ((wd or {}).get('results') or {}).get('bindings') or []:
                prof['genres'] = _clean_tags((b.get('genres') or {}).get('value', '').split('|'))
                prof['related'] = [x for x in (b.get('infl') or {}).get('value', '').split('|') if x][:MAX_RELATED]
                prof['about'] = (b.get('d') or {}).get('value') or prof['about']
        except Exception as e:
            if type(e).__name__ == 'OfflineError':
                raise
    if key:
        base = {'artist': name, 'api_key': key, 'format': 'json', 'autocorrect': 1}
        try:
            tt = http.get_json(LASTFM_BASE + '?' + _qs(
                dict(base, method='artist.gettoptags')), group='lastfm')
            tags = [t.get('name') for t in ((tt or {}).get('toptags') or {}).get('tag') or []
                    if int(t.get('count') or 0) >= 10]
            prof['tags'] = _clean_tags(prof['tags'] + tags)
            sim = http.get_json(LASTFM_BASE + '?' + _qs(
                dict(base, method='artist.getsimilar', limit=MAX_RELATED)), group='lastfm')
            names = [s.get('name') for s in ((sim or {}).get('similarartists') or {}).get('artist') or []
                     if s.get('name')]
            prof['related'] = (names + [r for r in prof['related'] if r not in names])[:MAX_RELATED]
        except Exception as e:
            if type(e).__name__ == 'OfflineError':
                raise
    found = bool(mbid or prof['tags'] or prof['related'])
    return prof, found


def load_profiles(db, names, now=None):
    """{name_key: profile} for the artists we already know (fresh or not),
    plus the set of keys that need (re)fetching."""
    import json
    now = time.time() if now is None else now
    keys = {norm_text(n) for n in names if norm_text(n)}
    have, stale = {}, set(keys)
    for row in db.execute('SELECT name_key, data, found, fetched_at FROM artist_info'):
        k = row['name_key']
        if k not in keys:
            continue
        ttl = PROFILE_TTL_DAYS if row['found'] else PROFILE_RETRY_DAYS
        if row['found']:
            have[k] = json.loads(row['data'])
        if now - row['fetched_at'] < ttl * 86400:
            stale.discard(k)
    return have, stale


def enrich(db, names, http, key='', limit=MAX_NEW_PROFILES, now=None, log=None):
    """Fetch what is missing for `names` (most important first), at most
    `limit` artists. Stops quietly when the network is down. Returns the
    profiles known at the end, by name_key."""
    import json
    now = time.time() if now is None else now
    have, stale = load_profiles(db, names, now)
    done = 0
    for name in names:
        k = norm_text(name)
        if k not in stale or http is None:
            continue
        if done >= limit:
            break
        stale.discard(k)
        try:
            prof, found = fetch_profile(name, http, key)
        except Exception as e:
            # Only the kind of error: a URL could carry the Last.fm key.
            if log:
                log.info('recommend: enrichment stopped (%s)', type(e).__name__)
            break
        done += 1
        with db:
            db.execute('INSERT OR REPLACE INTO artist_info '
                       '(name_key, name, data, found, fetched_at) VALUES (?,?,?,?,?)',
                       (k, name, json.dumps(prof), int(found), now))
        if found:
            have[k] = prof
    return have, done


def describe(artist, profile=None, genres=(), year=None):
    """The text that stands for an album: who, what kind of music, when,
    where, close to whom. This is what gets embedded (or TF-IDF'd)."""
    p = profile or {}
    kinds = _clean_tags(list(genres) + list(p.get('genres') or []) + list(p.get('tags') or []), 12)
    decade = p.get('decade') or ''
    try:
        if not decade and year and 1900 < int(year) < 2100:
            decade = str(int(year))[:3] + '0s'
    except (TypeError, ValueError):
        pass
    parts = [str(artist or '').strip(), ', '.join(kinds), decade, p.get('country') or '']
    if p.get('related'):
        parts.append('related: ' + ', '.join(p['related'][:MAX_RELATED]))
    if p.get('about'):
        parts.append(str(p['about'])[:200])
    return '; '.join(x for x in parts if x)


# ── Candidates ───────────────────────────────────────────────────────────────

MAX_SEARCHES_PER_SERVICE = 40
ALBUMS_PER_SEARCH = 6
MAX_LIBRARY_ALBUMS = 20000
# Where each plugin keeps its album results, for when the name or the icon of
# the category does not give it away (seen on Qobuz 3.x and TIDAL, 2026-11).
_ALBUM_CATEGORY = {'qobuz': 0, 'tidal': 3}
_ALBUM_WORDS = {'album', 'albums', 'releases', 'alben', 'albumes', 'álbumes'}


def library_albums(rpc):
    """Every album of the local library with its genres:
    [{album, artist, id, cover, year, genres}]."""
    out, at = {}, 0
    while at < MAX_LIBRARY_ALBUMS:
        r = rpc('', ['albums', at, 1000, 'tags:alyj']) or {}
        loop = r.get('albums_loop') or []
        for a in loop:
            if a.get('id') is None or not a.get('album') or not a.get('artist'):
                continue
            out[str(a['id'])] = {
                'album': a['album'], 'artist': a['artist'], 'id': str(a['id']),
                'cover': str(a.get('artwork_track_id') or ''),
                'year': a.get('year') or 0, 'genres': []}
        at += 1000
        if len(loop) < 1000:
            break
    for g in (rpc('', ['genres', 0, 500]) or {}).get('genres_loop') or []:
        name = g.get('genre')
        if not name or g.get('id') is None:
            continue
        r = rpc('', ['albums', 0, MAX_LIBRARY_ALBUMS, 'genre_id:%s' % g['id']]) or {}
        for a in r.get('albums_loop') or []:
            hit = out.get(str(a.get('id')))
            if hit is not None:
                hit['genres'].append(name)
    return list(out.values())


def _album_from_item(service, item):
    """A plugin's album row (menu format) → {album, artist, cover, play_id},
    or None when it carries nothing we could play later. The handle has to
    outlive the browsing session, so item ids are no use: we want the URL the
    plugin itself would save as a favourite."""
    text = str(item.get('text') or '')
    album, _, artist = text.partition('\n')
    artist = re.sub(r'\s*\(\d{4}\)\s*$', '', artist).strip()
    album = re.sub(r'\s*\[(E|AI)\]\s*$', '', album).strip()
    if album.startswith('* ') or not album or not artist:
        return None                       # '* ' marks "not streamable"
    preset = item.get('presetParams') or {}
    icon = str(item.get('icon') or preset.get('icon') or '')
    url = str(preset.get('favorites_url') or '')
    if not url and service == 'qobuz':
        # Qobuz rows carry no favourite URL, but the cover file is named
        # after the album id and qobuz://album:<id>.qbz is what the plugin's
        # own protocol handler expands into the album's tracks.
        import urllib.parse
        m = re.search(r'/([0-9a-z]+)_\d+\.jpg', urllib.parse.unquote(icon))
        if m:
            url = 'qobuz://album:%s.qbz' % m.group(1)
    if not url:
        return None
    return {'album': album, 'artist': artist, 'cover': icon, 'play_id': url}


class ServiceSearch:
    """Album search inside one streaming plugin, through Lyrion's own browse
    commands (no direct call to the service, no credentials of ours)."""

    def __init__(self, rpc, player, service):
        self.rpc, self.player, self.service = rpc, player, service
        self.node = None
        self.usable = None

    def _items(self, item_id=None, search=None, count=30, menu=False):
        cmd = [self.service, 'items', 0, count]
        if item_id is not None:
            cmd.append('item_id:%s' % item_id)
        if search is not None:
            cmd.append('search:%s' % search)
        if menu:
            cmd.append('menu:1')
        r = self.rpc(self.player, cmd) or {}
        return r.get('item_loop' if menu else 'loop_loop') or []

    def _find_node(self):
        """The id of the plugin's "new search" entry, at the root or one
        level down (Qobuz keeps it under its Search menu)."""
        root = self._items()
        for it in root:
            if it.get('type') == 'search':
                return str(it.get('id'))
        for it in root[:3]:
            if it.get('type') in ('link', None) and it.get('id') is not None:
                for sub in self._items(it['id'], count=5):
                    if sub.get('type') == 'search':
                        return str(sub.get('id'))
        return None

    def available(self):
        if self.usable is None:
            try:
                self.node = self._find_node()
            except Exception:
                self.node = None
            self.usable = self.node is not None    # not signed in: no search entry
        return self.usable

    def _qobuz_history(self):
        r = self.rpc('', ['pref', 'plugin.qobuz:qobuz_recent_search', '?']) or {}
        return list(r.get('_p2') or []) if isinstance(r.get('_p2'), list) else []

    def albums(self, artist):
        """Up to ALBUMS_PER_SEARCH albums by `artist` on this service."""
        if not self.available():
            return []
        before = None
        if self.service == 'qobuz':
            # Qobuz remembers every search in the owner's "recent searches".
            # Ours must not show up there: skip a term that would reorder or
            # push out one of theirs, and take ours back out afterwards.
            before = self._qobuz_history()
            if artist in before or len(before) >= 30:
                return []
        try:
            cats = self._items(self.node, search=artist)
            pick = None
            for c in cats:
                if norm_text(c.get('name')) in _ALBUM_WORDS or 'albums' in str(c.get('image') or ''):
                    pick = c
                    break
            if pick is None:
                i = _ALBUM_CATEGORY.get(self.service)
                pick = cats[i] if i is not None and i < len(cats) else None
            if pick is None:
                return []
            rows = self._items(pick.get('id'), count=40, menu=True)
        finally:
            if before is not None:
                after = self._qobuz_history()
                if len(after) == len(before) + 1 and after[-1] == artist:
                    self.rpc(self.player, ['qobuz', 'recentsearches',
                                           'delete:%d' % (len(after) - 1)])
        out = []
        for row in rows:
            a = _album_from_item(self.service, row)
            if a and norm_text(a['artist']) == norm_text(artist):
                out.append(a)
            if len(out) >= ALBUMS_PER_SEARCH:
                break
        return out


# Where each plugin keeps the owner's favourites, as the string tokens of its
# menu (read from the plugins' sources, 2026-11): (menu holding them or None
# for the plugin's first page, albums entry, artists entry). Lyrion is asked
# what the tokens read in its own language, so no translation is guessed here.
_FAVORITES_MENU = {
    'qobuz': ('PLUGIN_QOBUZ_USER_FAVORITES', 'PLUGIN_QOBUZ_RELEASES', 'ARTISTS'),
    'tidal': (None, 'ALBUMS', 'ARTISTS'),
    'spotty': (None, 'ALBUMS', 'ARTISTS'),
    'deezer': ('PLUGIN_DEEZER_COLLECTION', 'ALBUMS', 'ARTISTS'),
}
# Only Deezer's plugin shows what the account listened to elsewhere.
_HISTORY_MENU = {'deezer': 'PLUGIN_DEEZER_HISTORY'}
MAX_FAVORITES = 500        # rows read per list
_FALLBACK_STRINGS = {
    'ALBUMS': 'Albums', 'ARTISTS': 'Artists',
    'PLUGIN_QOBUZ_USER_FAVORITES': 'My Favorites', 'PLUGIN_QOBUZ_RELEASES': 'Releases',
    'PLUGIN_DEEZER_COLLECTION': 'My Collection', 'PLUGIN_DEEZER_HISTORY': 'Listening history',
}


def menu_strings(rpc):
    """{token: normalised text} of the menu entries above, in the language
    Lyrion is set to; English where the server does not know a token (the
    plugin is not installed)."""
    tokens = sorted(_FALLBACK_STRINGS)
    try:
        got = rpc('', ['getstring', ','.join(tokens)]) or {}
    except Exception:
        got = {}
    out = {}
    for t in tokens:
        v = got.get(t)
        out[t] = norm_text(v if isinstance(v, str) and v and v != t else _FALLBACK_STRINGS[t])
    return out


def _two_lines(item):
    """(title, artist) of an album or track row in menu format."""
    title, _, artist = str(item.get('text') or '').partition('\n')
    artist = re.sub(r'\s*\(\d{4}\)\s*$', '', artist).strip()
    title = re.sub(r'\s*\[(E|AI)\]\s*$', '', title).strip()
    return title, artist


def service_taste(rpc, player, service, strings):
    """What the owner's account on one streaming service says about their
    taste, read from the plugin's own menus (no call to the service from
    here): {'albums': [{artist, album}], 'artists': [name], 'history': [artist]}.
    All empty when the plugin is missing, signed out or laid out differently."""
    out = {'albums': [], 'artists': [], 'history': []}
    spec = _FAVORITES_MENU.get(service)
    if spec is None:
        return out
    browse = ServiceSearch(rpc, player, service)

    def entry(rows, token):
        want = strings.get(token)
        for it in rows:
            if it.get('id') is not None and want and norm_text(it.get('name')) == want \
                    and it.get('type') not in ('search', 'text', 'textarea'):
                return str(it['id'])
        return None

    root = browse._items()
    home, albums_t, artists_t = spec
    rows = root
    if home is not None:
        node = entry(root, home)
        rows = browse._items(node) if node is not None else []
    node = entry(rows, albums_t)
    if node is not None:
        for it in browse._items(node, count=MAX_FAVORITES, menu=True):
            album, artist = _two_lines(it)
            if album and artist:
                out['albums'].append({'album': album, 'artist': artist})
    node = entry(rows, artists_t)
    if node is not None:
        for it in browse._items(node, count=MAX_FAVORITES, menu=True):
            name = str(it.get('text') or '').strip()
            if name and '\n' not in name and it.get('type') not in ('text', 'textarea'):
                out['artists'].append(name)
    node = entry(root, _HISTORY_MENU.get(service))
    if node is not None:
        for it in browse._items(node, count=MAX_FAVORITES, menu=True):
            _, artist = _two_lines(it)
            if artist:
                out['history'].append(artist)
    return out


def account_taste(rpc, log=None):
    """service_taste of every streaming plugin, merged. A plugin that fails
    is skipped: favourites refine the profile, they must never stop a run."""
    out = {'albums': [], 'artists': [], 'history': []}
    try:
        player = pick_player(rpc)
    except Exception:
        player = ''
    if not player:
        return out
    strings = menu_strings(rpc)
    for service in SOURCES:
        if service == 'library':
            continue
        try:
            got = service_taste(rpc, player, service, strings)
        except Exception as e:
            if log:
                log.info('recommend: %s favourites not read (%s)', service, type(e).__name__)
            continue
        for k in out:
            out[k].extend(got[k])
    return out


def pick_player(rpc):
    """A connected player to browse plugins with (they want one); this box's
    own squeezelite if it is there."""
    players = (rpc('', ['players', 0, 99]) or {}).get('players_loop') or []
    players = [p for p in players if p.get('playerid')]
    for p in players:
        if str(p.get('ip') or '').startswith('127.0.0.1'):
            return p['playerid']
    return players[0]['playerid'] if players else ''


# ── The run ──────────────────────────────────────────────────────────────────

MAX_HISTORY_ARTISTS = 300
SEEDS_PER_RUN = MAX_SEARCHES_PER_SERVICE


def run(db, rpc, http=None, settings=None, embedder=None, now=None, log=None,
        model_dir=None):
    """One whole computation. `rpc(player, command)` talks to Lyrion; `http`
    is hifi_metadata's client or None for "stay offline". Returns a summary
    dict; the list itself goes to the recommendations table.

    The taste profile is the listening history, the albums of the local
    library (library_weights) and what the owner marked on the streaming
    services: favourite albums, artists followed, Deezer's listening history
    (account_taste). With none of them — a thin history, next to no library
    and next to no favourites — nothing is written and any earlier list is
    left alone."""
    now = time.time() if now is None else now
    settings = clean_settings(settings)
    summary = {'outcome': 'ok', 'mode': '', 'plays': play_count(db), 'items': 0,
               'fetched': 0, 'searches': 0}
    if not settings['enabled']:
        return dict(summary, outcome='disabled')
    library = library_albums(rpc)
    summary['library'] = len(library)
    # The accounts count whether or not their service is offered as a source,
    # like the library does.
    taste = account_taste(rpc, log=log)
    owned = {album_key(a['artist'], a['album']) for a in library}
    shelf = list(library)
    for a in taste['albums']:
        k = album_key(a['artist'], a['album'])
        if k not in owned:                # owned and favourite: one album
            owned.add(k)
            shelf.append(a)
    summary['favorites'] = len(shelf) - len(library) + len(set(taste['artists']))
    summary['service_plays'] = len(taste['history'])
    if (summary['plays'] + summary['service_plays'] < MIN_PLAYS
            and len(library) + summary['favorites'] < MIN_LIBRARY_ALBUMS):
        return dict(summary, outcome='few_plays')

    plays = [dict(r) for r in db.execute('SELECT ts, artist, album, album_key FROM plays')]
    for p in plays:
        p['artist_key'] = norm_text(p['artist'])
    artist_w = play_weights(plays, now, key='artist_key')
    names = {}
    for p in plays:
        names.setdefault(p['artist_key'], p['artist'])
    # The albums owned count as well, whether or not the library is also
    # offered as a source of recommendations.
    for a in library:
        names.setdefault(norm_text(a['artist']), a['artist'])
    for a in shelf[len(library):]:
        names.setdefault(norm_text(a['artist']), a['artist'])
    for name in taste['artists'] + taste['history']:
        names.setdefault(norm_text(name), name)
    for weights in (library_weights(shelf),
                    taste_weights(taste['artists'], taste['history'])):
        for k, w_more in weights.items():
            artist_w[k] = artist_w.get(k, 0.0) + w_more
    top = sorted((k for k in artist_w if k), key=lambda k: -artist_w[k])[:MAX_HISTORY_ARTISTS]
    exclude = heard_keys(db) | dismissed_keys(db)
    # An album already in the library, or kept as a favourite on a service,
    # is not offered again from a service (`owned`, above).

    # 1. What the library offers that has not been heard.
    #    The genres its files carry also describe the listened artists, which
    #    is all there is to go by when the network sources are out of reach.
    cands, own_genres = [], {}
    for a in library:
        seen_g = own_genres.setdefault(norm_text(a['artist']), [])
        seen_g.extend(g for g in a.get('genres') or () if g not in seen_g)
        if 'library' not in settings['sources']:
            continue
        if album_key(a['artist'], a['album']) in exclude:
            continue
        cands.append(dict(a, source='library', play_kind='album_id', play_id=a['id']))

    # 2. Learn about the artists: the listened ones first, then the library's.
    key = lastfm_key(settings, model_dir)
    order = [names[k] for k in top]
    seen = set(top)
    for c in cands:
        k = norm_text(c['artist'])
        if k and k not in seen:
            seen.add(k)
            order.append(c['artist'])
    profiles, summary['fetched'] = enrich(db, order, http, key, now=now, log=log)

    # 3. Streaming: more by the artists listened to, and albums by the names
    #    the sources put next to them.
    services = [s for s in settings['sources'] if s != 'library']
    if services:
        seeds, seed_keys = [], set()
        heard_artists = set(artist_w)
        for k in top:
            related = [r for r in (profiles.get(k) or {}).get('related') or []
                       if norm_text(r) not in heard_artists]
            for name in related[:2] + [names[k]]:
                nk = norm_text(name)
                if nk and nk not in seed_keys:
                    seed_keys.add(nk)
                    seeds.append(name)
            if len(seeds) >= SEEDS_PER_RUN:
                break
        seeds = seeds[:SEEDS_PER_RUN]
        new_names = [s for s in seeds if norm_text(s) not in profiles]
        more, n = enrich(db, new_names, http, key,
                         limit=max(0, MAX_NEW_PROFILES - summary['fetched']), now=now, log=log)
        profiles.update(more)
        summary['fetched'] += n
        player = pick_player(rpc)
        for service in services if player else []:
            search = ServiceSearch(rpc, player, service)
            for name in seeds:
                try:
                    found = search.albums(name)
                except Exception as e:
                    if log:
                        log.info('recommend: %s search failed (%s)', service, type(e).__name__)
                    break
                if not search.usable:
                    break
                summary['searches'] += 1
                for a in found:
                    k = album_key(a['artist'], a['album'])
                    if k not in exclude and k not in owned:
                        cands.append(dict(a, source=service, play_kind='url',
                                          genres=[], year=None))

    if not cands:
        return dict(summary, outcome='no_candidates')

    # 4. Vectors: listened artists and candidates through the same door.
    hist_texts = [describe(names[k], profiles.get(k), own_genres.get(k, ())) for k in top]
    cand_texts = [describe(c['artist'], profiles.get(norm_text(c['artist'])),
                           c.get('genres') or (), c.get('year')) for c in cands]
    X, summary['mode'] = vectors_for(db, hist_texts + cand_texts, embedder)
    H, V = X[:len(top)], X[len(top):]
    w = np.array([artist_w[k] for k in top], dtype=np.float64)
    # An artist the fallback knows no word of has an all-zero row: no opinion.
    keep = np.linalg.norm(H, axis=1) > 0
    if not keep.any():
        return dict(summary, outcome='no_profile')
    C, _, cw = taste_clusters(H[keep], w[keep])

    # 5. Rank and publish.
    picked = rank(V, cands, C, cw, exclude=exclude, source_caps=source_caps(cands))
    picked = [(i, s, c) for i, s, c in picked if s > 0]
    rows = [dict(cands[i], score=s, cluster=c) for i, s, c in picked]
    write_recommendations(db, rows, now)
    summary['items'] = len(rows)
    return summary


def start_run(db, now=None):
    cur = db.execute('INSERT INTO runs (started) VALUES (?)',
                     (time.time() if now is None else now,))
    db.commit()
    return cur.lastrowid


def finish_run(db, run_id, summary, now=None):
    import json
    db.execute('UPDATE runs SET finished = ?, outcome = ?, mode = ?, detail = ? WHERE id = ?',
               (time.time() if now is None else now, summary.get('outcome', 'error'),
                summary.get('mode', ''), json.dumps(summary), run_id))
    db.commit()
