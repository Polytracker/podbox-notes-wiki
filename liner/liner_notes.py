"""
liner_notes.py -- album notes for PodBox's Liner Notes screen.

For every album folder in the iPod's music folder it finds notes about the
album and writes two files into the iPod's Artwork\\Notes folder, which Liner
Notes (hold Select on Now Playing, or on an album in Music) reads:

  <Album Artist> - <Album>.txt   the title, a facts line, the notes, then the
                                 critics' scores and where the text came from
  <Album Artist> - <Album>.jpg   the album's own cover, cropped to a banner

Which album it is gets settled first, on Wikidata among the artist's albums,
else on MusicBrainz by the artist's ID and the title, so another album of the
same name can't slip in. The notes are that album's English Wikipedia
introduction, the first paragraph of its critical reception and the scores
from its ratings box. For an artist who doesn't work in English, the album's
article in their own language is translated (with a DeepL key in the settings
file). Failing those the notes come from Last.fm or Discogs, and failing
those the page is just the facts line: year, label, tracks and length.

Albums already done are skipped; one whose notes are over a year old is
checked again and only rewritten if the text has really changed. A file you
have edited yourself is never overwritten.

Usage:
  python liner_notes.py "G:\\Music"
  python liner_notes.py "G:\\Music" --only "Radiohead"           one artist
  python liner_notes.py "G:\\Music" --only "Radiohead - OK Computer"
  python liner_notes.py "G:\\Music" --refresh                    fetch all again
"""
from __future__ import annotations

import argparse, html, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import requests, mutagen
    import artist_bios as ab
    import translate as tr
    import ids
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to artist_bios.py, translate.py and art_fetch.py, and run: "
          "pip install requests pillow mutagen opencv-python")
    sys.exit(1)

CACHE = ab.CACHE.parent / "notes"
FOLDERS = CACHE / "_folders.json"          # tags read from each folder, until it changes
MISSING_LIST = HERE / "Albums without notes.txt"
WIKI_API = "https://{}.wikipedia.org/w/api.php"
MB = "https://musicbrainz.org/ws/2/"
MAX_SCORES = 8
SINGLES = {"singles", "single", "misc", "miscellaneous", "loose tracks"}
OTHER_LANGS = ("ja", "ko", "zh", "fr", "es", "it", "de", "pt", "nl", "sv")

# Wikidata's kinds of release. "album" covers studio, live, compilation and
# soundtrack albums, EPs and demos; a song or single is accepted only for a
# folder of three tracks or fewer.
ALBUM_TYPES = {"Q482994", "Q208569", "Q209939", "Q222910", "Q4176708", "Q169930", "Q220935"}
SINGLE_TYPES = {"Q134556", "Q7366", "Q105543609"}
NOT_RELEASES = {"Q10590726", "Q193977", "Q55850593", "Q108352648", "Q108352496", "Q6128115"}
                # video album, music video, music track, album/single release (editions), 7" single
SINGLE_MAX_TRACKS = 3
CRITIC = re.compile(r"\b(review|reviewer|critic|critics|critical|acclaim|praised|rated|rating|stars|"
                    r"out of|score|Metacritic|wrote|called it|described|panned|favou?rable)\b", re.I)


# ---------------------------------------------------------------- your files
def tag(f, *keys):
    for k in keys:
        v = (f.tags or {}).get(k) if f and f.tags else None
        if v:
            return str(v[0] if isinstance(v, list) else v).strip()
    return ""

def read_tags(p):
    try:
        return mutagen.File(p, easy=True)
    except Exception:
        return None

def album_tracks(folder):
    """The album's tracks: the audio files in its folder, or, for an album
    split into disc folders (CD1, CD2...), in those."""
    files = [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in ab.AUDIO]
    if files:
        return files
    out = []
    for d in sorted(x for x in folder.iterdir() if x.is_dir()):
        out += [p for p in sorted(d.iterdir()) if p.is_file() and p.suffix.lower() in ab.AUDIO]
    return out

def signature(tracks):
    """Changes when tracks are added, removed or retagged, without opening them."""
    out = [len(tracks)]
    for p in (tracks[0], tracks[-1]):
        st = p.stat()
        out += [p.name, int(st.st_mtime), st.st_size]
    return out

LABEL_JUNK = re.compile(r"https?://|www\.|\.(com|net|org)\b|^\[?no label\]?$|^not on label|^none$|^unknown$", re.I)

def clean_label(label):
    return "" if not label or LABEL_JUNK.search(label.strip()) else label.strip()

