"""Tests for hifi_metadata.py (album/artist information from MusicBrainz and
Wikipedia) and the CD-ripping lookup in sources_server.py that shares its
MusicBrainz client.

Hermetic: no request leaves the machine. urlopen is replaced by fakes, the
clock is a counter, Lyrion is a stub, and the MusicBrainz/Wikipedia answers
are real responses saved under tests/fixtures/metadata/ (trimmed).

Run with:  python3 tests/test_metadata.py
"""
import copy
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'metadata')

import hifi_metadata as hm  # noqa: E402


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return json.load(f)


DSOTM_OFFSETS = [183, 18018, 34143, 66003, 87533, 116218, 151488, 166913, 184200]
DSOTM_LEADOUT = 193293
DSOTM_DISC_ID = '8jTZJTgjGGtKjwdt8UyAgK3DnbY-'   # MusicBrainz, release c712a2bc


class FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, dt):
        self.sleeps.append(round(dt, 3))
        self.t += dt


def http_error(code):
    return urllib.error.HTTPError('https://musicbrainz.org/x', code, 'err', {}, io.BytesIO(b'{}'))


# ── text ─────────────────────────────────────────────────────────────
class TextTests(unittest.TestCase):

    def test_strip_edition(self):
        cases = {
            'American Idiot (20th Anniversary Deluxe Edition)': 'American Idiot',
            'Enjoy the Silence - EP': 'Enjoy the Silence',
            'Nevermind (Remastered)': 'Nevermind',
            "L'Era Del Cinghiale Bianco 40th Anniversary Remastered Edition": "L'Era Del Cinghiale Bianco",
            'Universi paralleli di Franco Battiato CD1': 'Universi paralleli di Franco Battiato',
            'Abbey Road,(Apple Records-AP-8815,Japan)': 'Abbey Road',
            'Legend [Bonus Tracks]': 'Legend',
            'Imagine (Disc 2)': 'Imagine',
            'Marathon (Remastered 2021)': 'Marathon',
            'Black Anima (Bonus Tracks Version)': 'Black Anima',
            "Il meglio dello zecchino d'oro ((Remastered 2017))": "Il meglio dello zecchino d'oro",
            # left alone
            'Dark Side Of The Moon': 'Dark Side Of The Moon',
            'Live': 'Live',
            'A Night At The Opera': 'A Night At The Opera',
            'EP': 'EP',
        }
        for raw, want in cases.items():
            self.assertEqual(hm.strip_edition(raw), want, raw)

    def test_normalise_and_fingerprint(self):
        self.assertEqual(hm.normalise('Cranberries, The'), hm.normalise('The Cranberries'))
        self.assertEqual(hm.normalise('Änglagård'), 'anglagard')
        self.assertEqual(hm.normalise('Simon & Garfunkel'), hm.normalise('Simon and Garfunkel'))
        self.assertEqual(hm.fingerprint('Dark Side Of The Moon', 'Pink Floyd', 10),
                         hm.fingerprint('dark side of the moon', 'PINK FLOYD', 10))
        self.assertNotEqual(hm.fingerprint('Dark Side Of The Moon', 'Pink Floyd', 10),
                            hm.fingerprint('Dark Side Of The Moon', 'Pink Floyd', 9))

    def test_various_artists(self):
        for name in ('Various Artists', 'VA', 'AA.VV.', 'Artisti vari'):
            self.assertTrue(hm.is_various(name), name)
        self.assertFalse(hm.is_various('Pink Floyd'))
        self.assertTrue(hm.is_various('Anybody', compilation=True))

    def test_lucene_quoting(self):
        self.assertEqual(hm.lucene_tokens('AC/DC: "Back" in Black (AND more)'), '(ac dc back in black and more)')
        self.assertEqual(hm.lucene_phrase('Say "hi"'), '"Say  hi"')
        url = hm.mb_url('release', query='release:"A & B" AND artist:"C+D"', inc='recordings+labels')
        self.assertIn('inc=recordings+labels', url)
        self.assertIn('query=release%3A%22A%20%26%20B%22%20AND%20artist%3A%22C%2BD%22', url)

    def test_clean_extract(self):
        text = 'First paragraph.\nSecond one.\n\n\nThird.'
        self.assertEqual(hm.clean_extract(text), 'First paragraph.\n\nSecond one.\n\nThird.')
        long_text = '\n'.join(['word ' * 300] * 5)
        out = hm.clean_extract(long_text, limit=4000)
        self.assertLessEqual(len(out), 4000)
        self.assertEqual(out.count('\n\n'), 1)          # whole paragraphs only
        self.assertLessEqual(len(hm.clean_extract('Sentence one. ' * 500, limit=1000)), 1001)

    def test_raw_tags_and_pairing(self):
        tags = hm.parse_raw_tags({
            'MUSICBRAINZ_ALBUMID': 'e6479787-3839-4082-b133-de2e5a1bd574',
            'ARTISTS': '[ Ludwig van Beethoven, Vladimir Ashkenazy ]',
            'MUSICBRAINZ_ARTISTID': '[ 1f9df192-a621-4f54-8850-2c5373b7eac9, 15a30428-87c4-455b-b7e8-71013237fea0 ]',
            'MusicBrainz Album Artist Id': '15a30428-87c4-455b-b7e8-71013237fea0',
            'TPE2': 'Vladimir Ashkenazy',
        })
        self.assertEqual(hm.tag_mbids(tags, 'MUSICBRAINZALBUMID'), ['e6479787-3839-4082-b133-de2e5a1bd574'])
        self.assertEqual(hm.pair_tag_artist(tags, hm.normalise('Vladimir Ashkenazy')),
                         '15a30428-87c4-455b-b7e8-71013237fea0')
        self.assertIsNone(hm.pair_tag_artist(tags, hm.normalise('Somebody Else')))
        # one id for two names: ambiguous, not taken
        ambiguous = hm.parse_raw_tags({'ARTIST': 'Queen & David Bowie',
                                       'MUSICBRAINZ_ARTISTID': '[ 0383dadf-2a4e-4d10-a46a-e9e041da8eb3, '
                                                               '5441c29d-3602-4898-b1a1-b77fa23b8e50 ]'})
        self.assertIsNone(hm.pair_tag_artist(ambiguous, hm.normalise('Queen')))

    def test_lms_host(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'squeezelite')
            with open(path, 'w') as f:
                f.write("ARGS='-o default -s 192.168.0.40:3483 -n Osmium'\n")
            self.assertEqual(hm.lms_host_from_squeezelite(path), '192.168.0.40')
            with open(path, 'w') as f:
                f.write("ARGS='-o default -n Osmium'\n")
            self.assertEqual(hm.lms_host_from_squeezelite(path), '127.0.0.1')
            self.assertEqual(hm.lms_host_from_squeezelite(os.path.join(tmp, 'missing')), '127.0.0.1')
        finally:
            shutil.rmtree(tmp)


# ── matching ─────────────────────────────────────────────────────────
# Lyrion's "Dark Side Of The Moon" (2003 remaster) against release be701edc:
# the edition moves 16 s of "Time" into "On the Run".
LIB_DSOTM = [68.44, 169.053, 209.693, 429.24, 284.626, 381.96, 469.4, 205.373, 227.626, 131.626]
MB_DSOTM = [67173, 169533, 225386, 413386, 284066, 383200, 469226, 206426, 226666, 132600]


class MatchingTests(unittest.TestCase):

    def test_alignments(self):
        self.assertEqual(hm.alignments(26, [13, 13]), [('all', None)])
        self.assertEqual(hm.alignments(13, [13, 13]), [('medium', 1), ('medium', 2)])
        self.assertEqual(hm.alignments(10, [10, 30], ['CD', 'DVD-Video']), [('audio', None), ('medium', 1)])
        self.assertEqual(hm.alignments(9, [10]), [])

    def test_duration_boundary_shift_is_accepted(self):
        ds = hm.duration_score(LIB_DSOTM, MB_DSOTM)
        self.assertGreater(ds['mean'], 3.0)          # two tracks 16 s off...
        self.assertLessEqual(ds['median'], 2.5)      # ...the rest agree
        self.assertTrue(hm.duration_accepted(ds))

    def test_different_album_same_count_is_rejected(self):
        shuffled = MB_DSOTM[3:] + MB_DSOTM[:3]
        self.assertFalse(hm.duration_accepted(hm.duration_score(LIB_DSOTM, shuffled)))
        self.assertIsNone(hm.duration_score(LIB_DSOTM, MB_DSOTM[:9]))
        self.assertIsNone(hm.duration_score(LIB_DSOTM, [None] * 10))

    def test_best_alignment_picks_the_disc_of_a_box_set(self):
        other = [200000] * 10
        media = [{'position': 1, 'format': 'CD', 'track-count': 10, 'tracks': [{'length': x} for x in other]},
                 {'position': 2, 'format': 'CD', 'track-count': 10, 'tracks': [{'length': x} for x in MB_DSOTM]}]
        lib = [{'duration': d} for d in LIB_DSOTM]
        mode, pos, ds = hm.best_alignment(lib, media)
        self.assertEqual((mode, pos), ('medium', 2))
        self.assertTrue(hm.duration_accepted(ds))

    def test_rank_candidates(self):
        results = [hm.release_summary(r) for r in fixture('search-dsotm-phrase.json')['releases']]
        ranked = hm.rank_candidates(results, 10, year=2003)
        self.assertTrue(ranked)
        self.assertTrue(all(10 in c['media_counts'] or sum(c['media_counts']) == 10 for c in ranked))
        # the bootleg DVD-Audio scored 100 by the search, still after official CDs
        ids = [c['mbid'] for c in ranked]
        bootleg = 'eb8cf4db-003f-49d4-8dbd-fbaa41da8d3d'
        if bootleg in ids:
            self.assertGreater(ids.index(bootleg), 0)
            self.assertEqual(ranked[0]['status'], 'Official')
        # whole release before a single disc of a bigger one
        whole = {'mbid': 'a', 'media_counts': [10], 'media_formats': ['CD'], 'score': 80, 'status': 'Official'}
        part = {'mbid': 'b', 'media_counts': [10, 10], 'media_formats': ['CD', 'CD'], 'score': 100,
                'status': 'Official'}
        self.assertEqual([c['mbid'] for c in hm.rank_candidates([part, whole], 10)], ['a', 'b'])

    def test_diverse_skips_identical_editions(self):
        c = lambda mbid, date: {'mbid': mbid, 'date': date, 'media_formats': ['CD'], 'media_counts': [10]}  # noqa: E731
        ranked = [c('1', '1993'), c('2', '1993-10-05'), c('3', '1993'), c('4', '2010'), c('5', '2003')]
        self.assertEqual([x['mbid'] for x in hm.diverse(ranked, 3)], ['1', '4', '5'])
        self.assertEqual([x['mbid'] for x in hm.diverse(ranked[:3], 2)], ['1', '2'])


