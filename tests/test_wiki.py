"""The wiki's pages, from a small saved library (fixture.py). No network.

  python -m pytest -q tests
"""
import io, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import fixture                       # noqa: E402

ROOT = fixture.make()
import wiki                          # noqa: E402,F401
from wiki import md, pages           # noqa: E402
fixture.write(ROOT)
import notes_wiki                    # noqa: E402

OUT = ROOT / "out"
notes_wiki.main(["--offline", "--out", str(OUT)])
NOTES = OUT / "Notes"


def page(place):
    return (NOTES / f"{place}.md").read_text(encoding="utf-8")


class Names(unittest.TestCase):
    def test_file_name_rule(self):
        # scraper mode's rule (notes_file_name() in the viewer)
        self.assertEqual(md.file_name('AC/DC: "Live"?'), "AC_DC_ _Live__")
        self.assertEqual(md.file_name("R.E.M."), "R.E.M")
        self.assertEqual(md.album_place("R.E.M.", "Murmur... "), "Albums/R.E.M - Murmur")

    def test_links(self):
        self.assertEqual(md.link("Steve Gadd", "People/Steve Gadd"), "[Steve Gadd](<People/Steve Gadd>)")
        self.assertEqual(md.link("A [b]", "People/X"), "[A (b)](<People/X>)")
        # a place the viewer can't follow is plain text
        self.assertEqual(md.link("Smile", "People/Smile _)"), "Smile")
        self.assertEqual(md.link("Long", "Albums/" + "x" * 130), "Long")

    def test_escapes(self):
        self.assertEqual(md.text("*NSYNC [live] {{x}}"), "\\*NSYNC \\[live\\] {\\{x}}")
        self.assertEqual(md.text("# 1 hit"), "\\# 1 hit")
        self.assertEqual(md.text("1. First"), "\\1. First")
        self.assertEqual(md.text("1984 was a year"), "1984 was a year")


class Pages(unittest.TestCase):
    def test_marker(self):
        self.assertTrue((NOTES / ".notes-wiki").exists())

    def test_album_page(self):
        p = page("Albums/Steely Dan - Aja")
        self.assertTrue(p.startswith("<small>*[Steely Dan](<People/Steely Dan>) · 1977 · ABC"))
        self.assertIn("{{tracks|notes=2}}", p)
        self.assertIn("## Key People", p)
        self.assertIn("[Gary Katz](<People/Gary Katz>) *Producer*", p)
        self.assertIn("John Smith *Mixing*", p)            # no page: plain
        self.assertTrue(p.rstrip().endswith('CC BY-SA 4.0*</small>'))

    def test_names_in_text_linked_once(self):
        p = page("Albums/Steely Dan - Aja")
        self.assertEqual(p.count("[Steve Gadd]"), 2)       # the notes, and Key People
        bio = page("People/Steely Dan")
        self.assertIn("Walter Becker and Donald Fagen", bio)   # no pages: not links

    def test_credits_page(self):
        p = page("Albums/Steely Dan - Aja - Credits")
        self.assertTrue(p.startswith("---\nalbum: Steely Dan - Aja\n---\n"))
        self.assertIn("[3 people appear elsewhere in your library](<Albums/Steely Dan - Aja - Other Appearances>)", p)
        self.assertIn("[Steve Gadd](<People/Steve Gadd>) *Drums \\[2, 5\\]*", p)

    def test_band_plays_the_whole_album(self):
        """Walter Becker is credited on one track of Aja, but he's in the band:
        no track numbers. Steve Gadd, a guest, keeps his."""
        p = page("Albums/Steely Dan - Aja - Credits")
        self.assertIn("Walter Becker *Bass*", p)
        self.assertIn("*Drums \\[2, 5\\]*", p)

    def test_other_appearances(self):
        p = page("Albums/Steely Dan - Aja - Other Appearances")
        self.assertIn("**[Steve Gadd](<People/Steve Gadd>)** *Drums*", p)
        self.assertIn("◉ [Mingus](<Albums/Joni Mitchell - Mingus>) *Drums*", p)
        self.assertIn("♪ {{track|number=3|album=Steely Dan - Gaucho}} *Drums*", p)

    def test_tracks_page(self):
        p = page("Albums/Steely Dan - Aja - Tracks")
        self.assertIn("{{contents|style=inline}}", p)
        self.assertIn("## 2. Aja\n", p)                    # the title as tagged

    def test_bio_page(self):
        p = page("People/Steely Dan")
        self.assertIn("## Members", p)
        self.assertIn("Walter Becker *bass guitar, guitar, 1972–2017*", p)
        self.assertIn("## Studio Albums\n\nCan't Buy a Thrill *1972*\n[Aja](<Albums/Steely Dan - Aja>) *1977*", p)
        self.assertNotIn("## Albums", p)

    def test_key_people_pages(self):
        self.assertTrue((NOTES / "People/Steve Gadd.md").exists())     # key on 3 albums
        self.assertTrue((NOTES / "People/Jaco Pastorius.md").exists())  # one album, a Wikipedia bio
        p = page("People/Steve Gadd")
        self.assertIn("[Aja](<Albums/Steely Dan - Aja>) *1977 · Drums \\[2, 5\\]*", p)
        self.assertNotIn("Mentioned In", p)     # only albums already listed name him

    def test_one_john_smith(self):
        # two John Smiths, only one with enough of a bio: no clash, no qualifier
        self.assertTrue((NOTES / "People/John Smith.md").exists())
        self.assertIn("A photographer.", page("People/John Smith"))

    def test_banners(self):
        from PIL import Image
        for f in ("People/Steely Dan.jpg", "Albums/Steely Dan - Aja.jpg"):
            with Image.open(NOTES / f) as im:
                self.assertEqual(im.size, (320, 132))
                self.assertFalse(im.info.get("progressive"))

    def test_pages_fit(self):
        for f in NOTES.rglob("*.md"):
            self.assertLess(f.stat().st_size, pages.PAGE_MAX + 2048, f.name)


