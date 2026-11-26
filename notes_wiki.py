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
import time
from pathlib import Path

import wiki                                    # noqa: F401  (liner/ on the path, settings file)
from wiki import ab, full, graph, lookups, pages, people, show, titles
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


TRACK_LOG = Path(__file__).resolve().parent / "Track notes log.txt"


def run_lookups(music, args, conf):
    """The copied scripts, in ipod-liner-notes' order, their files kept on this
    PC. track_notes.py asks only Wikidata, Wikipedia and Last.fm, so once the
    albums are identified it runs as a process of its own, alongside the three
    that ask MusicBrainz and Discogs (MusicBrainz allows one request a second
    in all, so those stay one after another). Its output goes to
    TRACK_LOG; the last lines are shown when it's done."""
    import subprocess
    STAGING.mkdir(parents=True, exist_ok=True)
    common = [str(music), "--ipod", str(STAGING)]
    stage = show.Stage("Identifying the albums (by ids.py, from ipod-liner-notes)")
    if ids.main([str(music)]):
        show.error("Identifying the albums stopped. Fix what it says and run again.")
        return False
    stage.done()
    root = Path(__file__).resolve().parent
    code = (f"import sys; sys.path.insert(0, {str(root)!r}); import wiki; import track_notes as t; "
            "sys.exit(t.main(sys.argv[1:]) or 0)")
    log = open(TRACK_LOG, "w", encoding="utf-8")
    tracks = subprocess.Popen([sys.executable, "-c", code] + common, cwd=str(root), stdout=log,
                              stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    show.info(f"Track notes are being looked up alongside, by track_notes.py (its output: {TRACK_LOG.name})")
    steps = [("Artists' bios and photos", ab.main), ("Album notes", ln.main), ("Credits", cr.main)]
    ok = True
    for n, (title, main) in enumerate(steps, 1):
        stage = show.Stage(f"{title} ({n} of {len(steps)}, by the scripts from ipod-liner-notes)")
        if main(common):
            show.error(f"{title} stopped. Fix what it says and run again.")
            ok = False
            break
        stage.done()
    stage = show.Stage("Track notes (by track_notes.py, alongside)")
    with show.Spinner("Waiting for it to finish"):
        code = tracks.wait()
    log.close()
    tail = [l for l in TRACK_LOG.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][-3:]
    for line in tail:
        show.info(line.strip())
    if code:
        show.error(f"Track notes stopped (see {TRACK_LOG.name}). Fix what it says and run again.")
        return False
    stage.done()
    return ok


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


BANNER_VERSION = 1      # raise when banner() changes, so every banner is cut again


def banner_source(folders, picture=None):
    """What a banner is cut from, as names, sizes and dates only, so an unchanged
    picture is known without opening it: the picture's file, or an album's
    cover files (cover, folder, front…), else its first audio file (embedded art)."""
    def mark(f):
        st = f.stat()
        return f"{f.name}:{st.st_size}:{st.st_mtime_ns}"
    if picture is not None:
        return f"{picture}|{mark(picture)}"
    files = sorted((f for d in folders for f in d.iterdir()), key=lambda f: str(f))
    covers = [f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png")
              and f.stem.lower().startswith(ab.COVER_NAMES)]
    if covers:
        return "|".join(f"{f.parent.name}/{mark(f)}" for f in covers)
    audio = [f for f in files if f.suffix.lower() in (".mp3", ".flac", ".m4a", ".ogg", ".opus")]
    return f"embedded|{mark(audio[0])}" if audio else ""


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

    began = time.time()
    online = not args.offline
    out = Path(args.out) / "Notes" if args.out else drive / "Notes"
    show.banner(f"  The notes wiki for PodBox{DOT}{'looking everything up' if online else 'offline: from what is saved'}"
                f"{DOT}writing to {out}" + (f"{DOT}dry run: nothing written" if args.dry_run else ""))

    if online:
        if not music.is_dir():
            show.error(f"Can't find {music}. Is the iPod plugged in?")
            return 1
        if not run_lookups(music, args, conf):
            return 1

    lib = ids.library().get("albums") or {}
    if not lib:
        show.error("No albums identified yet: run without --offline first.")
        return 1
    records = cr.load_records(lib)
    token = conf.get("discogs token") or os.environ.get("DISCOGS_TOKEN")
    mb = ids.Site(1.1) if online else None
    dc = ids.Site(1.1, {"Authorization": f"Discogs token={token}"}) if online and token else None
    if online and not token:
        show.info("No Discogs token: Discogs is skipped (see the settings file)")

    # -- what the pages are written from
    notes, tracks, bios, photos, discs = {}, {}, {}, {}, {}
    for k, a in lib.items():
        name = ab.safe_name(k)
        if name:
            notes[k] = ab.load_json(ln.CACHE / f"{name}.json")
        if a["artist"] not in bios:
            bios[a["artist"]], photos[a["artist"]] = bio_record(a["artist"], a.get("folder"))
    # the articles the Full sections and the chart line are read from (point 12)
    full_album, full_bio = full.setting(conf, "album pages") == "full", full.setting(conf, "bio pages") == "full"
    articles = [full.album_article(m) for m in notes.values()]
    if full_bio:
        articles += [full.bio_article(m) for m in bios.values()]
    articles = [t for t in articles if t]

    session = __import__("requests").Session()
    background = None
    if online:
        # In the background, Wikidata and Wikipedia only, one request at a time:
        # track write-ups found by title, then the albums' articles. They run
        # alongside the MusicBrainz and Discogs work that follows.
        import threading
        background = {"error": None}

        def wiki_work():
            s2 = __import__("requests").Session()
            try:
                titles.run(lib, s2, say=lambda s: None, quiet=True)
                full.fetch(articles, s2)
            except Exception as e:                          # reported, never fatal
                background["error"] = e
        background["thread"] = threading.Thread(target=wiki_work, daemon=True)
        background["thread"].start()
        show.info("Track write-ups by title and the albums' Wikipedia articles: looked up in the background")

    stage = show.Stage(f"Who's who, across {len(lib)} albums")
    with show.Spinner("Reading the credits and joining people across MusicBrainz and Discogs"):
        g = graph.build(lib, records, mb, dc, progress=lambda *a, **k: None)
    stage.done(f"{len(g.appear):,} people credited")

    # -- key people: a page if key on two albums or more, or if a bio is found
    per_album, keyed, _ = people.key_people(g, lib)
    lib_roots = people.library_artist_roots(g, lib)
    candidates = [r for r in sorted(keyed, key=str) if r not in lib_roots]
    look = argparse.Namespace(lastfm_key=key, discogs_token=token)
    stage = show.Stage(f"Key people: {len(candidates):,}")
    wanted = [(r, g.name.get(r, ""), graph.mb_id(g, r), graph.dc_id(g, r)) for r in candidates]
    wanted = [x for x in wanted if x[2] or x[3]]
    found = lookups.people(wanted, session, look, online=online)
    w = people.assign(g, lib, has_bio=lambda r: lookups.enough_bio(found.get(r)))
    sources = {}
    for m in found.values():
        if lookups.enough_bio(m):
            sources[m.get("bio_source")] = sources.get(m.get("bio_source"), 0) + 1
    with_page = sum(1 for r in w.root_page if r not in w.lib_root)
    stage.done(f"{with_page:,} get a page; bios: " +
               ", ".join(f"{n:,} {src}" for src, n in sorted(sources.items(), key=lambda x: -x[1])) or "none")

    artists = {}
    for tag in w.artist_page:
        roots = [r for r, t in w.lib_root.items() if t == tag]
        meta = bios.get(tag) or {}
        artists[tag] = {"mbid": next((m for m in map(lambda r: graph.mb_id(g, r), roots) if m), None)
                        or meta.get("mbid"),
                        "qid": meta.get("wikidata"),
                        "dcid": next((d for d in map(lambda r: graph.dc_id(g, r), roots) if d), None)}
    stage = show.Stage(f"Studio albums: {len(artists)} artists")
    discs = lookups.discographies(artists, session if online else None, mb, dc)
    stage.done(f"{sum(1 for v in discs.values() if v)} artists have a list; "
               f"the rest show the albums you own")

    # -- key people's photos, before the pages so each page can credit its photo (point 5)
    person_meta = {r: m for r, m in found.items() if m}
    if online and not args.no_banners:
        keys = lookups.photo_keys(conf)
        want = [r for r in w.root_page if r not in w.lib_root and person_meta.get(r)]
        stage = show.Stage(f"Key people's photos: {len(want):,} pages (Wikimedia Commons, then Discogs, by ID)")
        bar = show.Bar("Photos", len(want))
        got = {}
        for r in want:
            bar.update(note=g.name.get(r, ""))
            jpg = lookups.photo(person_meta[r], session, keys)
            if jpg:
                src = person_meta[r].get("photo_source") or "Wikimedia Commons"
                got[src] = got.get(src, 0) + 1
        bar.close()
        stage.done(", ".join(f"{n:,} {src}" for src, n in sorted(got.items(), key=lambda x: -x[1])) or "none")

    stage = show.Stage(f"Track write-ups by title, and Wikipedia articles: {len(articles)} "
                       f"(album pages {'full' if full_album else 'basic'}, bio pages {'full' if full_bio else 'basic'})")
    if background:
        with show.Spinner("Finishing the background lookups"):
            background["thread"].join()
        if background["error"]:
            show.warn(f"the background lookups stopped: {background['error']} (the next run carries on)")
    for k in lib:
        name = ab.safe_name(k)
        if name:
            tracks[k] = titles.merged(k, ab.load_json(tn.CACHE / "albums" / f"{name}.json"))
    stage.done(f"{sum(1 for t in articles if full.saved(t))} articles saved")

    stage = show.Stage("Making the pages")
    with show.Spinner("Linking names, credits and appearances"):
        folders = ab.load_json(ln.FOLDERS) or {}
        L = pages.Library(lib, records, g, w, notes, tracks, bios, person_meta, discs, folders)
        L.full_album, L.full_bio = full_album, full_bio
        every = pages.all_pages(L)
    kinds = {}
    for p in every:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    names = {"album": "albums", "credits": "credits", "appearances": "other appearances", "tracks": "tracks",
             "artist": "artists", "person": "key people"}
    stage.done(f"{len(every):,} pages: " + ", ".join(f"{kinds[k]:,} {names[k]}" for k in names if k in kinds))

    # -- onto the iPod
    stage = show.Stage(f"Writing to {out}" + (" (dry run: nothing written)" if args.dry_run else ""))
    wr = Writer(out, args.dry_run)
    banners, no_banner = 0, []
    bar = show.Bar("Pages and banners", len(every))
    for p in every:
        bar.update(note=p.place.split("/", 1)[-1])
        wr.put(p.place, ".md", p.text().encode("utf-8"))
        if args.no_banners:
            continue
        get, key, centre = None, None, False
        if p.kind == "album":
            folder = Path(lib[p.subject].get("folder") or "")
            if folder.is_dir():
                try:
                    folders = [folder] + [d for d in folder.iterdir() if d.is_dir()]
                    key = banner_source(folders)
                    get = lambda f=folders: ab.album_cover(f)[0]
                except OSError:
                    pass
            centre = True
        elif p.kind == "artist":
            jpg = photos.get(p.subject)
            if jpg and jpg.exists():
                key, get = banner_source([], jpg), jpg.read_bytes
                centre = (bios.get(p.subject) or {}).get("photo_source") == "album cover"
        elif p.kind == "person" and person_meta.get(p.subject):
            jpg = lookups.saved_person(graph.mb_id(g, p.subject), graph.dc_id(g, p.subject))[1]
            if jpg and Path(jpg).exists():
                key, get = banner_source([], Path(jpg)), Path(jpg).read_bytes
        if not get:
            continue
        key = f"{key}|{centre}|{BANNER_VERSION}" if key else None
        meta = wr.state.get(f"{p.place}.jpg") or {}
        if key and meta.get("from") == key and (wr.dir / f"{p.place}.jpg").exists():
            wr.counts["same"] += 1                      # the same picture as last time: not cut again
            banners += 1
            continue
        try:
            pic = get()
            if not pic:
                continue
            if wr.put(p.place, ".jpg", banner(pic, centre)) != "kept" and not args.dry_run and key:
                wr.state[f"{p.place}.jpg"]["from"] = key
            banners += 1
        except Exception as e:
            no_banner.append(f"{p.place}: {e}")
    bar.close(f"{len(every):,} pages, {banners:,} banners")
    wr.marker()
    wr.save()
    c = wr.counts
    for f in no_banner[:10]:
        show.warn(f"no banner: {f}")
    if len(no_banner) > 10:
        show.warn(f"and {len(no_banner) - 10} more without a banner")
    for f in wr.kept[:20]:
        show.warn(f"kept as you left it: {f}")
    if len(wr.kept) > 20:
        show.warn(f"and {len(wr.kept) - 20} more kept as you left them")
    stage.done(f"{c['written']:,} written or updated, {c['same']:,} unchanged, {c['kept']:,} kept as you left them")

    filled, left = titles.report(lib, Path(__file__).resolve().parent)
    show.info(f"Track write-ups found by title: {filled:,}; still from Last.fm: {left:,} "
              f"(both listed in \"{titles.REPORT}\")")

    for names in getattr(w, "case_clashes", []):
        show.warn(f"{' and '.join(repr(n) for n in names)} are different artists to MusicBrainz, but the "
                  f"iPod can't tell their names apart, so they share one page: check {w.artist_page[names[0]]}")
    print()
    show.good(show.bold(f"Done in {show.clock(time.time() - began)}. ") +
              (f"The wiki is in {out}." if not args.dry_run else "Dry run: nothing was written."))
    return 0


DOT = "  \u00b7  "


if __name__ == "__main__":
    sys.exit(main())
