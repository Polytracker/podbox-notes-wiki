"""The track title search (point 13), with Wikidata and Wikipedia stood in for.

  python -m unittest tests.test_titles
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCRIPT = r'''
import sys, json
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import fixture
root = fixture.make()
import wiki
from wiki import ab, titles
import track_notes as tn
fixture.write(root)
ab.time.sleep = lambda s: None
# Steely Dan's Wikidata item; Aja's item Q100 lists Black Cow by an entry with no article
meta = ab.load_json(ab.CACHE / "Steely Dan.json"); meta["wikidata"] = "Q1"
ab.save_json(ab.CACHE / "Steely Dan.json", meta)
ab.save_json(tn.CACHE / "albums" / f"{ab.safe_name('Steely Dan - Aja')}.json", {"wikidata": "Q100", "checked": 5,
    "tracks": {"0": {"paras": ["From Last.fm.", "# From Last.fm"], "source": "last.fm", "article": ""},
               "1": {"paras": ["Aja is a song.", "# From Wikipedia"], "source": "wikipedia", "article": "Aja (song)"}}})
LONG = " It was recorded in 1977 with session players, and is among the band's best-known songs." * 5

class R:
    def __init__(s, d): s.d, s.ok, s.status_code = d, True, 200
    def json(s): return s.d

def ent(label, article=None, p31="Q7366"):
    e = {"labels": {"en": {"value": label}}, "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": p31}}}}]}}
    if article:
        e["sitelinks"] = {"enwiki": {"title": article}}
    return e
ENTS = {"Q7": ent("Black Cow", "Black Cow (song)"), "Q8": ent("Aja", "Aja (album)", "Q482994"),
        "Q9": ent("Peg", "Peg (song)"), "Q300": ent("Gaucho", "Gaucho (album)", "Q482994"),
        "Q301": ent("Hey Nineteen", "Hey Nineteen")}
INTROS = {"Black Cow (song)": '"Black Cow" is a song by Steely Dan.' + LONG,
          "Peg (song)": "Peg is a 1977 song by someone else entirely." + LONG,
          "Hey Nineteen": '"Hey Nineteen" is a song by Steely Dan from Gaucho.' + LONG}
asked = []
def b(kind, item, label, article=""):
    row = {"artist": {"value": "http://www.wikidata.org/entity/Q1"},
           "item": {"value": "http://www.wikidata.org/entity/" + item},
           "kind": {"value": kind}, "label": {"value": label}}
    if article:
        row["article"] = {"value": "https://en.wikipedia.org/wiki/" + article.replace(" ", "_")}
    return row
CATALOGUE = [b("song", "Q7", "Black Cow", "Black Cow (song)"), b("song", "Q9", "Peg", "Peg (song)"),
             b("album", "Q8", "Aja", "Aja (album)"), b("album", "Q300", "Gaucho", "Gaucho (album)")]
class S:
    def post(s, url, data=None, headers=None, timeout=None):
        asked.append("sparql")
        assert "wd:Q1" in data["query"]
        return R({"results": {"bindings": CATALOGUE}})
    def get(s, url, params=None, headers=None, timeout=None):
        p = params or {}
        if p.get("list") == "search":
            asked.append("album songs" if "P361" in p["srsearch"] else "search")
            return R({"query": {"search": []}})
        if p.get("action") == "wbgetentities":
            if p.get("props") == "claims" and p["ids"] == "Q300":
                return R({"entities": {"Q300": {"claims": {"P658": [{"mainsnak": {"datavalue": {"value": {"id": "Q301"}}}}]}}}})
            if p.get("props") == "claims":
                return R({"entities": {}})
            return R({"entities": {q: ENTS.get(q, {}) for q in p["ids"].split("|")}})
        if p.get("prop") == "extracts":
            asked.append("extracts")
            out = [{"title": t, "extract": INTROS.get(t, "")} for t in p["titles"].split("|")]
            return R({"query": {"pages": out}})
        return R({})
lib = ab.load_json(__import__("ids").LIBRARY)["albums"]
titles.run(lib, S(), say=lambda s: None)
aja = titles.merged("Steely Dan - Aja", ab.load_json(tn.CACHE / "albums" / f"{ab.safe_name('Steely Dan - Aja')}.json"))
gau = titles.merged("Steely Dan - Gaucho", None)
untouched = ab.load_json(tn.CACHE / "albums" / f"{ab.safe_name('Steely Dan - Aja')}.json")
n = titles.report(lib, root)
print(json.dumps({"asked": asked, "aja": aja["tracks"], "gaucho": (gau or {}).get("tracks"), "untouched": untouched["tracks"]["0"],
                  "report": (root / titles.REPORT).read_text(), "counts": n,
                  "saved": ab.load_json(titles.SAVED / f"{ab.safe_name('Steely Dan - Aja')}.json")["tracks"]}))
'''


class TitleSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(SCRIPT)
        r = subprocess.run([sys.executable, f.name, str(HERE), str(HERE.parent)], capture_output=True, text=True)
        os.unlink(f.name)
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
        cls.r = json.loads(r.stdout.strip().split("\n")[-1])

    def test_lastfm_replaced(self):
        """Black Cow had a Last.fm write-up; its own song entry has an article."""
        t = self.r["aja"]["0"]
        self.assertEqual(t["source"], "wikipedia")
        self.assertEqual(t["article"], "Black Cow (song)")
        self.assertIn("is a song by Steely Dan", t["paras"][0])

    def test_wikipedia_kept(self):
        self.assertEqual(self.r["aja"]["1"]["article"], "Aja (song)")

    def test_album_of_the_same_name_refused(self):
        """A title track's only match is the album: not a song, not used."""
        self.assertNotIn("1", self.r["saved"])            # Aja had Wikipedia already: not searched
        self.assertNotIn("Aja (album)", json.dumps(self.r["aja"]))

    def test_checks_still_apply(self):
        """Peg's article is about someone else's song: refused, with the reason."""
        self.assertFalse(self.r["saved"]["3"]["paras"])
        self.assertIn("doesn't name the artist", self.r["saved"]["3"]["why"])
        self.assertIn("no song of that title", self.r["saved"]["2"]["why"])     # Deacon Blues

    def test_album_found_by_title(self):
        """Gaucho has no Wikidata item saved: found by title, its songs then as usual."""
        self.assertEqual(self.r["gaucho"]["1"]["article"], "Hey Nineteen")
        self.assertEqual(self.r["gaucho"]["1"]["how"], "album found by title")

    def test_saved_data_untouched(self):
        self.assertEqual(self.r["untouched"]["source"], "last.fm")

    def test_few_requests(self):
        """One Wikidata query for the artist, not a search a track; the
        articles' openings in one request."""
        self.assertEqual(self.r["asked"].count("sparql"), 1)
        self.assertEqual(self.r["asked"].count("search"), 0)
        self.assertEqual(self.r["asked"].count("album songs"), 1)    # only Gaucho, found by title
        self.assertEqual(self.r["asked"].count("extracts"), 1)

    def test_report(self):
        rep = self.r["report"]
        self.assertIn('Steely Dan - Aja: "Black Cow" from "Black Cow (song)" (title search)', rep)
        self.assertIn('Steely Dan - Gaucho: "Hey Nineteen" from "Hey Nineteen"', rep)
        self.assertEqual(self.r["counts"][1], 0)          # no Last.fm write-up left


if __name__ == "__main__":
    unittest.main()