# ── credits ──────────────────────────────────────────────────────────
def find(credits, group, role, attr='', credit=None):
    for c in credits:
        if c['group'] == group and c['role'] == role and c['attr'] == attr and (credit is None or c['credit'] == credit):
            return c
    return None


class CreditTests(unittest.TestCase):

    def setUp(self):
        self.model = hm.build_release_model(fixture('release-dsotm-be701edc-3tracks.json'))

    def test_model(self):
        m = self.model
        self.assertEqual(m['wikidata'], 'Q150901')
        self.assertEqual(m['first_release_date'], '1973-03-24')
        self.assertEqual(m['type'], 'album')
        self.assertEqual(m['disc_count'], 1)
        # nothing of the lookup's unrelated work relationships survives
        text = json.dumps(m)
        self.assertNotIn('based on', text)
        self.assertNotIn('"genres"', text)

    def test_album_view_merges_levels(self):
        credits, tracks, places = hm.album_view(self.model)
        # release level (design) and a credit on every track (composer, from
        # the works) cover the album: tracks null
        self.assertIsNone(find(credits, 'production', 'design')['tracks'])
        composer = find(credits, 'composition', 'composer')
        self.assertIsNone(composer['tracks'])
        self.assertEqual({p['name'] for p in composer['people']},
                         {'Nick Mason', 'David Gilmour', 'Richard Wright', 'Roger Waters'})
        # a credit on some tracks lists them as [disc, n]
        self.assertEqual(find(credits, 'composition', 'lyricist')['tracks'], [[1, 2]])
        guitar = find(credits, 'performer', 'instrument', 'electric guitar')
        self.assertEqual(guitar['tracks'], [[1, 2], [1, 3]])
        # one entry per instrument, lower case, with the attribute credit
        tape = find(credits, 'performer', 'instrument', 'tape', 'tape effects')
        self.assertEqual({p['name'] for p in tape['people']}, {'Nick Mason', 'Roger Waters'})
        self.assertIsNotNone(find(credits, 'performer', 'instrument', 'hammond organ'))
        self.assertIsNotNone(find(credits, 'engineering', 'engineer', 'assistant'))
        # people de-duplicated inside an entry
        for c in credits:
            names = [p['mbid'] for p in c['people']]
            self.assertEqual(len(names), len(set(names)))
        # group order
        order = [hm.GROUP_ORDER.index(c['group']) for c in credits]
        self.assertEqual(order, sorted(order))
        # per-track detail has no `tracks`
        self.assertEqual([(t['disc'], t['n']) for t in tracks], [(1, 1), (1, 2), (1, 3)])
        self.assertTrue(all('tracks' not in c for t in tracks for c in t['credits']))
        self.assertIn('Roger Waters', [p['name'] for c in tracks[1]['credits'] if c['role'] == 'lyricist'
                                        for p in c['people']])
        self.assertIn({'role': 'recorded_at', 'name': 'Abbey Road Studios', 'area': "St John's Wood"}, places)
        self.assertIn('mastered_at', [p['role'] for p in places])

    def test_medium_alignment_uses_library_disc(self):
        credits, tracks, _ = hm.album_view(self.model, 'medium', 1, disc_for_medium=2)
        self.assertEqual([(t['disc'], t['n']) for t in tracks], [(2, 1), (2, 2), (2, 3)])
        self.assertEqual(find(credits, 'composition', 'lyricist')['tracks'], [[2, 2]])

    def test_library_numbering_is_used_when_it_differs(self):
        # a 2-disc release kept in the library as one disc: [disc, n] follow
        # the library so the screens can pair credits with its tracks
        model = copy.deepcopy(self.model)
        second = copy.deepcopy(model['media'][0])
        second['position'] = 2
        model['media'].append(second)
        coords = [(1, n) for n in range(1, 7)]
        credits, tracks, _ = hm.album_view(model, 'all', None, coords=coords)
        self.assertEqual([(t['disc'], t['n']) for t in tracks], coords)
        self.assertEqual(find(credits, 'composition', 'lyricist')['tracks'], [[1, 2], [1, 5]])
        # a coordinate list that does not fit is ignored
        _, tracks, _ = hm.album_view(model, 'all', None, coords=coords[:4])
        self.assertEqual((tracks[3]['disc'], tracks[3]['n']), (2, 1))

    def test_parent_work_composer(self):
        rel = fixture('release-moonlight-e6479787.json')
        rel = copy.deepcopy(rel)
        work = rel['media'][0]['tracks'][0]['recording']['relations']
        work = next(r['work'] for r in work if r['target-type'] == 'work')
        composer = next(r for r in work['relations'] if r.get('type') == 'composer')
        work['relations'] = [r for r in work['relations'] if r.get('type') != 'composer']
        model = hm.build_release_model(rel)
        self.assertEqual(len(model['parent_works']), 1)
        parent = model['parent_works'][0]
        credits, tracks, _ = hm.album_view(model)
        self.assertEqual(find(credits, 'composition', 'composer')['tracks'], [[1, n] for n in range(2, 10)])
        model['parent_credits'][parent] = [composer]
        credits, tracks, _ = hm.album_view(model)
        self.assertIsNone(find(credits, 'composition', 'composer')['tracks'])
        self.assertIsNotNone(find(credits, 'performer', 'instrument', 'piano'))

    def test_classify_relation(self):
        self.assertEqual(hm.classify_relation({'type': 'producer', 'attributes': ['executive']}),
                         [('production', 'producer', 'executive', '')])
        self.assertEqual(hm.classify_relation({'type': 'instrument arranger', 'attributes': ['strings']}),
                         [('composition', 'arranger', 'strings', '')])
        self.assertEqual(hm.classify_relation({'type': 'instrument', 'attributes': ['guest', 'Hammond organ', 'piano'],
                                               'attribute-credits': {'piano': 'grand piano'}}),
                         [('performer', 'instrument', 'hammond organ', ''),
                          ('performer', 'instrument', 'piano', 'grand piano')])
        self.assertEqual(hm.classify_relation({'type': 'mix-DJ', 'attributes': []}), [('other', 'mix_dj', '', '')])
        self.assertEqual(hm.classify_relation({'type': 'recording', 'attributes': []}),
                         [('engineering', 'recording', '', '')])

    def test_track_credits_match_the_album_set(self):
        # per-track credits come out of the album's credit set: every entry of
        # track 2 is a line of the album that names track 2 (or the whole album)
        credits, tracks, _ = hm.album_view(self.model)
        for entry in tracks[1]['credits']:
            album_line = find(credits, entry['group'], entry['role'], entry['attr'], entry['credit'])
            self.assertIsNotNone(album_line)
            self.assertTrue(album_line['tracks'] is None or [1, 2] in album_line['tracks'])

    def test_artist_model(self):
        a = hm.build_artist_model(fixture('artist-pinkfloyd.json'))
        self.assertEqual((a['type'], a['begin'], a['end'], a['ended']), ('group', '1965', '2014', True))
        self.assertEqual(a['wikidata'], 'Q2306')
        self.assertEqual(a['urls']['official'], 'https://www.pinkfloyd.com/')
        syd = next(m for m in a['members'] if m['name'] == 'Syd Barrett')
        self.assertEqual(syd['attrs'], ['guitar', 'lead vocals', 'original'])
        self.assertTrue(syd['ended'])
        self.assertEqual(len([m for m in a['members'] if m['name'] == 'Richard Wright']), 2)
        self.assertEqual(a['member_of'], [])


# ── manual corrections ───────────────────────────────────────────────
WATERS = '0f50beab-d77d-4f0f-ac26-0b87d3e9b11b'
GILMOUR = '1dce970e-34bc-48b2-ab51-48d87544a4c2'