class Clash(unittest.TestCase):
    def test_qualifier(self):
        """Two key people of one name, both with pages: both take a qualifier.
        One with the name of a library artist takes it; the artist doesn't."""
        import credits as cr
        from wiki import people
        from wiki.graph import Graph
        a, b, c = ("mb", "aaaa1111-x"), ("mb", "bbbb2222-y"), ("mb", "cccc3333-z")
        g = Graph()
        g.same = cr.Same()
        g.name = {a: "John Smith", b: "John Smith", c: "Prince"}
        lib = {"X - Y": {"artist": "X", "album": "Y", "tracks": [[1, 1, "t"]]},
               "Prince - P": {"artist": "Prince", "album": "P", "tracks": [[1, 1, "t"]]}}
        g.chosen = {"X - Y": {"Engineers": ("MusicBrainz", [
            (a, "John Smith", "John Smith", "Mixing", "Engineers", None),
            (b, "John Smith", "John Smith", "Recording engineer", "Engineers", None),
            (c, "Prince", "Prince", "Recording engineer", "Engineers", None)])}, "Prince - P": {}}
        g.release_artists, g.members, g.mbart = {}, {}, {}
        w = people.assign(g, lib, has_bio=lambda r: True)
        self.assertEqual(w.root_page[a], "People/John Smith (aaaa1111)")
        self.assertEqual(w.root_page[b], "People/John Smith (bbbb2222)")
        self.assertEqual(w.root_page[c], "People/Prince (cccc3333)")
        self.assertEqual(w.artist_page["Prince"], "People/Prince")


class Splitting(unittest.TestCase):
    def test_long_tracks_split(self):
        """A Tracks page that would pass the read limit becomes Tracks 1, 2..."""
        L = pages.Library.__new__(pages.Library)
        L.linker = pages.Linker({})
        k = "A - B"
        L.lib = {k: {"artist": "A", "album": "B", "tracks": [[1, i + 1, f"T{i}"] for i in range(12)]}}
        L.tracks = {k: {"tracks": {str(i): {"paras": ["x" * 6000, "# From Last.fm"]} for i in range(12)}}}
        got = pages.tracks_pages(L, k)
        self.assertEqual([p.place for p in got], ["Albums/A - B - Tracks 1", "Albums/A - B - Tracks 2",
                                                  "Albums/A - B - Tracks 3"])
        for p in got:
            self.assertLessEqual(len(p.text().encode()), pages.PAGE_MAX)
            self.assertTrue(p.text().startswith("---\nalbum: A - B\n---\n"))

    def test_studio_albums(self):
        from wiki.lookups import studio_albums
        got = studio_albums([
            {"id": "2", "title": "Live", "primary-type": "Album", "secondary-types": ["Live"]},
            {"id": "1", "title": "Second", "primary-type": "Album", "first-release-date": "1980-01"},
            {"id": "3", "title": "First", "primary-type": "Album", "first-release-date": "1975"},
            {"id": "4", "title": "A Single", "primary-type": "Single"}])
        self.assertEqual([a["title"] for a in got], ["First", "Second"])


