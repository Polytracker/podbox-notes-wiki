"""
Offline checks for ids.py: matching a folder to the right release, and the
order the lookups run in. Nothing here touches the network.

  python -m unittest discover tests
"""
import os, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())

import ids  # noqa: E402


def album(artist, title, tracks, **kw):
    a = {"key": f"{artist} - {title}", "folder_artist": artist, "artist": artist, "album": title,
         "folder": "", "mb_album": "", "barcode": "", "catno": "", "label": "", "discid": "",
         "discogs": "", "links": [],
         "tracks": [{"i": i, "disc": 1, "num": i + 1, "length": length, "isrc": isrc, "title": t, "file": ""}
                    for i, (t, length, isrc) in enumerate(tracks)]}
    a.update(kw)
    return a

def release(artists, title, tracks, discs=None):
    return {"artists": artists, "title": title, "discs": discs or {},
            "tracks": [{"i": i, "len": length, "title": t, "isrcs": set(c), "position": str(i + 1)}
                       for i, (t, length, c) in enumerate(tracks)]}

ORIGINAL = [(f"Song {i}", 180 + i * 7, "") for i in range(14)]


class Check(unittest.TestCase):
    def test_accents_and_isrc(self):
        a = album("Charlotte Adigery", "Zandoli", [("A", 200, "X1"), ("B", 210, "X2")])
        r = release(["Charlotte Adigéry"], "Zandoli", [("A", 201, ["X1"]), ("B", 209, ["X2"])])
        self.assertEqual(ids.check(a, r)[:3], (True, "", "exact"))

    def test_alias_needs_an_id_or_the_title(self):
        a = album("MF DOOM", "Madvillainy", [("Accordion", 120, ""), ("Meat Grinder", 130, "")])
        r = release(["Madvillain"], "Madvillainy", [("Accordion", 121, []), ("Meat Grinder", 131, [])])
        self.assertTrue(ids.check(a, r, strong=True)[0])
        self.assertTrue(ids.check(a, r)[0])                       # same album title
        self.assertFalse(ids.check(a, dict(r, title="Other"))[0])
        self.assertFalse(ids.check(a, r, need_artist=True)[0])    # a name search never lets it pass

    def test_fewer_tracks_than_the_release(self):
        a = album("Tom Waits", "Small Change", ORIGINAL[:10])
        r = release(["Tom Waits"], "Small Change (Remastered)",
                    [(t + " - 2018 Remaster", n + 1, []) for t, n, _ in ORIGINAL[:10]] + [("Bonus", 100, [])])
        ok, _, how, pairs = ids.check(a, r, strong=True)
        self.assertEqual((ok, how, len(pairs)), (True, "subset", 10))

    def test_deluxe_copy_of_an_original_album(self):
        deluxe = ORIGINAL + [(f"Demo {i}", 150, "") for i in range(9)]
        a = album("Elliott Smith", "XO (Deluxe Edition)", deluxe)
        self.assertEqual(ids.check(a, release(["Elliott Smith"], "XO", ORIGINAL), True)[2], "superset")
        # never a single, another album, or an original missing more than one track in ten
        self.assertFalse(ids.check(a, release(["Elliott Smith"], "Waltz #2 (XO)", ORIGINAL[:3]), True)[0])
        self.assertFalse(ids.check(a, release(["Elliott Smith"], "Either/Or", ORIGINAL), True)[0])
        a2 = album("Elliott Smith", "XO (Deluxe Edition)", deluxe[2:])       # two originals missing: under 90%
        self.assertFalse(ids.check(a2, release(["Elliott Smith"], "XO", ORIGINAL), True)[0])

    def test_live_album_split_differently(self):
        a = album("Joni Mitchell", "Miles of Aisles", [(f"L{i}", 200 + i * 30, "") for i in range(6)])
        r = release(["Joni Mitchell"], "Miles of Aisles", [(f"L{i}", 260, []) for i in range(6)])
        self.assertTrue(ids.check(a, r, True)[0])

    def test_compilation_refused(self):
        a = album("Julian Lennon", "Valotte", [(f"V{i}", 200, "") for i in range(10)])
        r = release(["Various Artists"], "Classic Rock", [("V1", 200, [])] + [(f"Z{i}", 200, []) for i in range(35)])
        self.assertFalse(ids.check(a, r)[0])

    def test_notes(self):
        a = album("x", "y", ORIGINAL)
        self.assertEqual(ids.tracks_note(a, {"how": "superset", "release_tracks": 10}),
                         "its 10 tracks are 10 of your 14")
        self.assertEqual(ids.tracks_note(a, {"how": "subset", "release_tracks": 16}), "your 14 of its 16 tracks")
        self.assertEqual(ids.tracks_note(a, {"how": "exact", "release_tracks": 14}), "")


