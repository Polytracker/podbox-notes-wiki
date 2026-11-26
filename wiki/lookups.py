"""The lookups ipod-liner-notes doesn't do, saved beside its own caches in
%APPDATA%\\RockboxArtistArt\\notes wiki\\.

- discographies(): each artist's studio albums, for the Bio page's Studio
  Albums (all of them, not just the library's). Wikidata first, for every
  artist in one query; MusicBrainz for those Wikidata has none for (it marks
  studio albums best, but answers one request a second, and less when busy,
  so it's left for the run after BUSY_MAX failures in a row); Discogs last,
  which doesn't mark studio albums, so its list is filtered by format and
  title (FROM_DISCOGS_NOT).
- people(): key people's bios, many at a time. Wikidata gives each
  MusicBrainz ID's item, English Wikipedia article, dates and picture in one
  query for hundreds of people; Wikipedia gives article openings 20 at a
  time; Last.fm (by MusicBrainz ID) and Discogs (by Discogs ID) only for
  those Wikipedia has nothing on. A person is only ever found by an ID, never
  by name, so no one of the same name can slip in.
- photo(): a key person's picture from Wikimedia Commons, for those who get
  a page.

Each is looked up once and kept; one found nothing is looked for again
after `retry_days`, and a found one after `refresh_days`.
"""
import re
import time

from . import ab
from . import show
import ids
import liner_notes as ln

SPARQL = "https://query.wikidata.org/sparql"
SPARQL_BATCH = 200

CACHE = ab.CACHE.parent / "notes wiki"
DISCS = CACHE / "discographies"
PEOPLE = CACHE / "people"


def _age_days(meta):
    try:
        return (time.time() - time.mktime(time.strptime(meta.get("fetched", ""), "%Y-%m-%d"))) / 86400
    except (ValueError, OverflowError):
        return float("inf")


def studio_albums(groups):
    """MusicBrainz release groups -> the studio albums, oldest first."""
    out = []
    for rg in groups:
        if rg.get("primary-type") != "Album" or rg.get("secondary-types"):
            continue
        out.append({"id": rg["id"], "title": rg.get("title") or "",
                    "year": ab.year((rg.get("first-release-date") or "")[:4])})
    out.sort(key=lambda r: (r["year"] or "9999", r["title"].casefold()))
    return out


BUSY_MAX = 3
WD_ALBUMS_BATCH = 50
DC_PAGES_MAX = 2            # Discogs is trusted only for an artist this small: past it,
                            # its "main" entries are mostly singles it doesn't tell apart
MB_GAP = 1.1
STUDIO_ALBUM = "Q208569"
FROM_DISCOGS_NOT = re.compile(r"\b(live|greatest|best of|hits|collection|anthology|essential|remix(es)?|"
                              r"demos?|sessions|b-sides|rarities|singles|ep|soundtrack|tour)\b", re.I)


def _disc_path(key):
    return DISCS / f"{re.sub(r'[^A-Za-z0-9_-]', '', key)}.json"


def _disc_key(a):
    """Where an artist's list is kept: by MusicBrainz ID, else Wikidata, else
    Discogs (lists saved by MusicBrainz ID before keep being found)."""
    if a.get("mbid"):
        return a["mbid"]
    return f"wd_{a['qid']}" if a.get("qid") else (f"dc_{a['dcid']}" if a.get("dcid") else None)


def _save_disc(a, albums, source):
    DISCS.mkdir(parents=True, exist_ok=True)
    ab.save_json(_disc_path(_disc_key(a)), {**{k: v for k, v in a.items() if v}, "source": source,
                                             "fetched": time.strftime("%Y-%m-%d"), "albums": albums})
    return albums


_mb_last = [0.0]


def mb_once(session, url, params):
    """One MusicBrainz request, a second apart, not retried: a busy answer is
    None at once, so a busy MusicBrainz costs seconds, not minutes."""
    wait = _mb_last[0] + MB_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    _mb_last[0] = time.time()
    try:
        r = session.get(url, params=params, headers={"User-Agent": ids.UA, "Accept": "application/json"},
                        timeout=30)
    except ab.NET_ERRORS:
        return None
    return r.json() if r.status_code == 200 else None


