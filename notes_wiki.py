"""
notes_wiki.py -- writes the notes wiki onto the iPod.

A page for every artist and album in your library, its credits, its
tracks' notes, the people who appear on other albums of yours, and the key
people who made it, all linked to one another, in /Notes for the PodBox
Liner Notes and Biographies viewer.

It runs in two halves:

1. The lookups, by the scripts copied from ipod-liner-notes (liner/):
   which release each album is, artists' bios and photos, album notes,
   track notes and credits. They save what they find on this PC and write
   their own files into a folder on this PC, never onto the iPod. Then this
   project's own: each artist's studio albums, and key people's bios.
2. The pages, from what was saved, written into the iPod's /Notes, with
   /Notes/.notes-wiki, which tells the viewer the wiki was written by a
   program.

Usage:
  python notes_wiki.py                 lookups, then pages
  python notes_wiki.py --offline       pages only, from what's saved
  python notes_wiki.py --dry-run       says what it would write, writes nothing
  python notes_wiki.py --out FOLDER    writes the pages there, not onto the iPod
  python notes_wiki.py --music FOLDER  the music folder, if not the settings file's
"""
import argparse
import os
import sys
from pathlib import Path

import wiki                                    # noqa: F401  (liner/ on the path, settings file)
from wiki import ab, graph, lookups, pages, people
from wiki.write import Writer, banner
import credits as cr
import ids
import liner_notes as ln
import track_notes as tn

STAGING = lookups.CACHE / "liner files"        # where the copied scripts' own files go


def settings():
    conf = ab.settings()
    drive = (conf.get("ipod drive") or "G:").rstrip("\\/")
    if len(drive) == 1:
        drive += ":"
    music = conf.get("music folder", "").rstrip("\\/") or f"{drive}\\Music"
    return conf, Path(drive + "\\"), Path(music)


def run_lookups(music, args, conf):
    """The copied scripts, in ipod-liner-notes' order, their files kept on this PC."""
    STAGING.mkdir(parents=True, exist_ok=True)
    common = [str(music), "--ipod", str(STAGING)]
    steps = [("Identifying the albums", ids.main, [str(music)]),
             ("Artists' bios and photos", ab.main, common),
             ("Album notes", ln.main, common),
             ("Track notes", tn.main, common),
             ("Credits", cr.main, common)]
    for title, main, argv in steps:
        print(f"\n== {title}")
        if main(argv):
            print(f"{title} stopped. Fix what it says and run again.")
            return False
    return True


def bio_record(tag, folder):
    """artist_bios.py's saved record for an album artist, found by the names
    it files them under: the album artist, else the artist's folder."""
    names = [ab.clean_artist(tag)]
    if folder:
        f = Path(folder)
        names.append(ab.clean_artist(f.parent.name))
        if " - " in f.name:
            names.append(ab.clean_artist(f.name.split(" - ", 1)[0]))
    for n in dict.fromkeys(names):
        name = ab.safe_name(n)
        meta = ab.load_json(ab.CACHE / f"{name}.json") if name else None
        if meta:
            return meta, ab.CACHE / f"{name}.jpg"
    return None, None


def lastfm_key(conf):
    """The Last.fm key: the settings file's, saved where the copied scripts
    read it (art_fetch.py's credentials file), else the one already there."""
    key = conf.get("lastfm key", "").strip()
    creds = ab.af.load_credentials()
    if key and key != creds.lastfm_api_key:
        creds.lastfm_api_key = key
        ab.af.save_credentials(creds)
    return creds.lastfm_api_key or None