def album_info(folder, artist, seen):
    """Album, album artist, years, label and track count, from the first and last
    track's tags (reading every file on the iPod's disk takes minutes), reused
    from the last run while the folder is unchanged. None for a folder that isn't
    one album (a Singles folder, mixed album tags)."""
    if folder.name.lower() in SINGLES:
        return None
    tracks = album_tracks(folder)
    if not tracks:
        return None
    sig = signature(tracks)
    old = seen.get(str(folder))
    if old and old.get("sig") == sig:
        info = dict(old["info"])
    else:
        first, last = read_tags(tracks[0]), read_tags(tracks[-1])
        album = tag(first, "album")
        if not album or (last is not None and tag(last, "album").casefold() != album.casefold()):
            seen[str(folder)] = {"sig": sig, "info": None}
            return None
        info = {"album": album,
                "artist": tag(first, "albumartist", "album artist") or tag(first, "artist") or artist,
                "orig_year": ab.year(tag(first, "originaldate", "originalyear")),
                "tag_year": ab.year(tag(first, "date", "year")),
                "label": clean_label(tag(first, "organization", "label", "publisher")),
                "tracks": len(tracks)}
        seen[str(folder)] = {"sig": sig, "info": dict(info)}
    if not info:
        return None
    info.update(files=tracks, minutes=None)
    return info

def add_minutes(info, meta):
    """The album's length. Reading every track is slow, so the last run's
    figure is kept while the track count is the same."""
    if meta and meta.get("minutes") and meta.get("tracks") == info["tracks"]:
        info["minutes"] = meta["minutes"]
        return
    seconds = 0.0
    for p in info["files"]:
        f = read_tags(p)
        seconds += getattr(getattr(f, "info", None), "length", 0) or 0
    info["minutes"] = round(seconds / 60)

def release_year(info, found):
    """The year the album first came out: the earliest the confirmed album's
    MusicBrainz release group and Wikidata item give, else your files' original
    date, else their date (often a reissue's)."""
    known = [y for y in (found.get("rg_year"), found.get("wd_year")) if y]
    return min(known) if known else (info["orig_year"] or info["tag_year"] or "")

def facts_line(info, year, label):
    n = info["tracks"]
    return " \u00b7 ".join(x for x in (
        info["artist"], year, info["label"] or label or "",
        f"{n} track{'s' if n != 1 else ''}",
        f"{info['minutes']} min" if info["minutes"] else "") if x)


# ---------------------------------------------------------------- which album
EDITION = r"(edition|remaster|deluxe|expanded|anniversary|version|bonus|reissue|legacy|mono|stereo|mix)"

def clean_title(t):
    """The album's own title, without the edition a release adds to it:
    "Blue (2021 Remaster)", "Kid A [Deluxe Edition]", "Spirit of Eden - Remastered
    and Expanded" and "In Rainbows (Disk 2)" all come back as the plain title."""
    t = re.sub(rf"\s*[\(\[][^)\]]*{EDITION}[^)\]]*[\)\]]", "", t or "", flags=re.I)
    t = re.sub(r"\s*[\(\[]\s*(disc|disk|cd)\s*\d+\s*[\)\]]", "", t, flags=re.I)
    t = re.sub(rf"(?:\s+[-–—]|:)\s+[^-–—:]*{EDITION}[^-–—:]*$", "", t, flags=re.I)
    return t.strip() or (t or "")

def bare_title(t):
    """"OK Computer (Collector's Edition)" -> "okcomputer", for comparing titles."""
    return ab.norm(clean_title(t))

def wd_kind(ent):
    """"album", "single", "video", "other" or "" (unknown) for a Wikidata item."""
    kinds = set(ab.wd_claim_ids(ent, "P31"))
    desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "").lower()
    if "video" in desc or kinds & {"Q10590726", "Q193977"}:
        return "video"
    if kinds & ALBUM_TYPES:
        return "album"
    if kinds & SINGLE_TYPES or re.search(r"\b(song|single|track)\b", desc):
        return "single"
    if kinds & NOT_RELEASES:
        return "other"
    if re.search(r"\b(album|EP|mixtape|soundtrack|compilation)\b", desc, re.I):
        return "album"
    return ""

