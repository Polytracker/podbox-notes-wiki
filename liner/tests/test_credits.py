"""
Offline checks for credits.py: which credits reach the page, how they're
laid out, and who links where. Nothing here touches the network.

  python -m unittest discover tests
"""
import os, sys, tempfile, unittest
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())

import credits as cr  # noqa: E402
import ids  # noqa: E402


def lib_album(artist, album, n, discs=1):
    per = n // discs
    return {"artist": artist, "album": album,
            "tracks": [[d + 1, i + 1, f"Song {d * per + i + 1}"] for d in range(discs) for i in range(per)],
            "tag_credits": []}


def mb_rel(track_rels, release_rels=()):
    return {"relations": list(release_rels),
            "media": [{"tracks": [{"title": f"Song {i + 1}", "recording": {"id": f"rec{i}", "relations": rels}}
                                  for i, rels in enumerate(track_rels)]}]}


def mb_person(aid, name, typ, attrs=(), credit=None):
    return {"target-type": "artist", "type": typ, "attributes": list(attrs),
            "target-credit": credit or "", "artist": {"id": aid, "name": name}}


class Roles(unittest.TestCase):
    def test_country_names(self):
        self.assertEqual(cr.plain_edition('Paranoid · 1970 · 12" Vinyl · CH', "Paranoid"),
                         '1970 · 12" Vinyl · Switzerland')
        self.assertEqual(cr.plain_edition("X · 2001 · CD · GB", "Y"), "X · 2001 · CD · UK")

    def test_engineer_names(self):
        self.assertEqual(cr.mb_role({"type": "recording", "attributes": []}), "Recording engineer")
        self.assertEqual(cr.mb_role({"type": "recording", "attributes": ["assistant"]}),
                         "Assistant recording engineer")
        self.assertEqual(cr.mb_role({"type": "mix", "attributes": []}), "Mixing")
        self.assertEqual(cr.dc_role("Recorded By"), "Recording engineer")
        self.assertEqual(cr.dc_role("Mixed By [Assistant Mix Engineer]"), "Assistant mixing engineer")
        self.assertEqual(cr.dc_role("Recorded By [Additional Strings]"),
                         "Recording engineer (Additional Strings)")
        self.assertEqual(cr.dc_role("Mastered By"), "Mastering")

    def test_mb_roles(self):
        self.assertEqual(cr.mb_role({"type": "instrument", "attributes": ["bass guitar"]}), "Bass guitar")
        self.assertEqual(cr.mb_role({"type": "vocal", "attributes": []}), "Vocals")
        self.assertEqual(cr.mb_role({"type": "producer", "attributes": ["executive"]}), "Executive producer")
        self.assertEqual(cr.mb_role({"type": "instrument", "attributes": ["guest", "piano"]}), "Guest piano")

    def test_dc_role(self):
        self.assertEqual(cr.dc_role("Guitar [Electric]"), "Guitar (Electric)")
        self.assertEqual(cr.dc_role("Synthesizer [Moog]"), "Synthesizer (Moog)")
        self.assertEqual(cr.dc_role("Mixed By"), "Mixing")
        self.assertEqual(cr.dc_role("Written-By"), "Written-by")
        self.assertEqual(cr.dc_role("Engineer [Engineered By]"), "Engineer")
        self.assertEqual(cr.dc_role("Backing Vocals [Background Vocals]"), "Backing Vocals")
        self.assertEqual(cr.dc_role("Bass [Live Bass]"), "Bass")
        self.assertEqual(cr.dc_role("Electric Piano [Wurlitzer]"), "Electric Piano (Wurlitzer)")
        self.assertEqual(cr.dc_role("Arranged By [Strings]"), "Arranged by (Strings)")


class FromSources(unittest.TestCase):
    def test_mb_only_your_tracks(self):
        # the release has 3 recordings; you have the first two
        rel = mb_rel([[mb_person("p1", "Ann", "instrument", ["drums"])],
                      [mb_person("p2", "Bob", "producer")],
                      [mb_person("p3", "Cat", "instrument", ["harp"])]],
                     [mb_person("p4", "Dan", "mastering")])
        rec = {"tracks": {"0": {"recording": "rec0"}, "1": {"recording": "rec1"}}}
        got = {c[1]: (c[3], c[4], c[5]) for c in cr.mb_credits(rel, rec)}
        self.assertEqual(got["Ann"], ("Drums", "Musicians", {0}))
        self.assertEqual(got["Dan"], ("Mastering", "Engineers", None))
        self.assertNotIn("Cat", got)

    def test_mb_songwriters_from_works(self):
        work = {"target-type": "work", "work": {"relations": [mb_person("w1", "Wes", "composer")]}}
        rel = mb_rel([[work]])
        got = cr.mb_credits(rel, {"tracks": {"0": {"recording": "rec0"}}})
        self.assertEqual([(c[1], c[4]) for c in got], [("Wes", "Songwriters")])

    def test_dc_tracks_field(self):
        rel = {"tracklist": [{"position": p} for p in ("A1", "A2", "A3", "B1")],
               "extraartists": [{"id": 1, "name": "Ann (2)", "role": "Bass", "tracks": "A1 to A2"},
                                {"id": 2, "name": "Bob", "role": "Organ", "tracks": "B1"},
                                {"id": 3, "name": "Cat", "role": "Producer, Mixed By", "tracks": ""}]}
        rec = {"tracks": {"0": {"position": "A1"}, "1": {"position": "A2"}, "2": {"position": "A3"}}}
        got = cr.dc_credits(rel, rec)
        by = defaultdict(list)
        for c in got:
            by[c[1]].append((c[3], c[5]))
        self.assertEqual(by["Ann"], [("Bass", {0, 1})])          # the "(2)" is dropped
        self.assertNotIn("Bob", by)                              # only on a track you don't have
        self.assertEqual(by["Cat"], [("Producer", None), ("Mixing", None)])

    def test_track_list(self):
        order = ["A1", "A2", "A3", "B1", "B2"]
        self.assertEqual(cr.dc_track_list("A2 to B1, B2", order), ["A2", "A3", "B1", "B2"])
        self.assertIsNone(cr.dc_track_list("C9", order))