class Batched(unittest.TestCase):
    """Key people looked up many at a time: Wikidata by MusicBrainz ID, then
    Wikipedia's openings, then Last.fm only for the rest. Sites faked."""
    def test_people(self):
        import argparse
        from unittest import mock
        from wiki import lookups
        a, b, c = ("1" * 8 + "-1111-1111-1111-" + "1" * 12, "2" * 8 + "-2222-2222-2222-" + "2" * 12,
                   "3" * 8 + "-3333-3333-3333-" + "3" * 12)
        sparql = {"results": {"bindings": [
            {"mbid": {"value": a}, "item": {"value": "http://www.wikidata.org/entity/Q1"},
             "article": {"value": "https://en.wikipedia.org/wiki/Ann_Smith"},
             "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/Ann.jpg"},
             "born": {"value": "1950-03-01T00:00:00Z"}, "human": {"value": "true"}},
            {"mbid": {"value": b}, "item": {"value": "http://www.wikidata.org/entity/Q2"},
             "human": {"value": "true"}}]}}
        reply = mock.Mock(ok=True, status_code=200, json=lambda: sparql)
        asked = []
        with mock.patch.object(lookups, "sparql", return_value=reply), \
                mock.patch.object(lookups.ln, "wiki_summaries",
                                  side_effect=lambda t, s: asked.append(t) or {"Ann Smith": "Ann Smith is an engineer."}), \
                mock.patch.object(lookups.ab, "lastfm_bio",
                                  side_effect=lambda n, s, k, m: "Bob plays bass. He is from Leeds. He tours." if m == b else None):
            got = lookups.people([("A", "Ann Smith", a, None), ("B", "Bob Jones", b, None), ("C", "Cy", c, None)],
                                 None, argparse.Namespace(lastfm_key="k", discogs_token=None))
        self.assertEqual(asked, [["Ann Smith"]])                 # one Wikipedia request for the batch
        self.assertEqual(got["A"]["bio_source"], "wikipedia")
        self.assertEqual(got["A"]["subtitle"], "b. 1950")
        self.assertTrue(got["A"]["image"].endswith("Ann.jpg"))
        self.assertEqual(got["B"]["bio_source"], "lastfm")
        self.assertTrue(lookups.enough_bio(got["B"]))
        self.assertFalse(lookups.enough_bio(got["C"]))
        # saved: a second run asks nothing
        with mock.patch.object(lookups, "sparql", side_effect=AssertionError("asked again")):
            again = lookups.people([("A", "Ann Smith", a, None)], None,
                                   argparse.Namespace(lastfm_key="k", discogs_token=None))
        self.assertEqual(again["A"]["bio_source"], "wikipedia")


class Ids(unittest.TestCase):
    def test_same_answers_as_reading_the_whole_table(self):
        """ids_of() gives each person the IDs a walk of the whole table did."""
        import credits as cr
        from wiki import graph
        g = graph.Graph()
        g.same = cr.Same()
        g.same.join(("mb", "m1"), ("dc", 5))
        g.same.join(("mb", "m2"), ("dc", 7))
        g.same.join(("dc", 7), ("mb", "m3"))
        g.same.find(("mb", "m4"))
        g.same.find(("tag", "someone"))

        def walk(root, kind):
            if root[0] == kind:
                return root[1]
            return next((x[1] for x in list(g.same.up) if x[0] == kind and g.same.find(x) == root), None)

        for x in list(g.same.up):
            r = g.same.find(x)
            self.assertEqual(graph.mb_id(g, r), walk(r, "mb"), r)
            self.assertEqual(graph.dc_id(g, r), walk(r, "dc"), r)