def mb_albums(mbid, site):
    """The studio albums MusicBrainz has for an artist, or None if it didn't
    answer. `site` is a requests session (one try a request) or an ids.Site."""
    groups, offset = [], 0
    get = site.get if isinstance(site, ids.Site) else \
        (lambda url, params: mb_once(site, url, params))
    while True:
        data = get(f"{ids.MB}release-group", {"artist": mbid, "type": "album", "limit": 100,
                                               "offset": offset, "fmt": "json"})
        if data is None:
            return None
        page = data.get("release-groups") or []
        groups += page
        offset += len(page)
        if not page or offset >= (data.get("release-group-count") or 0):
            return studio_albums(groups)


def wd_albums(qids, session):
    """{artist's Wikidata item: [studio albums]} for many artists, a query per
    WD_ALBUMS_BATCH; None for a batch Wikidata didn't answer."""
    out = {}
    for n in range(0, len(qids), WD_ALBUMS_BATCH):
        batch = [q for q in qids[n:n + WD_ALBUMS_BATCH] if re.fullmatch(r"Q\d+", q)]
        if not batch:
            continue
        query = ("SELECT ?artist ?album ?albumLabel ?date ?rg WHERE { "
                 f"VALUES ?artist {{ {' '.join('wd:' + q for q in batch)} }} "
                 f"?album wdt:P175 ?artist . {{ ?album wdt:P31 wd:{STUDIO_ALBUM} }} "
                 f"UNION {{ ?album wdt:P7937 wd:{STUDIO_ALBUM} }} "
                 "OPTIONAL { ?album wdt:P577 ?date } OPTIONAL { ?album wdt:P436 ?rg } "
                 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". } }')
        r = sparql(session, query)
        if r is None or not r.ok:
            show.warn(f"Wikidata didn't answer for {len(batch)} artists "
                      f"({getattr(r, 'status_code', 'no answer')}): asking MusicBrainz and Discogs instead")
            for q in batch:
                out[q] = None
            continue
        found = {q: {} for q in batch}
        for b in (r.json().get("results") or {}).get("bindings") or []:
            v = {k: x.get("value", "") for k, x in b.items()}
            q, item = v["artist"].rsplit("/", 1)[-1], v["album"].rsplit("/", 1)[-1]
            title = v.get("albumLabel") or ""
            if q not in found or not title or re.fullmatch(r"Q\d+", title):
                continue
            rec = found[q].setdefault(item, {"id": v.get("rg") or f"wd:{item}", "title": title, "year": ""})
            y = ab.year((v.get("date") or "")[:4])
            if y and (not rec["year"] or y < rec["year"]):
                rec["year"] = y
            if v.get("rg") and rec["id"].startswith("wd:"):
                rec["id"] = v["rg"]
        for q, albums in found.items():
            out[q] = sorted(albums.values(), key=lambda r: (r["year"] or "9999", r["title"].casefold()))
    return out


def dc_albums(dcid, site, note=lambda s: None):
    """The artist's own albums on Discogs, as well as they can be told from
    the rest: their main masters, less anything whose title says live,
    best-of, soundtrack and so on. Discogs doesn't mark singles, so for an
    artist with more than DC_PAGES_MAX pages, whose main entries are mostly
    singles, it's [] (no list: the page shows the albums you own). None if
    Discogs didn't answer."""
    out, page = [], 1
    while True:
        data = site.get(f"{ids.DISCOGS}artists/{dcid}/releases",
                        {"sort": "year", "sort_order": "asc", "per_page": 100, "page": page})
        if data is None:
            return None
        for r in data.get("releases") or []:
            if r.get("type") != "master" or r.get("role") != "Main" or FROM_DISCOGS_NOT.search(r.get("title") or ""):
                continue
            out.append({"id": f"dc:{r['id']}", "title": r.get("title") or "", "year": str(r.get("year") or "")})
        pages = (data.get("pagination") or {}).get("pages") or 1
        if pages > DC_PAGES_MAX:
            return []
        if page >= pages:
            return out
        page += 1
        note(f"page {page} of {pages}")


def discographies(artists, session=None, mb=None, dc=None, refresh_days=180, say=show.info):
    """{album artist: [{id, title, year}]} for {album artist: {mbid, qid, dcid}}.
    With no sites, only what was saved."""
    out, due, guessed = {}, {}, set()
    for tag, a in artists.items():
        key = _disc_key(a)
        if not key:
            continue
        saved = ab.load_json(_disc_path(key))
        if saved:
            out[tag] = saved.get("albums")
        fresh = saved and _age_days(saved) < refresh_days
        if session is not None and fresh and saved.get("source") == "discogs":
            guessed.add(tag)                    # Discogs' list was a guess: Wikidata may have better
            due[tag] = dict(a)
        elif session is not None and not fresh:
            due[tag] = dict(a)
    say(f"{len(out)} already saved, {len(due)} to look up")
    if not due:
        return out
    with show.Spinner(f"Asking Wikidata for {len(due)} artists' studio albums"):
        need_qid = sorted({a["mbid"] for a in due.values() if a.get("mbid") and not a.get("qid")})
        if need_qid:
            by_mbid = wikidata_by_mbid(need_qid, session)
            for a in due.values():
                if not a.get("qid") and a.get("mbid") in by_mbid:
                    a["qid"] = by_mbid[a["mbid"]]["wikidata"]
        wd = wd_albums(sorted({a["qid"] for a in due.values() if a.get("qid")}), session)
    rest = []
    for tag, a in due.items():
        albums = wd.get(a.get("qid"))
        if albums:
            out[tag] = _save_disc(a, albums, "wikidata")
        elif tag not in guessed:                # a Discogs list still fresh is kept as it is
            rest.append(tag)
    say(f"Wikidata had {len(due) - len(rest)}; MusicBrainz and Discogs for {len(rest)}")
    busy = 0
    bar = show.Bar("MusicBrainz and Discogs", len(rest))
    for tag in rest:
        bar.update(note=tag)
        a, albums = due[tag], None
        if mb is not None and a.get("mbid") and busy < BUSY_MAX:
            albums = mb_albums(a["mbid"], session)
            busy = busy + 1 if albums is None else 0
            if busy == BUSY_MAX:
                show.warn("MusicBrainz isn't answering: the rest go to Discogs this run")
            if albums:
                out[tag] = _save_disc(a, albums, "musicbrainz")
                continue
        if dc is not None and a.get("dcid"):
            got = dc_albums(a["dcid"], dc, note=lambda s, t=tag: bar.update(0, f"{t}, Discogs {s}"))
            if got is not None:
                albums = got
                out[tag] = _save_disc(a, albums, "discogs")
                continue
        if albums is not None:                # an answer of none is kept as one
            out[tag] = _save_disc(a, albums, "musicbrainz")
    bar.close(f"{sum(1 for t in rest if out.get(t))} found")
    return out


def person_key(mbid, dcid):
    return f"mb_{mbid}" if mbid else f"dc_{dcid}"


SENTENCE = re.compile(r"[.!?](?:\s|$)")


def enough_bio(meta):
    """The page test (design point 6): an English Wikipedia article, or at
    least three sentences from anywhere else."""
    if not meta or not meta.get("bio") or meta.get("bio_source") in ("", "facts"):
        return False
    if meta.get("bio_source") == "wikipedia" and not meta.get("bio_lang"):
        return True
    return len(SENTENCE.findall(meta["bio"])) >= 3


def saved_person(mbid, dcid):
    key = person_key(mbid, dcid)
    return ab.load_json(PEOPLE / f"{key}.json"), PEOPLE / f"{key}.jpg"


# ---------------------------------------------------------------- many at a time
def _due(meta, retry_days, refresh_days):
    if not meta:
        return True
    return _age_days(meta) >= (refresh_days if enough_bio(meta) else retry_days)


def wikidata_by_mbid(mbids, session):
    """{MusicBrainz ID: {wikidata, article, image, born, died, human}} from
    Wikidata, SPARQL_BATCH IDs a query. An ID Wikidata doesn't know is left out."""
    out = {}
    for n in range(0, len(mbids), SPARQL_BATCH):
        batch = mbids[n:n + SPARQL_BATCH]
        values = " ".join(f'"{m}"' for m in batch if re.fullmatch(r"[0-9a-f-]{36}", m))
        if not values:
            continue
        query = ("SELECT ?mbid ?item ?article ?image ?born ?died ?human WHERE { "
                 f"VALUES ?mbid {{ {values} }} ?item wdt:P434 ?mbid . "
                 "OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } "
                 "OPTIONAL { ?item wdt:P18 ?image } OPTIONAL { ?item wdt:P569 ?born } "
                 "OPTIONAL { ?item wdt:P570 ?died } "
                 "BIND(EXISTS { ?item wdt:P31 wd:Q5 } AS ?human) }")
        r = sparql(session, query)
        if r is None or not r.ok:
            print(f"     wikidata: {getattr(r, 'status_code', 'no answer')}, {len(batch)} people left for next time")
            continue
        for b in (r.json().get("results") or {}).get("bindings") or []:
            v = {k: x.get("value", "") for k, x in b.items()}
            rec = out.setdefault(v["mbid"], {"wikidata": v["item"].rsplit("/", 1)[-1]})
            if v.get("article") and "article" not in rec:
                rec["article"] = urllib_unquote(v["article"].rsplit("/wiki/", 1)[-1]).replace("_", " ")
            for k in ("image", "born", "died"):
                if v.get(k) and k not in rec:
                    rec[k] = v[k]
            rec["human"] = v.get("human") == "true"
    return out


def sparql(session, query):
    """A Wikidata query, sent as a form (a long one is too long for a URL),
    with the User-Agent Wikimedia asks for, waiting when told it's busy."""
    for attempt in range(4):
        try:
            r = session.post(SPARQL, data={"query": query, "format": "json"}, headers=ab.WIKI_UA, timeout=60)
        except ab.NET_ERRORS as e:
            ab.problem("wikidata", e)
            return None
        if r.status_code not in (429, 503):
            return r
        time.sleep(int(r.headers.get("Retry-After", "0") or 0) or 15 * (attempt + 1))
    return r


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


def people(wanted, session, args, online=True, retry_days=30, refresh_days=365, say=show.info):
    """{key: record} for [(key, name, MusicBrainz ID, Discogs ID)], looking up
    those due. `args` gives lastfm_key and discogs_token."""
    PEOPLE.mkdir(parents=True, exist_ok=True)
    have, due = {}, []
    for key, name, mbid, dcid in wanted:
        meta, _ = saved_person(mbid, dcid)
        have[key] = meta
        if online and _due(meta, retry_days, refresh_days):
            due.append((key, name, mbid, dcid))
    say(f"{len(wanted) - len(due):,} already saved, {len(due):,} to look up")
    if not due:
        return have
    today = time.strftime("%Y-%m-%d")
    mbids = sorted({m for _, _, m, _ in due if m})
    with show.Spinner(f"Asking Wikidata about {len(mbids):,} people, {SPARQL_BATCH} a query"):
        wd = wikidata_by_mbid(mbids, session)
    say(f"Wikidata knows {len(wd):,} of them")
    titles = sorted({wd[m]["article"] for _, _, m, _ in due if m in wd and wd[m].get("article")})
    intros = {}
    bar = show.Bar("Wikipedia", len(titles))
    for n in range(0, len(titles), 20):
        intros.update(ln.wiki_summaries(titles[n:n + 20], session))
        bar.update(len(titles[n:n + 20]))
    bar.close(f"{len(intros):,} articles read")
    found, rest = [], []
    for item in due:
        w = wd.get(item[2]) or {}
        (found if intros.get(w.get("article") or "") else rest).append(item)
    asked = args.lastfm_key or args.discogs_token
    bar = show.Bar("Last.fm and Discogs", len(rest) if asked else 0)
    for key, name, mbid, dcid in found + rest:
        w = wd.get(mbid) or {}
        new = {"artist": name, "mbid": mbid, "discogs": dcid, "wikidata": w.get("wikidata"),
               "image": w.get("image", ""), "bio": "", "bio_source": "", "fetched": today,
               "subtitle": ab.life_dates(w.get("human", True), w.get("born"), w.get("died"))}
        text = intros.get(w.get("article") or "")
        if text:
            new.update(bio=ab.trim_bio(text), bio_source="wikipedia", bio_title=w["article"], bio_date=today)
        elif asked:
            bar.update(note=name)
            try:
                if args.lastfm_key and mbid:
                    text = ab.lastfm_bio(name, session, args.lastfm_key, mbid)
                    if text:
                        new.update(bio=ab.trim_bio(text), bio_source="lastfm", bio_date=today)
                if not new["bio"] and args.discogs_token and dcid:
                    d = ab.discogs_artist(name, session, args.discogs_token, dcid)
                    if d and d[1]:
                        new.update(bio=ab.trim_bio(d[1]), bio_source="discogs", bio_date=today)
            except ab.NET_ERRORS as e:
                ab.problem(name, e)
        old = have.get(key)
        for k in ("photo_source", "photo_tried"):          # what the photo ladder found is kept
            if old and old.get(k):
                new[k] = old[k]
        if old and enough_bio(old) and not enough_bio(new):
            new.update({k: old.get(k) for k in ab.BIO_FIELDS})      # a site being down costs nothing
        ab.save_json(PEOPLE / f"{person_key(mbid, dcid)}.json", new)
        have[key] = new
    if asked:
        bar.close(f"{sum(1 for k, *_ in rest if enough_bio(have[k])):,} more bios found")
    return have


IMAGE_HEADS = (b"\xff\xd8\xff", b"\x89PN")
PHOTO_RETRY_DAYS = 30
PHOTO_SOURCES = ("Wikimedia Commons", "Discogs")


def _image(data):
    """The bytes when they're a picture Pillow can read: JPEG, PNG or WebP
    (Commons now sends some pictures as WebP)."""
    if not data:
        return None
    if data[:3] in IMAGE_HEADS or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return data
    return None


def _get(session, url, params=None, headers=None):
    try:
        r = session.get(url, params=params, headers={**ab.UA, **(headers or {})}, timeout=30)
    except ab.NET_ERRORS:
        return None
    return r if r.ok else None


def _commons(meta, session, keys):
    url = meta.get("image") or ""
    if not url.startswith("http"):
        return None
    try:
        r = ab.wiki_get(session, url.replace("http://", "https://"), {"width": 640})
    except ab.NET_ERRORS as e:
        ab.problem(meta.get("artist", ""), e)
        return None
    return _image(r.content) if r.ok else None


def _discogs(meta, session, keys):
    if not meta.get("discogs") or not keys.get("discogs token"):
        return None
    time.sleep(1.1)                                     # Discogs: 60 a minute with a token
    r = _get(session, f"{ids.DISCOGS}artists/{meta['discogs']}",
             headers={"Authorization": f"Discogs token={keys['discogs token']}"})
    imgs = (r.json().get("images") or []) if r else []
    pick = next((i for i in imgs if i.get("type") == "primary"), imgs[0] if imgs else None)
    url = (pick or {}).get("uri")
    got = _get(session, url, headers={"Authorization": f"Discogs token={keys['discogs token']}"}) if url else None
    return _image(got.content) if got else None


# The quickest sources only (Joe, 26 Nov): TheAudioDB (30 requests a minute)
# and fanart.tv would add about 20 people for a quarter of an hour more
LADDER = (("Wikimedia Commons", _commons), ("Discogs", _discogs))


def photo_keys(conf):
    """The keys the ladder uses: the Discogs token from the settings or keys file."""
    return {"discogs token": (conf.get("discogs token") or "").strip()}


def photo(meta, session, keys=None):
    """A key person's picture, saved beside their record; its path, or None.
    Asked of each source in turn, always by the person's own ID and never by
    name (point 5, Joe 26 Nov): their Wikidata item's picture on Wikimedia
    Commons, then Discogs by Discogs ID. Which gave it is kept in the record (for the page's credit line); a
    person none had a picture for is asked again after PHOTO_RETRY_DAYS."""
    mbid, dcid = meta.get("mbid"), meta.get("discogs")
    rec_path = PEOPLE / f"{person_key(mbid, dcid)}.json"
    _, jpg = saved_person(mbid, dcid)
    if jpg.exists():
        return jpg
    if session is None:
        return None
    tried = meta.get("photo_tried")
    if tried and _age_days({"fetched": tried}) < PHOTO_RETRY_DAYS:
        return None
    keys = keys or {}
    for name, ask in LADDER:
        data = ask(meta, session, keys)
        if data:
            ab.atomic_write(jpg, data)
            meta["photo_source"] = name
            meta.pop("photo_tried", None)
            ab.save_json(rec_path, meta)
            return jpg
    meta["photo_tried"] = time.strftime("%Y-%m-%d")
    ab.save_json(rec_path, meta)
    return None


def photo_credit(meta):
    """The page's photo credit line, or ''."""
    meta = meta or {}
    src = meta.get("photo_source") or ""
    if not src and "discogs" in meta and (meta.get("image") or "").startswith("http") \
            and saved_person(meta.get("mbid"), meta.get("discogs"))[1].exists():
        src = "Wikimedia Commons"               # a key person's photo saved before the ladder kept its source
    if src in PHOTO_SOURCES:
        return f"Photo from {src}"
    low = src.lower()
    for name in ("Last.fm", "fanart.tv", "TheAudioDB", "Deezer", "MusicBrainz", "Discogs"):
        if name.lower().replace(".", "") in low.replace(".", ""):
            return f"Photo from {name}"
    return ""