def wd_year(ent):
    years = []
    for c in (ent.get("claims") or {}).get("P577", []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("time"):
            y = ab.year(v["time"].lstrip("+"))
            if y:
                years.append(y)
    return min(years) if years else ""

def wd_label(ent, session):
    """The album's first record label, by name, from its Wikidata item."""
    ids = ab.wd_claim_ids(ent, "P264")[:1]
    if not ids:
        return ""
    lab = ab.wd_entities(ids, session, props="labels").get(ids[0]) or {}
    labels = lab.get("labels") or {}
    return ((labels.get("en") or labels.get("mul") or {}).get("value") or "").strip()

def item_names(ent):
    """The item's names, and its English article's title without "(album)"."""
    names = ab.wd_names(ent)
    t = ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")
    if t:
        names.add(ab.norm(re.sub(r"\s*\([^)]*\)$", "", t)))
    return names

def pick_item(ents, info):
    """The best acceptable item: an album (or, for three tracks or fewer, a
    single first), nearest the year in your tags, with an English article."""
    want_year = info["orig_year"] or info["tag_year"]
    short = info["tracks"] <= SINGLE_MAX_TRACKS
    order = {"album": 1, "": 2, "single": 0 if short else None}
    ok = [(e, wd_kind(e)) for e in ents]
    ok = [(e, k) for e, k in ok if order.get(k) is not None]
    if not ok:
        return None
    def rank(ek):
        e, k = ek
        y = wd_year(e)
        gap = abs(int(y) - int(want_year)) if y and want_year else 99
        return (order[k], gap, "enwiki" not in (e.get("sitelinks") or {}))
    return min(ok, key=rank)[0]

def title_item(title, session):
    """The Wikidata item of an English Wikipedia article, or None."""
    r = ab.wiki_get(session, ab.WD_API, {"action": "wbgetentities", "sites": "enwiki",
                                         "titles": title, "props": "claims", "format": "json"})
    ents = (r.json().get("entities") or {}) if r.ok else {}
    return next((e for q, e in ents.items() if q.startswith("Q")), None)

def item_result(ent, session, info):
    q = ent.get("id")
    return {"q": q, "ent": ent, "sure": True,
            "enwiki": ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title"),
            "wd_year": wd_year(ent),
            "label": "" if info.get("label") else wd_label(ent, session)}

def wd_album(info, artist_qid, session):
    """The album's Wikidata item: one whose performer is the artist and whose
    name is the album's, and which is an album (see pick_item). Names are
    checked on a light download first; only the matches are fetched in full."""
    want = {bare_title(info["album"]), ab.norm(info["album"])}
    for query in (f"haswbstatement:P175={artist_qid} {clean_title(info['album'])}",
                  f"haswbstatement:P175={artist_qid}"):
        r = ab.wiki_get(session, ab.WD_API, {"action": "query", "list": "search", "srsearch": query,
                                             "srlimit": 50, "srnamespace": 0, "format": "json"})
        r.raise_for_status()
        ids = [h["title"] for h in (r.json().get("query") or {}).get("search") or []]
        if not ids:
            continue
        light = ab.wd_entities(ids[:50], session, props="labels|aliases|sitelinks")
        named = [q for q in ids if item_names(light.get(q) or {}) & want]
        if not named:
            continue
        full = ab.wd_entities(named, session, props="labels|descriptions|claims|sitelinks", sites=None)
        best = pick_item([full[q] for q in named if q in full], info)
        if best:
            return item_result(best, session, info)
    return None

def release_group(info, artist_mbid, session):
    """The MusicBrainz release group for this album, or None."""
    esc = lambda s: s.replace('"', '\\"')
    who = f"arid:{artist_mbid}" if artist_mbid else f'artist:"{esc(info["artist"])}"'
    j = ab.mb_get(session, MB + "release-group",
                  {"query": f'releasegroup:"{esc(clean_title(info["album"]))}" AND {who}',
                   "fmt": "json", "limit": 15})
    want = bare_title(info["album"])
    hits = [g for g in (j or {}).get("release-groups") or [] if bare_title(g.get("title")) == want]
    if not hits:
        return None
    short = info["tracks"] <= SINGLE_MAX_TRACKS
    year = info["orig_year"] or info["tag_year"] or "x"
    rank = lambda g: ((g.get("primary-type") not in (("Single", "EP") if short else ("Album", "EP"))),
                      (g.get("first-release-date") or "")[:4] != year,
                      -int(g.get("score") or 0))
    return sorted(hits, key=rank)[0]

def rg_item(rg, session, info):
    """The Wikidata item for a MusicBrainz release group: asked of Wikidata by
    the release group's ID first, which spares MusicBrainz a request, then
    through MusicBrainz's own link."""
    r = ab.wiki_get(session, ab.WD_API, {"action": "query", "list": "search", "srnamespace": 0,
                                         "srsearch": f"haswbstatement:P436={rg['id']}", "format": "json"})
    ids = [h["title"] for h in ((r.json().get("query") or {}).get("search") or [])] if r.ok else []
    if not ids:
        j = ab.mb_get(session, MB + f"release-group/{rg['id']}", {"inc": "url-rels", "fmt": "json"})
        for rel in (j or {}).get("relations") or []:
            if rel.get("type") == "wikidata":
                m = re.search(r"(Q\d+)$", (rel.get("url") or {}).get("resource", ""))
                if m:
                    ids = [m.group(1)]
    if not ids:
        return None
    ents = ab.wd_entities(ids[:10], session, props="labels|descriptions|claims|sitelinks", sites=None)
    best = pick_item(list(ents.values()), info)
    return item_result(best, session, info) if best else None

def wiki_summaries(titles, session):
    """{title asked for: introduction} for up to 20 English articles. Wikipedia
    sends a long batch in parts ("continue"), so this asks until it has them all."""
    params = {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "exlimit": 20,
              "redirects": 1, "titles": "|".join(titles[:20]), "format": "json", "formatversion": 2}
    out, more = {}, {}
    for _ in range(20):
        r = ab.wiki_get(session, WIKI_API.format("en"), {**params, **more})
        if not r.ok:
            break
        data = r.json()
        q = data.get("query") or {}
        back = {}
        for k in ("normalized", "redirects"):
            for m in q.get(k) or []:
                back[m["to"]] = back.get(m["from"], m["from"])
        for p in q.get("pages") or []:
            if p.get("extract"):
                out[back.get(p["title"], p["title"])] = p["extract"].strip()
        more = data.get("continue") or {}
        if not more:
            break
    return out

def guess_title(info, session):
    """(English Wikipedia title, False) by likely titles and a search, accepted
    only for an album article that names the artist; else (None, False). Used
    only when neither Wikidata nor MusicBrainz knows the album."""
    album = clean_title(info["album"])
    tries = [f"{album} ({info['artist']} album)", f"{album} (album)", f"{album} (EP)", album]
    r = ab.wiki_get(session, WIKI_API.format("en"), {
        "action": "query", "list": "search", "srlimit": 3,
        "srsearch": f"{album} {info['artist']} album", "format": "json"})
    if r.ok:
        tries += [h["title"] for h in (r.json().get("query") or {}).get("search") or []]
    tries = list(dict.fromkeys(tries))
    leads = wiki_summaries(tries, session)
    songs_ok = info["tracks"] <= SINGLE_MAX_TRACKS
    for t in tries:
        lead = leads.get(t) or ""
        if not songs_ok and re.search(r"\bis an? (\w+ )?(song|single)\b", lead[:250]):
            continue                        # a song's article, for a whole album
        if lead and ab.norm(info["artist"]) in ab.norm(lead[:600]) \
                and bare_title(info["album"]) in ab.norm(lead[:200]) \
                and re.search(r"\b(album|EP|record)\b", lead[:300], re.I):
            return t, False
    return None, False


# ---------------------------------------------------------------- the notes
def wiki_article(title, session, lang="en"):
    """(plain text with == headings ==, wikitext) of the whole article."""
    r = ab.wiki_get(session, WIKI_API.format(lang), {
        "action": "query", "prop": "extracts|revisions", "explaintext": 1,
        "exsectionformat": "wiki", "rvprop": "content", "rvslots": "main",
        "redirects": 1, "titles": title, "format": "json", "formatversion": 2})
    if not r.ok:
        return "", ""
    pages = (r.json().get("query") or {}).get("pages") or []
    if not pages:
        return "", ""
    p = pages[0]
    rev = (p.get("revisions") or [{}])[0]
    return p.get("extract") or "", ((rev.get("slots") or {}).get("main") or {}).get("content") or ""

def sections(text):
    """[(heading, body)] with the lead as heading ""."""
    parts = re.split(r"\n(={2,4})\s*(.+?)\s*\1\s*\n", "\n" + text)
    out = [("", parts[0])]
    for i in range(1, len(parts) - 2, 3):
        out.append((parts[i + 1], parts[i + 2]))
    return out

def paragraphs(body):
    return [p.strip() for p in re.split(r"\n+", body or "") if len(p.strip()) > 80]

def reception(text):
    """The first paragraph about what critics made of it, from the reception
    section: in a "Release and reception" section the first paragraph is often
    about sales, so the first one that speaks of critics is taken."""
    secs = sections(text)
    for want in (r"critical reception", r"^reception$", r"reception", r"critical response"):
        for head, body in secs:
            if re.search(want, head, re.I):
                for p in paragraphs(body):
                    if CRITIC.search(p):
                        return p
    return ""

def unwiki(s):
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"\{\{\s*[Rr]ating\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\}\}", r"\1/\2", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", html.unescape(s))
    return re.sub(r"\s+", " ", s).strip(" |")

def tidy_score(score):
    """"(favourable)" -> "favourable"; "(not rated)", "()" and the like -> ""."""
    score = re.sub(r"\(\s*\)", "", score).strip(" |")
    score = re.sub(r"^\((.*)\)$", r"\1", score).strip()
    return "" if re.fullmatch(r"(not rated|n/?a|none|-|–)?", score, re.I) else score

def scores(wikitext):
    """["Pitchfork 10/10", ...] from the article's Music ratings box."""
    m = re.search(r"\{\{\s*(?:Music|Album) ratings(.*?)\n\}\}", wikitext or "", re.S | re.I)
    if not m:
        return []
    box, out = m.group(1), []
    mc = re.search(r"^\s*\|\s*MC\s*=\s*(.+)$", box, re.M)
    if mc:
        v = re.search(r"\d+", unwiki(mc.group(1)))
        if v:
            out.append(f"Metacritic {v.group(0)}")
    for n, name in re.findall(r"^\s*\|\s*rev(\d+)\s*=\s*(.+)$", box, re.M):
        sc = re.search(rf"^\s*\|\s*rev{n}[Ss]core\s*=\s*(.+)$", box, re.M)
        name, score = unwiki(name), tidy_score(unwiki(sc.group(1))) if sc else ""
        name = re.sub(r"\s*\(\s*\)", "", name).strip()
        if name and score and len(score) <= 12:
            out.append(f"{name} {score}")
    return out[:MAX_SCORES]

def english_notes(title, session, sure):
    """(paragraphs, source) from the English article, or None."""
    text, wt = wiki_article(title, session)
    lead = ab.trim_bio(sections(text)[0][1]) if text else ""
    if not lead:
        return None
    paras = lead.split("\n")
    rec = ab.trim_bio(reception(text))
    if rec:
        paras += ["# Critical reception", rec]
    sc = scores(wt)
    if sc:
        paras.append("# " + " \u00b7 ".join(sc))
    paras.append(tr.credit("wikipedia", title=title, part="excerpts" if rec else "introduction"))
    return paras, "wikipedia" + ("" if sure else " (not confirmed)")

def foreign_notes(found, lang, session, translator):
    """(paragraphs, source) from the album's article in another language,
    translated, or None. The artist's own language comes first."""
    links = found["ent"].get("sitelinks") or {}
    langs = ([lang] if lang else []) + [x for x in OTHER_LANGS if x != lang]
    for code in langs:
        title = (links.get(f"{code}wiki") or {}).get("title")
        if not title:
            continue
        text, _ = wiki_article(title, session, code)
        secs = sections(text) if text else []
        paras = paragraphs(secs[0][1]) if secs else []
        lead = len(paras)
        if secs and sum(len(p) for p in paras) < 300:          # a short lead: add the next section's start
            paras += next((paragraphs(b)[:1] for _, b in secs[1:] if paragraphs(b)), [])
        part = "excerpts" if len(paras) > lead else "introduction"
        paras = paras or [p.strip() for p in (secs[0][1] if secs else "").split("\n") if p.strip()]
        if not paras or not tr.needs_translation(" ".join(paras), code):
            continue
        english = translator.translate(paras, code)
        if english:
            return (ab.trim_bio("\n".join(english)).split("\n")
                    + [tr.credit("wikipedia", lang=code, part=part)]), f"wikipedia ({code}, translated)"
    return None

def lastfm_notes(info, names, session, key, lang=None, mbid=None):
    """Last.fm's album write-up: asked by the MusicBrainz release ids.py
    matched when there is one, then by artist and title."""
    asks = ([{"mbid": mbid}] if mbid else []) + \
           [{"artist": name, "album": clean_title(info["album"]), "autocorrect": 1} for name in names]
    for ask in asks:
        params = {"method": "album.getinfo", "api_key": key, "format": "json", **ask}
        if lang:
            params["lang"] = lang
        r = session.get("https://ws.audioscrobbler.com/2.0/", headers=ab.UA, timeout=20, params=params)
        if not r.ok:
            continue
        raw = (((r.json().get("album") or {}).get("wiki")) or {}).get("content") or ""
        raw = re.split(r"User-contributed text is available|<a href=\"https?://www\.last\.fm[^>]*>Read more", raw)[0]
        text = "\n".join(p for p in (ab.strip_markup(x) for x in re.split(r"\n+", raw)) if p)
        if len(text) > 80:
            return text
    return ""

def ids_record(info):
    """What ids.py settled about this album (its MusicBrainz release and
    group, Wikidata item, Discogs release), or {} if it hasn't identified it."""
    name = ab.safe_name(f"{info['artist']} - {info['album']}")
    rec = ab.load_json(ids.CACHE / f"{name}.json") if name else None
    return rec if rec and rec.get("key") else {}

def discogs_notes(info, session, token, rec=None):
    h = dict(ab.UA, Authorization=f"Discogs token={token}")
    dc = (rec or {}).get("discogs") or {}
    if dc.get("id"):
        # the exact release ids.py matched: its notes, from the copy ids.py saved
        rel = ids.saved_release("dcrel", dc["id"])
        if rel is None:
            d = session.get(f"https://api.discogs.com/releases/{dc['id']}", headers=h, timeout=20)
            time.sleep(1.1)
            rel = d.json() if d.ok else {}
        notes = ab.strip_markup(rel.get("notes") or "")
        return notes if len(notes) > 80 else ""
    r = session.get("https://api.discogs.com/database/search", headers=h, timeout=20, params={
        "artist": info["artist"], "release_title": clean_title(info["album"]), "type": "master",
        "per_page": 5})
    time.sleep(1.1)
    if not r.ok:
        return ""
    for hit in r.json().get("results") or []:
        if bare_title(hit.get("title", "").split(" - ", 1)[-1]) != bare_title(info["album"]):
            continue
        d = session.get(hit["resource_url"], headers=h, timeout=20)
        time.sleep(1.1)
        notes = ab.strip_markup((d.json() if d.ok else {}).get("notes") or "")
        return notes if len(notes) > 80 else ""
    return ""

_languages = {}

def artist_language(who, session):
    """The language the artist works in (None for English or unknown), from
    their Wikidata item, asked once per run."""
    q = who.get("wikidata")
    if not q:
        return None
    if q not in _languages:
        ent = ab.wd_entities([q], session, props="claims", sites=None).get(q) or {}
        _languages[q] = tr.artist_language(ent)
    return _languages[q]

def find_notes(info, who, session, args, found):
    """(paragraphs, source) -- paragraphs may be empty, leaving the facts line.
    `who` is the artist's saved IDs from artist_bios.py; what was learnt about
    the album (item, release group, years, label) is left in `found`."""
    def attempt(name, fn):
        try:
            return fn()
        except Exception as e:
            ab.problem(name, e)
            return None
    rec = ids_record(info)
    mb = rec.get("mb") or {}
    item = None
    if mb.get("rg"):
        # ids.py has identified the album: its release group and Wikidata item, no guessing by name
        rel = ids.saved_release("mbrel", mb["id"]) if mb.get("id") else None
        rg = (rel or {}).get("release-group") or {"id": mb["rg"]}
        found["rg"] = rg
        found["rg_year"] = ab.year((rg.get("first-release-date") or "")[:4])
        if mb.get("wikidata"):
            ents = attempt("wikidata", lambda: ab.wd_entities(
                [mb["wikidata"]], session, props="labels|descriptions|claims|sitelinks", sites=None))
            ent = (ents or {}).get(mb["wikidata"])
            item = item_result(ent, session, info) if ent else None
        if not item:
            item = attempt("wikidata", lambda: rg_item(rg, session, info))
    elif who.get("wikidata"):
        item = attempt("wikidata", lambda: wd_album(info, who["wikidata"], session))
    if not item and not mb.get("rg"):
        rg = attempt("musicbrainz", lambda: release_group(info, who.get("mbid"), session))
        if rg:
            found["rg"] = rg
            found["rg_year"] = ab.year((rg.get("first-release-date") or "")[:4])
            item = attempt("wikidata", lambda: rg_item(rg, session, info))
    if item:
        found.update(wd_year=item["wd_year"], label=item["label"], q=item["q"])
    lang = None
    if item and item["enwiki"]:
        got = attempt("wikipedia", lambda: english_notes(item["enwiki"], session, True))
        if got:
            return got
    elif item:
        # a confirmed album with no English article: never a guess by title
        if args.translator:
            lang = attempt("wikidata", lambda: artist_language(who, session))
            if lang:
                got = attempt("other languages", lambda: foreign_notes(item, lang, session, args.translator))
                if got:
                    return got
    else:
        title, _ = attempt("wikipedia", lambda: guess_title(info, session)) or (None, False)
        if title:
            got = attempt("wikipedia", lambda: english_notes(title, session, False))
            if got:
                # the article names the artist, so its item gives the year
                ent = attempt("wikidata", lambda: title_item(title, session))
                if ent:
                    found.update(wd_year=wd_year(ent), q=ent.get("id"),
                                 label="" if info.get("label") else wd_label(ent, session))
                return got
    names = list(dict.fromkeys(n for n in (who.get("name"), ab.clean_artist(info["artist"]),
                                           info["folder_artist"]) if n))
    if args.lastfm_key:
        text = attempt("last.fm", lambda: lastfm_notes(info, names, session, args.lastfm_key, mbid=mb.get("id")))
        if text:
            return ab.trim_bio(text).split("\n") + [tr.credit("lastfm")], "last.fm"
        if args.translator:
            lang = lang or attempt("wikidata", lambda: artist_language(who, session))
            if lang:
                text = attempt("last.fm", lambda: lastfm_notes(info, names, session, args.lastfm_key, lang,
                                                               mbid=mb.get("id")))
                if text and tr.needs_translation(text, lang):
                    english = args.translator.translate(text.split("\n"), lang)
                    if english:
                        return (ab.trim_bio("\n".join(english)).split("\n")
                                + [tr.credit("lastfm", lang=lang)]), f"last.fm ({lang}, translated)"
    if args.discogs_token:
        text = attempt("discogs", lambda: discogs_notes(info, session, args.discogs_token, rec))
        if text:
            return ab.trim_bio(text).split("\n") + [tr.credit("discogs")], "discogs"
    return [], ""


# ---------------------------------------------------------------- main
def artist_ids(folder_artist):
    """The artist's Wikidata and MusicBrainz IDs and proper name, as
    artist_bios.py confirmed them."""
    name = ab.safe_name(folder_artist)
    m = ab.load_json(ab.CACHE / f"{name}.json") if name else None
    if not m or not m.get("identity_verified", True):
        return {}
    return {"wikidata": m.get("wikidata"), "mbid": m.get("mbid"), "name": m.get("name")}

def due(meta, days):
    if not days:
        return False
    try:
        age = time.time() - time.mktime(time.strptime(meta.get("fetched", ""), "%Y-%m-%d"))
    except ValueError:
        return True
    return age > days * 86400

def main(argv=None):
    conf = ab.settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_root", help="the iPod's music folder, Artist\\Album folders")
    ap.add_argument("--ipod", help="the iPod's own folder (default: the folder holding the music folder)")
    ap.add_argument("--refresh", action="store_true", help="fetch every album's notes again")
    ap.add_argument("--retry-not-found", action="store_true",
                    help="look again now for every album no notes were found for")
    ap.add_argument("--retry-after", type=int, default=ab.setting_days(conf, "recheck missing days", 30),
                    metavar="DAYS", help="look again for an album with no notes once this many days "
                                         "have passed (default 30; 0 = never)")
    ap.add_argument("--refresh-after", type=int, default=ab.setting_days(conf, "notes recheck days", 365),
                    metavar="DAYS",
                    help="check an album's notes again once they are this old (default 365; 0 = never)")
    ap.add_argument("--only", action="append", default=[],
                    help='just this artist, or "Artist - Album" (can be given more than once)')
    ap.add_argument("--no-banners", action="store_true", default=not ab.setting_on(conf, "banners", True),
                    help="notes only, no covers")
    ap.add_argument("--discogs-token", default=conf.get("discogs token") or os.environ.get("DISCOGS_TOKEN"),
                    help="Discogs personal token, an extra source (or set DISCOGS_TOKEN)")
    ap.add_argument("--deepl-key", default=conf.get("deepl key") or os.environ.get("DEEPL_KEY"),
                    help="DeepL key, to translate notes for artists who don't work in English")
    args = ap.parse_args(argv)
    args.lastfm_key = ab.af.load_credentials().lastfm_api_key or None

    music = Path(args.music_root)
    if not music.is_dir():
        print(f"Can't find {music}")
        return 1
    if not ab.ipod_page_on(Path(args.ipod) if args.ipod else music.resolve().parent, "album notes"):
        print("Album Notes is switched off on the iPod, so no album notes are fetched.")
        return 0
    out_dir = Path(args.ipod) / "Artwork" / "Notes" if args.ipod else music.resolve().parent / "Artwork" / "Notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"Writing liner notes to {out_dir}")
    session = requests.Session()
    args.translator = tr.Translator(args.deepl_key, CACHE.parent / "translations.json", session)
    if args.translator:
        print("Translating notes for artists who don't work in English, with DeepL")
    print("Reading the album folders...")

    only = {ab.norm(o) for o in args.only}
    seen = ab.load_json(FOLDERS) or {}
    work = []
    for artist, folders in sorted(ab.scan_library(music).items(), key=lambda kv: kv[0].casefold()):
        if only and not any(o.startswith(ab.norm(artist)) for o in only):
            continue
        for folder in sorted(folders):
            try:
                info = album_info(folder, artist, seen)
            except OSError as e:
                print(f"  !! {folder}: {e}")
                continue
            if not info:
                continue
            info["folder_artist"] = artist
            key = f"{info['artist']} - {info['album']}"
            if only and ab.norm(artist) not in only and ab.norm(info["artist"]) not in only \
                    and ab.norm(key) not in only:
                continue
            work.append((artist, folder, info, key))
    ab.save_json(FOLDERS, seen)
    print(f"{len(work)} albums\n")

    counts = {"written": 0, "same": 0, "kept": 0, "error": 0}
    try:
        for i, (artist, folder, info, key) in enumerate(work, 1):
            name = ab.safe_name(key)
            if not name:
                print(f"{i:4d}/{len(work)} {key}\n     skipped: the name is too long for the iPod to open")
                continue
            mp = CACHE / f"{name}.json"
            meta = ab.load_json(mp)
            fresh = False
            try:
                missing = meta is not None and not meta.get("notes")
                rg = ((ids_record(info).get("mb") or {}).get("rg"))
                # ids.py settled on a different album than these notes were found for
                moved = bool(meta and rg and meta.get("rg") and meta["rg"] != rg)
                if meta is None or args.refresh or due(meta, args.refresh_after) or moved or \
                        (missing and (args.retry_not_found or due(meta, args.retry_after))):
                    fresh = True
                    print(f"{i:4d}/{len(work)} {key}")
                    add_minutes(info, meta)
                    found = {}
                    paras, source = find_notes(info, artist_ids(artist), session, args, found)
                    new = {"key": key, "notes": "\n".join(paras), "source": source,
                           "rg": (found.get("rg") or {}).get("id"), "wikidata": found.get("q"),
                           "year": release_year(info, found), "label": found.get("label", ""),
                           "tracks": info["tracks"], "minutes": info["minutes"],
                           "fetched": time.strftime("%Y-%m-%d")}
                    if meta:
                        new.update({k: meta[k] for k in ("txt_sha1", "jpg_sha1") if k in meta})
                        if not args.refresh and ab.same_bio(meta.get("notes"), new["notes"]):
                            new["notes"], new["source"] = meta["notes"], meta.get("source", "")
                        if meta.get("notes") and not new["notes"]:
                            # a source being down never costs notes already found
                            new["notes"], new["source"] = meta["notes"], meta.get("source", "")
                    meta = new
                    print(f"     notes: {meta['source'] or 'facts only'}")
                if "year" in meta:
                    info["minutes"] = info["minutes"] or meta.get("minutes")
                    facts = facts_line(info, meta["year"], meta.get("label", ""))
                else:                   # a record from before the year was looked up: as it was
                    facts = meta.get("facts", "")
                text = f"{clean_title(info['album'])}\n{facts}\n\n{tr.plain(meta['notes'])}\n"
                res = [ab.write_if_ours(out_dir / f"{name}.txt", text.encode("utf-8"), meta, "txt_sha1")]
                jpg = out_dir / f"{name}.jpg"
                if not args.no_banners and (fresh or not jpg.exists()):
                    cover = ab.album_cover([folder] + [d for d in folder.iterdir() if d.is_dir()])[0]
                    if cover:
                        res.append(ab.write_if_ours(jpg, ab.banner_bytes(cover, True), meta, "jpg_sha1"))
                ab.save_json(mp, meta)
                counts["written" if "written" in res else "kept" if "kept" in res else "same"] += 1
            except Exception as e:
                counts["error"] += 1
                ab.problem(key, e)
    except KeyboardInterrupt:
        print("\nStopped. Run again to carry on where it left off.")

    # the list covers every album in scope, whether or not this run reached it
    missing = []
    for _, _, _, key in work:
        m = ab.load_json(CACHE / f"{ab.safe_name(key)}.json") if ab.safe_name(key) else None
        if m is not None and not m.get("notes"):
            missing.append(key)
    if not only:
        ab.atomic_write(MISSING_LIST, ("\n".join(missing) + ("\n" if missing else "")).encode("utf-8"))
    print(f"\nLiner notes written or updated: {counts['written']}, unchanged: {counts['same']}, "
          f"kept as you left them: {counts['kept']}, facts only: {len(missing)}"
          + (f", failed: {counts['error']}" if counts["error"] else ""))
    if missing and not only:
        print(f"Albums with only a facts line are listed in \"{MISSING_LIST.name}\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
