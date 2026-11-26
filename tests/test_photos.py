"""The key people's photo ladder (point 5), with the sites stood in for.

  python -m unittest tests.test_photos
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCRIPT = r'''
import sys, json, io
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import fixture
root = fixture.make()
import wiki
from wiki import ab, lookups
fixture.write(root)
lookups.time.sleep = lambda s: None
ab.time.sleep = lambda s: None
from PIL import Image
def pic(fmt):
    b = io.BytesIO(); Image.new("RGB", (400, 400), (90, 40, 20)).save(b, fmt); return b.getvalue()
JPG, WEBP = pic("JPEG"), pic("WEBP")

class R:
    def __init__(s, d=None, content=b"", code=200): s.d, s.content, s.status_code, s.ok = d, content, code, code == 200
    def json(s): return s.d
asked = []
class S:
    def get(s, url, params=None, headers=None, timeout=None):
        asked.append(url)
        if "commons" in url: return R(content=WEBP)
        if "api.discogs.com/artists/" in url: return R({"images": [{"type": "primary", "uri": "https://i.discogs.com/x.jpg"}]})
        if "i.discogs.com" in url: return R(content=JPG)
        if "theaudiodb" in url: return R({"artists": None})
        return R(code=404)
keys = {"discogs token": "t" * 40, "fanart key": ""}
people = {
  "commons": {"artist": "A", "mbid": "a" * 8, "discogs": None, "image": "http://commons.wikimedia.org/x.webp"},
  "discogs": {"artist": "B", "mbid": None, "discogs": 123, "image": ""},
  "none":    {"artist": "C", "mbid": "c" * 8, "discogs": None, "image": ""},
}
out = {}
for name, m in people.items():
    jpg = lookups.photo(m, S(), keys)
    out[name] = {"saved": bool(jpg and jpg.exists()), "source": m.get("photo_source"),
                 "tried": m.get("photo_tried"), "credit": lookups.photo_credit(m)}
n = len(asked)
lookups.photo(people["none"], S(), keys)               # asked again within 30 days: no requests
out["asked_again"] = len(asked) - n
from wiki.write import banner
from PIL import Image as I
b = banner(WEBP, False)
out["webp_banner"] = list(I.open(io.BytesIO(b)).size)
print(json.dumps(out))
'''


class Ladder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(SCRIPT)
        r = subprocess.run([sys.executable, f.name, str(HERE), str(HERE.parent)], capture_output=True, text=True)
        os.unlink(f.name)
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
        cls.r = json.loads(r.stdout.strip().split("\n")[-1])

    def test_commons_webp(self):
        """Mal Evans' case: Commons sends WebP, which is now taken, and cut to a banner."""
        self.assertTrue(self.r["commons"]["saved"])
        self.assertEqual(self.r["commons"]["credit"], "Photo from Wikimedia Commons")
        self.assertEqual(self.r["webp_banner"], [320, 132])

    def test_discogs_by_id(self):
        self.assertTrue(self.r["discogs"]["saved"])
        self.assertEqual(self.r["discogs"]["credit"], "Photo from Discogs")

    def test_none_remembered(self):
        self.assertFalse(self.r["none"]["saved"])
        self.assertTrue(self.r["none"]["tried"])
        self.assertEqual(self.r["asked_again"], 0)


if __name__ == "__main__":
    unittest.main()
