"""
Offline checks for the cases real runs have tripped on. Nothing here touches
the network: Wikidata items are cut down from real replies (November 2026).

  python -m unittest discover tests
"""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())

import artist_bios as ab          # noqa: E402
import liner_notes as ln          # noqa: E402
import translate as tr            # noqa: E402


def item(q, label, desc, p31, enwiki=None, date=None, sitelinks=()):
    links = {f"{s}wiki": {"title": t} for s, t in sitelinks}
    if enwiki:
        links["enwiki"] = {"title": enwiki}
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": x}}}} for x in p31]}
    if date:
        claims["P577"] = [{"mainsnak": {"datavalue": {"value": {"time": f"+{date}-01-01T00:00:00Z"}}}}]
    return {"id": q, "labels": {"en": {"value": label}} if label else {},
            "descriptions": {"en": {"value": desc}}, "claims": claims, "sitelinks": links}


def info(album, tracks=10, year=""):
    return {"album": album, "artist": "x", "orig_year": "", "tag_year": year, "label": "",
            "tracks": tracks, "minutes": None, "folder_artist": "x"}


class WhichItem(unittest.TestCase):
    def test_album_not_song(self):
        song = item("Q2707288", "Both Sides Now", "original song by Joni Mitchell", ["Q105543609"], "Both Sides, Now", 1966)
        album = item("Q4992532", "Both Sides Now", "2000 studio album by Joni Mitchell", ["Q482994"],
                     "Both Sides Now (Joni Mitchell album)", 2000)
        self.assertEqual(ln.pick_item([song, album], info("Both Sides Now", 12, "2000"))["id"], "Q4992532")

    def test_album_not_video(self):
        video = item("Q1766234", "Rage Against the Machine", "video by Rage Against the Machine",
                     ["Q482994"], "Rage Against the Machine (video)", 1997)
        debut = item("Q540943", None, "1992 debut studio album by Rage Against the Machine", ["Q482994"],
                     "Rage Against the Machine (album)", 1992)
        self.assertIn("rageagainstthemachine", ln.item_names(debut))
        self.assertEqual(ln.pick_item([video, debut], info("Rage Against The Machine", 10, "1992"))["id"], "Q540943")

    def test_single_only_for_a_short_folder(self):
        single = item("Q7783752", "They Reminisce Over You", "1992 single by Pete Rock & CL Smooth", ["Q134556"])
        self.assertIsNone(ln.pick_item([single], info("They Reminisce Over You", 12)))
        self.assertEqual(ln.pick_item([single], info("They Reminisce Over You", 3))["id"], "Q7783752")

    def test_editions_and_tracks_refused(self):
        edition = item("Q61126804", "Help!", "1965 UK LP by the Beatles; first edition", ["Q108352648"])
        track = item("Q60607942", "Help!", "vocal track by The Beatles", ["Q55850593"])
        self.assertIsNone(ln.pick_item([edition, track], info("Help!", 14)))


class Guess(unittest.TestCase):
    def test_song_article_refused_for_an_album(self):
        lead = ('"They Reminisce Over You (T.R.O.Y.)" is a song by Pete Rock & CL Smooth, from their '
                "debut album Mecca and the Soul Brother, released as a single in 1992.")
        i = dict(info("They Reminisce Over You", 13), artist="Pete Rock & C.L. Smooth")
        reply = mock.Mock(ok=True, json=lambda: {"query": {"search": []}})
        with mock.patch.object(ab, "wiki_get", return_value=reply), \
                mock.patch.object(ln, "wiki_summaries", return_value={"They Reminisce Over You": lead}):
            self.assertEqual(ln.guess_title(i, None), (None, False))
            i["tracks"] = 2
            self.assertEqual(ln.guess_title(i, None), ("They Reminisce Over You", False))


    def test_guessed_article_gives_the_year(self):
        info = {"album": "Axis: Bold As Love", "artist": "Jimi Hendrix", "tracks": 13,
                "label": "", "orig_year": "", "tag_year": "2010", "folder_artist": "Jimi Hendrix"}
        item = {"id": "Q1", "claims": {"P577": [{"mainsnak": {"datavalue": {"value": {
            "time": "+1967-12-01T00:00:00Z"}}}}]}}
        found = {}
        args = mock.Mock(translator=None, lastfm_key=None)
        with mock.patch.object(ln, "release_group", return_value=None), \
                mock.patch.object(ln, "guess_title", return_value=("Axis: Bold as Love", False)), \
                mock.patch.object(ln, "english_notes", return_value=(["text"], "wikipedia")), \
                mock.patch.object(ln, "title_item", return_value=item), \
                mock.patch.object(ln, "wd_label", return_value=""):
            ln.find_notes(info, {}, None, args, found)
        self.assertEqual(ln.release_year(info, found), "1967")


