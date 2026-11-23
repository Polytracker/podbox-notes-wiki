"""
track_notes.py -- the Track page in PodBox's liner notes viewer.

For every track with its own English Wikipedia article it writes one file
into the iPod's Artwork\\Tracks folder:

  <Album Artist> - <Track Title>.txt

The page is the article's introduction, under the track's title and a facts
line, with the article credited at the end, as its licence asks. Most tracks
have no article and get no page; the viewer then leaves Track out.

The songs are found from the album ids.py identified, not by searching for
their titles: Wikidata lists an album's songs (its "tracklist", and songs
that say they are "part of" it), and a song counts only when its title
matches one of your tracks. Its introduction must be a real write-up (300
characters or more, not a list of other meanings) and must name the artist
in its opening, so the article about the original of a cover isn't used for
the cover. Many songs' introductions are a sentence or two; those get the
first paragraph of the article's background (or writing, recording…)
section after them, as the Album pages add one from the reception.

Last.fm is asked only where Wikipedia couldn't be (as the Album pages fall
back to it): songs Wikidata knows that have no usable English article
("Airbag" is a redirect to its album's article), and every track on albums
Wikidata doesn't have. It's asked by MusicBrainz recording when ids.py knows
it, and its text is used only when Last.fm puts the track on your album or
by your artist, with the same checks. --no-lastfm leaves Last.fm out.

Requests: about two to Wikidata per album with a Wikidata item, one to
Wikipedia per 20 songs found, and one to Last.fm per track it's asked about
(about 4 a second; around 1,000 tracks, 4-5 minutes, the first time for
Joe's library). What was found is kept, so later runs only
look at new albums, and look again at others after 180 days.

Files you've edited yourself are never overwritten, and nothing is ever
deleted. If the Track page is switched off on the iPod (Settings >
Appearance > Viewers), this does nothing.

Usage:
  python track_notes.py                              the iPod in the settings file
  python track_notes.py --only "Radiohead - OK Computer"
  python track_notes.py --ipod "credits test"        write to a test folder, not the iPod
"""
from __future__ import annotations

import argparse, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import requests
    import artist_bios as ab
    import ids
    import translate as tr
    from credits import fold
    from liner_notes import (wiki_summaries, wiki_article, sections, paragraphs, foreign_notes,
                             artist_language, artist_ids)
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to ids.py, credits.py, artist_bios.py and translate.py.")
    sys.exit(1)

CACHE = ab.CACHE.parent / "tracks"
WIKIDATA = "https://www.wikidata.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
RECHECK_DAYS = 180
MIN_CHARS = 300
VERSION = 5           # albums looked up by an older version are looked up again
# sections a short lead is filled out from, in order of preference; never lists or tables
BODY_SECTIONS = (r"background", r"writing|composition|recording|production", r"music|lyrics|theme",
                 r"history|release", r"^(?!.*(track|personnel|chart|certif|reference|note|cover|"
                 r"version|link|further|see also|accolade|single)).*$")


# ---------------------------------------------------------------- Wikidata
def album_songs(album_q, session):
    """Wikidata items for the album's songs: its tracklist (P658) and the
    items that say they are part of it (P361)."""
    found = []
    r = ab.wiki_get(session, WIKIDATA, {"action": "wbgetentities", "ids": album_q, "props": "claims",
                                         "format": "json"})
    if r.ok:
        claims = ((r.json().get("entities") or {}).get(album_q) or {}).get("claims") or {}
        for c in claims.get("P658") or []:
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
            if v.get("id"):
                found.append(v["id"])
    r = ab.wiki_get(session, WIKIDATA, {"action": "query", "list": "search", "srnamespace": 0,
                                         "srsearch": f"haswbstatement:P361={album_q}", "srlimit": 50,
                                         "format": "json"})
    if r.ok:
        found += [h["title"] for h in (r.json().get("query") or {}).get("search") or []
                  if re.fullmatch(r"Q\d+", h.get("title", ""))]
    return list(dict.fromkeys(found))

def song_items(items, session):
    """{item: entity} for the song items, with every language's article
    (for the other-language step), for those with an English article or label."""
    out = {}
    for n in range(0, len(items), 50):
        r = ab.wiki_get(session, WIKIDATA, {"action": "wbgetentities", "ids": "|".join(items[n:n + 50]),
                                             "props": "sitelinks|labels", "languages": "en|mul",
                                             "format": "json"})
        if not r.ok:
            continue
        for q, e in (r.json().get("entities") or {}).items():
            if enwiki(e) or label(e):
                out[q] = e
    return out

def enwiki(ent):
    return ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title") or ""

def label(ent):
    labels = ent.get("labels") or {}
    return ((labels.get("en") or labels.get("mul")) or {}).get("value", "")


