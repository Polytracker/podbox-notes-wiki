"""check_banners.py -- checks the wiki's banners; reads only, changes nothing.

For every album page and person page in a wiki's Notes folder: is there a
banner beside it with exactly the page's name, and is it what the viewer
draws straight from the file (a JPEG of exactly 320 x 132, baseline, not
progressive)? A banner that fails isn't drawn from the file: the viewer
then falls back to its own, stretched from the art cache's square cover
(album pages), or shows none (people).

Usage:
  python tools/check_banners.py                 the iPod (G:\\Notes)
  python tools/check_banners.py FOLDER          a Notes folder elsewhere
"""
import sys
from pathlib import Path

PARTS = (" - Credits", " - Tracks", " - Tracks 1", " - Tracks 2", " - Tracks 3", " - Other Appearances")


def jpeg_kind(data):
    """'baseline', 'progressive', 'other JPEG' or 'not a JPEG', and (w, h)."""
    if data[:3] != b"\xff\xd8\xff":
        return "not a JPEG", None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return "other JPEG", None
        m = data[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        n = int.from_bytes(data[i + 2:i + 4], "big")
        if m in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return ("progressive" if m == 0xC2 else "baseline"), (w, h)
        if 0xC3 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            return "other JPEG", None
        i += 2 + n
    return "other JPEG", None


def check(notes):
    rows = {"album": [], "person": []}
    problems = []
    for kind, sub in (("album", "Albums"), ("person", "People")):
        folder = notes / sub
        if not folder.is_dir():
            continue
        for md in sorted(folder.glob("*.md")):
            if kind == "album" and md.stem.endswith(PARTS):
                continue
            jpg = md.with_suffix(".jpg")
            if not jpg.exists():
                rows[kind].append((md.stem, "no banner"))
                continue
            what, size = jpeg_kind(jpg.read_bytes())
            if what != "baseline" or size != (320, 132):
                why = what if what != "baseline" else f"{size[0]} x {size[1]}"
                rows[kind].append((md.stem, why))
                problems.append(f"{sub}/{jpg.name}: {why}")
            else:
                rows[kind].append((md.stem, "ok"))
    return rows, problems


def main(argv):
    notes = Path(argv[0]) if argv else Path("G:\\Notes")
    if not notes.is_dir():
        print(f"Can't find {notes}. Is the iPod plugged in?")
        return 1
    rows, problems = check(notes)
    print(f"Banners in {notes}\n")
    for kind, label in (("album", "Album pages"), ("person", "People pages")):
        r = rows[kind]
        ok = sum(1 for _, w in r if w == "ok")
        none = sum(1 for _, w in r if w == "no banner")
        print(f"  {label}: {len(r):,}; banner right: {ok:,}; no banner: {none:,}; "
              f"banner the viewer can't draw from the file: {len(r) - ok - none:,}")
    if problems:
        print("\nBanners the viewer can't draw from the file:")
        for p in problems:
            print(f"  {p}")
    else:
        print("\nEvery banner there is a 320 x 132 baseline JPEG with its page's exact name.")
    lone = [j.name for sub in ("Albums", "People") if (notes / sub).is_dir()
            for j in sorted((notes / sub).glob("*.jpg")) if not j.with_suffix(".md").exists()]
    if lone:
        print(f"\nBanners with no page of the same name ({len(lone)}):")
        for n in lone[:30]:
            print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