class Text(unittest.TestCase):
    def test_quotes_kept(self):
        self.assertEqual(ab.trim_bio('"Both Sides, Now" is a song by Joni Mitchell.'),
                         '"Both Sides, Now" is a song by Joni Mitchell.')
        self.assertEqual(ab.trim_bio('Kludge called it "full of passion and atmosphere."'),
                         'Kludge called it "full of passion and atmosphere."')
        self.assertEqual(ab.trim_bio('"A stray quote at the start'), "A stray quote at the start")

    def test_colon_ending_dropped(self):
        self.assertEqual(ab.trim_bio("It was praised. PopMatters gave it 6/10, stating:"), "It was praised.")

    def test_invisible_characters(self):
        self.assertEqual(ab.clean_bio("Blind‌ Faith‍"), "Blind Faith")

    def test_scores(self):
        box = ("{{Music ratings\n| rev1 = AllMusic\n| rev1Score = {{Rating|4.5|5}}|\n"
               "| rev2 = Rolling Stone\n| rev2Score = (not rated)\n| rev3 = The Quietus\n"
               "| rev3Score = (favourable)\n| rev4 = Tom Hull\n| rev4Score = B+ ()\n}}")
        self.assertEqual(ln.scores(box), ["AllMusic 4.5/5", "The Quietus favourable", "Tom Hull B+"])

    def test_reception_skips_sales(self):
        text = ("Lead.\n\n== Release and reception ==\n" + "It debuted at number one on the chart and sold "
                "many copies in its first week, the band's best start so far by some way.\n"
                "Critics praised it: Pitchfork's reviewer called it the band's best record yet, and it "
                "holds a Metacritic score of 87 out of 100.\n")
        self.assertTrue(ln.reception(text).startswith("Critics praised"))

    def test_labels(self):
        self.assertEqual(ln.clean_label("https://musicriders.blogspot.com/"), "")
        self.assertEqual(ln.clean_label("not on label"), "")
        self.assertEqual(ln.clean_label("Warp"), "Warp")

    def test_plain_title(self):
        self.assertEqual(ln.clean_title("Kid A [Deluxe Edition]"), "Kid A")


class Years(unittest.TestCase):
    def test_order(self):
        i = info("Axis: Bold as Love", 13, "2010")
        self.assertEqual(ln.release_year(i, {"wd_year": "1967", "rg_year": "1968"}), "1967")
        i["orig_year"] = "1967"
        self.assertEqual(ln.release_year(i, {}), "1967")
        i["orig_year"] = ""
        self.assertEqual(ln.release_year(i, {}), "2010")