# ---------------------------------------------------------------- matching and checking
def bare(title):
    """An article title without its disambiguation: "Lucky (Radiohead song)" -> "Lucky"."""
    return re.sub(r"\s*\([^)]*\)$", "", title or "").strip()

def match_tracks(tracks, songs):
    """{your track's place: song item} for songs whose title (their English
    article's, without its disambiguation, or their label) is one of your
    tracks'. Songs with an English article are matched first."""
    by_title = {}
    for i, (_, _, title) in enumerate(tracks):
        by_title.setdefault(ids.clean_title(title), []).append(i)
    out = {}
    for q, ent in sorted(songs.items(), key=lambda kv: not enwiki(kv[1])):
        for name in (bare(enwiki(ent)), label(ent)):
            for i in by_title.get(ids.clean_title(name), []) if name else []:
                out.setdefault(i, q)
    return out

def opening(text, chars=200):
    """The start of an introduction, where it says whose song it is. Not cut
    at the first full stop: "…by American rapper Dr. Dre" has one early."""
    return text.strip()[:chars]

def fill_out(lead, article, session):
    """A lead under MIN_CHARS with the first paragraph from the article's
    background (or writing, recording…) section after it, as the Album pages
    add a paragraph from the reception: (text, "excerpts"), or (lead, "introduction")."""
    if len(lead) >= MIN_CHARS:
        return lead, "introduction"
    text, _ = wiki_article(article, session)
    secs = sections(text)[1:] if text else []
    for want in BODY_SECTIONS:
        for head, body in secs:
            if re.search(want, head, re.I):
                paras = paragraphs(body)
                if paras:
                    return lead.rstrip() + "\n" + paras[0], "excerpts"
    return lead, "introduction"

ENSEMBLE = re.compile(r"\s+(trio|quartet|quintet|sextet|band|orchestra|group|ensemble|experience|"
                      r"and his orchestra|& his orchestra)$", re.I)

def usable(intro, artist, need=MIN_CHARS, album=""):
    """Why an introduction can't be used, or "" if it can."""
    if not intro:
        return "no introduction"
    if len(intro) < need:
        return "too short, even with a paragraph from the article"
    if re.search(r"\bmay (also )?refer to\b", intro[:300]):
        return "a list of other meanings"
    names = [fold(a) for a in re.split(r"\s*(?:,|&| and | feat\.? | with )\s*", artist) if a.strip()]
    names += [fold(ENSEMBLE.sub("", artist))]                  # "Vince Guaraldi Trio" -> "Vince Guaraldi"
    lead = fold(opening(intro))
    named = any(n and n in lead for n in names + [fold(artist)])
    # or it names the album (a song "by Madvillain" on Madvillainy, filed under MF DOOM):
    # the song came from the album's own Wikidata item, and the article about the
    # original of a cover doesn't open by naming the cover's album
    on_album = album and fold(ids.plain_album(album)) in lead
    if not (named or on_album):
        return "doesn't name the artist or album first (perhaps the original of a cover)"
    return ""


# ---------------------------------------------------------------- Last.fm
LASTFM = "https://ws.audioscrobbler.com/2.0/"

def lastfm_track(artist, title, album, session, key, mbid=None, lang=None):
    """(text, why) from Last.fm's write-up of the track: asked by its
    MusicBrainz recording when known, else by artist and title, and used only
    when Last.fm puts it on your album or by your artist (a same-named song by
    someone else is never used)."""
    asks = ([{"mbid": mbid}] if mbid else []) + [{"artist": artist, "track": title}]
    for ask in asks:
        time.sleep(0.25)                                   # Last.fm asks for no more than 5 a second
        try:
            r = session.get(LASTFM, headers=ab.UA, timeout=20,
                            params={"method": "track.getinfo", "api_key": key, "format": "json", **ask,
                                    **({"lang": lang} if lang else {})})
        except requests.RequestException:
            return "", "Last.fm didn't answer"
        if not r.ok:
            continue
        t = r.json().get("track") or {}
        if not t:
            continue
        theirs_album = fold(((t.get("album") or {}).get("title")) or "")
        theirs_artist = fold(((t.get("artist") or {}).get("name")) or "")
        if not (theirs_artist == fold(artist) or (theirs_album and theirs_album == fold(ids.plain_album(album)))):
            continue
        raw = ((t.get("wiki") or {}).get("content")) or ((t.get("wiki") or {}).get("summary")) or ""
        raw = re.split(r"User-contributed text is available|<a href=\"https?://www\.last\.fm[^>]*>Read more", raw)[0]
        text = "\n".join(p for p in (ab.strip_markup(x) for x in re.split(r"\n+", raw)) if p)
        if text:
            return text, ""
    return "", "no Last.fm write-up"