class Tags(unittest.TestCase):
    def test_names(self):
        self.assertEqual(ids.norm_key("TXXX:MusicBrainz Album Id"), "MUSICBRAINZALBUMID")
        self.assertEqual(ids.norm_key("----:com.apple.iTunes:MusicBrainz Album Id"), "MUSICBRAINZALBUMID")
        self.assertEqual(ids.ALIASES[ids.norm_key("discogs_release_id")], "DISCOGS")
        self.assertEqual(ids.norm_key("COMM::eng"), "COMMENT")
        self.assertEqual(ids.norm_key("WXXX:"), "URL")

    def test_store_links(self):
        first = {"SOURCE": "Deezer", "SOURCEID": "123", "APPLEALBUM": "1440"}
        urls = ["Visit https://artist.bandcamp.com",                      # the artist's page: not an album
                "https://artist.bandcamp.com/album/first-light?from=x",
                "http://www.discogs.com/Artist-Title/release/4567"]
        links = ids.store_links(first, [u for s in urls for u in ids.URL_RE.findall(s)])
        self.assertIn(("deezer-track", "123"), links)
        self.assertIn(("apple", "1440"), links)
        self.assertIn(("url", "https://artist.bandcamp.com/album/first-light"), links)
        self.assertIn(("discogs", "4567"), links)
        self.assertNotIn(("url", "https://artist.bandcamp.com"), links)

    def test_signature_follows_the_ids(self):
        a = album("x", "y", ORIGINAL)
        before = ids.signature(a)
        self.assertEqual(before, ids.signature(dict(a)))
        self.assertNotEqual(before, ids.signature(dict(a, mb_album="abc")))


class FakeSite:
    """Answers by URL fragment; records what was asked."""
    def __init__(self, routes):
        self.routes, self.asked, self.count = routes, [], 0

    def get(self, url, params=None):
        self.asked.append((url, params))
        for frag, answer in self.routes:
            if frag in url + " " + repr(params):
                return answer(url, params) if callable(answer) else answer
        return None


def mb_release(rid, title, artist, tracks, discogs=None, rg="RG"):
    rels = [{"target-type": "url", "url": {"resource": f"https://www.discogs.com/release/{discogs}"}}] if discogs else []
    return {"id": rid, "title": title, "date": "1998-08-25", "country": "US",
            "release-group": {"id": rg}, "relations": rels,
            "artist-credit": [{"name": artist, "artist": {"id": "A", "name": artist}}],
            "media": [{"position": 1, "format": "CD",
                       "tracks": [{"title": t, "length": n * 1000, "position": i + 1,
                                   "recording": {"id": f"rec{i}", "isrcs": [c] if c else []}}
                                  for i, (t, n, c) in enumerate(tracks)]}]}