class OverrideTests(unittest.TestCase):

    def setUp(self):
        self.model = hm.build_release_model(fixture('release-dsotm-be701edc-3tracks.json'))
        self.people = {p['name']: p['mbid'] for c in hm.album_view(self.model)[0] for p in c['people']}

    def view(self, overrides):
        cset, coords, rows, _ = hm.credit_sets(self.model)
        changed = hm.apply_album_overrides(cset, hm.validate_album_overrides(overrides), coords)
        credits = hm._serialise_credits(cset, all_tracks=coords)
        tracks = [dict(r, credits=hm.track_credits(cset, (r['disc'], r['n']))) for r in rows]
        return changed, hm.keyed_credits(credits), [dict(t, credits=hm.keyed_credits(t['credits'])) for t in tracks]

    def test_keys(self):
        self.assertEqual(hm.credit_key('performer', 'instrument', 'piano', ''), 'performer|instrument|piano|')
        self.assertEqual(hm.credit_key(('other', 'a|b', '', 'x')), 'other|a/b||x')
        self.assertEqual(hm.person_key({'name': 'X', 'mbid': GILMOUR}), GILMOUR)
        self.assertEqual(hm.person_key({'name': 'Péter  JAMES', 'mbid': None}), 'name:peter james')
        changed, credits, tracks = self.view({})
        self.assertFalse(changed)
        tape = find(credits, 'performer', 'instrument', 'tape', 'tape effects')
        self.assertEqual(tape['key'], 'performer|instrument|tape|tape effects')
        self.assertEqual({p['key'] for p in tape['people']}, {self.people['Nick Mason'], WATERS})
        self.assertTrue(all('key' in e for t in tracks for e in t['credits']))

    def test_hide_and_remove_people(self):
        changed, credits, tracks = self.view({
            'hide': ['performer|instrument|piano|'],
            'remove_people': {'performer|instrument|tape|tape effects': [WATERS]}})
        self.assertTrue(changed)
        self.assertIsNone(find(credits, 'performer', 'instrument', 'piano'))
        self.assertFalse(any(e['key'] == 'performer|instrument|piano|' for t in tracks for e in t['credits']))
        tape = find(credits, 'performer', 'instrument', 'tape', 'tape effects')
        self.assertEqual([p['name'] for p in tape['people']], ['Nick Mason'])
        # a line left with nobody goes
        _, credits, _ = self.view({'remove_people': {'composition|lyricist||': [WATERS]}})
        self.assertIsNone(find(credits, 'composition', 'lyricist'))

    def test_rename_relink_and_role_change(self):
        james = self.people['Peter James']
        changed, credits, tracks = self.view({
            'people': {james: {'name': 'Pete James', 'artist_id': 12}},
            'entries': {'performer|instrument|electric guitar|': {'group': 'performer', 'role': 'instrument',
                                                                 'attr': 'Guitar', 'credit': ''}}})
        self.assertTrue(changed)
        stomps = find(credits, 'performer', 'instrument', 'foot stomps')
        self.assertEqual((stomps['people'][0]['name'], stomps['people'][0]['artist_id']), ('Pete James', 12))
        assistant = find(credits, 'engineering', 'engineer', 'assistant')
        self.assertEqual(assistant['people'][0]['name'], 'Pete James')      # everywhere on the album
        self.assertIsNone(find(credits, 'performer', 'instrument', 'electric guitar'))
        guitar = find(credits, 'performer', 'instrument', 'guitar')
        self.assertEqual((guitar['key'], guitar['tracks']), ('performer|instrument|guitar|', [[1, 2], [1, 3]]))
        self.assertIsNotNone(find(tracks[2]['credits'], 'performer', 'instrument', 'guitar'))

    def test_unlink_values(self):
        doc = hm.validate_album_overrides({'people': {GILMOUR: {'name': None, 'artist_id': 0, 'mbid': ''},
                                                      WATERS: {'artist_id': '0'}}})
        self.assertEqual(doc, {'people': {GILMOUR: {'artist_id': 0, 'mbid': ''}, WATERS: {'artist_id': 0}}})
        _, credits, _ = self.view({'people': {GILMOUR: {'artist_id': 0, 'mbid': ''}}})
        solo = find(credits, 'performer', 'instrument', 'pedal steel guitar')['people'][0]
        self.assertEqual((solo['name'], solo['mbid'], solo['artist_id'], solo['key']),
                         ('David Gilmour', None, None, 'name:david gilmour'))

    def test_add_lines(self):
        _, credits, tracks = self.view({'add': [
            {'group': 'performer', 'role': 'instrument', 'attr': 'saxophone', 'credit': '',
             'people': [{'name': 'Dick Parry', 'artist_id': None, 'mbid': None}], 'tracks': [[1, 2]]},
            {'group': 'production', 'role': 'liner_notes', 'attr': '', 'credit': '',
             'people': [{'name': 'Nobody', 'mbid': GILMOUR}], 'tracks': None},
            # same key as an existing line: merged into it
            {'group': 'composition', 'role': 'lyricist', 'attr': '', 'credit': '',
             'people': [{'name': 'Someone Else'}], 'tracks': [[1, 3]]}]})
        sax = find(credits, 'performer', 'instrument', 'saxophone')
        self.assertEqual((sax['tracks'], sax['people'][0]['key']), ([[1, 2]], 'name:dick parry'))
        self.assertIsNotNone(find(tracks[1]['credits'], 'performer', 'instrument', 'saxophone'))
        self.assertIsNone(find(tracks[0]['credits'], 'performer', 'instrument', 'saxophone'))
        notes = find(credits, 'production', 'liner_notes')
        self.assertIsNone(notes['tracks'])
        self.assertFalse(any(find(t['credits'], 'production', 'liner_notes') for t in tracks))
        lyricist = find(credits, 'composition', 'lyricist')
        self.assertEqual({p['name'] for p in lyricist['people']}, {'Roger Waters', 'Someone Else'})
        self.assertEqual(lyricist['tracks'], [[1, 2], [1, 3]])

    def test_per_track_corrections(self):
        _, credits, tracks = self.view({'tracks': {'1.2': {
            'hide': ['composition|lyricist||', 'performer|instrument|electric guitar|'],
            'add': [{'group': 'performer', 'role': 'vocal', 'attr': 'choir vocals', 'credit': '',
                     'people': [{'name': 'Choir'}]}]}}})
        self.assertIsNone(find(credits, 'composition', 'lyricist'))                  # it was only on 1.2
        self.assertEqual(find(credits, 'performer', 'instrument', 'electric guitar')['tracks'], [[1, 3]])
        self.assertIsNone(find(tracks[1]['credits'], 'performer', 'instrument', 'electric guitar'))
        self.assertIsNotNone(find(tracks[2]['credits'], 'performer', 'instrument', 'electric guitar'))
        self.assertEqual(find(credits, 'performer', 'vocal', 'choir vocals')['tracks'], [[1, 2]])
        roles = hm.cset_roles(hm.credit_sets(self.model)[0])
        self.assertIn(('composition', 'lyricist', ''), roles[WATERS][1])

    def test_validation(self):
        bad = [
            {'nonsense': True},
            {'hide': 'performer|instrument|piano|'},
            {'people': {'not-a-key': {'name': 'x'}}},
            {'people': {GILMOUR: {'mbid': 'nope'}}},
            {'entries': {'k': {'group': 'band', 'role': 'x'}}},
            {'add': [{'group': 'performer', 'role': 'vocal', 'people': []}]},
            {'add': [{'group': 'performer', 'role': 'vocal', 'people': [{'name': 'x'}], 'tracks': [[1]]}]},
            {'tracks': {'side A': {'hide': ['x']}}},
            {'about_hidden': 'yes'},
            {'add': [{'group': 'performer', 'role': 'vocal', 'people': [{'name': 'x' * 400}]}]},
        ]
        for doc in bad:
            with self.assertRaises(hm.OverrideError, msg=json.dumps(doc)[:80]):
                hm.validate_album_overrides(doc)
        ok = hm.validate_album_overrides({
            'hide': ['b', 'a', 'a'], 'people': {'name:Peter  James': {'name': ' Peter\x07James ', 'artist_id': '12',
                                                                        'mbid': None},
                                                GILMOUR.upper(): {'name': None, 'artist_id': None, 'mbid': None}},
            'add': [{'group': 'performer', 'role': 'Lead Vocal', 'attr': 'Lead', 'people': [{'name': 'x'}],
                     'tracks': [[1, 3], [1, 3]]}],
            'tracks': {'01.003': {}}, 'about_hidden': False, 'remove_people': {}})
        self.assertEqual(ok, {'hide': ['a', 'b'], 'people': {'name:peter james': {'name': 'PeterJames', 'artist_id': 12}},
                              'add': [{'group': 'performer', 'role': 'lead_vocal', 'attr': 'lead', 'credit': '',
                                       'people': [{'name': 'x', 'artist_id': None, 'mbid': None}],
                                       'tracks': [[1, 3]]}]})
        self.assertEqual(hm.validate_album_overrides({}), {})
        self.assertEqual(hm.validate_artist_overrides({'name': ' Floyd ', 'bio_hidden': True,
                                                       'hide_members': [GILMOUR, 'name:Syd']}),
                         {'name': 'Floyd', 'bio_hidden': True, 'hide_members': sorted([GILMOUR, 'name:syd'])})
        with self.assertRaises(hm.OverrideError):
            hm.validate_artist_overrides({'members': []})

    def test_artist_overrides(self):
        answer = {'status': 'ok', 'artist': {'name': 'Pink Floyd', 'urls': {'wikipedia': 'w', 'musicbrainz': 'm'},
                                             'members': [{'name': 'David Gilmour', 'mbid': GILMOUR},
                                                         {'name': 'Bob Klose', 'mbid': None}],
                                             'member_of': []},
                  'bio': {'text': 'wrong band'}}
        self.assertTrue(hm.apply_artist_overrides(answer, {'name': 'The Pink Floyd', 'bio_hidden': True,
                                                           'hide_members': ['name:bob klose']}))
        self.assertEqual(answer['artist']['name'], 'The Pink Floyd')
        self.assertEqual([m['name'] for m in answer['artist']['members']], ['David Gilmour'])
        self.assertIsNone(answer['bio'])
        self.assertEqual(answer['artist']['urls'], {'musicbrainz': 'm'})
        self.assertTrue(answer['edited'])
        untouched = {'status': 'ok', 'artist': {'name': 'X', 'members': [], 'member_of': []}, 'bio': None}
        self.assertFalse(hm.apply_artist_overrides(untouched, {'hide_members': [GILMOUR]}))
        self.assertNotIn('edited', untouched)