# ---------------------------------------------------------------- the page
def page_text(title, place, album, paras):
    """The Track file: "#title", a "#facts" line, the paragraphs, and
    "#sources" from the credit line ("# From …") the ladder ends them with."""
    body = [tr.plain(p) for p in paras if p and not p.startswith("# ")]
    credit = next((p[2:] for p in paras if p.startswith("# ")), "")
    lines = [f"#title\t{title}", f"#facts\tTrack {place} \u00b7 {album}", ""] + body
    if credit:
        lines += ["", f"#sources\t{credit}"]
    return "\n".join(lines) + "\n"

def english_paras(text, part, article, date=None):
    return ab.trim_bio(text).split("\n") + [tr.credit("wikipedia", title=article, part=part, date=date)]


# ---------------------------------------------------------------- the ladder, as for the Album pages
def track_notes(i, album, song, intros, session, ctx):
    """(paragraphs ending in a credit line, source, why not) for one track,
    trying what the Album pages try, in the same order: the English article
    (filled out from its background section if short), the article in the
    artist's own language or another, translated, then Last.fm in English,
    then Last.fm in the artist's language, translated. `song` is the track's
    Wikidata item, or None (Last.fm only)."""
    title = album["tracks"][i][2]
    whys = []
    def check(text):
        return usable(text, album["artist"], album=album["album"])
    if song:
        article = enwiki(song)
        lead = intros.get(article, "") if article else ""
        why = usable(lead, album["artist"], need=0, album=album["album"]) if article else "no English article"
        if not why:
            text, part = fill_out(lead, article, session)
            why = check(text)
            if not why:
                return english_paras(text, part, article), "wikipedia", ""
        whys.append(f"Wikipedia: {why}")
        if ctx["translator"]:
            got = foreign_notes({"ent": song}, ctx["lang"], session, ctx["translator"])
            if got:
                why = check(" ".join(p for p in got[0] if not p.startswith("# ")))
                if not why:
                    return got[0], got[1], ""
                whys.append(f"translated Wikipedia: {why}")
    if ctx["lastfm"]:
        mbid = (ctx["tracks_mb"].get(str(i)) or {}).get("recording")
        text, why = lastfm_track(album["artist"], title, album["album"], session, ctx["lastfm"], mbid)
        why = why or check(text)
        if not why:
            return ab.trim_bio(text).split("\n") + [tr.credit("lastfm")], "last.fm", ""
        whys.append(f"Last.fm: {why}")
        if ctx["translator"] and ctx["lang"]:
            text, why = lastfm_track(album["artist"], title, album["album"], session, ctx["lastfm"], mbid,
                                     ctx["lang"])
            if text and tr.needs_translation(text, ctx["lang"]):
                english = ctx["translator"].translate(text.split("\n"), ctx["lang"])
                if english and not check(" ".join(english)):
                    return (ab.trim_bio("\n".join(english)).split("\n")
                            + [tr.credit("lastfm", lang=ctx["lang"])]), f"last.fm ({ctx['lang']}, translated)", ""
    return [], "", "; ".join(whys)

def track_number(album, i):
    disc, num, _ = album["tracks"][i]
    multi = len({t[0] for t in album["tracks"]}) > 1
    return f"{disc}-{num}" if multi else str(num)


