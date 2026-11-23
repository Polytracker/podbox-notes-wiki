"""The lookups ipod-liner-notes doesn't do, saved beside its own caches in
%APPDATA%\\RockboxArtistArt\\notes wiki\\.

- discography(): an artist's studio albums from MusicBrainz, for the Bio
  page's Studio Albums (all of them, not just the library's).
- person(): a key person's bio, facts line and photo, by the same ladder
  artist_bios.py uses for artists (artist_bios.fetch()), started from their
  MusicBrainz ID so no one of the same name can slip in. Someone known only
  to Discogs gets their Discogs profile alone: a search by name could find
  someone else.

Each is looked up once and kept; one found nothing is looked for again
after `retry_days`, and a found one after `refresh_days`.
"""
import re
import time

from . import ab
import ids

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


def person(name, mbid, dcid, session, args, retry_days=30, refresh_days=365):
    """(record, photo path or None) for a key person; looks them up when due.
    `args` is what artist_bios.fetch() takes: lastfm_key, discogs_token,
    translator, long_bio, no_banners."""
    meta, jpg = saved_person(mbid, dcid)
    found = enough_bio(meta)
    if meta and _age_days(meta) < (refresh_days if found else retry_days):
        return meta, (jpg if jpg.exists() else None)
    PEOPLE.mkdir(parents=True, exist_ok=True)
    photo = None
    if mbid:
        args._dc_id = dcid
        new, photo = ab.fetch(name, [], session, args, {"ids": {"mbid": mbid, "discogs": dcid}})
    else:
        new = {"artist": name, "bio": "", "bio_source": "", "subtitle": "",
               "fetched": time.strftime("%Y-%m-%d")}
        if args.discogs_token and dcid:
            try:
                d = ab.discogs_artist(name, session, args.discogs_token, dcid)
            except ab.NET_ERRORS as e:
                ab.problem("discogs", e)
                d = None
            if d and d[1]:
                new.update(bio=ab.trim_bio(d[1]), bio_source="discogs", bio_date=time.strftime("%Y-%m-%d"))
    new.update(mbid=mbid, discogs=dcid)
    if meta and enough_bio(meta) and not enough_bio(new):
        new.update({k: meta.get(k) for k in ab.BIO_FIELDS})     # a site being down costs nothing
    if photo and new.get("photo_source") not in ("album cover", "artist photo"):
        ab.atomic_write(jpg, photo)
    ab.save_json(PEOPLE / f"{person_key(mbid, dcid)}.json", new)
    return new, (jpg if jpg.exists() else None)