# ── HTTP client ──────────────────────────────────────────────────────
class HttpClientTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        version = os.path.join(self.tmp, 'UI_VERSION')
        with open(version, 'w') as f:
            f.write('v2.5.25-dev.1\n')
        self._files = hm.VERSION_FILES
        hm.VERSION_FILES = (version,)
        hm._version_cache.update(value=None, at=0.0)
        self.clock = FakeClock()
        self.requests = []
        self.answers = []

    def tearDown(self):
        hm.VERSION_FILES = self._files
        hm._version_cache.update(value=None, at=0.0)
        shutil.rmtree(self.tmp)

    def urlopen(self, req, timeout=None):
        self.requests.append((req, self.clock.t))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self):
        return hm.HttpClient(urlopen=self.urlopen, clock=self.clock.now, sleep=self.clock.sleep)

    def test_user_agent(self):
        self.assertEqual(hm.user_agent(), 'OsmiumSound/2.5.25-dev.1 ( https://osmiumsound.it ; info@osmiumsound.it )')
        self.answers = [FakeResponse(b'{"ok": 1}')]
        self.assertEqual(self.client().get_json(hm.mb_url('artist/x')), {'ok': 1})
        req = self.requests[0][0]
        self.assertEqual(req.get_header('User-agent'), hm.user_agent())
        self.assertNotIn('qd.je', req.get_header('User-agent'))

    def test_spacing(self):
        c = self.client()
        self.answers = [FakeResponse(b'{}') for _ in range(3)]
        for _ in range(3):
            c.get_json('https://musicbrainz.org/ws/2/a')
        times = [t for _, t in self.requests]
        self.assertGreaterEqual(times[1] - times[0], hm.MB_SPACING - 1e-9)
        self.assertGreaterEqual(times[2] - times[1], hm.MB_SPACING - 1e-9)
        # another host group has its own spacing
        self.answers = [FakeResponse(b'{}')]
        before = len(self.clock.sleeps)
        c.get_json('https://it.wikipedia.org/w/api.php', group='wiki')
        self.assertEqual(len(self.clock.sleeps), before)

    def test_max_wait(self):
        c = self.client()
        self.answers = [FakeResponse(b'{}')]
        c.get_json('https://musicbrainz.org/ws/2/a')
        c._push_back('mb', 30)
        with self.assertRaises(hm.HttpError):
            c.get_json('https://musicbrainz.org/ws/2/a', max_wait=5)

    def test_503_backoff_then_success(self):
        c = self.client()
        self.answers = [http_error(503), http_error(503), FakeResponse(b'{"x": 2}')]
        self.assertEqual(c.get_json('https://musicbrainz.org/ws/2/a'), {'x': 2})
        times = [t for _, t in self.requests]
        self.assertGreaterEqual(times[1] - times[0], 2.0)
        self.assertGreaterEqual(times[2] - times[1], 4.0)

    def test_back_off_can_be_abandoned(self):
        c = self.client()
        self.answers = [http_error(503)]
        calls = []

        class Stop(Exception):
            pass

        def check():
            calls.append(self.clock.t)
            if len(calls) > 2:
                raise Stop()
        with self.assertRaises(Stop):
            c.get_json('https://musicbrainz.org/ws/2/a', retries=5, check=check)
        self.assertEqual(len(self.requests), 1)             # no second request after the stop
        self.assertLess(max(self.clock.sleeps), 1.01)       # the wait is sliced

    def test_503_gives_up(self):
        c = self.client()
        self.answers = [http_error(503)] * 3
        with self.assertRaises(hm.HttpError) as ctx:
            c.get_json('https://musicbrainz.org/ws/2/a', retries=2)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(self.requests), 3)

    def test_offline_circuit(self):
        c = self.client()
        self.answers = [urllib.error.URLError(OSError('Network is unreachable'))]
        with self.assertRaises(hm.OfflineError):
            c.get_json('https://musicbrainz.org/ws/2/a')
        # no request at all while the circuit is open
        with self.assertRaises(hm.OfflineError):
            c.get_json('https://musicbrainz.org/ws/2/a')
        self.assertEqual(len(self.requests), 1)
        self.clock.t += hm.OFFLINE_HOLD + 1
        self.answers = [FakeResponse(b'{}')]
        c.get_json('https://musicbrainz.org/ws/2/a')
        self.assertEqual(len(self.requests), 2)

    def test_not_found_and_gzip(self):
        c = self.client()
        self.answers = [http_error(404), FakeResponse(gzip.compress(b'{"z": 3}'), {'Content-Encoding': 'gzip'}),
                        FakeResponse(b'<html>busy</html>')]
        with self.assertRaises(hm.NotFoundError):
            c.get_json('https://musicbrainz.org/ws/2/a')
        self.assertEqual(c.get_json('https://musicbrainz.org/ws/2/a'), {'z': 3})
        with self.assertRaises(hm.HttpError):
            c.get_json('https://musicbrainz.org/ws/2/a')
        self.assertFalse(c.offline())


# ── cache ────────────────────────────────────────────────────────────
class CacheTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = FakeClock(1_000_000.0)
        self.cache = hm.Cache(os.path.join(self.tmp, 'meta'), clock=self.clock.now)

    def tearDown(self):
        self.cache.close()
        shutil.rmtree(self.tmp)

    def test_put_get_and_ttl(self):
        svc = hm.MetadataService(cache_dir=self.cache.directory, etc_dir=self.tmp, lyrion=object(),
                                 start_worker=False)
        svc._cache = self.cache
        self.cache.put('release:a', {'x': 1})
        self.cache.put('match:n', {'mbid': None}, negative=True)
        self.assertEqual(svc._fresh('release:a'), ({'x': 1}, False, False))
        self.clock.t += hm.NEGATIVE_TTL + 1
        self.assertTrue(svc._fresh('match:n')[2])          # negative: asked again after 7 days
        # what was downloaded never goes stale, however old it is
        self.clock.t += 10 * 365 * 86400
        self.assertFalse(svc._fresh('release:a')[2])
        self.assertIsNone(svc._fresh('nothing'))

    def test_clear_keeps_pins(self):
        self.cache.put('match:fp', {'mbid': 'm'})
        self.cache.set_pin('fp', 5, 'none', 'T', 'A')
        self.cache.set_pin('fp2', 6, '14518b26-55fe-387b-94c6-a3843a1af487')
        self.cache.set_appearances('fp', 5, 'T', 'A', 'abc', {'p1': {('performer', 'instrument', 'piano')}})
        self.cache.clear()
        self.assertIsNone(self.cache.get('match:fp'))
        self.assertEqual(self.cache.appearances('p1'), [])
        self.assertEqual(self.cache.get_pin('fp')['mbid'], 'none')
        self.assertEqual(self.cache.get_pin('fp2')['album_id'], 6)
        self.cache.set_pin('fp2', 6, None)
        self.assertIsNone(self.cache.get_pin('fp2'))

    def test_stats_and_nothing_is_ever_thrown_away(self):
        self.cache.put('match:a', {'mbid': 'x'})
        self.cache.put('match:b', {'mbid': None}, negative=True)
        self.cache.put('artist:x', {'name': 'X'})
        stats = self.cache.stats()
        self.assertEqual((stats['albums'], stats['artists']), (1, 1))
        self.assertGreater(stats['bytes'], 0)
        # however much goes in, and however long ago: only clear() empties it
        for i in range(60):
            self.clock.t += 10
            self.cache.put(f'release:{i}', {'blob': 'x' * 20000})
        self.assertIsNotNone(self.cache.get('release:0'))
        self.assertIsNotNone(self.cache.get('release:59'))
        self.assertIsNotNone(self.cache.get('match:a'))