class Names(unittest.TestCase):
    def test_long_name_fits(self):
        name = "⣎⡇ꉺლ༽இ•̛)ྀ◞ ༎ຶ ༽ৣৢ؞ৢ؞ؖ ꉺლ - ʅ" + "͡" * 40 + "(̸̢̛̼̞̭͋ͅ) ҉ ͡ ͞ ͞ ͞ ҉● ࿀ ● ࿀ ●" + " ⃝" * 30
        self.assertGreater(len(name.encode()), 230)
        fitted = ab.safe_name(name)
        self.assertTrue(fitted and len(fitted.encode()) <= 230)

    def test_ordinary_names_untouched(self):
        self.assertEqual(ab.safe_name("The Notorious B.I.G."), "The Notorious B.I.G")
        self.assertEqual(ab.safe_name("AC/DC - Back in Black"), "AC_DC - Back in Black")


class Languages(unittest.TestCase):
    def test_detection(self):
        ja = "「Azalea」（アザレア）は、日本のシンガーソングライター・米津玄師の楽曲。"
        self.assertTrue(tr.needs_translation(ja, "ja"))
        self.assertFalse(tr.needs_translation("This album was released in 2010 by the band on their own label.", "ja"))
        self.assertTrue(tr.needs_translation("Es el primer álbum de estudio del músico asturiano Nacho Vegas, "
                                             "publicado en 2001 por la discográfica Limbo Starr.", "es"))
        self.assertFalse(tr.needs_translation("The album was released by the band in 2001 and it was "
                                              "recorded in Gijón with their friends.", "es"))

    def test_artist_language(self):
        def claim(*ids):
            return [{"mainsnak": {"datavalue": {"value": {"id": i}}}} for i in ids]
        self.assertEqual(tr.artist_language({"claims": {"P495": claim("Q17")}}), "ja")
        self.assertEqual(tr.artist_language({"claims": {"P1412": claim("Q5287"), "P27": claim("Q17")}}), "ja")
        self.assertIsNone(tr.artist_language({"claims": {"P27": claim("Q145")}}))
        self.assertIsNone(tr.artist_language({"claims": {}}))


class FakeReply:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.ok = status, data, 200 <= status < 300

    def json(self):
        return self._data


