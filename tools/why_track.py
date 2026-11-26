"""why_track.py -- why a track's write-up came from Last.fm, not Wikipedia.
Reads only: it asks Wikidata and Wikipedia, and writes nothing.

track_notes.py (copied from ipod-liner-notes) finds an album's songs only
from the album's Wikidata item: its track list (P658) and the songs that
say they are part of it (P361). It asks Last.fm about a track in two cases
only, so a Last.fm write-up means one of:

  A  the album has no Wikidata item: every track on it went to Last.fm
  B  the album's item names the song, but the song has no English article
  C  the song has an English article, but it failed the checks (too short,
     a list of other meanings, or its opening doesn't name the artist or
     album); the reason isn't kept, so it's worked out again here

A track the album's item doesn't name gets nothing at all, not Last.fm.

For each, it then asks Wikidata the question the planned title fallback
would: a song of this title performed by this artist (P175), and whether
its article would pass the same checks. With --unlisted it asks that for
every track left with no write-up on an album that has a Wikidata item,
too: what the fallback would add.

Usage:
  python tools/why_track.py                          every Last.fm track
  python tools/why_track.py "The Beatles" "All My Loving"
  python tools/why_track.py --offline                causes from what's saved only
  python tools/why_track.py --unlisted               and the fallback's gain
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki                                            # noqa: E402,F401  (liner/ on the path)
from wiki import ab                                    # noqa: E402
import ids                                             # noqa: E402
import liner_notes as ln                               # noqa: E402
import track_notes as tn                               # noqa: E402
from credits import fold                               # noqa: E402

CAUSES = {"A": "the album has no Wikidata item, so every track went to Last.fm",
          "B": "the album's Wikidata item names the song, but it has no English article",
          "C": "the song's English article failed the checks"}


def saved():
    """[(album key, album, its saved track notes)] for every album looked up."""
    lib = ids.library().get("albums") or {}
    out = []
    for k in sorted(lib):
        name = ab.safe_name(k)
        seen = ab.load_json(tn.CACHE / "albums" / f"{name}.json") if name else None
        out.append((k, lib[k], seen or {}))
    return out


def artist_q(album):
    return (ln.artist_ids(album["artist"]) or {}).get("wikidata")


def by_title(title, q_artist, session):
    """Songs of this title performed by the artist: [(item, English article)]."""
    if not q_artist:
        return []
    words = re.sub(r"[\"\\]", " ", tn.bare(title))
    r = ab.wiki_get(session, tn.WIKIDATA, {"action": "query", "list": "search", "srnamespace": 0,
                                            "srsearch": f"haswbstatement:P175={q_artist} {words}",
                                            "srlimit": 10, "format": "json"})
    if not r.ok:
        return None
    items = [h["title"] for h in (r.json().get("query") or {}).get("search") or []
             if re.fullmatch(r"Q\d+", h.get("title", ""))]
    songs = tn.song_items(items, session) if items else {}
    want = ids.clean_title(title)
    return [(q, tn.enwiki(e)) for q, e in songs.items()
            if want in (ids.clean_title(tn.bare(tn.enwiki(e))), ids.clean_title(tn.label(e)))]


def verdict(article, album, session):
    """'' if the article would be used, else why not."""
    intro = ln.wiki_summaries([article], session).get(article, "")
    why = tn.usable(intro, album["artist"], need=0, album=album["album"])
    if why:
        return why
    text, _ = tn.fill_out(intro, article, session)
    return tn.usable(text, album["artist"], album=album["album"])


def fallback(title, album, session, say):
    """What a title search finds; (found a usable article?, line)."""
    q = artist_q(album)
    if not q:
        return False, "the artist has no Wikidata item saved, so a title search can't be made"
    hits = by_title(title, q, session)
    if hits is None:
        return False, "Wikidata didn't answer"
    if not hits:
        return False, f"a title search finds no song of that title by {album['artist']} ({q})"
    for item, article in hits:
        if not article:
            say(f"      title search: {item}, no English article")
            continue
        why = verdict(article, album, session)
        if not why:
            return True, f"a title search finds {item}, \"{article}\": it would be used"
        say(f"      title search: {item}, \"{article}\": {why}")
    return False, "a title search finds the song, but nothing usable"


def album_item(album, session):
    """An album item by the artist with the album's title that ids.py didn't
    link, or ''."""
    q = artist_q(album)
    if not q:
        return ""
    words = re.sub(r"[\"\\]", " ", ids.plain_album(album["album"]))
    r = ab.wiki_get(session, tn.WIKIDATA, {"action": "query", "list": "search", "srnamespace": 0,
                                            "srsearch": f"haswbstatement:P175={q} {words}",
                                            "srlimit": 10, "format": "json"})
    if not r.ok:
        return ""
    items = [h["title"] for h in (r.json().get("query") or {}).get("search") or []
             if re.fullmatch(r"Q\d+", h.get("title", ""))]
    want = ids.clean_title(ids.plain_album(album["album"]))
    for item, e in (tn.song_items(items, session) if items else {}).items():
        if want in (ids.clean_title(tn.bare(tn.enwiki(e))), ids.clean_title(tn.label(e))):
            return f"{item} ({tn.enwiki(e) or tn.label(e)})"
    return ""


def cause(seen, t):
    if not seen.get("wikidata"):
        return "A"
    return "C" if t.get("article") else "B"


def one(artist, title, session, offline):
    hits = [(k, a, s, i) for k, a, s in saved() if fold(a["artist"]) == fold(artist)
            for i, (_, _, tt) in enumerate(a["tracks"]) if ids.clean_title(tt) == ids.clean_title(title)]
    if not hits:
        print(f"No track \"{title}\" by {artist} in the library ids.py saved.")
        return 1
    for k, a, seen, i in hits:
        t = (seen.get("tracks") or {}).get(str(i))
        print(f"\n{k}, track {a['tracks'][i][1]}: \"{a['tracks'][i][2]}\"")
        print(f"  album's Wikidata item: {seen.get('wikidata') or 'none'}"
              f"   artist's: {artist_q(a) or 'none saved'}")
        if not seen:
            print("  the album hasn't been looked up by track_notes.py")
            continue
        if not t:
            print("  no write-up, and not asked of Last.fm: the album's item doesn't name the song")
        else:
            print(f"  write-up from: {t.get('source') or 'nowhere'}"
                  + (f"; article: \"{t['article']}\"" if t.get("article") else ""))
            if t.get("why"):
                print(f"  saved reason: {t['why']}")
            if t.get("source", "").startswith("last.fm"):
                c = cause(seen, t)
                print(f"  cause {c}: {CAUSES[c]}")
                if c == "C" and not offline:
                    print(f"  the checks now say: {verdict(t['article'], a, session) or 'it would be used'}")
        if not offline and seen.get("wikidata"):
            songs = tn.song_items(tn.album_songs(seen["wikidata"], session), session)
            print(f"  the album's item names {len(songs)} songs" +
                  (": " + ", ".join(sorted(tn.enwiki(e) or tn.label(e) for e in songs.values()))[:600]
                   if songs else ""))
        if not offline and (not t or not t.get("source", "").startswith("wikipedia")):
            ok, line = fallback(a["tracks"][i][2], a, session, print)
            print(f"  {line}")
    return 0


def every(session, offline, unlisted):
    albums = saved()
    looked = sum(1 for _, _, s in albums if s)
    lastfm, empty = [], []
    for k, a, seen in albums:
        tracks = seen.get("tracks") or {}
        for i, t in tracks.items():
            if t.get("source", "").startswith("last.fm"):
                lastfm.append((k, a, seen, int(i), t))
        if seen.get("wikidata"):
            for i in range(len(a["tracks"])):
                t = tracks.get(str(i))
                if not t or not t.get("paras"):
                    empty.append((k, a, seen, i))
    sources = {}
    for _, _, seen in albums:
        for t in (seen.get("tracks") or {}).values():
            s = t.get("source") or "none"
            sources[s] = sources.get(s, 0) + 1
    print(f"{len(albums)} albums in the library, {looked} looked up by track_notes.py; "
          f"{sum(1 for _, _, s in albums if s.get('wikidata'))} with a Wikidata item.")
    print("Write-ups by source: " + ", ".join(f"{n} {s}" for s, n in sorted(sources.items(), key=lambda x: -x[1])))
    print(f"\n{len(lastfm)} tracks have a Last.fm write-up:")
    by = {}
    for row in lastfm:
        by.setdefault(cause(row[2], row[4]), []).append(row)
    for c in "ABC":
        print(f"  {c}: {len(by.get(c, [])):4}  {CAUSES[c]}")
    if offline:
        for c in "ABC":
            for k, a, seen, i, t in by.get(c, [])[:15]:
                print(f"    {c} {k}: \"{a['tracks'][i][2]}\"" + (f" ({t['article']})" if t.get("article") else ""))
        return 0
    found = {}
    a_albums = {k: a for k, a, *_ in by.get("A", [])}
    if a_albums:
        print(f"\nThe {len(a_albums)} albums with no Wikidata item: does Wikidata have one by title?")
        have = 0
        for k, a in sorted(a_albums.items()):
            item = album_item(a, session)
            have += bool(item)
            print(f"  {k}: " + (f"yes, {item}" if item else "no"))
        print(f"  {have} of {len(a_albums)} have an item ids.py didn't link")
    print("\nEach asked again (a few seconds a track):")
    for c in "ABC":
        for k, a, seen, i, t in by.get(c, []):
            title = a["tracks"][i][2]
            if c == "C":
                why = verdict(t["article"], a, session)
                print(f"  C {k}: \"{title}\" ({t['article']}): {why or 'would now be used'}")
                found[c] = found.get(c, 0) + (not why)
                continue
            ok, line = fallback(title, a, session, lambda s: None)
            found[c] = found.get(c, 0) + ok
            print(f"  {c} {k}: \"{title}\": {line}")
    print("\nWould a Wikipedia write-up be found instead of Last.fm's?")
    for c in "ABC":
        print(f"  {c}: {found.get(c, 0)} of {len(by.get(c, []))}")
    if unlisted:
        print(f"\n{len(empty)} tracks on albums with a Wikidata item have no write-up. A title search for each:")
        gain = 0
        for k, a, seen, i in empty:
            ok, line = fallback(a["tracks"][i][2], a, session, lambda s: None)
            if ok:
                gain += 1
                print(f"  {k}: \"{a['tracks'][i][2]}\": {line}")
        print(f"\nThe title fallback would add {gain} write-up(s) from Wikipedia to tracks that have none.")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artist", nargs="?")
    ap.add_argument("title", nargs="?")
    ap.add_argument("--offline", action="store_true", help="only what's saved: no requests")
    ap.add_argument("--unlisted", action="store_true", help="also every track with no write-up")
    args = ap.parse_args(argv)
    session = None if args.offline else __import__("requests").Session()
    if args.artist and args.title:
        return one(args.artist, args.title, session, args.offline)
    if args.artist:
        ap.error("give an artist and a title, or neither")
    return every(session, args.offline, args.unlisted)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