# ── where the downloaded information is kept ─────────────────────────
class CacheLocationTests(unittest.TestCase):
    """The owner picks the disk; the archive moves there and stays there
    until they clear it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.etc = os.path.join(self.tmp, 'etc')
        self.here = os.path.join(self.tmp, 'internal', 'metadata')
        self.disk = os.path.join(self.tmp, 'disk')       # a disk of the owner's
        self.share = os.path.join(self.tmp, 'share')     # a folder on a NAS
        for d in (self.etc, self.disk, self.share):
            os.makedirs(d)
        self.ram = os.path.join(self.tmp, 'ram')          # /mnt and /media are tmpfs here
        os.makedirs(self.ram)
        self.mounts = [(self.disk, 'ext4'), (self.share, 'cifs'), (self.ram, 'tmpfs'), (self.tmp, 'ext4')]
        for target, value in (('CACHE_MOUNT_ROOTS', (self.tmp,)),):
            patcher = mock.patch.object(hm, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # a tmp folder is one filesystem: pretend each mount is its own disk
        patcher = mock.patch.object(hm, '_device_of', self._device_of)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.svc = self.service()

    def tearDown(self):
        if self.svc._cache is not None:
            self.svc._cache.close()
        shutil.rmtree(self.tmp)

    def service(self):
        return hm.MetadataService(cache_dir=self.here, etc_dir=self.etc, lyrion=object(),
                                  start_worker=False, mounts=lambda: list(self.mounts))

    def _device_of(self, path):
        for number, root in enumerate((self.disk, self.share), start=2):
            if path == root or path.startswith(root + os.sep):
                return number
        return 1

    def place(self, path):
        return next(i for i in self.svc.cache_locations() if i['path'] == path)

    def test_lists_the_places_and_refuses_a_share(self):
        places = self.svc.cache_locations()
        self.assertEqual(places[0]['id'], 'default')
        self.assertTrue(places[0]['current'] and places[0]['usable'])
        self.assertGreater(places[0]['total'], 0)
        disk = self.place(self.disk)
        self.assertTrue(disk['usable'] and not disk['current'])
        self.assertEqual(disk['label'], 'disk')
        self.assertGreater(disk['free'], 0)
        share = self.place(self.share)
        self.assertEqual((share['usable'], share['reason'], share['kind']), (False, 'network', 'disk'))
        # neither RAM nor the folder those mounts merely sit in are offered
        paths = [i['path'] for i in places]
        self.assertNotIn(self.ram, paths)
        self.assertNotIn(self.tmp, paths)
        with self.assertRaises(hm.CacheMoveError) as e:
            self.svc.set_cache_location(self.share)
        self.assertEqual(e.exception.code, 'meta.cacheDirNetwork')
        with self.assertRaises(hm.CacheMoveError) as e:
            self.svc.set_cache_location('/somewhere/else')
        self.assertEqual(e.exception.code, 'meta.cacheDirUnknown')

    def test_the_archive_travels_with_the_setting(self):
        self.svc.cache.put('release:a', {'x': 1})
        self.assertTrue(os.path.exists(os.path.join(self.here, 'metadata.db')))
        out = self.svc.set_cache_location(self.disk)
        moved = os.path.join(self.disk, hm.CACHE_FOLDER)
        self.assertEqual(out['cache']['dir'], moved)
        self.assertEqual(out['cache']['location'], self.disk)
        self.assertFalse(out['cache']['detached'])
        self.assertTrue(os.path.exists(os.path.join(moved, 'metadata.db')))
        self.assertFalse(os.path.exists(os.path.join(self.here, 'metadata.db')))
        with open(os.path.join(self.etc, hm.CACHE_DIR_SETTING)) as f:
            self.assertEqual(f.read().strip(), self.disk)
        # what was downloaded is still there, and a fresh service finds it
        self.assertEqual(self.svc.cache.get('release:a')[0], {'x': 1})
        other = self.service()
        self.assertEqual(other.cache.get('release:a')[0], {'x': 1})
        other.cache.close()
        self.assertTrue(self.place(self.disk)['current'])
        self.svc.set_cache_location('')
        self.assertEqual(self.svc.cache.get('release:a')[0], {'x': 1})
        self.assertTrue(os.path.exists(os.path.join(self.here, 'metadata.db')))
        self.assertFalse(os.path.exists(os.path.join(moved, 'metadata.db')))

    def test_a_disk_taken_away_does_not_write_onto_its_mount_point(self):
        self.svc.cache.put('release:a', {'x': 1})
        self.svc.set_cache_location(self.disk)
        self.mounts = [(self.share, 'cifs')]              # unplugged
        self.svc._dir = {'value': None, 'at': 0.0}        # (checked every few seconds)
        self.assertEqual(self.svc.effective_cache_dir(), self.here)
        self.assertEqual(self.svc.cache.directory, self.here)   # reopened on its own
        self.assertEqual(self.svc.cache_location(), self.disk)
        stats = self.svc.settings()['cache']
        self.assertTrue(stats['detached'])
        self.assertEqual(stats['dir'], self.here)
        away = self.place(self.disk)
        self.assertEqual((away['current'], away['usable'], away['reason']),
                         (True, False, 'unavailable'))
        # the archive is untouched on the disk, waiting for it to come back
        self.assertTrue(os.path.exists(os.path.join(self.disk, hm.CACHE_FOLDER, 'metadata.db')))
        self.mounts = [(self.disk, 'ext4'), (self.share, 'cifs'), (self.ram, 'tmpfs'), (self.tmp, 'ext4')]
        self.svc._dir = {'value': None, 'at': 0.0}
        self.assertEqual(self.svc.cache.get('release:a')[0], {'x': 1})



# ── the service, end to end with fakes ───────────────────────────────
MOONLIGHT_MBID = 'e6479787-3839-4082-b133-de2e5a1bd574'
ASHKENAZY = '15a30428-87c4-455b-b7e8-71013237fea0'
SOMEBODY = '5441c29d-3602-4898-b1a1-b77fa23b8e50'


class FakeLyrion:
    def __init__(self):
        rel = fixture('release-moonlight-e6479787.json')
        self.tracks = [{'id': 100 + t['position'], 'title': t['title'], 'disc': 1, 'n': t['position'],
                        'duration': t['length'] / 1000.0} for t in rel['media'][0]['tracks']]
        self.raw = {}
        self.albums = {64: {'id': 64, 'title': 'Beethoven: Moonlight Sonata', 'artist': 'Vladimir Ashkenazy',
                            'artist_id': 12, 'year': 2012, 'compilation': False, 'artwork_track_id': 'abc'}}

    def base_url(self):
        return 'http://lyrion.test:9000'

    def album(self, album_id):
        a = self.albums.get(album_id)
        return dict(a) if a else None

    def album_tracks(self, album_id):
        return [dict(t) for t in self.tracks]

    def raw_tags(self, track_id):
        return hm.parse_raw_tags(self.raw)

    def artist_name_index(self):
        return {hm.normalise('Vladimir Ashkenazy'): 12}

    def artist_id_by_mbid(self, mbid):
        return None

    def all_albums(self):
        return [dict(a) for a in self.albums.values()]

    def artist_tracks(self, artist_id, limit=5):
        return [t['id'] for t in self.tracks[:limit]]

    def artist_albums(self, artist_id):
        return [{'id': a['id'], 'title': a['title'], 'artist': a['artist']} for a in self.albums.values()]

    def artist(self, artist_id):
        return {'id': 12, 'name': 'Vladimir Ashkenazy'} if artist_id == 12 else None

    def request(self, params, timeout=None):
        if params[0] == 'artists':
            q = next((p[7:] for p in params if str(p).startswith('search:')), '')
            loop = [{'id': 12, 'artist': 'Vladimir Ashkenazy'}] if q.lower() in 'vladimir ashkenazy' else []
            return {'count': len(loop), 'artists_loop': loop}
        raise AssertionError(f'unexpected Lyrion request {params}')


class FakeClient:
    """Serves fixtures by URL; `fail` makes every call raise instead."""

    def __init__(self):
        self.urls = []
        self.fail = None
        self.moonlight = fixture('release-moonlight-e6479787.json')
        self.artist_search = []

    def offline(self):
        return False

    def reset(self):
        pass

    def get_json(self, url, group='mb', timeout=20, retries=3, max_wait=None, check=None):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        if '/ws/2/release?' in url and 'query=' in url:
            return fixture('search-moonlight-tokens.json') if 'release%3A%28' in url else {'releases': []}
        if f'/ws/2/release/{MOONLIGHT_MBID}' in url:
            return self.moonlight
        if '/ws/2/release/' in url:
            raise hm.NotFoundError(url)
        if '/ws/2/release?' in url and 'release-group=' in url:
            return {'releases': [self.moonlight]}
        if '/ws/2/artist?' in url:
            return {'artists': self.artist_search if 'query=artist%3A' not in url else []}
        if '/ws/2/artist/' in url:
            mbid = url.split('/ws/2/artist/')[1].split('?')[0]
            return {'id': mbid, 'name': 'Vladimir Ashkenazy', 'sort-name': 'Ashkenazy, Vladimir', 'type': 'Person',
                    'life-span': {'begin': '1937-07-06'}, 'relations': []}
        raise AssertionError(f'unexpected request {url}')


class ServiceTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lyrion = FakeLyrion()
        self.client = FakeClient()
        self.svc = hm.MetadataService(cache_dir=os.path.join(self.tmp, 'cache'), etc_dir=self.tmp,
                                      lyrion=self.lyrion, client=self.client, start_worker=False)

    def tearDown(self):
        if self.svc._cache:
            self.svc._cache.close()
        shutil.rmtree(self.tmp)

    def drain(self):
        """The worker loop, inline."""
        while True:
            with self.svc._cv:
                if not self.svc._heap:
                    return
                priority, _seq, key = hm.heapq.heappop(self.svc._heap)
                job = self.svc._jobs.get(key)
                if job is None or job[1] != priority:
                    continue
                del self.svc._jobs[key]
                self.svc._running = (key, priority)
            self.svc.run_job(key, job[0], priority)

    def test_settings_default_on_and_persisted(self):
        s = self.svc.settings()
        self.assertTrue(s['online'] and s['prefetch'])
        self.assertEqual(set(s['cache']),
                         {'albums', 'artists', 'bytes', 'dir', 'location', 'detached', 'free', 'total'})
        self.assertEqual(set(s['prefetch_state']), {'running', 'done', 'total'})
        self.svc.set_settings(online=False)
        with open(os.path.join(self.tmp, 'meta-online')) as f:
            self.assertEqual(f.read().strip(), '0')
        self.assertEqual(self.svc.album(64)['status'], 'disabled')
        self.assertEqual(self.client.urls, [])

    def test_album_search_match_end_to_end(self):
        first = self.svc.album(64, 'it')
        self.assertEqual(first['status'], 'pending')
        self.assertEqual(self.client.urls, [])            # the handler never touches the network
        self.drain()
        out = self.svc.album(64, 'it')
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['match']['mbid'], MOONLIGHT_MBID)
        self.assertEqual(out['match']['how'], 'search')
        self.assertGreaterEqual(out['match']['score'], 90)
        self.assertEqual(out['release']['track_count'], 9)
        piano = find(out['credits'], 'performer', 'instrument', 'piano')
        self.assertEqual(piano['people'][0]['artist_id'], 12)
        self.assertIsNone(piano['tracks'])
        self.assertIsNone(out['about'])                   # no wikidata link on this release group
        self.assertEqual(out['attribution'][0]['license'], 'CC0')
        # searches are words/phrases only — never genres/tags includes
        self.assertTrue(all('genres' not in u and 'tags' not in u and 'ratings' not in u for u in self.client.urls))
        # a second request is served from the cache
        n = len(self.client.urls)
        self.svc.album(64, 'en')
        self.drain()
        self.assertEqual(len(self.client.urls), n)
        # the person index feeds appearances
        ashkenazy = '15a30428-87c4-455b-b7e8-71013237fea0'
        app = self.svc.appearances(ashkenazy)
        self.assertEqual(app['albums'][0]['album_id'], 64)
        self.assertIn({'group': 'performer', 'role': 'instrument', 'attr': 'piano'}, app['albums'][0]['roles'])

    def test_tag_match_skips_search(self):
        self.lyrion.raw = {'MUSICBRAINZ_ALBUMID': MOONLIGHT_MBID}
        self.svc.album(64)
        self.drain()
        out = self.svc.album(64)
        self.assertEqual((out['status'], out['match']['how']), ('ok', 'tag'))
        self.assertFalse(any('query=' in u for u in self.client.urls))

    def test_offline_is_not_cached(self):
        self.client.fail = hm.OfflineError('down')
        self.assertEqual(self.svc.album(64)['status'], 'pending')
        self.drain()
        self.assertEqual(self.svc.album(64)['status'], 'offline')
        self.assertEqual(self.svc.cache.stats()['albums'], 0)
        self.assertIsNone(self.svc.cache.get('match:' + hm.fingerprint('Beethoven: Moonlight Sonata',
                                                                       'Vladimir Ashkenazy', 9)))
        # back online: the next request after the hold queues the lookup again
        self.client.fail = None
        for key in list(self.svc._failures):
            f = self.svc._failures[key]
            self.svc._failures[key] = (f[0], f[1], f[2] - hm.FAILURE_HOLD - 1)
        self.assertEqual(self.svc.album(64)['status'], 'pending')
        self.drain()
        self.assertEqual(self.svc.album(64)['status'], 'ok')

    def test_busy_stays_pending(self):
        self.client.fail = hm.HttpError(503)
        self.svc.album(64)
        self.drain()
        self.assertEqual(self.svc.album(64)['status'], 'pending')

    def test_nomatch_is_cached_negative(self):
        self.lyrion.tracks = self.lyrion.tracks[:5]
        self.svc.album(64)
        self.drain()
        out = self.svc.album(64)
        self.assertEqual(out['status'], 'nomatch')
        n = len(self.client.urls)
        self.svc.album(64)
        self.drain()
        self.assertEqual(len(self.client.urls), n)

    def test_edits_move_with_a_renamed_album(self):
        e = hm.Edits(os.path.join(self.tmp, 'edits'))
        e.set_pin('old', 1, 'none', 'T', 'A')
        e.set_album_overrides('old', 1, 'T', 'A', {'about_hidden': True})
        e.set_album_overrides('taken', 2, 'U', 'B', {'hide': ['x']})
        self.assertTrue(e.move_album('old', 'new', 3, 'T2', 'A'))
        self.assertIsNone(e.album('old'))
        doc = e.album('new')
        self.assertEqual((doc['pin'], doc['overrides'], doc['album_id'], doc['title']), ('none', {'about_hidden': True}, 3, 'T2'))
        # an album that already has its own edits under the new key keeps them
        e.set_pin('other', 4, 'none')
        self.assertFalse(e.move_album('other', 'taken', 4, 'U', 'B'))
        self.assertEqual(e.album_overrides('taken'), {'hide': ['x']})
        self.assertIsNotNone(e.album('other'))
        # an artist name corrected in the tags: corrections copied, the old spelling keeps its own
        e.set_artist_overrides('pnk floid', 9, 'Pnk Floid', None, {'bio_hidden': True})
        self.assertTrue(e.copy_artist('pnk floid', 'pink floyd', 10, 'Pink Floyd'))
        self.assertEqual(e.artist_overrides('pink floyd'), {'bio_hidden': True})
        self.assertIsNotNone(e.artist('pnk floid'))

    def test_album_renamed_moves_its_edits(self):
        self.svc.album_pin(64, 'none')
        old = {'title': 'Beethoven: Moonlight Sonata', 'artist': 'Vladimir Ashkenazy', 'track_count': len(self.lyrion.tracks)}
        # the rescan after the tag edit: a new title, a new album id
        self.lyrion.albums[65] = dict(self.lyrion.albums.pop(64), id=65, title='Moonlight Sonata (fixed)')
        new_fp = self.svc.album_renamed(old, 65)
        self.assertEqual(new_fp, hm.fingerprint('Moonlight Sonata (fixed)', 'Vladimir Ashkenazy', len(self.lyrion.tracks)))
        self.assertEqual(self.svc.album(65)['status'], 'nomatch')       # the "none" choice followed it
        self.assertIsNone(self.svc.edits.album(hm.fingerprint(old['title'], old['artist'], old['track_count'])))
        self.assertIsNone(self.svc.album_renamed(old, 65))               # nothing left to move
        self.assertIsNone(self.svc.album_renamed(old, 999))              # unknown album

    def test_pin_none_and_back(self):
        out = self.svc.album_pin(64, 'none')
        self.assertEqual(out['status'], 'nomatch')
        self.svc.clear_cache()
        self.assertEqual(self.svc.album(64)['status'], 'nomatch')
        self.svc.album_pin(64, MOONLIGHT_MBID)
        self.drain()
        out = self.svc.album(64)
        self.assertEqual((out['status'], out['match']['how']), ('ok', 'manual'))
        self.assertFalse(any('query=' in u for u in self.client.urls))
        self.assertEqual(self.svc.album_pin(64, 'not-an-mbid')['status'], 'error')

    def test_candidates(self):
        self.assertEqual(self.svc.album_candidates(64)['status'], 'pending')
        self.drain()
        out = self.svc.album_candidates(64)
        self.drain()
        out = self.svc.album_candidates(64)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['current'], MOONLIGHT_MBID)
        self.assertEqual(out['candidates'][0]['mbid'], MOONLIGHT_MBID)
        self.assertLessEqual(len(out['candidates']), 25)
        self.assertEqual(set(out['candidates'][0]), {'mbid', 'title', 'artist', 'date', 'country', 'labels',
                                                     'format', 'track_count', 'score', 'release_group'})

    def test_prefetch_step(self):
        svc = hm.MetadataService(cache_dir=os.path.join(self.tmp, 'cache2'), etc_dir=self.tmp,
                                 lyrion=self.lyrion, client=self.client, start_worker=True)
        try:
            album = self.lyrion.all_albums()[0]
            self.assertTrue(svc._prefetch_one(album))           # looked up: pause after it
            self.assertTrue(svc._album_resolved(album))
            # the same album under a new id after a rescan: nothing to fetch
            self.lyrion.albums[99] = dict(self.lyrion.albums[64], id=99)
            n = len(self.client.urls)
            self.assertFalse(svc._prefetch_one(dict(album, id=99)))
            self.assertEqual(len(self.client.urls), n)
            # the album artist was resolved on the way: from the album's credits
            match = svc.cache.get('artistmatch:' + hm.normalise('Vladimir Ashkenazy'))[0]
            self.assertEqual((match['mbid'], match['how']), ('15a30428-87c4-455b-b7e8-71013237fea0', 'album'))
            # switching the prefetch off stops a background job at its next step
            svc.set_settings(prefetch=False)
            ctx = hm._Ctx(svc, hm.PRIO_PREFETCH)
            with self.assertRaises(hm._Disabled):
                ctx.check()
            hm._Ctx(svc, hm.PRIO_INTERACTIVE).check()           # screens still get answers
        finally:
            svc._cache.close()

    def test_album_corrections_end_to_end(self):
        self.svc.album(64)
        self.drain()
        edit = self.svc.album_edit(64)
        self.assertEqual((edit['status'], edit['overrides']), ('ok', {}))
        piano = find(edit['credits'], 'performer', 'instrument', 'piano')
        self.assertEqual(piano['key'], 'performer|instrument|piano|')
        self.assertEqual(piano['people'][0]['key'], ASHKENAZY)
        self.assertNotIn('edited', edit['effective'])
        self.assertTrue(all('key' in e for t in edit['tracks'] for e in t['credits']))
        saved = self.svc.album_edit_save(64, {
            'hide': ['performer|instrument|piano|'],
            'add': [{'group': 'performer', 'role': 'instrument', 'attr': 'Harpsichord', 'credit': '',
                     'people': [{'name': 'Somebody', 'artist_id': None, 'mbid': SOMEBODY}], 'tracks': [[1, 2]]}],
            'about_hidden': True})
        # the corrected answer, at the top level and under `effective`, with what was stored
        self.assertTrue(saved['edited'] and saved['effective']['edited'])
        self.assertEqual(saved['credits'], saved['effective']['credits'])
        self.assertEqual(saved['overrides']['hide'], ['performer|instrument|piano|'])
        out = self.svc.album(64)
        self.assertTrue(out['edited'])
        self.assertIsNone(find(out['credits'], 'performer', 'instrument', 'piano'))
        self.assertEqual(find(out['credits'], 'performer', 'instrument', 'harpsichord')['tracks'], [[1, 2]])
        # the raw answer is still what MusicBrainz gave
        self.assertIsNotNone(find(self.svc.album_edit(64)['credits'], 'performer', 'instrument', 'piano'))
        # appearances follow the corrections, at once
        self.assertEqual(self.svc.appearances(ASHKENAZY)['albums'], [])
        self.assertEqual(self.svc.appearances(SOMEBODY)['albums'][0]['roles'],
                         [{'group': 'performer', 'role': 'instrument', 'attr': 'harpsichord'}])
        # stored with the edits, not in the cache: clearing the cache keeps them
        fp = hm.fingerprint('Beethoven: Moonlight Sonata', 'Vladimir Ashkenazy', 9)
        path = os.path.join(self.tmp, 'metadata-edits', 'albums', fp + '.json')
        self.assertTrue(os.path.isfile(path))
        self.svc.clear_cache()
        self.svc.album(64)
        self.drain()
        self.assertTrue(self.svc.album(64)['edited'])
        self.assertEqual(self.svc.appearances(ASHKENAZY)['albums'], [])        # rebuilt with the corrections
        # a file put back from a backup is picked up without a restart
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        doc['overrides'] = {'about_hidden': True}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        os.utime(os.path.dirname(path), ns=(1, 1))
        self.assertNotIn('edited', self.svc.album(64))          # nothing to hide: no about on this release
        # {} = back to MusicBrainz; the file goes
        reset = self.svc.album_edit_save(64, {})
        self.assertNotIn('edited', reset)
        self.assertFalse(os.path.exists(path))
        with self.assertRaises(hm.OverrideError):
            self.svc.album_edit_save(64, {'hide': 'not a list'})

    def test_unlinking_people(self):
        self.svc.album(64)
        self.drain()
        out = self.svc.album_edit_save(64, {'people': {ASHKENAZY: {'artist_id': 0, 'mbid': ''}}})
        person = find(out['credits'], 'performer', 'instrument', 'piano')['people'][0]
        self.assertEqual((person['artist_id'], person['mbid'], person['key']),
                         (None, None, 'name:vladimir ashkenazy'))
        self.assertTrue(out['edited'])
        self.assertEqual(self.svc.appearances(ASHKENAZY)['albums'], [])
        # null keeps; a number relinks by hand
        out = self.svc.album_edit_save(64, {'people': {ASHKENAZY: {'name': None, 'artist_id': 99, 'mbid': None}}})
        person = find(out['credits'], 'performer', 'instrument', 'piano')['people'][0]
        self.assertEqual((person['artist_id'], person['mbid']), (99, ASHKENAZY))
        stored = self.svc.edits.album_overrides(hm.fingerprint('Beethoven: Moonlight Sonata', 'Vladimir Ashkenazy', 9))
        self.assertEqual(stored, {'people': {ASHKENAZY: {'artist_id': 99}}})

    def test_nomatch_album_keeps_added_credits(self):
        self.svc.album_pin(64, 'none')
        out = self.svc.album_edit_save(64, {'add': [{'group': 'composition', 'role': 'composer', 'attr': '',
                                                     'credit': '', 'tracks': None,
                                                     'people': [{'name': 'Ludwig', 'mbid': SOMEBODY}]}]})
        self.assertEqual((out['status'], out['edited']), ('nomatch', True))
        self.assertEqual(out['credits'][0]['people'][0]['name'], 'Ludwig')
        self.assertEqual(self.svc.appearances(SOMEBODY)['albums'][0]['album_id'], 64)

    def test_pins_move_out_of_the_cache(self):
        cache_dir = os.path.join(self.tmp, 'legacy-cache')
        old = hm.Cache(cache_dir)
        fp = hm.fingerprint('Beethoven: Moonlight Sonata', 'Vladimir Ashkenazy', 9)
        old.set_pin(fp, 64, MOONLIGHT_MBID, 'Beethoven: Moonlight Sonata', 'Vladimir Ashkenazy')
        old.set_pin('other', 5, 'none', 'T', 'A')
        old.close()
        svc = hm.MetadataService(cache_dir=cache_dir, etc_dir=self.tmp, lyrion=self.lyrion, client=self.client,
                                 start_worker=False)
        try:
            self.assertEqual(svc.album(64)['status'], 'pending')
            self.assertEqual(svc.edits.get_pin(fp), {'mbid': MOONLIGHT_MBID, 'album_id': 64})
            self.assertEqual(svc.edits.get_pin('other')['mbid'], 'none')
            self.assertEqual(svc.cache.all_pins(), [])
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'metadata-edits', 'albums', fp + '.json')))
            self.assertEqual(svc.edits_dir, os.path.join(self.tmp, 'metadata-edits'))
        finally:
            svc._cache.close()

    def test_artist_pin_corrections_and_candidates(self):
        self.client.artist_search = [{'id': ASHKENAZY, 'name': 'Vladimir Ashkenazy', 'type': 'Person', 'score': 100,
                                      'area': {'name': 'Iceland'}, 'life-span': {'begin': '1937-07-06'},
                                      'disambiguation': 'pianist'},
                                     {'id': SOMEBODY, 'name': 'Vladimir Ashkenazy', 'score': 60}]
        self.assertEqual(self.svc.artist_candidates(12)['status'], 'pending')
        self.drain()
        cands = self.svc.artist_candidates(12)
        self.assertEqual(cands['status'], 'ok')
        self.assertEqual(cands['candidates'][0], {'mbid': ASHKENAZY, 'name': 'Vladimir Ashkenazy',
                                                  'disambiguation': 'pianist', 'type': 'person', 'area': 'Iceland',
                                                  'begin': '1937-07-06', 'end': '', 'score': 100})
        self.assertIsNone(cands['pinned'])
        self.svc.artist_pin(12, ASHKENAZY)
        self.drain()
        out = self.svc.artist(12)
        self.assertEqual((out['status'], out['artist']['mbid']), ('ok', ASHKENAZY))
        edit = self.svc.artist_edit(12)
        self.assertEqual((edit['match'], edit['library_name'], edit['overrides']),
                         ({'mbid': ASHKENAZY, 'how': 'manual'}, 'Vladimir Ashkenazy', {}))
        self.assertEqual(self.svc.artist_candidates(12)['pinned'], ASHKENAZY)
        saved = self.svc.artist_edit_save(12, {'name': 'V. Ashkenazy', 'bio_hidden': True, 'hide_members': []})
        self.assertEqual((saved['artist']['name'], saved['edited'], saved['overrides']),
                         ('V. Ashkenazy', True, {'name': 'V. Ashkenazy', 'bio_hidden': True}))
        self.assertEqual(self.svc.artist(12)['artist']['name'], 'V. Ashkenazy')
        self.assertEqual(self.svc.person(ASHKENAZY)['artist']['name'], 'V. Ashkenazy')   # same artist elsewhere
        self.assertEqual(self.svc.artist_edit(12)['artist']['name'], 'Vladimir Ashkenazy')
        self.svc.clear_cache()
        self.assertEqual(self.svc.edits.artist_pin(hm.normalise('Vladimir Ashkenazy')), ASHKENAZY)
        self.assertEqual(self.svc.artist_pin(12, 'none')['status'], 'nomatch')
        self.assertEqual(self.svc.artist_pin(12, 'bad')['status'], 'error')

    def test_search_people(self):
        self.client.artist_search = [{'id': SOMEBODY, 'name': 'Vladimir Ashkenazy', 'type': 'Person',
                                      'disambiguation': 'pianist', 'score': 90}]
        first = self.svc.search_people('ashk')
        self.assertEqual((first['status'], first['library'], first['musicbrainz']),
                         ('pending', [{'artist_id': 12, 'name': 'Vladimir Ashkenazy'}], []))
        self.svc.search_people('ashke')                     # typing on: only the latest search is asked
        self.drain()
        self.assertEqual(sum(1 for u in self.client.urls if '/ws/2/artist?' in u), 1)
        out = self.svc.search_people('ashke')
        self.assertEqual(out['musicbrainz'], [{'mbid': SOMEBODY, 'name': 'Vladimir Ashkenazy',
                                               'disambiguation': 'pianist', 'type': 'person'}])
        self.assertEqual(out['status'], 'ok')
        self.svc.set_settings(online=False)
        self.assertEqual(self.svc.search_people('ashke')['status'], 'disabled')

    def test_about_language_fallback(self):
        model = hm.build_release_model(fixture('release-dsotm-be701edc-3tracks.json'))
        self.svc.cache.put('wikidata:Q150901', {'en': 'The Dark Side of the Moon'})
        self.svc.cache.put('wiki:en:The Dark Side of the Moon', {'title': 'The Dark Side of the Moon', 'text': 'EN'})
        about, status = self.svc._about(model['wikidata'], 'it', hm.PRIO_INTERACTIVE)
        self.assertEqual(status, 'ok')
        self.assertEqual((about['lang'], about['text'], about['license']), ('en', 'EN', 'CC BY-SA 4.0'))
        self.assertEqual(about['url'], 'https://en.wikipedia.org/wiki/The_Dark_Side_of_the_Moon')

    def test_job_about_reads_wikidata_and_extract(self):
        calls = []

        def fake_wiki(ctx, url):
            calls.append(url)
            return fixture('wikidata-Q150901.json') if 'wikidata.org' in url else fixture('wikipedia-it-dsotm.json')
        self.svc._wiki = fake_wiki
        self.svc._job_about(hm._Ctx(self.svc, hm.PRIO_INTERACTIVE), 'Q150901', 'it')
        about, status = self.svc._about('Q150901', 'it', hm.PRIO_INTERACTIVE)
        self.assertEqual((status, about['lang']), ('ok', 'it'))
        self.assertIn('\n\n', about['text'])
        self.assertTrue(about['text'].startswith('The Dark Side of the Moon è'))
        self.assertIn('sitefilter=itwiki%7Cenwiki', calls[0])
        self.assertIn('prop=extracts', calls[1])
        self.assertIn('exintro=1', calls[1])


# ── CD ripping ───────────────────────────────────────────────────────
class CdTests(unittest.TestCase):

    def test_disc_ids(self):
        self.assertEqual(hm.mb_disc_id(DSOTM_OFFSETS, DSOTM_LEADOUT), DSOTM_DISC_ID)
        disc = fixture('release-dsotm-discids-c712a2bc.json')['media'][0]['discs'][0]
        self.assertEqual(hm.mb_disc_id(disc['offsets'], disc['sectors']), disc['id'])
        self.assertEqual(hm.cd_toc_string([150, 300], 900), '1+2+900+150+300')
        self.assertRegex(hm.freedb_disc_id(DSOTM_OFFSETS, DSOTM_LEADOUT), r'^[0-9a-f]{6}09$')

    def test_choices_prefer_exact_disc_over_box_set(self):
        data = fixture('toc-dsotm-fuzzy.json')
        # the box set "Shine On" sorts first in MusicBrainz's answer
        self.assertEqual(data['releases'][0]['title'], 'Shine On')
        choices = hm.cd_choices(data, DSOTM_DISC_ID, hm.cd_toc_lengths_ms(DSOTM_OFFSETS, DSOTM_LEADOUT))
        self.assertTrue(choices[0]['exact'])
        self.assertNotEqual(choices[0]['release']['title'], 'Shine On')
        box = [c for c in choices if c['release']['title'] == 'Shine On']
        self.assertEqual(len(box), 1)
        self.assertEqual(box[0]['medium']['position'], 3)     # the right disc of the box, not the first
        entry = hm.cd_release_entry(box[0])
        self.assertEqual((entry['disc_position'], entry['disc_count'], entry['track_count']), (3, 9, 9))
        self.assertEqual(set(entry), {'mbid', 'title', 'artist', 'date', 'country', 'label', 'catno',
                                      'track_count', 'disc_position', 'disc_count'})

    def test_tags(self):
        album, tracks, artists = hm.cd_tags(fixture('release-moonlight-e6479787.json'), 1)
        a = {}
        for k, v in album:
            a.setdefault(k, []).append(v)
        self.assertEqual(a['MUSICBRAINZ_ALBUMID'], [MOONLIGHT_MBID])
        self.assertEqual(len(a['MUSICBRAINZ_ALBUMARTISTID']), 2)          # repeated, one per artist
        self.assertEqual((a['DISCNUMBER'], a['DISCTOTAL'], a['TOTALDISCS']), (['1'], ['1'], ['1']))
        for key in ('MUSICBRAINZ_RELEASEGROUPID', 'ALBUMARTIST', 'RELEASETYPE', 'ORIGINALDATE', 'LABEL',
                    'CATALOGNUMBER'):
            self.assertIn(key, a)
        t = dict(tracks[0])
        rec = fixture('release-moonlight-e6479787.json')['media'][0]['tracks'][0]
        self.assertEqual(t['MUSICBRAINZ_TRACKID'], rec['recording']['id'])     # the recording, as Picard
        self.assertEqual(t['MUSICBRAINZ_RELEASETRACKID'], rec['id'])
        self.assertEqual(t['COMPOSER'], 'Ludwig van Beethoven')
        self.assertIn('ISRC', t)
        self.assertEqual(len(tracks), 9)
        self.assertEqual(len(artists), 9)


class SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._run = lambda: target(*args, **(kwargs or {}))

    def start(self):
        self._run()


class SourcesServerCdTests(unittest.TestCase):
    """The TOC read, the lookup cache and the edition choice in
    sources_server.py, with cd-discid and MusicBrainz faked."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['HIFI_META_CACHE_DIR'] = os.path.join(cls.tmp, 'cache')
        os.environ['HIFI_META_ETC_DIR'] = cls.tmp
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            import sources_server
        cls.ss = sources_server

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.ss._cd_info_cache.clear()
        self.ss._cd_leadouts.clear()
        total_sec = DSOTM_LEADOUT // 75
        plain = f"700a0f09 9 {' '.join(map(str, DSOTM_OFFSETS))} {total_sec}\n"
        mbfmt = f"9 {' '.join(map(str, DSOTM_OFFSETS))} {DSOTM_LEADOUT}\n"

        def fake_run(cmd, timeout=30):
            out = mbfmt if '--musicbrainz' in cmd else plain
            return mock.Mock(returncode=0, stdout=out, stderr='')
        self.run_patch = mock.patch.object(self.ss, '_run', side_effect=fake_run)
        self.run_patch.start()
        self.lookups = []
        self.answer = fixture('toc-dsotm-fuzzy.json')

        def fake_mb_get(path, **kw):
            self.lookups.append((path, kw))
            if isinstance(self.answer, Exception):
                raise self.answer
            if path.startswith('release/'):
                raise hm.HttpError(503)
            return self.answer
        self.mb_patch = mock.patch.object(self.ss.hmeta, 'mb_get', side_effect=fake_mb_get)
        self.mb_patch.start()
        # the background full lookup runs inline, so no thread can outlive
        # the fake MusicBrainz and reach the real one
        self.thread_patch = mock.patch.object(self.ss.threading, 'Thread', SyncThread)
        self.thread_patch.start()

    def tearDown(self):
        self.thread_patch.stop()
        self.mb_patch.stop()
        self.run_patch.stop()

    def test_toc_uses_exact_leadout(self):
        toc = self.ss._cd_toc()
        self.assertEqual(toc['leadout'], DSOTM_LEADOUT)
        self.assertEqual(len(toc['lengths']), 9)

    def test_toc_falls_back_when_the_musicbrainz_read_disagrees(self):
        self.run_patch.stop()
        plain = f"700a0f09 9 {' '.join(map(str, DSOTM_OFFSETS))} {DSOTM_LEADOUT // 75}\n"

        def fake_run(cmd, timeout=30):
            out = '9 1 2 3\n' if '--musicbrainz' in cmd else plain
            return mock.Mock(returncode=0, stdout=out, stderr='')
        with mock.patch.object(self.ss, '_run', side_effect=fake_run):
            toc = self.ss._cd_toc()
        self.run_patch.start()
        self.assertEqual(toc['leadout'], (DSOTM_LEADOUT // 75) * 75)

    def test_lookup_choice_override_and_cache(self):
        toc = self.ss._cd_toc()
        meta = self.ss._cd_metadata(toc)
        path, kw = self.lookups[0]
        self.assertEqual(path, f'discid/{DSOTM_DISC_ID}')
        self.assertNotIn('recording-level-rels', kw['inc'])      # refused by the discid resource
        self.assertIn('Dark Side of the Moon', meta['album'])   # not the box set listed first
        self.assertEqual(len(meta['tracks']), 9)
        box = next(r for r in meta['releases'] if r['title'] == 'Shine On')
        self.assertEqual(box['disc_position'], 3)
        chosen = self.ss._cd_metadata(toc, box['mbid'])
        self.assertEqual((chosen['mbid'], chosen['album']), (box['mbid'], 'Shine On'))
        self.assertEqual(chosen['tracks'][0]['title'], meta['tracks'][0]['title'])
        discid_calls = [p for p, _ in self.lookups if p.startswith('discid/')]
        self.assertEqual(len(discid_calls), 1)                   # polls are served from the cache

    def test_unknown_disc_is_not_asked_again(self):
        self.answer = hm.NotFoundError('x')
        toc = self.ss._cd_toc()
        for _ in range(5):
            meta = self.ss._cd_metadata(toc)
        self.assertEqual(meta['album'], 'Unknown Album')
        self.assertEqual(meta['releases'], [])
        self.assertEqual(len(self.lookups), 1)
        with mock.patch.object(self.ss.time, 'monotonic', return_value=self.ss.time.monotonic() + 601):
            self.ss._cd_metadata(toc)
        self.assertEqual(len(self.lookups), 2)

    def test_offline_disc_is_held(self):
        self.answer = hm.OfflineError('down')
        toc = self.ss._cd_toc()
        for _ in range(3):
            self.ss._cd_metadata(toc)
        self.assertEqual(len(self.lookups), 1)

    def test_rip_tag_plan_follows_user_artist(self):
        toc = self.ss._cd_toc()
        meta = self.ss._cd_metadata(toc)
        album_tags, track_tags, artists = self.ss._cd_tag_plan(meta, 'Pink Floyd (edited)')
        a = dict(album_tags)
        self.assertEqual(a['ALBUMARTIST'], 'Pink Floyd (edited)')
        self.assertEqual(a['MUSICBRAINZ_ALBUMID'], meta['mbid'])
        self.assertEqual(a['MUSICBRAINZ_DISCID'], DSOTM_DISC_ID)
        self.assertEqual(artists, ['Pink Floyd (edited)'] * 9)
        self.assertEqual(len(track_tags), 9)
        self.assertIn('MUSICBRAINZ_TRACKID', dict(track_tags[0]))


class RipWorkerTests(unittest.TestCase):

    def test_extra_tags(self):
        import importlib.util
        path = os.path.join(ROOT, 'distro', 'config', 'includes.chroot', 'usr', 'local', 'sbin', 'hifi-rip-cd.py')
        spec = importlib.util.spec_from_file_location('hifi_rip_cd', path)
        mod = importlib.util.module_from_spec(spec)
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            spec.loader.exec_module(mod)
        self.assertEqual(mod.extra_tags([['MUSICBRAINZ_ARTISTID', 'a'], ('MUSICBRAINZ_ARTISTID', 'b'),
                                         ['bad name', 'x'], ['COMPOSER', 'Line\nbreak'], ['ISRC', ''], 'junk']),
                         ['--tag=MUSICBRAINZ_ARTISTID=a', '--tag=MUSICBRAINZ_ARTISTID=b', '--tag=COMPOSER=Line break'])


class RoutesTests(unittest.TestCase):

    def test_routes_and_auth(self):
        from flask import Flask, jsonify
        app = Flask(__name__)
        calls = []

        class Svc:
            def album(self, album_id, lang):
                calls.append(('album', album_id, lang))
                return {'status': 'pending', 'album_id': album_id}

            def settings(self):
                return {'online': True}

            def set_settings(self, online=None, prefetch=None, cache_location=None):
                calls.append(('set', online, prefetch, cache_location))
                if cache_location == '/nope':
                    raise hm.CacheMoveError('meta.cacheDirNetwork')
                return {'online': online}

        allowed = {'yes': True}

        def auth():
            return None if allowed['yes'] else (jsonify({'success': False}), 401)
        svc = Svc()
        hm.init_app(app, auth, service_getter=lambda: svc)
        c = app.test_client()
        r = c.get('/api/meta/album?album_id=7', headers={'X-UI-Lang': 'it'})
        self.assertEqual(r.get_json(), {'status': 'pending', 'album_id': 7})
        c.get('/api/meta/album?album_id=7&lang=en', headers={'X-UI-Lang': 'it'})
        self.assertEqual(calls[:2], [('album', 7, 'it'), ('album', 7, 'en')])
        self.assertEqual(c.get('/api/meta/album').status_code, 400)
        self.assertEqual(c.post('/api/meta/settings', json={'online': 'yes'}).status_code, 400)
        self.assertEqual(c.post('/api/meta/settings', json={'cache_location': 3}).status_code, 400)
        c.post('/api/meta/settings', json={'prefetch': False})
        self.assertEqual(calls[-1], ('set', None, False, None))
        c.post('/api/meta/settings', json={'cache_location': '/mnt/x'})
        self.assertEqual(calls[-1], ('set', None, None, '/mnt/x'))
        r = c.post('/api/meta/settings', json={'cache_location': '/nope'}, headers={'X-UI-Lang': 'it'})
        self.assertEqual((r.status_code, r.get_json()['code']), (400, 'meta.cacheDirNetwork'))
        self.assertIn('cartella di rete', r.get_json()['message'])
        allowed['yes'] = False
        self.assertEqual(c.get('/api/meta/settings').status_code, 401)

    def test_edit_routes(self):
        from flask import Flask
        app = Flask(__name__)
        calls = []

        class Svc:
            def album_edit_save(self, album_id, overrides, lang):
                calls.append(('album_save', album_id, lang))
                hm.validate_album_overrides(overrides)
                return {'status': 'ok', 'album_id': album_id}

            def artist_pin(self, artist_id, mbid, lang):
                calls.append(('artist_pin', artist_id, mbid))
                return {'status': 'ok'}

            def search_people(self, q):
                return {'status': 'ok', 'library': [], 'musicbrainz': []}

        svc = Svc()
        hm.init_app(app, lambda: None, service_getter=lambda: svc)
        c = app.test_client()
        self.assertEqual(c.post('/api/meta/album/edit', json={'album_id': 3, 'overrides': {}}).get_json()['status'], 'ok')
        r = c.post('/api/meta/album/edit', json={'album_id': 3, 'overrides': {'bogus': 1}}, headers={'X-UI-Lang': 'it'})
        body = r.get_json()
        self.assertEqual((r.status_code, body['success'], body['code']), (400, False, 'meta.badOverrides'))
        self.assertTrue(body['message'].startswith('Impossibile salvare le correzioni'))
        self.assertEqual(c.post('/api/meta/album/edit', json={'overrides': {}}).status_code, 400)
        self.assertEqual(c.post('/api/meta/artist/pin', json={'artist_id': 1, 'mbid': 'x'}).status_code, 400)
        c.post('/api/meta/artist/pin', json={'artist_id': 1, 'mbid': None})
        self.assertEqual(calls[-1], ('artist_pin', 1, None))
        self.assertEqual(c.get('/api/meta/search/people?q=a').status_code, 400)
        self.assertEqual(c.get('/api/meta/search/people?q=ab').status_code, 200)

    def test_sources_server_mounts_the_routes(self):
        with mock.patch('hifi_logging.tee_stdio_to_file'):
            import sources_server
        rules = {r.rule for r in sources_server.app.url_map.iter_rules()}
        for path in ('/api/meta/album', '/api/meta/album/candidates', '/api/meta/album/pin', '/api/meta/artist',
                     '/api/meta/person', '/api/meta/appearances', '/api/meta/settings', '/api/meta/cache/clear',
                     '/api/meta/album/edit', '/api/meta/artist/edit', '/api/meta/artist/candidates',
                     '/api/meta/artist/pin', '/api/meta/search/people'):
            self.assertIn(path, rules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
