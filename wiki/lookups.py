"""The lookups ipod-liner-notes doesn't do, saved beside its own caches in
%APPDATA%\\RockboxArtistArt\\notes wiki\\.

- discography(): an artist's studio albums from MusicBrainz, for the Bio
  page's Studio Albums (all of them, not just the library's).
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


def discography(mbid, site=None, refresh_days=180):
    """[{id, title, year}] for the artist's studio albums, or None if never
    looked up. With `site` None, only what was saved."""
    path = DISCS / f"{re.sub(r'[^A-Za-z0-9-]', '', mbid)}.json"
    saved = ab.load_json(path)
    if site is None or (saved and _age_days(saved) < refresh_days):
        return saved.get("albums") if saved else None
    groups, offset = [], 0
    while True:
        data = site.get(f"{ids.MB}release-group", {"artist": mbid, "type": "album", "limit": 100,
                                                    "offset": offset, "fmt": "json"})
        if data is None:
            return saved.get("albums") if saved else None
        page = data.get("release-groups") or []
        groups += page
        offset += len(page)
        if not page or offset >= (data.get("release-group-count") or 0):
            break
    DISCS.mkdir(parents=True, exist_ok=True)
    rec = {"mbid": mbid, "fetched": time.strftime("%Y-%m-%d"), "albums": studio_albums(groups)}
    ab.save_json(path, rec)
    return rec["albums"]


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


def people(wanted, session, args, online=True, retry_days=30, refresh_days=365, say=print):
    """{key: record} for [(key, name, MusicBrainz ID, Discogs ID)], looking up
    those due. `args` gives lastfm_key and discogs_token."""
    PEOPLE.mkdir(parents=True, exist_ok=True)
    have, due = {}, []
    for key, name, mbid, dcid in wanted:
        meta, _ = saved_person(mbid, dcid)
        have[key] = meta
        if online and _due(meta, retry_days, refresh_days):
            due.append((key, name, mbid, dcid))
    if not due:
        return have
    today = time.strftime("%Y-%m-%d")
    say(f"  looking up {len(due)} of {len(wanted)}: Wikidata")
    wd = wikidata_by_mbid(sorted({m for _, _, m, _ in due if m}), session)
    titles = sorted({wd[m]["article"] for _, _, m, _ in due if m in wd and wd[m].get("article")})
    say(f"  Wikipedia: {len(titles)} articles")
    intros = {}
    for n in range(0, len(titles), 20):
        intros.update(ln.wiki_summaries(titles[n:n + 20], session))
    rest = 0
    for key, name, mbid, dcid in due:
        w = wd.get(mbid) or {}
        new = {"artist": name, "mbid": mbid, "discogs": dcid, "wikidata": w.get("wikidata"),
               "image": w.get("image", ""), "bio": "", "bio_source": "", "fetched": today,
               "subtitle": ab.life_dates(w.get("human", True), w.get("born"), w.get("died"))}
        text = intros.get(w.get("article") or "")
        if text:
            new.update(bio=ab.trim_bio(text), bio_source="wikipedia", bio_title=w["article"], bio_date=today)
        else:
            rest += 1
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
        if old and enough_bio(old) and not enough_bio(new):
            new.update({k: old.get(k) for k in ab.BIO_FIELDS})      # a site being down costs nothing
        ab.save_json(PEOPLE / f"{person_key(mbid, dcid)}.json", new)
        have[key] = new
    say(f"  Last.fm and Discogs asked about {rest}")
    return have


def photo(meta, session):
    """The person's Wikimedia Commons picture, saved beside their record; its
    path, or None."""
    mbid, dcid = meta.get("mbid"), meta.get("discogs")
    _, jpg = saved_person(mbid, dcid)
    if jpg.exists():
        return jpg
    url = meta.get("image") or ""
    if not url.startswith("http"):
        return None
    try:
        r = ab.wiki_get(session, url.replace("http://", "https://"), {"width": 640})
        data = r.content if r.ok and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN") else None
    except ab.NET_ERRORS as e:
        ab.problem(meta.get("artist", ""), e)
        data = None
    if data:
        ab.atomic_write(jpg, data)
        return jpg
    return None
