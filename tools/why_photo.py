"""why_photo.py -- why a people page has no banner photo. Reads only: it may
ask Wikidata, TheAudioDB, fanart.tv and Discogs, and writes nothing.

The wiki's people pages are of two kinds, with different photo ladders:
  library artists  art_fetch.py's photo (Last.fm, fanart.tv, TheAudioDB,
                   Deezer, MusicBrainz), saved by ipod-liner-notes
  key people       one source only: the picture (P18) on their Wikidata
                   item, found by their MusicBrainz ID

A key person's page without a banner is counted by cause:
  1  known only by a Discogs ID, so Wikidata is never asked
  2  Wikidata has no picture for them (or doesn't know the MusicBrainz ID)
  3  Wikidata has a picture, but the download failed and nothing is saved
  4  the photo is saved on this PC, but the page has no banner beside it
     (the banner wasn't cut, or the wiki on the iPod is older)

Online (the default) it then asks, for each key person without a photo,
what each source in the proposed ladder would give, by ID only: Wikidata
again, TheAudioDB and fanart.tv by MusicBrainz ID, Discogs by Discogs ID.

Usage:
  python tools/why_photo.py                       every people page on the iPod
  python tools/why_photo.py "Robert Smith"        one page, in detail
  python tools/why_photo.py --offline             causes from what's saved only
  python tools/why_photo.py --notes FOLDER        a Notes folder other than G:\\Notes
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notes_wiki as nw                                # noqa: E402
from wiki import ab, graph, lookups, pages, people     # noqa: E402
import credits as cr                                   # noqa: E402
import ids                                             # noqa: E402
import liner_notes as ln                               # noqa: E402
import track_notes as tn                               # noqa: E402

CAUSES = {1: "known only by a Discogs ID, so Wikidata is never asked",
          2: "Wikidata has no picture for them, or doesn't know their MusicBrainz ID",
          3: "Wikidata has a picture, but it wasn't downloaded",
          4: "the photo is saved on this PC, but the page has no banner"}


def build():
    """The wiki's people pages, as notes_wiki.py --offline makes them:
    [(place, kind, subject)], with what each was made from."""
    lib = ids.library().get("albums") or {}
    if not lib:
        print("No albums identified yet: run notes_wiki.py first.")
        return None
    records = cr.load_records(lib)
    print(f"Reading the credits of {len(lib)} albums, as the scraper does (a minute or so)...")
    g = graph.build(lib, records, None, None, progress=lambda *a, **k: None)
    _, keyed, _ = people.key_people(g, lib)
    roots = people.library_artist_roots(g, lib)
    wanted = [(r, g.name.get(r, ""), graph.mb_id(g, r), graph.dc_id(g, r))
              for r in sorted(keyed, key=str) if r not in roots]
    wanted = [x for x in wanted if x[2] or x[3]]
    found = lookups.people(wanted, None, None, online=False, say=lambda s: None)
    w = people.assign(g, lib, has_bio=lambda r: lookups.enough_bio(found.get(r)))
    notes, tracks, bios, photos = {}, {}, {}, {}
    for k, a in lib.items():
        name = ab.safe_name(k)
        if name:
            notes[k] = ab.load_json(ln.CACHE / f"{name}.json")
            tracks[k] = ab.load_json(tn.CACHE / "albums" / f"{name}.json")
        if a["artist"] not in bios:
            bios[a["artist"]], photos[a["artist"]] = nw.bio_record(a["artist"], a.get("folder"))
    person_meta = {r: m for r, m in found.items() if m}
    L = pages.Library(lib, records, g, w, notes, tracks, bios, person_meta, {}, ab.load_json(ln.FOLDERS) or {})
    out = []
    for p in pages.all_pages(L):
        if p.kind == "artist":
            out.append({"place": p.place, "kind": "artist", "name": p.subject,
                        "meta": bios.get(p.subject) or {}, "photo": photos.get(p.subject)})
        elif p.kind == "person":
            mbid, dcid = graph.mb_id(g, p.subject), graph.dc_id(g, p.subject)
            meta, jpg = lookups.saved_person(mbid, dcid)
            out.append({"place": p.place, "kind": "person", "name": g.name.get(p.subject, ""),
                        "mbid": mbid, "dcid": dcid, "meta": meta or {}, "photo": jpg})
    return out


def person_cause(p):
    if p["photo"] and p["photo"].exists():
        return 4
    if not p["mbid"]:
        return 1
    return 3 if (p["meta"].get("image") or "").startswith("http") else 2


# ---------------------------------------------------------------- the other sources, by ID
def key(name):
    conf = ab.settings()
    v = (conf.get(name) or "").strip()
    if not v and name == "fanart key":
        v = ab.af.load_credentials().fanart_api_key.strip()
    return v


def get_json(session, url, params=None, headers=None, gap=0.0):
    if gap:
        time.sleep(gap)
    try:
        r = session.get(url, params=params, headers={**ab.UA, **(headers or {})}, timeout=30)
    except ab.NET_ERRORS as e:
        return None, f"no answer ({type(e).__name__})"
    if not r.ok:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json(), ""
    except ValueError:
        return None, "not JSON"


def wikidata_now(mbids, session):
    return lookups.wikidata_by_mbid(sorted(set(mbids)), session) if mbids else {}


def audiodb(mbid, session):
    data, err = get_json(session, f"{ab.AUDIODB}artist-mb.php", {"i": mbid}, gap=2.1)  # 30 a minute
    if data is None:
        return None, err
    a = (data.get("artists") or [None])[0] or {}
    url = a.get("strArtistThumb") or a.get("strArtistFanart") or ""
    return (url or None), "" if url else "no picture"


def fanart(mbid, session, api_key):
    data, err = get_json(session, f"{ab.af.FANART_API}/{mbid}", {"api_key": api_key}, gap=0.3)
    if data is None:
        return None, "not known" if err == "HTTP 404" else err
    for kind in ("artistthumb", "artistbackground"):
        if data.get(kind):
            return data[kind][0].get("url"), ""
    return None, "no picture"


def discogs(dcid, session, token):
    data, err = get_json(session, f"{ids.DISCOGS}artists/{dcid}",
                         headers={"Authorization": f"Discogs token={token}"}, gap=1.1)
    if data is None:
        return None, err
    imgs = data.get("images") or []
    pick = next((i for i in imgs if i.get("type") == "primary"), imgs[0] if imgs else None)
    return (pick or {}).get("uri") or None, "" if pick else "no picture"


def download_works(url, session):
    try:
        r = ab.wiki_get(session, url.replace("http://", "https://"), {"width": 640})
    except ab.NET_ERRORS as e:
        return f"no answer ({type(e).__name__})"
    if not r.ok:
        return f"HTTP {r.status_code}"
    head = r.content[:4]
    if head[:3] == b"\xff\xd8\xff" or head[:3] == b"\x89PN":
        return ""
    return f"not a JPEG or PNG ({r.headers.get('Content-Type', '?')})"


def ladder(rows, session, say=print):
    """{source: found} for the key people in rows, each asked in turn."""
    fan, token = key("fanart key"), key("discogs token")
    if len(token) < 20:
        say("  (no usable Discogs token in the keys file: Discogs is left out)")
        token = ""
    if not fan:
        say("  (no fanart.tv key in the keys file or art_fetch's credentials: fanart.tv is left out)")
    wd = wikidata_now([p["mbid"] for p in rows if p["mbid"]], session)
    got = {"Wikidata now": 0, "TheAudioDB": 0, "fanart.tv": 0, "Discogs": 0, "any": 0}
    for n, p in enumerate(rows, 1):
        print(f"\r  {n}/{len(rows)}", end="", flush=True)
        hits = []
        if p["mbid"] and (wd.get(p["mbid"]) or {}).get("image"):
            hits.append("Wikidata now")
        if p["mbid"]:
            if audiodb(p["mbid"], session)[0]:
                hits.append("TheAudioDB")
            if fan and fanart(p["mbid"], session, fan)[0]:
                hits.append("fanart.tv")
        if token and p["dcid"] and discogs(p["dcid"], session, token)[0]:
            hits.append("Discogs")
        for h in hits:
            got[h] += 1
        got["any"] += bool(hits)
        p["hits"] = hits
    print()
    return got


# ---------------------------------------------------------------- reports
def one(rows, name, notes, session):
    hits = [p for p in rows if cr.fold(p["name"]) == cr.fold(name) or cr.fold(p["place"].split("/")[-1]) == cr.fold(name)]
    if not hits:
        print(f"No people page for {name}.")
        return 1
    for p in hits:
        jpg = notes / f"{p['place']}.jpg"
        print(f"\n{p['place']}.md  ({'library artist' if p['kind'] == 'artist' else 'key person'})")
        print(f"  banner in {notes}: {'yes' if jpg.exists() else 'no'}")
        if p["kind"] == "artist":
            m = p["meta"]
            print(f"  art_fetch's photo saved: {'yes' if p['photo'] and p['photo'].exists() else 'no'}"
                  f"; photo source: {m.get('photo_source') or 'none'}")
            continue
        m = p["meta"]
        print(f"  MusicBrainz ID: {p['mbid'] or 'none'}   Discogs ID: {p['dcid'] or 'none'}")
        print(f"  saved record: {'yes, looked up ' + m.get('fetched', '?') if m else 'none'}"
              f"; Wikidata item: {m.get('wikidata') or 'none'}; picture: {m.get('image') or 'none'}")
        print(f"  photo saved on this PC: {'yes' if p['photo'] and p['photo'].exists() else 'no'}")
        if not jpg.exists():
            c = person_cause(p)
            print(f"  cause {c}: {CAUSES[c]}")
        if session is None:
            continue
        if p["mbid"]:
            now = wikidata_now([p["mbid"]], session).get(p["mbid"]) or {}
            print(f"  Wikidata now: item {now.get('wikidata') or 'none'}, picture {now.get('image') or 'none'}")
            if now.get("image"):
                print(f"  download: {download_works(now['image'], session) or 'works'}")
            url, why = audiodb(p["mbid"], session)
            print(f"  TheAudioDB: {url or why}")
            fan = key("fanart key")
            if fan:
                url, why = fanart(p["mbid"], session, fan)
                print(f"  fanart.tv: {url or why}")
        if p["dcid"] and len(key("discogs token")) >= 20:
            url, why = discogs(p["dcid"], session, key("discogs token"))
            print(f"  Discogs: {url or why}")
    return 0


def every(rows, notes, session):
    for kind, label in (("artist", "Library artists"), ("person", "Key people")):
        r = [p for p in rows if p["kind"] == kind]
        have = sum(1 for p in r if (notes / f"{p['place']}.jpg").exists())
        print(f"  {label}: {len(r):,} pages, {have:,} with a banner, {len(r) - have:,} without")
    lib_none = [p for p in rows if p["kind"] == "artist" and not (notes / f"{p['place']}.jpg").exists()]
    if lib_none:
        saved = sum(1 for p in lib_none if p["photo"] and p["photo"].exists())
        print(f"\nLibrary artists without a banner: {len(lib_none)}; art_fetch found no photo for "
              f"{len(lib_none) - saved}, a photo is saved but no banner for {saved}")
        for p in lib_none[:20]:
            print(f"    {p['place']}")
    none = [p for p in rows if p["kind"] == "person" and not (notes / f"{p['place']}.jpg").exists()]
    by = {}
    for p in none:
        by.setdefault(person_cause(p), []).append(p)
    print(f"\nKey people without a banner: {len(none)}")
    for c in (1, 2, 3, 4):
        print(f"  {c}: {len(by.get(c, [])):5}  {CAUSES[c]}")
        for p in by.get(c, [])[:8]:
            print(f"         {p['place'].split('/', 1)[-1]}")
    if session is None:
        return 0
    if by.get(3):
        print("\nCause 3: does the download work now?")
        bad = {}
        for p in by[3]:
            why = download_works(p["meta"]["image"], session) or "works now"
            bad[why] = bad.get(why, 0) + 1
        for why, n in sorted(bad.items(), key=lambda x: -x[1]):
            print(f"  {n:5}  {why}")
    ask = by.get(1, []) + by.get(2, []) + by.get(3, [])
    if ask:
        mins = sum(2.6 if p["mbid"] else 1.1 for p in ask) / 60
        print(f"\nWhat each source would give the {len(ask)} key people with no photo saved "
              f"(about {mins:.0f} minutes; TheAudioDB answers 30 a minute):")
        got = ladder(ask, session)
        for src, n in got.items():
            if src != "any":
                print(f"  {src:13} {n:5}")
        print(f"  {'at least one':13} {got['any']:5} of {len(ask)}")
        for c in (1, 2, 3):
            r = by.get(c, [])
            if r:
                print(f"    cause {c}: {sum(1 for p in r if p.get('hits'))} of {len(r)}")
    return 0


def main(argv):
    conf, drive, _ = nw.settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="one person or artist, in detail")
    ap.add_argument("--notes", help="the Notes folder (default: the iPod's)")
    ap.add_argument("--offline", action="store_true", help="only what's saved: no requests")
    args = ap.parse_args(argv)
    notes = Path(args.notes) if args.notes else drive / "Notes"
    if not notes.is_dir():
        print(f"Can't find {notes}. Is the iPod plugged in?")
        return 1
    rows = build()
    if rows is None:
        return 1
    session = None if args.offline else __import__("requests").Session()
    print(f"\nPeople pages in {notes}:")
    if args.name:
        return one(rows, args.name, notes, session)
    return every(rows, notes, session)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