class StudioAlbums(unittest.TestCase):
    """The ladder: Wikidata for all, MusicBrainz for the rest until it stops
    answering, Discogs last. Sites faked."""
    WD = {"results": {"bindings": [
        {"artist": {"value": "http://www.wikidata.org/entity/Q10"},
         "album": {"value": "http://www.wikidata.org/entity/Q11"}, "albumLabel": {"value": "First"},
         "date": {"value": "1999-05-01T00:00:00Z"}, "rg": {"value": "rg-first"}},
        {"artist": {"value": "http://www.wikidata.org/entity/Q10"},
         "album": {"value": "http://www.wikidata.org/entity/Q11"}, "albumLabel": {"value": "First"},
         "date": {"value": "1998-01-01T00:00:00Z"}},
        {"artist": {"value": "http://www.wikidata.org/entity/Q10"},
         "album": {"value": "http://www.wikidata.org/entity/Q12"}, "albumLabel": {"value": "Q12"}}]}}

    class DC:
        def __init__(self, pages=2):
            self.pages, self.total = [], pages

        def get(self, url, params=None):
            self.pages.append(params["page"])
            return {"pagination": {"pages": self.total}, "releases": [
                {"type": "master", "role": "Main", "id": params["page"], "title": f"Debut {params['page']}",
                 "year": 2000 + params["page"]},
                {"type": "master", "role": "Main", "id": 99, "title": "Live at Leeds", "year": 2003},
                {"type": "master", "role": "Appearance", "id": 3, "title": "Guesting", "year": 2004},
                {"type": "release", "role": "Main", "id": 4, "title": "Promo", "year": 2005}]}

    def ask(self, artists, dc, queries):
        from unittest import mock
        from wiki import lookups
        mb_calls = []

        def sparql(session, query):
            queries.append(query)
            return mock.Mock(ok=True, json=lambda: self.WD)
        with mock.patch.object(lookups, "sparql", side_effect=sparql), \
                mock.patch.object(lookups, "wikidata_by_mbid", return_value={}), \
                mock.patch.object(lookups, "mb_once", side_effect=lambda s, u, p: mb_calls.append(p["artist"])):
            got = lookups.discographies(artists, session=object(), mb=True, dc=dc, say=lambda s: None)
        return got, mb_calls

    def test_ladder(self):
        from wiki import lookups
        dc, queries = self.DC(), []
        artists = {"A": {"qid": "Q10"}, "B": {"mbid": "b1", "dcid": 7}, "C": {"mbid": "c1"},
                   "D": {"mbid": "d1"}, "E": {"mbid": "e1", "dcid": 9}}
        got, mb_calls = self.ask(artists, dc, queries)
        self.assertIn("wdt:P7937 wd:Q208569", queries[0])       # albums described either way
        self.assertIn("wdt:P31 wd:Q208569", queries[0])
        self.assertEqual(got["A"], [{"id": "rg-first", "title": "First", "year": "1998"}])
        self.assertEqual(mb_calls, ["b1", "c1", "d1"])          # stops after three busy answers
        self.assertEqual([a["title"] for a in got["B"]], ["Debut 1", "Debut 2"])
        self.assertEqual(dc.pages[:3], [1, 2, 1])
        self.assertNotIn("C", got)                               # no answer anywhere: asked again next run
        again = lookups.discographies(artists)                  # saved: no sites, same answers
        self.assertEqual(again["A"], got["A"])
        self.assertEqual(again["B"], got["B"])

        # next run: Discogs' guesses are asked of Wikidata again, and kept if it has nothing
        dc2, queries2 = self.DC(), []
        got2, mb2 = self.ask({"B": {"mbid": "b1", "dcid": 7, "qid": "Q20"}}, dc2, queries2)
        self.assertEqual(len(queries2), 1)
        self.assertEqual(mb2, [])
        self.assertEqual(dc2.pages, [])
        self.assertEqual(got2["B"], got["B"])

    def test_big_discogs_artist_gets_no_list(self):
        """Past two pages Discogs' main entries are mostly singles: no list,
        and only one page read."""
        dc = self.DC(pages=110)
        got, _ = self.ask({"F": {"dcid": 10263}}, dc, [])
        self.assertEqual(got["F"], [])
        self.assertEqual(dc.pages, [1])


class Keys(unittest.TestCase):
    def test_keys_file_wins(self):
        import wiki
        from wiki import ab
        wiki.KEYS.write_text("discogs token = abc\nlastfm key =\n", encoding="utf-8")
        try:
            conf = ab.settings()
            self.assertEqual(conf["discogs token"], "abc")
            self.assertEqual(conf.get("ipod drive"), "G:")       # the settings file still read
        finally:
            wiki.KEYS.unlink()


class OnePerson(unittest.TestCase):
    def test_two_sites_one_band(self):
        """A MusicBrainz and a Discogs entry of one name, both on albums by the
        same artist, are one person; on different artists' albums, two."""
        import credits as cr
        from wiki import graph
        lib = {"R - A": {"artist": "R"}, "R - B": {"artist": "R"}, "X - C": {"artist": "X"}}
        same = cr.Same()
        m, d, d2 = ("mb", "m-selway"), ("dc", 365781), ("dc", 99)
        by_name = {"philip selway": {m, d}, "john smith": {("mb", "m-js"), d2}}
        albums_of = {m: {"R - A"}, d: {"R - B"}, ("mb", "m-js"): {"R - A"}, d2: {"X - C"}}
        graph.join_by_artist(same, by_name, albums_of, lib)
        self.assertEqual(same.find(m), same.find(d))
        self.assertNotEqual(same.find(("mb", "m-js")), same.find(d2))