def main(argv=None):
    conf, drive, music = settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--music", help="the music folder (default: from the settings file)")
    ap.add_argument("--offline", action="store_true", help="no lookups: pages from what's saved")
    ap.add_argument("--dry-run", action="store_true", help="write nothing, say what would be written")
    ap.add_argument("--out", help="the folder to write Notes into (default: the iPod)")
    ap.add_argument("--no-banners", action="store_true", default=not ab.setting_on(conf, "banners", True))
    args = ap.parse_args(argv)
    if args.music:
        music = Path(args.music)
    key = lastfm_key(conf)

    if not args.offline:
        if not music.is_dir():
            print(f"Can't find {music}. Is the iPod plugged in?")
            return 1
        if not run_lookups(music, args, conf):
            return 1

    lib = ids.library().get("albums") or {}
    if not lib:
        print("No albums identified yet: run without --offline first.")
        return 1
    records = cr.load_records(lib)
    online = not args.offline
    token = conf.get("discogs token") or os.environ.get("DISCOGS_TOKEN")
    mb = ids.Site(1.1) if online else None
    dc = ids.Site(1.1, {"Authorization": f"Discogs token={token}"}) if online and token else None
    print(f"\n== Who's who, across {len(lib)} albums")
    g = graph.build(lib, records, mb, dc)

    # -- key people: a page if key on two albums or more, or if a bio is found
    per_album, keyed, _ = people.key_people(g, lib)
    lib_roots = people.library_artist_roots(g, lib)
    candidates = [r for r in sorted(keyed, key=str) if r not in lib_roots]
    session = __import__("requests").Session()
    look = argparse.Namespace(lastfm_key=key, discogs_token=token)
    print(f"\n== Key people: {len(candidates)}")
    wanted = [(r, g.name.get(r, ""), graph.mb_id(g, r), graph.dc_id(g, r)) for r in candidates]
    wanted = [x for x in wanted if x[2] or x[3]]
    found = lookups.people(wanted, session, look, online=online)
    w = people.assign(g, lib, has_bio=lambda r: lookups.enough_bio(found.get(r)))

    # -- what the pages are written from
    notes, tracks, bios, photos, discs = {}, {}, {}, {}, {}
    for k, a in lib.items():
        name = ab.safe_name(k)
        if name:
            notes[k] = ab.load_json(ln.CACHE / f"{name}.json")
            tracks[k] = ab.load_json(tn.CACHE / "albums" / f"{name}.json")
        if a["artist"] not in bios:
            bios[a["artist"]], photos[a["artist"]] = bio_record(a["artist"], a.get("folder"))
    for tag in w.artist_page:
        mbids = [graph.mb_id(g, r) for r, t in w.lib_root.items() if t == tag]
        mbid = next((m for m in mbids if m), None) or (bios.get(tag) or {}).get("mbid")
        if mbid:
            discs[tag] = lookups.discography(mbid, mb)
    folders = ab.load_json(ln.FOLDERS) or {}
    person_meta = {r: m for r, m in found.items() if m}
    L = pages.Library(lib, records, g, w, notes, tracks, bios, person_meta, discs, folders)
    every = pages.all_pages(L)

    # -- onto the iPod
    out = Path(args.out) / "Notes" if args.out else drive / "Notes"
    print(f"\n== Writing {len(every)} pages to {out}" + (" (dry run: nothing written)" if args.dry_run else ""))
    wr = Writer(out, args.dry_run)
    banners = 0
    for p in every:
        wr.put(p.place, ".md", p.text().encode("utf-8"))
        if args.no_banners:
            continue
        pic, centre = None, False
        if p.kind == "album":
            a = lib[p.subject]
            folder = Path(a.get("folder") or "")
            if folder.is_dir():
                try:
                    pic = ab.album_cover([folder] + [d for d in folder.iterdir() if d.is_dir()])[0]
                except OSError:
                    pic = None
            centre = True
        elif p.kind == "artist":
            jpg = photos.get(p.subject)
            if jpg and jpg.exists():
                pic = jpg.read_bytes()
                centre = (bios.get(p.subject) or {}).get("photo_source") == "album cover"
        elif p.kind == "person" and person_meta.get(p.subject):
            jpg = lookups.photo(person_meta[p.subject], session) if online else \
                lookups.saved_person(graph.mb_id(g, p.subject), graph.dc_id(g, p.subject))[1]
            if jpg and Path(jpg).exists():
                pic = Path(jpg).read_bytes()
        if pic:
            try:
                wr.put(p.place, ".jpg", banner(pic, centre))
                banners += 1
            except Exception as e:
                print(f"  {p.place}: no banner ({e})")
    wr.marker()
    wr.save()
    c = wr.counts
    print(f"Pages and banners written or updated: {c['written']}, unchanged: {c['same']}, "
          f"kept as you left them: {c['kept']}. Banners: {banners}.")
    for f in wr.kept[:20]:
        print(f"  kept: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