class Translation(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_cached_and_refused(self):
        session = mock.Mock()
        session.post.return_value = FakeReply(200, {"translations": [{"text": "Azalea is a song."}]})
        t = tr.Translator("abc:fx", self.dir / "t.json", session)
        self.assertEqual(t.translate(["アザレアは楽曲。"], "ja"), ["Azalea is a song."])
        self.assertIn("api-free.deepl.com", session.post.call_args[0][0])
        t2 = tr.Translator("abc:fx", self.dir / "t.json", session)
        self.assertEqual(t2.translate(["アザレアは楽曲。"], "ja"), ["Azalea is a song."])
        self.assertEqual(session.post.call_count, 1)                 # the second came from the file
        session.post.return_value = FakeReply(456)
        self.assertIsNone(t2.translate(["別の文。"], "ja"))
        self.assertFalse(t2)                                         # off for the rest of the run

    def test_no_key_no_translation(self):
        self.assertFalse(tr.Translator("", self.dir / "t.json"))

    def test_foreign_notes(self):
        extract = ("「Azalea」（アザレア）は、日本のシンガーソングライター・米津玄師の楽曲。配信限定シングルとして"
                   "Sony Music Labelsより2024年11月18日にリリースされた。\n\n\n== 背景と制作 ==\n"
                   "「Azalea」は、2024年11月14日に配信が開始したNetflixシリーズ『さよならのつづき』の主題歌として"
                   "書き下ろされた。共同編曲にはYaffleが参加している。米津玄師はインタビューにて語っている。")
        found = {"ent": item("Q132454568", "Azalea", "2024 Kenshi Yonezu single", ["Q134556"],
                             sitelinks=[("ja", "Azalea (米津玄師の曲)")])}
        translator = mock.Mock()
        translator.translate.side_effect = lambda paras, lang: [f"[en] {len(p)}" for p in paras]
        with mock.patch.object(ln, "wiki_article", return_value=(extract, "")):
            paras, source = ln.foreign_notes(found, "ja", None, translator)
        self.assertEqual(source, "wikipedia (ja, translated)")
        self.assertEqual(len(translator.translate.call_args[0][0]), 2)      # short lead + next section
        self.assertRegex(paras[-1], r'^# Machine-translated excerpts from the Japanese Wikipedia article, '
                                    r"CC BY-SA 4\.0, retrieved ")


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_damaged_record_is_absent(self):
        p = self.dir / "a.json"
        p.write_text('{"half": ', encoding="utf-8")
        self.assertIsNone(ab.load_json(p))
        ab.save_json(p, {"ok": 1})
        self.assertEqual(ab.load_json(p), {"ok": 1})
        self.assertFalse((self.dir / "a.json.tmp").exists())

    def test_your_edits_kept(self):
        p, meta = self.dir / "x.txt", {}
        self.assertEqual(ab.write_if_ours(p, b"one", meta, "sha"), "written")
        self.assertEqual(ab.write_if_ours(p, b"one", meta, "sha"), "same")
        p.write_bytes(b"mine")
        self.assertEqual(ab.write_if_ours(p, b"two", meta, "sha"), "kept")

    def test_disc_folders_and_reuse(self):
        album = self.dir / "Artist" / "Album"
        for d in ("CD1", "CD2"):
            (album / d).mkdir(parents=True)
            (album / d / "01.mp3").write_bytes(b"")
        self.assertEqual(len(ln.album_tracks(album)), 2)
        seen = {str(album): {"sig": ln.signature(ln.album_tracks(album)),
                             "info": {"album": "Album", "artist": "Artist", "orig_year": "", "tag_year": "1999",
                                      "label": "", "tracks": 2}}}
        got = ln.album_info(album, "Artist", seen)                    # reused: the files are empty
        self.assertEqual((got["album"], got["tracks"]), ("Album", 2))

    def test_artist_photo_last_resort(self):
        album = self.dir / "Band" / "2001 - Record"
        album.mkdir(parents=True)
        self.assertIsNone(ab.artist_photo([album], "Band"))
        photo = self.dir / "Band" / "folder.jpg"
        photo.write_bytes(b"photo")
        self.assertEqual(ab.artist_photo([album], "Band"), b"photo")
        flat = self.dir / "Band - Other"                       # no artist folder of its own
        flat.mkdir()
        self.assertIsNone(ab.artist_photo([flat], "Band"))
        with mock.patch.object(ab.af, "is_standin", return_value=True):   # artist_fallback's cover
            self.assertIsNone(ab.artist_photo([album], "Band"))


class Credits(unittest.TestCase):
    def test_lines(self):
        day = "2026-11-04"
        self.assertEqual(tr.credit("wikipedia", title="OK Computer", part="excerpts", date=day),
                         '# Excerpts from the Wikipedia article "OK Computer", CC BY-SA 4.0, '
                         'retrieved 4 Nov 2026')
        self.assertEqual(tr.credit("wikipedia", title="Radiohead", date=day),
                         '# From the introduction to the Wikipedia article "Radiohead", CC BY-SA 4.0, '
                         'retrieved 4 Nov 2026')
        self.assertEqual(tr.credit("wikipedia", lang="ja", title="青葉市子", date=day),
                         '# Machine-translated from the introduction to the Japanese Wikipedia article, '
                         'CC BY-SA 4.0, retrieved 4 Nov 2026')
        self.assertEqual(tr.credit("lastfm", date=day), "# From Last.fm, CC BY-SA, retrieved 4 Nov 2026")
        self.assertEqual(tr.credit("lastfm", lang="ja", date=day),
                         "# Machine-translated from Last.fm (Japanese), CC BY-SA, retrieved 4 Nov 2026")
        self.assertEqual(tr.credit("facts", date=day), "")
        self.assertTrue(tr.credit("discogs").startswith("# From Discogs, retrieved "))


if __name__ == "__main__":
    unittest.main()
