"""
Offline checks that liner_notes.py uses what ids.py identified: the exact
Discogs release's notes, the Wikidata item from the record, and Last.fm by
MusicBrainz release, with no searching by name.

  python -m unittest discover tests
"""
import os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())

import artist_bios as ab  # noqa: E402
import ids  # noqa: E402
import liner_notes as ln  # noqa: E402

INFO = {"artist": "Talk Talk", "album": "Spirit of Eden", "folder_artist": "Talk Talk", "tracks": 6}


class NoNetwork:
    def get(self, *a, **k):
        raise AssertionError("asked the network: " + str(a[:1]))


def write_record(rec):
    ids.CACHE.mkdir(parents=True, exist_ok=True)
    ab.save_json(ids.CACHE / f"{ab.safe_name('Talk Talk - Spirit of Eden')}.json",
                 {"key": "Talk Talk - Spirit of Eden", **rec})


class UsesIds(unittest.TestCase):
    def test_discogs_notes_from_the_saved_release(self):
        write_record({"discogs": {"id": 4242}})
        ids.save_release("dcrel", 4242, {"notes": "Recorded at Wessex Studios over fourteen months, "
                                                  "with more than a dozen guest musicians improvising."})
        got = ln.discogs_notes(INFO, NoNetwork(), "token", ln.ids_record(INFO))
        self.assertTrue(got.startswith("Recorded at Wessex"))

    def test_wikidata_item_from_the_record(self):
        write_record({"mb": {"id": "rel1", "rg": "rg1", "wikidata": "Q99"}})
        ids.save_release("mbrel", "rel1", {"release-group": {"id": "rg1", "first-release-date": "1988-09-12"}})
        asked = []
        saved = (ab.wd_entities, ln.item_result, ln.english_notes, ln.wd_album, ln.release_group)
        try:
            ab.wd_entities = lambda q, *a, **k: asked.append(q) or {"Q99": {"id": "Q99"}}
            ln.item_result = lambda ent, session, info: {"q": ent["id"], "ent": ent, "enwiki": "Spirit of Eden",
                                                         "wd_year": 1988, "label": ""}
            ln.english_notes = lambda title, session, sure: (["notes about " + title], "wikipedia")
            ln.wd_album = ln.release_group = lambda *a, **k: self.fail("searched by name")

            class Args:
                translator = None
                lastfm_key = None
                discogs_token = None
            found = {}
            paras, source = ln.find_notes(INFO, {"wikidata": "Q1"}, None, Args(), found)
        finally:
            ab.wd_entities, ln.item_result, ln.english_notes, ln.wd_album, ln.release_group = saved
        self.assertEqual(asked, [["Q99"]])
        self.assertEqual(paras, ["notes about Spirit of Eden"])
        self.assertEqual((found["q"], found["rg_year"]), ("Q99", "1988"))

    def test_lastfm_asked_by_release_first(self):
        asked = []

        class S:
            def get(self, url, headers=None, timeout=None, params=None):
                asked.append(dict(params))

                class R:
                    ok = True
                    def json(self):
                        return {"album": {"wiki": {"content": "x" * 100}}}
                return R()
        ln.lastfm_notes(INFO, ["Talk Talk"], S(), "key", mbid="rel1")
        self.assertEqual(asked[0].get("mbid"), "rel1")


class BioIds(unittest.TestCase):
    def test_artist_from_your_albums(self):
        ab.save_json(ids.LIBRARY, {"keys": ["Breis - Stranger On Earth", "Breis - Other"],
                                   "albums": {"Breis - Stranger On Earth": {"artist": "Breis", "album": "Stranger On Earth",
                                                                           "folder": "G:/Music/Breis/2012 - Stranger On Earth"},
                                              "Breis - Other": {"artist": "Breis feat. X", "album": "Other",
                                                                "folder": "G:/Music/Breis/2014 - Other"}}})
        ab.save_json(ids.CACHE / f"{ab.safe_name('Breis - Stranger On Earth')}.json",
                     {"key": "Breis - Stranger On Earth", "discogs": {"id": 1, "artists": [{"id": 777, "name": "Breis"}]}})
        ab.save_json(ids.CACHE / f"{ab.safe_name('Breis - Other')}.json",
                     {"key": "Breis - Other", "mb": {"artists": [{"id": "mb-breis", "name": "Breis"},
                                                               {"id": "mb-x", "name": "X"}]}})
        self.assertEqual(ab.ids_artist("Breis"), {"mbid": "mb-breis", "discogs": 777})
        self.assertEqual(ab.ids_artist("Nobody"), {})

    def test_short_profile_from_the_exact_artist(self):
        class Args:
            lastfm_key = None
            discogs_token = "t"
            translator = None
        saved = (ab.identify, ab.discogs_artist, ab.summary_line)
        try:
            ab.identify = lambda *a, **k: None
            ab.discogs_artist = lambda artist, session, token, dc_id=None: (None, "MC from London.") if dc_id else (None, None)
            ab.summary_line = lambda *a: ""
            bio, src, sure = ab.find_bio_first("Breis", None, Args(), (), {"known": {"ids": {"discogs": 777}}})
        finally:
            ab.identify, ab.discogs_artist, ab.summary_line = saved
        self.assertEqual((bio, src, sure), ("MC from London.", "discogs", True))
