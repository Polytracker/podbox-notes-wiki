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