class Lookups(unittest.TestCase):
    def test_barcode_then_isrc(self):
        a = album("Elliott Smith", "XO", ORIGINAL, barcode="600445026020")
        wrong = mb_release("R-wrong", "XO", "Elliott Smith", ORIGINAL[:6])   # passes, but only as a partial edition
        right = mb_release("R-right", "XO", "Elliott Smith", ORIGINAL, discogs=77)
        site = FakeSite([("barcode:", {"releases": [{"id": "R-wrong"}]}),
                         ("release/R-wrong", wrong), ("release/R-right", right),
                         ("isrc/", {"recordings": [{"releases": [{"id": "R-right", "title": "XO"}]}]}),
                         ("release-group/RG", {"relations": [
                             {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q123"}}]})])
        a["tracks"][0]["isrc"] = "USX"
        r, failed = ids.MusicBrainz(site, FakeSite([])).identify(a)
        self.assertEqual((r["id"], r["rung"], r["wikidata"], r["discogs"]["release"]), ("R-right", "isrc", "Q123", 77))
        self.assertNotIn("R-wrong", [f["id"] for f in failed])     # kept aside, then beaten by the exact match
        self.assertEqual(r["tracks"]["0"]["recording"], "rec0")

    def test_name_search_last(self):
        a = album("Pinback", "Summer in Abaddon", ORIGINAL)
        site = FakeSite([("release:", {"releases": [{"id": "R1", "score": 100}]}),
                         ("release/R1", mb_release("R1", "Summer in Abaddon", "Pinback", ORIGINAL))])
        r, _ = ids.MusicBrainz(site, FakeSite([])).identify(a)
        self.assertEqual(r["rung"], "name search")

    def test_discogs_skips_promo_editions(self):
        a = album("Elliott Smith", "XO", ORIGINAL)
        def rel(rid):
            return {"title": "XO", "year": 1998, "country": "US", "artists": [{"name": "Elliott Smith"}],
                    "formats": [{"name": "CD", "descriptions": ["Album"]}],
                    "tracklist": [{"title": t, "duration": f"{n // 60}:{n % 60:02d}", "position": str(i + 1)}
                                  for i, (t, n, _) in enumerate(ORIGINAL)]}
        site = FakeSite([("masters/9/versions", {"versions": [
                            {"id": 1, "format": "CD, Album, Promo", "released": "1998"},
                            {"id": 2, "format": "Cassette, Album", "released": "1998"},
                            {"id": 3, "format": "CD, Album", "released": "1998", "major_formats": ["CD"]}]}),
                         ("masters/9", {"main_release": 1}),
                         ("releases/", lambda url, p: rel(url.rsplit("/", 1)[1]))])
        r, _ = ids.Discogs(site).identify(a, {"master": 9})
        self.assertEqual((r["id"], r["rung"]), (3, "musicbrainz master"))

    def test_discogs_tag_first(self):
        a = album("x", "y", ORIGINAL, discogs="55")
        site = FakeSite([("releases/55", {"title": "y", "artists": [{"name": "x"}], "tracklist": [
            {"title": t, "duration": "", "position": str(i)} for i, (t, n, _) in enumerate(ORIGINAL)]})])
        r, _ = ids.Discogs(site).identify(a, {"release": 99})
        self.assertEqual((r["id"], r["rung"]), (55, "discogs id"))


class Saved(unittest.TestCase):
    def test_when_to_look_again(self):
        a = album("x", "y", ORIGINAL)
        now = int(time.time())
        rec = {"format": ids.FORMAT, "sig": ids.signature(a), "checked": now, "mb": {"id": "R"},
               "discogs": None, "discogs_tried": False}
        self.assertFalse(ids.needs_lookup(a, rec))                         # found, no token
        self.assertTrue(ids.needs_lookup(a, rec, token="t"))              # a token was added since
        rec.update(discogs_tried=True)
        self.assertFalse(ids.needs_lookup(a, rec, token="t"))             # Discogs missed recently
        self.assertTrue(ids.needs_lookup(a, dict(rec, checked=now - 31 * 86400), token="t"))
        self.assertTrue(ids.needs_lookup(dict(a, mb_album="new"), rec))    # tags changed (Picard)


if __name__ == "__main__":
    unittest.main()


class Groups(unittest.TestCase):
    def test_musicbrainz(self):
        self.assertEqual([ids.mb_group(t) for t in ("instrument", "producer", "mix", "lyricist", "design")],
                         ["Musicians", "Producers", "Engineers", "Songwriters", "Credited"])

    def test_discogs(self):
        roles = {"Bass [Fretless]": "Musicians", "Vocals, Guitar": "Musicians", "Co-producer": "Producers",
                 "Mixed By": "Engineers", "Mastered By": "Engineers", "Lacquer Cut By": "Engineers",
                 "Written-By": "Songwriters", "Lyrics By": "Songwriters", "Music By": "Songwriters",
                 "Design": "Credited", "Photography By": "Credited", "Arranged By [Strings]": "Credited",
                 "Drums [Uncredited]": "Musicians"}
        for role, group in roles.items():
            self.assertEqual(ids.dc_group(role), group, role)


class SavedReleases(unittest.TestCase):
    def test_round_trip_and_age(self):
        ids.save_release("mbrel", "abc-123", {"title": "XO"})
        self.assertEqual(ids.saved_release("mbrel", "abc-123"), {"title": "XO"})
        self.assertIsNone(ids.saved_release("mbrel", "abc-123", max_days=-1))   # too old: fetch again
        self.assertIsNone(ids.saved_release("dcrel", "999"))

    def test_chosen_release_is_kept(self):
        a = album("Pinback", "Summer in Abaddon", ORIGINAL)
        rel = mb_release("R-kept", "Summer in Abaddon", "Pinback", ORIGINAL)
        site = FakeSite([("release:", {"releases": [{"id": "R-kept", "score": 100}]}), ("release/R-kept", rel)])
        ids.MusicBrainz(site, FakeSite([])).identify(a)
        self.assertEqual(ids.saved_release("mbrel", "R-kept")["title"], "Summer in Abaddon")
        site2 = FakeSite([("release:", {"releases": [{"id": "R-kept", "score": 100}]})])
        r, _ = ids.MusicBrainz(site2, FakeSite([])).identify(a)          # no second fetch of the release
        self.assertEqual(r["id"], "R-kept")
        self.assertFalse(any("release/R-kept" in u for u, _ in site2.asked))


class FewerRequests(unittest.TestCase):
    def test_only_plausible_search_results_are_fetched(self):
        a = album("x", "y", ORIGINAL)                                   # 14 tracks
        results = [{"id": "single", "track-count": 2}, {"id": "box", "track-count": 60},
                   {"id": "near", "track-count": 15}, {"id": "same", "track-count": 14},
                   {"id": "weak", "track-count": 14, "score": 60}]
        self.assertEqual(ids.MusicBrainz.plausible(a, results, min_score=80), ["same", "near"])

    def test_group_links_come_with_the_release(self):
        a = album("Pinback", "Summer in Abaddon", ORIGINAL)
        rel = mb_release("R9", "Summer in Abaddon", "Pinback", ORIGINAL)
        rel["release-group"]["relations"] = [
            {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q9"}},
            {"type": "discogs", "url": {"resource": "https://www.discogs.com/master/42"}}]
        site = FakeSite([("release:", {"releases": [{"id": "R9", "score": 100, "track-count": 14}]}),
                         ("release/R9", rel)])
        r, _ = ids.MusicBrainz(site, FakeSite([])).identify(a)
        self.assertEqual((r["wikidata"], r["discogs"]["master"]), ("Q9", 42))
        self.assertFalse(any("release-group/" in u for u, _ in site.asked))   # no separate request

    def test_partial_edition_stops_before_a_name_search(self):
        deluxe = ORIGINAL + [(f"Demo {i}", 150, "") for i in range(9)]
        a = album("Elliott Smith", "XO (Deluxe Edition)", deluxe, barcode="600445026020")
        site = FakeSite([("barcode:", {"releases": [{"id": "R-orig", "track-count": 14}]}),
                         ("release/R-orig", mb_release("R-orig", "XO", "Elliott Smith", ORIGINAL)),
                         ("release:", {"releases": [{"id": "R-other", "score": 100}]})])
        r, _ = ids.MusicBrainz(site, FakeSite([])).identify(a)
        self.assertEqual((r["id"], r["how"]), ("R-orig", "superset"))
        self.assertFalse(any("release:" in repr(p) for _, p in site.asked))


class Editions(unittest.TestCase):
    def test_cd_before_vinyl_and_cassette(self):
        vs = [{"id": 1, "format": "Vinyl, LP, Album", "released": "1984"},
              {"id": 2, "format": "Cassette, Album", "released": "1984"},
              {"id": 3, "format": "CD, Album", "released": "1990"},
              {"id": 4, "format": "CD, Album, Promo", "released": "1984"}]
        self.assertEqual([v["id"] for v in sorted(vs, key=ids.version_rank)], [3, 1, 2, 4])

    def test_index_track_counts_once(self):
        rel = {"tracklist": [{"type_": "heading", "title": "Side A"},
                             {"type_": "index", "title": "Close to the Edge",
                              "sub_tracks": [{"title": "I"}, {"title": "II"}]},
                             {"type_": "track", "title": "And You and I"}]}
        self.assertEqual([t["title"] for t in ids.discogs_tracks(rel)], ["Close to the Edge", "And You and I"])

    def test_deluxe_with_a_retitled_track(self):
        deluxe = [(t if i != 3 else "Something else entirely", n, c) for i, (t, n, c) in enumerate(ORIGINAL)] + \
                 [(f"Demo {i}", 150, "") for i in range(9)]
        a = album("Elliott Smith", "XO (Deluxe Edition)", deluxe)
        self.assertEqual(ids.check(a, release(["Elliott Smith"], "XO", ORIGINAL), True)[2], "superset")


class NameSearch(unittest.TestCase):
    def test_artist_spellings(self):
        self.assertEqual(ids.search_artists("Ryo Fukui, 福居良"), ["Ryo Fukui, 福居良", "Ryo Fukui"])
        self.assertEqual(ids.search_artists("Pete Rock & C.L. Smooth"), ["Pete Rock & C.L. Smooth"])
        self.assertEqual(ids.search_artists("Earth, Wind & Fire"), ["Earth, Wind & Fire"])      # never split
        self.assertEqual(ids.search_artists("Tyler, the Creator"), ["Tyler, the Creator"])
        self.assertEqual(ids.search_artists("Beyoncé"), ["Beyoncé"])                            # accents are Latin
        self.assertEqual(ids.search_artists("福居良 Ryo Fukui"), ["福居良 Ryo Fukui", "Ryo Fukui"])

    def test_discogs_artist_discography(self):
        a = album("Eliza", "Live at RAK", ORIGINAL[:6])
        rel = {"title": "Live At RAK", "artists": [{"name": "Eliza (26)"}],
               "tracklist": [{"title": t, "duration": f"{n // 60}:{n % 60:02d}", "position": str(i + 1)}
                             for i, (t, n, _) in enumerate(ORIGINAL[:6])]}
        site = FakeSite([("'type': 'artist'", {"results": [{"id": 1, "title": "Eliza (26)"}, {"id": 2, "title": "Elizabeth"}]}),
                         ("database/search", {"results": []}),
                         ("artists/1/releases", {"releases": [
                             {"id": 70, "type": "release", "role": "Main", "title": "Live At RAK"},
                             {"id": 71, "type": "release", "role": "Appearance", "title": "Live at RAK"}]}),
                         ("releases/70", rel)])
        r, _ = ids.Discogs(site).identify(a, {})
        self.assertEqual((r["id"], r["rung"]), (70, "artist discography"))

    def test_discography_of_an_artist_already_known(self):
        a = album("Eliza", "Live at RAK", ORIGINAL[:6])
        rel = {"title": "Live At RAK", "artists": [{"name": "Eliza (26)"}],
               "tracklist": [{"title": t, "duration": f"{n // 60}:{n % 60:02d}", "position": str(i + 1)}
                             for i, (t, n, _) in enumerate(ORIGINAL[:6])]}
        site = FakeSite([("database/search", {"results": []}),
                         ("artists/10886986/releases", {"releases": [
                             {"id": 70, "type": "release", "role": "Main", "title": "Live At RAK"}]}),
                         ("releases/70", rel)])
        r, _ = ids.Discogs(site).identify(a, {}, known_artists=[10886986])
        self.assertEqual((r["id"], r["rung"]), (70, "artist discography"))
        self.assertFalse(any("'type': 'artist'" in repr(p) for _, p in site.asked))   # no artist search needed

    def test_right_artist_among_same_names(self):
        a = album("Eliza", "Live at RAK", ORIGINAL[:6])
        rel = {"title": "Live At RAK", "artists": [{"name": "Eliza (26)"}],
               "tracklist": [{"title": t, "duration": f"{n // 60}:{n % 60:02d}", "position": str(i + 1)}
                             for i, (t, n, _) in enumerate(ORIGINAL[:6])]}
        site = FakeSite([("'type': 'artist'", {"results": [{"id": 3, "title": "Eliza (3)"},
                                                           {"id": 26, "title": "Eliza (26)"}]}),
                         ("database/search", {"results": []}),
                         ("artists/3/releases", {"releases": [{"id": 1, "role": "Main", "title": "Something Else"}]}),
                         ("artists/26/releases", {"releases": [
                             {"id": 70, "type": "release", "role": "Main", "title": "Live At RAK"},
                             {"id": 71, "type": "release", "role": "Main", "title": "A Sky Without Stars"}]}),
                         ("releases/70", rel)])
        r, _ = ids.Discogs(site).identify(a, {}, sibling_titles=["Live at RAK", "A Sky Without Stars"])
        self.assertEqual((r["id"], r["rung"]), (70, "artist discography"))


class Singles(unittest.TestCase):
    def test_spotted(self):
        self.assertTrue(ids.is_single(album("x", "Mother (Ultimate Mix)", [("Mother (Ultimate Mix)", 340, "")])))
        self.assertTrue(ids.is_single(album("x", "Falling out of Love", [("Falling out of Love", 200, ""),
                                                                         ("B-side", 180, "")])))
        self.assertFalse(ids.is_single(album("x", "XO", ORIGINAL)))
        self.assertFalse(ids.is_single(album("x", "Close to the Edge", [("Close to the Edge", 1100, ""),
                                                                        ("And You and I", 600, ""),
                                                                        ("Siberian Khatru", 540, "")])))  # 37 min

    def test_a_side_on_a_two_track_single(self):
        a = album("John Lennon", "Mother", [("Mother", 334, "")])
        r = release(["John Lennon"], "Mother", [("Mother", 335, []), ("Why", 180, [])])
        self.assertTrue(ids.check(a, r, strong=True)[0])
        # but never one song against an album that happens to contain it
        r2 = release(["John Lennon"], "Plastic Ono Band", [("Mother", 335, [])] + [(f"S{i}", 200, []) for i in range(10)])
        self.assertFalse(ids.check(a, r2, strong=True)[0])


class Titles(unittest.TestCase):
    def test_title_inside_another(self):
        want = [{"title": "Something / Blue Jay Way"}, {"title": "Help!"}]
        have = [{"title": "Help!"}, {"title": "Something / Blue Jay Way (Transition)"}]
        self.assertEqual(len(ids.by_title(want, have)), 2)

    def test_translated_titles(self):
        want = [{"title": "Making of a Cyborg"}]
        have = [{"title": "謡 Ⅰ = Making Of A Cyborg"}]
        self.assertEqual(len(ids.by_title(want, have)), 1)

    def test_each_track_used_once(self):
        want = [{"title": "Intro"}, {"title": "Intro"}]
        have = [{"title": "Intro"}]
        self.assertEqual(len(ids.by_title(want, have)), 1)

    def test_edition_year(self):
        album = {"album": "Close to the Edge (Deluxe Edition)",
                 "tracks": [{"title": "America (2003 Remaster)"}, {"title": "Siberian Khatru (2003 Remaster)"}]}
        self.assertEqual(ids.edition_year(album), 2003)
        self.assertIsNone(ids.edition_year({"album": "1999", "tracks": [{"title": "1999"}]}))


class FromDiscogs(unittest.TestCase):
    def test_musicbrainz_found_through_discogs_master(self):
        a = album("The Durutti Column", "The Best of Durutti Column", ORIGINAL)
        site = FakeSite([("discogs.com/release/5", {"relations": []}),
                         ("discogs.com/master/9", {"relations": [{"release_group": {"id": "RG"}}]}),
                         ("'release-group': 'RG'", {"releases": [{"id": "R-durutti"}]}),
                         ("release/R-durutti", mb_release("R-durutti", "The Best Of", "The Durutti Column", ORIGINAL)),
                         ("release-group/RG", {"relations": []})])
        r = ids.MusicBrainz(site, FakeSite([])).from_discogs(a, {"id": 5, "master": 9}, [])
        self.assertEqual((r["id"], r["rung"]), ("R-durutti", "discogs link"))


class SplitFolders(unittest.TestCase):
    def test_one_album_across_two_folders(self):
        d1 = album("Muse", "Hullabaloo", [("A", 100, "I1"), ("B", 100, "I2")], folder="d1",
                   tag_credits=[["Pat", "producer", "Producers", 1]])
        d2 = album("Muse", "Hullabaloo", [("C", 100, "I3")], folder="d2", barcode="123",
                   tag_credits=[["Kay", "composer", "Songwriters", 0]])
        for t in d2["tracks"]:
            t["disc"] = 2
        other = album("Muse", "Absolution", [("X", 100, "")], folder="d3", tag_credits=[])
        got = ids.merge_folders([d1, other, d2])
        self.assertEqual([a["key"] for a in got], ["Muse - Hullabaloo", "Muse - Absolution"])
        m = got[0]
        self.assertEqual([t["title"] for t in m["tracks"]], ["A", "B", "C"])
        self.assertEqual([t["i"] for t in m["tracks"]], [0, 1, 2])
        self.assertEqual(m["barcode"], "123")
        self.assertEqual(sorted(c[3] for c in m["tag_credits"]), [1, 2])     # Kay is on track C, now 2
        self.assertEqual(m["folders"], ["d1", "d2"])
