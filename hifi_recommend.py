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
MAX_RESULTS = 40
MAX_PER_ARTIST = 2
MMR_LAMBDA = 0.7          # 1 = pure relevance, 0 = pure diversity
K_MIN, K_MAX = 2, 5
MIN_POINTS_PER_CLUSTER = 4
UNIFORM_COHESION = 0.95   # mean cosine to the one centre above which k = 1

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
         n=MAX_RESULTS, lam=MMR_LAMBDA, max_per_artist=MAX_PER_ARTIST):
    """Choose up to `n` candidates.

    `cands` is a list of mappings with at least 'artist' and 'album', parallel
    to the rows of `cand_vecs`. A candidate's relevance is its cosine to the
    nearest taste centroid, which is also the cluster it is filed under.
    Selection is MMR (relevance against similarity to what is already chosen),
    with at most `max_per_artist` albums per artist and a quota per cluster in
    proportion to its weight, relaxed only when the other clusters run dry.
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
    chosen, out = [], []
    alive = [i for i in range(len(cands))
             if keys[i] not in exclude and np.isfinite(rel[i])]
    max_sim = np.zeros(len(cands), dtype=np.float32)

    def pick(respect_quota):
        best, best_score = None, -1e9
        for i in alive:
            if keys[i] in taken_keys:
                continue
            if taken_artist.get(artists[i], 0) >= max_per_artist:
                continue
            if respect_quota and taken_cluster[cluster[i]] >= quota[cluster[i]]:
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
            break
        out.append((i, float(rel[i]), int(cluster[i])))
        chosen.append(i)
        taken_keys.add(keys[i])
        taken_artist[artists[i]] = taken_artist.get(artists[i], 0) + 1
        taken_cluster[cluster[i]] += 1
        max_sim = np.maximum(max_sim, V @ V[i])
    return out


def history_state(db, min_plays=MIN_PLAYS):
    """What the screen should say before it shows a list."""
    plays = play_count(db)
    last = db.execute(
        'SELECT started, finished, outcome, mode FROM runs '
        'ORDER BY id DESC LIMIT 1').fetchone()
    running = bool(last and last['outcome'] == 'running')
    have = db.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0]
    if plays < min_plays:
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