class SamePersonAsArtist(unittest.TestCase):
    def test_key_person_named_as_library_artist(self):
        """Credited on an album their name is in: the artist's own page. A
        credit from the files' tags, with no ID, isn't a second person."""
        import credits as cr
        from wiki import people
        from wiki.graph import Graph
        g = Graph()
        hend, tagged, gm = ("dc", 110593), ("tag", "george martin"), ("mb", "26fa8b67-x")
        g.same, g.release_artists, g.members, g.mbart = cr.Same(), {}, {}, {}
        g.name = {hend: "Jimi Hendrix", tagged: "George Martin", gm: "George Martin"}
        lib = {"Jimi Hendrix - Axis": {"artist": "Jimi Hendrix", "album": "Axis", "tracks": [[1, 1, "t"]]},
               "Love - False Start": {"artist": "Love", "album": "False Start", "tracks": [[1, 1, "t"]]},
               "The Beatles - Help!": {"artist": "The Beatles", "album": "Help!", "tracks": [[1, 1, "t"]]}}
        def credit(root, name, role, group):
            return (root, name, name, role, group, None)
        g.chosen = {"Jimi Hendrix - Axis": {"Songwriters": ("Discogs", [credit(hend, "Jimi Hendrix", "Written-by", "Songwriters")])},
                    "Love - False Start": {"Musicians": ("Discogs", [credit(hend, "Jimi Hendrix", "Lead Guitar", "Musicians")])},
                    "The Beatles - Help!": {"Producers": ("MusicBrainz", [credit(gm, "George Martin", "Producer", "Producers"),
                                                                          credit(tagged, "George Martin", "Producer", "Producers")])}}
        w = people.assign(g, lib, has_bio=lambda r: True)
        self.assertEqual(w.root_page[hend], "People/Jimi Hendrix")
        self.assertEqual(w.root_page[gm], "People/George Martin")
        self.assertNotIn(tagged, w.root_page)


class Capitals(unittest.TestCase):
    def test_one_page_for_names_that_differ_in_capitals(self):
        import credits as cr
        from wiki import people
        from wiki.graph import Graph
        g = Graph()
        g.same, g.name, g.chosen = cr.Same(), {}, {"N - A": {}, "N - B": {}}
        g.release_artists, g.members, g.mbart = {}, {}, {}
        lib = {"N - A": {"artist": "Nightmares On Wax", "album": "A", "tracks": []},
               "N - B": {"artist": "Nightmares on Wax", "album": "B", "tracks": []}}
        w = people.assign(g, lib)
        self.assertEqual(w.artist_page["Nightmares On Wax"], w.artist_page["Nightmares on Wax"])
        self.assertEqual(len(set(w.canon.values())), 1)
        self.assertEqual(w.case_clashes, [])

    def test_different_artists_differing_in_capitals_are_flagged(self):
        import credits as cr
        from wiki import people
        from wiki.graph import Graph
        g = Graph()
        g.same, g.chosen = cr.Same(), {"L - A": {}, "L - B": {}}
        a, b = ("mb", "low-us"), ("mb", "low-jp")
        g.name = {a: "Low", b: "LOW"}
        g.release_artists, g.members, g.mbart = {"L - A": {a}, "L - B": {b}}, {}, {}
        lib = {"L - A": {"artist": "Low", "album": "A", "tracks": []},
               "L - B": {"artist": "LOW", "album": "B", "tracks": []}}
        w = people.assign(g, lib)
        self.assertEqual(w.case_clashes, [["LOW", "Low"]])


class Writing(unittest.TestCase):
    def test_own_edits_kept(self):
        f = NOTES / "People/Joni Mitchell.md"
        f.write_text("My own words\n", encoding="utf-8")
        notes_wiki.main(["--offline", "--out", str(OUT)])
        self.assertEqual(f.read_text(encoding="utf-8"), "My own words\n")

    def test_dry_run_writes_nothing(self):
        out = ROOT / "dry"
        notes_wiki.main(["--offline", "--dry-run", "--out", str(out)])
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
