"""Writing /Notes on the iPod.

- Every page and banner is written with artist_bios.write_if_ours(): a
  file is replaced only while it is still the one this script last wrote,
  so a page you edit is kept, and nothing is ever deleted.
- Banners are exactly 320 x 132, baseline JPEG, so the viewer draws them
  straight from the file (design point 11): an artist's photo cropped by
  artist_bios.make_banner() to keep faces whole, an album's a band across
  the middle of its cover.
- /Notes/.notes-wiki, empty, switches the viewer to scraper mode.
"""
import io

from PIL import Image, ImageOps

from . import ab
from .lookups import CACHE

W, H = 320, 132
STATE = CACHE / "written.json"
MARKER = ".notes-wiki"


def banner(picture, centre):
    """The banner cut from a picture's bytes."""
    keep = ab.BAN_MIN, ab.BAN_MAX
    ab.BAN_MIN = ab.BAN_MAX = H      # faces kept above the strip the page's name is set over
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(picture))).convert("RGB")
        faces = [] if centre else ab.find_faces_any_way_up(img)[0]
        cut, _ = ab.make_banner(img, faces, centre=centre)
    finally:
        ab.BAN_MIN, ab.BAN_MAX = keep
    if cut.size != (W, H):
        cut = ImageOps.fit(cut, (W, H), Image.LANCZOS)
    out = io.BytesIO()
    cut.save(out, "JPEG", quality=88, progressive=False, optimize=True)
    return out.getvalue()


class Writer:
    def __init__(self, notes_dir, dry_run=False):
        self.dir = notes_dir
        self.dry = dry_run
        self.state = ab.load_json(STATE) or {}
        self.counts = {"written": 0, "same": 0, "kept": 0}
        self.kept = []

    def put(self, place, ext, data):
        path = self.dir / f"{place}{ext}"
        meta = self.state.setdefault(f"{place}{ext}", {})
        if self.dry:
            res = "same" if path.exists() and ab.sha1(path) == __import__("hashlib").sha1(data).hexdigest() \
                else "written"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            res = ab.write_if_ours(path, data, meta, "sha1")
        self.counts[res] += 1
        if res == "kept":
            self.kept.append(f"{place}{ext}")
        return res

    def marker(self):
        path = self.dir / MARKER
        if not path.exists() and not self.dry:
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")

    def save(self):
        if not self.dry:
            CACHE.mkdir(parents=True, exist_ok=True)
            ab.save_json(STATE, self.state)