class Layout(unittest.TestCase):
    def test_tags_first_then_most(self):
        tags = [(("tag", "x"), "X", "X", "Composer", "Songwriters", {0})]
        mb = [(("mb", "a"), "A", "A", "Drums", "Musicians", None),
              (("mb", "b"), "B", "B", "Writer", "Songwriters", None)]
        dc = [(("dc", 1), "A", "A", "Drums", "Musicians", None),
              (("dc", 2), "C", "C", "Bass", "Musicians", None)]
        got = cr.choose([("tags", tags), ("MusicBrainz", mb), ("Discogs", dc)])
        self.assertEqual(got["Songwriters"][0], "tags")
        self.assertEqual(got["Musicians"][0], "Discogs")

    def test_whole_album_beats_one_track_guests(self):
        mb = [(("mb", "b"), "Band", "Band", "Guitar", "Musicians", {0})] + \
             [(("mb", f"h{i}"), f"H{i}", f"H{i}", "Horn", "Musicians", {2}) for i in range(6)]
        dc = [(("dc", 1), "Band", "Band", "Guitar", "Musicians", None),
              (("dc", 2), "Drum", "Drum", "Drums", "Musicians", None)]
        sources = [("MusicBrainz", mb), ("Discogs", dc)]
        self.assertEqual(cr.choose(sources, 10)["Musicians"][0], "Discogs")
        self.assertEqual(cr.choose(sources, 10, weighted=False)["Musicians"][0], "MusicBrainz")

    def test_rows_and_ranges(self):
        album = lib_album("Band", "Album", 8)
        creds = [(("dc", 1), "Ann", "Ann", "Drums", "Musicians", {0, 1, 2, 4}),
                 (("dc", 1), "Ann", "Ann", "Vocals", "Musicians", None),
                 (("dc", 2), "Bob", "Bobby", "Bass", "Musicians", set(range(8)))]
        rows = cr.people_rows(creds, album)
        self.assertEqual(rows[0][1:], ("Ann", ["Drums [1–3, 5]", "Vocals"]))
        self.assertEqual(cr.roles_text(rows[0][2]), "Drums [1–3, 5], Vocals")
        self.assertEqual(cr.roles_text(["Vocals", "Guitar"]), "Vocals, Guitar")
        self.assertEqual(rows[1][1:], ("Bobby", ["Bass"]))          # every track: no numbers

    def test_roles_on_same_tracks_share_numbers(self):
        album = lib_album("Band", "Album", 8)
        creds = [(("dc", 1), "Bud", "Bud", r, "Musicians", {0, 6}) for r in ("Alto Saxophone", "Flute")] + \
                [(("dc", 1), "Bud", "Bud", "Vocals", "Musicians", {2})]
        self.assertEqual(cr.people_rows(creds, album)[0][2], ["Alto Saxophone, Flute [1, 7]", "Vocals [3]"])

    def test_multi_disc_labels(self):
        album = lib_album("Band", "Album", 4, discs=2)
        label = cr.track_label(album)
        self.assertEqual(cr.track_ranges({2, 3}, label), "2-1–2-2")

    def test_page_text(self):
        album = lib_album("Band", "Album", 3)
        rec = {"discogs": {"edition": "Album · 1999 · CD · UK", "how": "subset", "release_tracks": 5}}
        chosen = {"Musicians": ("Discogs", [(("dc", 1), "Ann", "Ann", "Drums", "Musicians", None)])}
        text = cr.page_text("Band - Album", album, rec, chosen,
                            [("Ann", "Drums", ["A\tOther\tRecord\tDrums"])])
        lines = text.splitlines()
        self.assertEqual(lines[0], "#facts\tEdition: 1999 · CD · UK · your 3 of its 5 tracks")
        self.assertEqual(lines[1], "#status\t1 person appears elsewhere in your library")
        self.assertIn("## Musicians", lines)
        self.assertIn("Ann\tDrums", lines)
        self.assertIn("#sources\tCredits from Discogs", lines)
        self.assertEqual(lines[-3:], ["#links", "P\tAnn\tDrums", "A\tOther\tRecord\tDrums"])

    def test_plain_edition(self):
        self.assertEqual(cr.plain_edition("OK Computer · 2016 · Digital Media · XW", "OK Computer"),
                         "2016 · Digital · Worldwide")
        self.assertEqual(cr.plain_edition("Down in Albion (deluxe edition) · 2005 · 2×CD · GB", "Down in Albion"),
                         "Down in Albion (deluxe edition) · 2005 · 2×CD · UK")
        self.assertEqual(cr.mb_role({"type": "instrument", "attributes": ["additional", "bass guitar"]}),
                         "Additional bass guitar")

    def test_sources_line_other_credits(self):
        c = {"Musicians": ("Discogs", []), "Credited": ("Discogs", []), "Producers": ("MusicBrainz", [])}
        self.assertEqual(cr.sources_line(c), "Musicians and other credits from Discogs, producers from MusicBrainz")

    def test_sources_line(self):
        c = {"Musicians": ("Discogs", []), "Engineers": ("Discogs", []), "Producers": ("MusicBrainz", [])}
        self.assertEqual(cr.sources_line(c), "Musicians and engineers from Discogs, producers from MusicBrainz")

    def test_status_wording(self):
        self.assertEqual(cr.status_line(0), "No one here appears elsewhere in your library")
        self.assertEqual(cr.status_line(3), "3 people appear elsewhere in your library")