# ---------------------------------------------------------------- the run
def main(argv=None):
    conf = ab.settings()
    drive = (conf.get("ipod drive") or "G:").rstrip("\\/")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_root", nargs="?", default=conf.get("music folder", "").rstrip("\\/") or f"{drive}\\Music",
                    help="the iPod's music folder (default: from the settings file)")
    ap.add_argument("--ipod", help="the iPod's own folder (default: the folder holding the music folder)")
    ap.add_argument("--only", action="append", default=[], help='"Artist - Album" (can be given more than once)')
    ap.add_argument("--refresh", action="store_true", help="look every album up again")
    ap.add_argument("--no-lastfm", action="store_true", help="leave Last.fm out")
    ap.add_argument("--deepl-key", default=conf.get("deepl key") or os.environ.get("DEEPL_KEY"),
                    help="DeepL key, to translate notes for artists who don't work in English")
    args = ap.parse_args(argv)
    lastfm_key = None if args.no_lastfm else (ab.af.load_credentials().lastfm_api_key or None)

    music = Path(args.music_root)
    ipod = Path(args.ipod) if args.ipod else music.resolve().parent
    if not ab.ipod_page_on(ipod, "track notes"):
        print("The Track page is switched off on the iPod, so no track notes are fetched.")
        return 0
    lib = ids.library().get("albums") or {}
    if not lib:
        print("Run ids.py first: it reads your albums and identifies them.")
        return 1
    records = {}
    for path in ids.CACHE.glob("*.json"):
        rec = ab.load_json(path)
        if rec and rec.get("key") in lib:
            records[rec["key"]] = rec
    only = {ab.norm(o) for o in args.only}
    keys = [k for k in sorted(lib) if not only or ab.norm(k) in only or ab.norm(lib[k]["artist"]) in only]
    with_q = [k for k in keys if ((records.get(k) or {}).get("mb") or {}).get("wikidata")]
    if not lastfm_key:
        keys = with_q
    print(f"{len(keys)} albums: {len(with_q)} with a Wikidata item to find their songs from"
          + (", the others asked about on Last.fm." if lastfm_key else "."))

    out_dir = ipod / "Artwork" / "Tracks"
    out_dir.mkdir(parents=True, exist_ok=True)
    (CACHE / "albums").mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    translator = tr.Translator(args.deepl_key, CACHE.parent / "translations.json", session)
    if translator:
        print("Translating notes for artists who don't work in English, with DeepL")
    counts = {"written": 0, "same": 0, "kept": 0, "albums looked up": 0}
    sources, rejected = {}, []
    try:
        for n, k in enumerate(keys, 1):
            album = lib[k]
            rec = records.get(k) or {}
            q = (rec.get("mb") or {}).get("wikidata")
            name = ab.safe_name(k)
            if not name:
                continue
            path = CACHE / "albums" / f"{name}.json"
            seen = ab.load_json(path) or {}
            fresh = seen.get("wikidata") == q and seen.get("version") == VERSION and not args.refresh and \
                time.time() - seen.get("checked", 0) < RECHECK_DAYS * 86400 and \
                seen.get("lastfm") == bool(lastfm_key) and seen.get("translated") == bool(translator)
            if not fresh:
                counts["albums looked up"] += 1
                songs = song_items(album_songs(q, session), session) if q else {}
                found = match_tracks(album["tracks"], songs)
                articles = sorted({enwiki(songs[s]) for s in found.values() if enwiki(songs[s])})
                intros = {}
                for m in range(0, len(articles), 20):
                    intros.update(wiki_summaries(articles[m:m + 20], session))
                who = artist_ids(album["artist"])
                ctx = {"translator": translator, "lastfm": lastfm_key,
                       "lang": artist_language(who, session) if translator and who else None,
                       "tracks_mb": (rec.get("mb") or {}).get("tracks") or {}}
                seen = {"wikidata": q, "version": VERSION, "checked": int(time.time()),
                        "lastfm": bool(lastfm_key), "translated": bool(translator), "tracks": {}}
                # Last.fm only where Wikipedia couldn't be: songs Wikidata knows,
                # and every track on an album Wikidata doesn't have
                places = sorted(found) if q else range(len(album["tracks"]))
                for i in places:
                    song = songs.get(found.get(i)) if found.get(i) else None
                    paras, source, why = track_notes(i, album, song, intros, session, ctx)
                    seen["tracks"][str(i)] = {"paras": paras, "source": source, "why": why,
                                              "article": enwiki(song) if song else ""}
                ab.save_json(path, seen)
            for i, t in sorted(seen.get("tracks", {}).items(), key=lambda kv: int(kv[0])):
                title = album["tracks"][int(i)][2]
                if not t.get("paras"):
                    if t.get("article"):
                        rejected.append(f"{k}: \"{title}\" ({t['article']}): {t.get('why')}")
                    continue
                fname = ab.safe_name(f"{album['artist']} - {title}")
                if not fname:
                    continue
                sources[t["source"]] = sources.get(t["source"], 0) + 1
                text = page_text(title, track_number(album, int(i)), album["album"], t["paras"])
                mp = CACHE / f"{fname}.json"
                meta = ab.load_json(mp) or {"key": f"{album['artist']} - {title}"}
                res = ab.write_if_ours(out_dir / f"{fname}.txt", text.encode("utf-8"), meta, "txt_sha1")
                ab.save_json(mp, meta)
                counts[res] += 1
            print(f"\r  {n}/{len(keys)} albums", end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopped. Albums finished are kept; run again to carry on.")
    print()
    report = HERE / "Tracks not used.txt"
    report.write_text("Songs with an English Wikipedia article for which no notes were used, and why.\n\n"
                      + "\n".join(rejected) + "\n", encoding="utf-8")
    print(f"Track notes written or updated: {counts['written']}, unchanged: {counts['same']}, "
          f"kept as you left them: {counts['kept']}. Albums looked up: {counts['albums looked up']}.")
    print("  From: " + ", ".join(f"{v} {k}" for k, v in sorted(sources.items(), key=lambda kv: -kv[1])))
    print(f"  Not used: {len(rejected)} (listed in \"{report.name}\").")
    return 0

if __name__ == "__main__":
    sys.exit(main())