class Links(unittest.TestCase):
    def test_other_artists_only_and_few_tracks(self):
        lib = {"Band - One": lib_album("Band", "One", 5), "Band - Two": lib_album("Band", "Two", 5),
               "Other - Three": lib_album("Other", "Three", 5), "Else - Four": lib_album("Else", "Four", 5)}
        appear = {"ann": {"Band - One": {("Drums", None)}, "Band - Two": {("Drums", None)},
                          "Other - Three": {("Drums", frozenset({1}))},
                          "Else - Four": {("Producer", None)}}}
        rows = cr.link_rows("ann", "Band - One", cr.fold("Band"), appear, lib,
                            {"Band - One": {"ann"}, "Band - Two": {"ann"}})
        self.assertEqual(rows, ["A\tElse\tFour\tProducer", "T\tOther\tThree\tSong 2\tDrums"])

    def test_same_artist_only_for_outsiders(self):
        lib = {"Band - One": lib_album("Band", "One", 5), "Band - Two": lib_album("Band", "Two", 5),
               "Solo - Three": lib_album("Solo", "Three", 5)}
        appear = {"member": {"Band - One": {("Guitar", None)}, "Band - Two": {("Guitar", None)},
                             "Solo - Three": {("Album artist", None)}},
                  "producer": {"Band - One": {("Producer", None)}, "Band - Two": {("Producer", None)}}}
        insiders = {"Band - One": {"member"}, "Band - Two": {"member"}}
        self.assertEqual(cr.link_rows("member", "Band - One", cr.fold("Band"), appear, lib, insiders),
                         ["A\tSolo\tThree\tAlbum artist"])
        self.assertEqual(cr.link_rows("producer", "Band - One", cr.fold("Band"), appear, lib, insiders),
                         ["A\tBand\tTwo\tProducer"])

    def test_capped(self):
        lib = {f"A{i} - B{i}": lib_album(f"A{i}", f"B{i}", 5) for i in range(cr.LINK_ROWS + 10)}
        appear = {"eng": {k: {("Mastering", None)} for k in lib}}
        rows = cr.link_rows("eng", "A0 - B0", cr.fold("A0"), appear, lib)
        self.assertEqual(len(rows), cr.LINK_ROWS)

    def test_page_switch(self):
        import tempfile, artist_bios as ab
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(ab.ipod_page_on(d, "credits"))          # no settings file: on
            (Path(d) / ".rockbox").mkdir()
            cfg = Path(d) / ".rockbox" / "config.cfg"
            cfg.write_text("liner notes credits: off\n")
            self.assertFalse(ab.ipod_page_on(d, "credits"))
            self.assertTrue(ab.ipod_page_on(d, "track notes"))
            cfg.write_text("liner notes: off\n")
            self.assertFalse(ab.ipod_page_on(d, "track notes"))

    def test_vorbis_and_id3_people(self):
        self.assertEqual(ids.credit_pairs("PERFORMER", ["Ann (drums)", "Bob"]),
                         [("Ann", "drums", "Musicians"), ("Bob", "performer", "Musicians")])
        self.assertEqual(ids.credit_pairs("COMPOSER", ["Wes; Kay"]),
                         [("Wes", "composer", "Songwriters"), ("Kay", "composer", "Songwriters")])

        class Frame:
            people = [["producer", "Pat"], ["mix", "Max"]]
        self.assertEqual(ids.credit_pairs("TIPL", Frame()),
                         [("Pat", "producer", "Producers"), ("Max", "mix", "Engineers")])
        self.assertEqual(ids.credit_pairs("TITLE", ["x"]), [])
