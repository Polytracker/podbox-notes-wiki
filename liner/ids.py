"""
ids.py -- which release is each album? Worked out once, from the IDs already
in your files, and kept for every step that needs it (credits, track notes,
album notes, bios, art).

For each album folder it finds the MusicBrainz release and the Discogs
release, best evidence first:

  MusicBrainz                         Discogs
  1. MusicBrainz album ID in tags     1. Discogs release ID in tags
  2. Discogs ID in tags (via MB)      2. the release MusicBrainz links to
  3. barcode                          3. the master MusicBrainz links to
  4. ISRCs                               (main release, then the plainest editions)
  5. store links in tags (Deezer,     4. barcode
     Bandcamp, Apple, Spotify, ...)   5. catalogue number
  6. CD disc ID, catalogue number     6. artist + title search
  7. artist + title search

Every match is checked against your files: the artist, the track list (by
title, with remaster notes ignored) and the track lengths. A match that fails
drops to the next rung. An edition with more or fewer tracks than yours is
accepted only when the tracks line up, and the result says so, so the pages
can name exactly which edition their information is for.

Results are kept in %APPDATA%\\RockboxArtistArt\\ids\\, one small file per
album. An album is looked up again only when the IDs in its tags change (for
instance after tagging it in Picard), or, if nothing was found, after 30
days. It changes none of your files.

Usage:
  python ids.py                      the iPod's music folder, from the settings file
  python ids.py "Y:\\Music"
  python ids.py --only "Artist"      just one artist, or "Artist - Album"
  python ids.py --refresh            look everything up again
  python ids.py --retry-not-found    look again at albums nothing was found for

Writes "Albums not identified.txt" beside this file.
"""
from __future__ import annotations

import argparse, gzip, hashlib, json, os, re, sys, threading, time, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import requests, mutagen
    import artist_bios as ab
except ModuleNotFoundError as e:
    print(f"Missing something: {e}. Run: pip install requests mutagen")
    sys.exit(1)

FORMAT = 1                     # bump when a saved record's shape changes
MB = "https://musicbrainz.org/ws/2/"
DISCOGS = "https://api.discogs.com/"
DEEZER = "https://api.deezer.com/"
UA = "ipod-liner-notes/0.2 ( https://github.com/Polytracker/ipod-liner-notes )"
CACHE = ab.CACHE.parent / "ids"
RELEASES = CACHE / "releases"   # the matched releases, compressed, shared by the credits and links steps
RELEASE_DAYS = 180              # how long a saved release is reused before it's fetched again
LIBRARY = CACHE.parent / "library.json"   # the album keys found by the last full scan
MISSING_LIST = HERE / "Albums not identified.txt"
RETRY_DAYS = 30
VARIOUS = "89ad4ac3-39f7-470e-963a-56509c546377"
SINGLES = {"singles", "single", "misc", "miscellaneous", "loose tracks"}
LOOKUP_INC = ("artist-credits+recordings+release-groups+isrcs+labels+url-rels+artist-rels"
              "+recording-level-rels+work-rels+work-level-rels"     # works carry the songwriters
              "+release-group-level-rels")                         # the group's Wikidata and Discogs links
EXTRA = r"remaster|version|edit|mix|mono|stereo|live|demo|take|bonus|instrumental|deluxe|expanded|anniversary|edition"


# ================================================================ your files
ALIASES = {"TSRC": "ISRC", "TPOS": "DISCNUMBER", "TRCK": "TRACKNUMBER", "TPE2": "ALBUMARTIST",
           "TPE1": "ARTIST", "TALB": "ALBUM", "TIT2": "TITLE", "UPC": "BARCODE", "EAN": "BARCODE",
           "MUSICBRAINZALBUMID": "MBALBUM", "MUSICBRAINZDISCID": "DISCID",
           "DISCOGSRELEASEID": "DISCOGS", "DISCOGSRELEASE": "DISCOGS", "DISCOGSID": "DISCOGS",
           "DISCOGSALBUMID": "DISCOGS", "CATALOGNUMBER": "CATNO", "CATALOG": "CATNO", "CATALOGNO": "CATNO",
           "AART": "ALBUMARTIST", "©ALB": "ALBUM", "©ART": "ARTIST", "©NAM": "TITLE", "©CMT": "COMMENT",
           "TRKN": "TRACKNUMBER", "DISK": "DISCNUMBER", "PLID": "APPLEALBUM",
           "COMM": "COMMENT", "DESCRIPTION": "COMMENT", "WOAS": "URL", "WOAR": "URL", "WCOM": "URL",
           "WXXX": "URL", "WEBSITE": "URL", "SPOTIFYALBUMID": "SPOTIFYALBUM"}

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)

def norm_key(k):
    """A tag's name in one spelling across formats: "TXXX:MusicBrainz Album Id",
    "----:com.apple.iTunes:MusicBrainz Album Id" and "MUSICBRAINZ_ALBUMID" all
    become "MUSICBRAINZALBUMID"; ID3 comments and link frames become
    "COMMENT" and "URL"."""
    k = str(k)
    up = k.upper()
    if up.startswith("COMM"):
        return "COMMENT"
    if up[:4] in ("WXXX", "WOAS", "WOAR", "WCOM", "WOAF", "WPUB"):
        return "URL"
    for p in ("TXXX:", "----:COM.APPLE.ITUNES:"):
        if up.startswith(p):
            up = up[len(p):]
    return re.sub(r"[\s_]", "", up)

def text(v):
    """A tag's first value as text: ID3 frames, Vorbis lists, MP4 bytes."""
    if hasattr(v, "url"):
        v = v.url
    elif hasattr(v, "text"):
        v = v.text
    while isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return str(v).strip().strip("\x00")

# credit tags (ID3 frames by their usual names, Vorbis/MP4 by name) and the
# group each goes in; a tag's own role text wins where it has one
CREDIT_TAGS = {"COMPOSER": ("composer", "Songwriters"), "TCOM": ("composer", "Songwriters"),
               "©WRT": ("composer", "Songwriters"), "LYRICIST": ("lyricist", "Songwriters"),
               "TEXT": ("lyricist", "Songwriters"), "WRITER": ("writer", "Songwriters"),
               "SONGWRITER": ("writer", "Songwriters"), "PRODUCER": ("producer", "Producers"),
               "ENGINEER": ("engineer", "Engineers"), "MIXER": ("mix", "Engineers"),
               "MIXEDBY": ("mix", "Engineers"), "MASTEREDBY": ("mastering", "Engineers"),
               "ARRANGER": ("arranger", "Credited"), "TPE3": ("conductor", "Musicians"),
               "CONDUCTOR": ("conductor", "Musicians"), "PERFORMER": ("performer", "Musicians")}
PEOPLE_FRAMES = {"TMCL": "Musicians", "TIPL": None, "IPLS": None}

def all_texts(v):
    """Every value of a tag, not just the first."""
    if hasattr(v, "text"):
        v = v.text
    if not isinstance(v, (list, tuple)):
        v = [v]
    out = []
    for x in v:
        if isinstance(x, bytes):
            x = x.decode("utf-8", "replace")
        out += [y.strip() for y in re.split(r"\x00|; ", str(x)) if y.strip()]
    return out

def credit_pairs(name, v):
    """(person, role, group) from one credit tag, or []."""
    frame = name[:4]
    if frame in PEOPLE_FRAMES and hasattr(v, "people"):
        out = []
        for role, who in v.people:
            group = PEOPLE_FRAMES[frame] or dc_group(role)
            out += [(w, role or "performer", group) for w in all_texts(who)]
        return out
    base = name.split(":", 1)[0]
    if base not in CREDIT_TAGS:
        return []
    role, group = CREDIT_TAGS[base]
    if ":" in name:                                   # Vorbis "PERFORMER:GUITAR"
        role = name.split(":", 1)[1].lower()
    out = []
    for value in all_texts(v):
        m = re.match(r"^(.*?)\s*\(([^()]+)\)$", value) if base == "PERFORMER" else None
        out.append((m.group(1), m.group(2), group) if m else (value, role, group))
    return out

def read_track(p):
    """The tags the lookups use, whatever format the file is."""
    try:
        f = mutagen.File(p)
    except Exception:
        return None
    if f is None:
        return None
    out = {"path": p.name, "length": round(getattr(f.info, "length", 0) or 0, 1), "urls": []}
    for k in (f.tags.keys() if f.tags else []):
        name = ALIASES.get(norm_key(k), norm_key(k))
        try:
            v = f.tags[k]
            if name in ("TRACKNUMBER", "DISCNUMBER") and isinstance(v, list) and v and isinstance(v[0], tuple):
                v = str(v[0][0])                               # MP4 (track, total)
            value = text(v)
        except Exception:
            continue
        out["urls"] += URL_RE.findall(value)
        out.setdefault(name, value)
        try:
            out.setdefault("credits", []).extend(credit_pairs(name, f.tags[k]))
        except Exception:
            pass
    return out

def number(s, default):
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else default

def album_tracks(folder):
    files = [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in ab.AUDIO]
    if files:
        return files
    out = []
    for d in sorted(x for x in folder.iterdir() if x.is_dir()):
        out += [p for p in sorted(d.iterdir()) if p.is_file() and p.suffix.lower() in ab.AUDIO]
    return out

def store_links(first, urls):
    """Album pages on stores and Discogs, from the links and IDs in the tags."""
    links = []
    if first.get("SOURCEID") and "deezer" in first.get("SOURCE", "deezer").lower():
        links.append(("deezer-track", first["SOURCEID"]))
    if first.get("APPLEALBUM", "").isdigit():
        links.append(("apple", first["APPLEALBUM"]))
    if re.fullmatch(r"[A-Za-z0-9]{22}", first.get("SPOTIFYALBUM", "")):
        links.append(("url", f"https://open.spotify.com/album/{first['SPOTIFYALBUM']}"))
    for u in urls:
        u = u.rstrip(".,);]").split("?")[0].split("#")[0].rstrip("/")
        u = re.sub(r"^http://", "https://", u)
        if re.search(r"\.bandcamp\.com/(album|track)/", u) or \
                re.search(r"open\.spotify\.com/album/", u) or \
                re.search(r"(music|itunes)\.apple\.com/.*album/", u) or \
                re.search(r"(tidal\.com|qobuz\.com)/.*album/", u) or \
                re.search(r"deezer\.com/(\w+/)?album/\d+", u):
            links.append(("url", u))
        m = re.search(r"discogs\.com/(?:[^/]+/)?release/(\d+)", u)
        if m:
            links.append(("discogs", m.group(1)))
    return list(dict.fromkeys(links))

def scan(music, only=None, quiet=False):
    """Every album folder with its tracks, in a stable order."""
    albums = []
    want = ab.norm(only) if only else None
    for artist, folders in sorted(ab.scan_library(music).items(), key=lambda kv: kv[0].casefold()):
        for folder in sorted(folders):
            if folder.name.lower() in SINGLES:
                continue
            try:
                paths = album_tracks(folder)
            except OSError:
                continue
            tracks = [t for t in (read_track(p) for p in paths) if t]
            if not tracks or not tracks[0].get("ALBUM"):
                continue
            for i, t in enumerate(tracks):
                t["disc"] = number(t.get("DISCNUMBER"), 1)
                t["num"] = number(t.get("TRACKNUMBER"), i + 1)
            tracks.sort(key=lambda t: (t["disc"], t["num"], t["path"]))
            first = tracks[0]
            album_artist = first.get("ALBUMARTIST") or first.get("ARTIST") or artist
            key = f"{album_artist} - {first['ALBUM']}"
            if want and want not in (ab.norm(artist), ab.norm(album_artist), ab.norm(key)):
                continue
            urls = [u for t in tracks[:1] + tracks[-1:] for u in t["urls"]]
            discogs_tag = re.sub(r"\D", "", first.get("DISCOGS", ""))
            albums.append({
                "key": key, "folder_artist": artist, "artist": album_artist, "album": first["ALBUM"],
                "folder": str(folder), "mb_album": first.get("MBALBUM", ""),
                "barcode": first.get("BARCODE", ""), "catno": first.get("CATNO", ""),
                "label": first.get("LABEL") or first.get("ORGANIZATION") or first.get("PUBLISHER") or "",
                "discid": first.get("DISCID", ""), "discogs": discogs_tag,
                "links": store_links(first, urls),
                "tracks": [{"i": i, "disc": t["disc"], "num": t["num"], "length": t["length"],
                            "isrc": t.get("ISRC", "").replace("-", "").upper(),
                            "title": t.get("TITLE", ""), "file": t["path"]} for i, t in enumerate(tracks)],
                "tag_credits": [[who, role, group, i] for i, t in enumerate(tracks)
                                for who, role, group in t.get("credits") or [] if who]})
            if not quiet:
                print(f"\r  {len(albums)} albums read", end="", flush=True)
    if not quiet:
        print()
    return merge_folders(albums)

def merge_folders(albums):
    """One album per album name, as the iPod sees it: an album split across
    folders (a disc in each, say) becomes one album with all its tracks,
    in disc and track order, so it's identified whole and has one record."""
    by_key, order = {}, []
    for a in albums:
        first = by_key.get(a["key"])
        if first is None:
            by_key[a["key"]] = a
            order.append(a["key"])
            continue
        shift = len(first["tracks"])
        for t in a["tracks"]:
            t["i"] += shift
        first["tracks"] += a["tracks"]
        first["tag_credits"] += [[w, r, g, i + shift] for w, r, g, i in a["tag_credits"]]
        first["links"] = list(dict.fromkeys(first["links"] + a["links"]))
        first.setdefault("folders", [first["folder"]]).append(a["folder"])
        for field in ("mb_album", "barcode", "catno", "label", "discid", "discogs"):
            first[field] = first[field] or a[field]
    out = []
    for k in order:
        a = by_key[k]
        if "folders" in a:                       # merged: put the tracks in order and number them again
            a["tracks"].sort(key=lambda t: (t["disc"], t["num"], t["file"]))
            place = {t["i"]: n for n, t in enumerate(a["tracks"])}
            for n, t in enumerate(a["tracks"]):
                t["i"] = n
            a["tag_credits"] = [[w, r, g, place[i]] for w, r, g, i in a["tag_credits"]]
        out.append(a)
    return out

def signature(album):
    """Changes when the IDs in the tags or the track list change."""
    parts = [album["mb_album"], album["barcode"], album["catno"], album["discid"], album["discogs"],
             repr(album["links"]), str(len(album["tracks"]))] + [t["isrc"] for t in album["tracks"]]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ================================================================ the web
class Site:
    """One site's requests, spaced to its rate limit and retried when busy.
    Discogs also says how many requests are left in its 60-second window;
    when that runs low this waits rather than being refused."""
    def __init__(self, gap, headers=None):
        self.gap, self.last, self.lock = gap, 0.0, threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "application/json", **(headers or {})})
        self.count = 0
        self.remaining = None

    def get(self, url, params=None):
        for attempt in range(6):
            with self.lock:
                wait = self.last + self.gap - time.time()
                if self.remaining is not None and self.remaining <= 2:
                    wait = max(wait, 15)
                    self.remaining = None
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                self.count += 1
            try:
                r = self.session.get(url, params=params, timeout=30)
            except requests.RequestException:
                time.sleep(3 * (attempt + 1))
                continue
            left = r.headers.get("X-Discogs-Ratelimit-Remaining")
            if left and left.isdigit():
                self.remaining = int(left)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                try:
                    pause = float(r.headers.get("Retry-After") or 0)
                except ValueError:
                    pause = 0
                # a busy server needs longer than its Retry-After of a second
                # or so: 2, 4, 8, 16, 32 s, about a minute in all
                time.sleep(max(pause, 10 * (attempt + 1) if r.status_code == 429
                                      else 2 ** (attempt + 1)))
                continue
            if r.status_code != 200:
                return None
            try:
                return r.json()
            except ValueError:
                return None
        return None


# ================================================================ the check
def fold(s):
    """Lower case, accents and punctuation gone: "Adigéry" == "Adigery"."""
    s = unicodedata.normalize("NFKD", (s or "").casefold().replace("&", "and"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\(\d+\)$", "", s.strip())             # Discogs "Name (2)"
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[\W_]", "", s)

def clean_title(s):
    """A track or album title without its remaster/edition notes, folded."""
    s = re.sub(rf"\s*[\(\[][^\)\]]*({EXTRA})[^\)\]]*[\)\]]", "", s or "", flags=re.I)
    s = re.sub(rf"\s+[-–]\s+[^-–]*({EXTRA}).*$", "", s, flags=re.I)
    return fold(s)

def is_single(album):
    """A single or short EP rather than an album: four tracks or fewer and
    under 25 minutes in all, or one track named like the release."""
    tracks = album["tracks"]
    total = sum(t["length"] or 0 for t in tracks)
    if len(tracks) <= 4 and total and total < 25 * 60:
        return True
    return len(tracks) <= 2 and any(clean_title(t["title"]) == clean_title(album["album"]) for t in tracks)

def search_artists(name):
    """Spellings of an album artist worth searching under: as tagged, then,
    only when the name also carries a non-Latin form ("Ryo Fukui, 福居良"),
    its Latin part on its own ("Ryo Fukui"). Names like "Earth, Wind & Fire"
    or "Tyler, the Creator" are never split."""
    out = [name]
    if re.search(r"[^\x00-\u024f\u2000-\u206f]", name or ""):
        latin = re.sub(r"[^\x00-\u024f]+", " ", name)
        latin = re.sub(r"\s*[,;/]\s*$|^\s*[,;/]\s*", "", latin.strip()).strip(" ,;/")
        if latin and re.search(r"[A-Za-z]", latin):
            out.append(latin)
    return [a for a in dict.fromkeys(out) if a]

def plain_album(s):
    """An album title without "(Deluxe Edition)" and the like, for searching."""
    return re.sub(rf"\s*[\(\[][^\)\]]*({EXTRA})[^\)\]]*[\)\]]", "", s or "", flags=re.I).strip() or s

def same_artist(mine, theirs):
    mine = fold(mine)
    theirs = [fold(t) for t in theirs if t]
    return not mine or not theirs or "variousartists" in theirs + [mine] or \
        any(t and (t == mine or t in mine or mine in t) for t in theirs)

def same_album(mine, theirs):
    a, b = clean_title(mine), clean_title(theirs)
    return bool(a and b) and (a == b or a in b or b in a)

def _close(a, b):
    return abs(a - b) <= max(5, a * 0.02)

def durations_ok(pairs, share):
    timed = [(a["length"], b["len"]) for a, b in pairs if a["length"] and b.get("len")]
    close = sum(1 for x, y in timed if _close(x, y))
    return not timed or close >= share * len(timed), len(timed) - close, len(timed)

def titles_ok(pairs, share=0.8):
    named = [(title_keys(a["title"]), title_keys(b.get("title"))) for a, b in pairs]
    named = [(x, y) for x, y in named if x and y]
    same = sum(1 for x, y in named if any(_title_like(p, q) for p in x for q in y))
    return bool(named) and same >= share * len(named)

def title_keys(s):
    """The ways a title can be compared: Discogs gives translated titles as
    "Original = Translation", so each side counts."""
    parts = [s or ""] + ([p for p in (s or "").split(" = ")] if " = " in (s or "") else [])
    return [k for k in dict.fromkeys(clean_title(p) for p in parts) if k]

def _title_like(a, b):
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))

def by_title(want, have):
    """Pair each track in want with the track in have of the same title:
    an exact match first, then one title inside the other ("Something /
    Blue Jay Way" and "Something / Blue Jay Way (Transition)")."""
    have = [(t, title_keys(t.get("title"))) for t in have]
    used, pairs, left = set(), [], []
    exact = {}
    for i, (t, keys) in enumerate(have):
        for k in keys:
            exact.setdefault(k, i)
    for w in want:
        i = next((exact[k] for k in title_keys(w.get("title")) if k in exact and exact[k] not in used), None)
        if i is None:
            left.append(w)
        else:
            used.add(i); pairs.append((w, have[i][0]))
    for w in left:
        mine = title_keys(w.get("title"))
        i = next((i for i, (t, keys) in enumerate(have) if i not in used
                  and any(_title_like(a, b) for a in mine for b in keys)), None)
        if i is not None:
            used.add(i); pairs.append((w, have[i][0]))
    return pairs

def check(album, remote, strong=False, need_artist=False):
    """Is this release the album in the folder? remote holds "tracks"
    (i, len, title, isrcs), "discs" (track lists per disc), "artists" and
    "title". Returns (ok, why, how, pairs), how being:

      exact     the same tracks
      disc      the one disc of a set that the folder holds
      subset    a bigger edition, every one of your tracks on it
      superset  your copy has extra tracks; every track of the release is in it

    pairs are (local track, release track). A track list that matches by
    title passes even when the lengths don't (live albums and segues split
    tracks differently). The artist must match unless strong (an ID or
    barcode pointed here) or the album title matches; after a name search
    (need_artist) it must always match."""
    local, tracks = album["tracks"], remote["tracks"]
    title_match = same_album(album["album"], remote.get("title", ""))
    if not same_artist(album["artist"], remote["artists"]) and (need_artist or (not strong and not title_match)):
        return False, f"artist {album['artist']} here, {' / '.join(remote['artists'])} on the release", "", []
    ways = []
    if len(local) == len(tracks):
        ways.append(("exact", list(zip(local, tracks)), True))
    discs = remote.get("discs") or {}
    local_discs = {t["disc"] for t in local}
    if len(discs) > 1 and len(local_discs) == 1:
        d = next(iter(local_discs))
        if d in discs and len(discs[d]) == len(local):
            ways.append(("disc", list(zip(local, discs[d])), True))
    if len(local) < len(tracks):
        where = {c: t for t in tracks for c in t.get("isrcs") or ()}
        coded = [t for t in local if t["isrc"]]
        found = [(t, where[t["isrc"]]) for t in coded if t["isrc"] in where]
        if coded and len(coded) >= 0.8 * len(local) and len(found) == len(coded):
            ways.append(("subset", found, True))
        found = by_title(local, tracks)
        enough = 1 if len(local) <= 2 and title_match and len(tracks) <= 4 else 2   # a single's A-side
        if (strong or title_match) and len(found) >= 0.9 * len(local) and len(found) >= enough:
            ways.append(("subset", found, False))
    if len(local) > len(tracks) and (strong or title_match):
        found = by_title(tracks, local)
        extra = len(local) - len(tracks)
        if len(found) >= 0.9 * len(tracks) and len(found) >= 2 and extra <= max(5, len(tracks) // 2):
            ways.append(("superset", [(b, a) for a, b in found], False))
        elif extra > max(5, len(tracks) // 2) and title_match and len(tracks) >= max(5, 0.4 * len(local)) \
                and len(found) >= 0.9 * len(tracks):
            # a deluxe/expanded copy of an album only listed in its original
            # form: nearly every original track (90%) must be in it, under the same album
            # title, and the original must be a real album (5+ tracks, and at
            # least 40% of yours), so a single or EP never passes
            ways.append(("superset", [(b, a) for a, b in found], False))
    if not ways:
        why = f"{len(local)} tracks here, {len(tracks)} on the release"
        found = {id(w) for w, _ in by_title(local, tracks)}
        missing = [t["title"] for t in local if id(t) not in found]
        if 0 < len(missing) < len(local):
            # name the titles that didn't line up, so the reason can be checked
            why += f"; not on it by title: {', '.join(missing[:3])}" + (" ..." if len(missing) > 3 else "")
        return False, why, "", []
    why = ""
    for how, pairs, by_order in ways:
        ok, off, timed = durations_ok(pairs, 0.8 if by_order else 0.7)
        if ok or (by_order and titles_ok(pairs)):
            return True, "", how, pairs
        why = why or f"durations differ on {off} of {timed} tracks"
    return False, why, "", []

def tracks_note(album, found):
    """ "your 10 of its 11 tracks" and the like, or "" when they're the same."""
    mine, theirs = len(album["tracks"]), found.get("release_tracks") or 0
    if found.get("how") == "superset":
        return f"its {theirs} tracks are {theirs} of your {mine}"
    if found.get("how") in ("subset", "disc"):
        return f"your {mine} of its {theirs} tracks"
    return ""


# ================================================================ credit groups
GROUPS = ("Musicians", "Producers", "Engineers", "Songwriters", "Credited")

MB_GROUP = {"instrument": "Musicians", "vocal": "Musicians", "performer": "Musicians",
            "performing orchestra": "Musicians", "conductor": "Musicians", "chorus master": "Musicians",
            "concertmaster": "Musicians",
            "producer": "Producers",
            "engineer": "Engineers", "recording": "Engineers", "mix": "Engineers", "mastering": "Engineers",
            "sound": "Engineers", "audio": "Engineers", "balance": "Engineers", "editor": "Engineers",
            "composer": "Songwriters", "lyricist": "Songwriters", "writer": "Songwriters",
            "librettist": "Songwriters"}

def mb_group(rel_type):
    """The credits group for a MusicBrainz relationship type."""
    return MB_GROUP.get((rel_type or "").lower(), "Credited")

DC_SONGWRITER = re.compile(r"written|compos|lyrics|music by|songwriter|words by|libretto", re.I)
DC_PRODUCER = re.compile(r"produc", re.I)
DC_ENGINEER = re.compile(r"engineer|recorded by|mixed by|mastered by|\bmix|\bmaster|lacquer|remaster|"
                         r"edited by|tape op|transfer", re.I)
DC_CREDITED = re.compile(
    r"design|photo|art|layout|liner|manage|a&r|coordinat|technician|supervis|booking|legal|copyright|"
    r"notes|translated|illustrat|painting|label|publish|arrang|score|orchestrat|copyist|contractor|"
    r"liaison|director|programm|sequenc|by\b", re.I)

def dc_group(role):
    """The credits group for a Discogs role such as "Bass [Fretless]" or "Mixed By"."""
    role = re.sub(r"\[.*?\]", "", role or "").strip()
    for group, rx in (("Songwriters", DC_SONGWRITER), ("Producers", DC_PRODUCER),
                      ("Engineers", DC_ENGINEER), ("Credited", DC_CREDITED)):
        if rx.search(role):
            return group
    return "Musicians"


# ================================================================ saved releases
def _release_path(kind, rid):
    return RELEASES / f"{kind}_{re.sub(r'[^A-Za-z0-9-]', '', str(rid))}.json.gz"

def saved_release(kind, rid, max_days=RELEASE_DAYS):
    """A release saved by an earlier lookup ("mbrel" or "dcrel"), or None."""
    path = _release_path(kind, rid)
    try:
        if max_days is not None and time.time() - path.stat().st_mtime > max_days * 86400:
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def save_release(kind, rid, data):
    if not data or not rid:
        return
    path = _release_path(kind, rid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


# ================================================================ MusicBrainz
MUSICIAN_TYPES = {"instrument", "vocal", "performer", "performing orchestra", "conductor",
                  "chorus master", "concertmaster"}

def seconds(ms):
    return ms / 1000 if ms else None

def discogs_links(rels):
    """Discogs release and master IDs among MusicBrainz URL links."""
    out = {}
    for r in rels or []:
        m = re.search(r"discogs\.com/(release|master)/(\d+)", (r.get("url") or {}).get("resource") or "")
        if m:
            out.setdefault(m.group(1), int(m.group(2)))
    return out

def mb_shape(rel):
    """The release as check() wants it."""
    tracks, discs = [], {}
    for medium in rel.get("media") or []:
        these = []
        for t in medium.get("tracks") or []:
            rec = t.get("recording") or {}
            these.append({"i": len(tracks) + len(these), "len": seconds(t.get("length") or rec.get("length")),
                          "title": t.get("title") or rec.get("title") or "", "recording": rec.get("id"),
                          "position": f"{medium.get('position') or 1}-{t.get('position') or len(these) + 1}",
                          "isrcs": {c.replace("-", "").upper() for c in rec.get("isrcs") or []}})
        discs[medium.get("position") or len(discs) + 1] = these
        tracks += these
    credits = [c for c in rel.get("artist-credit") or [] if isinstance(c, dict)]
    names = []
    for c in credits:
        a = c.get("artist") or {}
        names += [c.get("name"), a.get("name"), a.get("sort-name")]
    return {"tracks": tracks, "discs": discs, "artists": [n for n in names if n], "title": rel.get("title", "")}

def mb_edition(rel):
    """What the pages say their information is for, e.g.
    "Down in Albion (deluxe edition) · 2005 · 2×CD · GB"."""
    title = rel.get("title") or ""
    if rel.get("disambiguation"):
        title += f" ({rel['disambiguation']})"
    formats = {}
    for m in rel.get("media") or []:
        f = m.get("format") or "?"
        formats[f] = formats.get(f, 0) + 1
    fmt = " + ".join(f"{n}×{f}" if n > 1 else f for f, n in formats.items())
    return " · ".join(x for x in (title, (rel.get("date") or "")[:4], fmt, rel.get("country") or "") if x)

class MusicBrainz:
    STRONG = {"musicbrainz id", "discogs id", "barcode", "store link", "disc id", "catalogue number"}

    def __init__(self, site, deezer):
        self.site, self.deezer = site, deezer

    def release(self, rid):
        return saved_release("mbrel", rid) or self.site.get(f"{MB}release/{rid}", {"inc": LOOKUP_INC, "fmt": "json"})

    def attempt(self, album, rid, rung, tried):
        if not rid or rid in tried:
            return None, None
        tried.add(rid)
        rel = self.release(rid)
        if not rel:
            return {"rung": rung, "id": rid, "ok": False, "why": "not on MusicBrainz"}, None
        remote = mb_shape(rel)
        ok, why, how, pairs = check(album, remote, rung in self.STRONG, need_artist=rung == "name search")
        result = {"rung": rung, "id": rid, "ok": ok, "why": why, "how": how, "title": rel.get("title"),
                  "edition": mb_edition(rel), "release_tracks": len(remote["tracks"]),
                  "rg": (rel.get("release-group") or {}).get("id"),
                  "artists": [{"id": (c.get("artist") or {}).get("id"), "name": c.get("name")}
                              for c in rel.get("artist-credit") or [] if isinstance(c, dict)],
                  "discogs": discogs_links(rel.get("relations")),
                  "tracks": {str(a["i"]): {"recording": b["recording"], "position": b["position"]}
                             for a, b in pairs}}
        return result, rel

    def best(self, album, rids, rung, tried, failed):
        """The first of these releases that passes; one with exactly your
        tracks beats a bigger or smaller edition."""
        partial = None
        for rid in rids:
            r, rel = self.attempt(album, rid, rung, tried)
            if not r:
                continue
            if not r["ok"]:
                failed.append(r)
            elif r["how"] not in ("subset", "superset"):
                return r, rel
            elif not partial:
                partial = (r, rel)
        return partial or (None, None)

    def search(self, query, limit=5):
        found = self.site.get(f"{MB}release/", {"query": query, "fmt": "json", "limit": limit}) or {}
        return found.get("releases") or []

    @staticmethod
    def plausible(album, results, keep=3, min_score=0):
        """Search results worth a full lookup: a release far shorter or
        longer than your copy can't pass the check, so it isn't fetched;
        the nearest in length come first. Saves most wasted lookups."""
        n = len(album["tracks"])
        out = []
        for r in results:
            if int(r.get("score") or 100) < min_score:
                continue
            count = r.get("track-count") or sum(m.get("track-count", 0) for m in r.get("media") or [])
            if count and not (0.4 * n <= count <= 2.5 * n):
                continue
            out.append((abs(count - n) if count else 50, r.get("id")))
        return [rid for _, rid in sorted(out, key=lambda x: x[0])][:keep]

    def url_releases(self, url):
        data = self.site.get(f"{MB}url", {"resource": url, "inc": "release-rels", "fmt": "json"}) or {}
        return [(r.get("release") or {}).get("id") for r in data.get("relations") or []]

    def link_urls(self, album):
        """MusicBrainz-style album URLs from the tags' store links and IDs."""
        out = []
        for kind, value in album["links"]:
            if kind == "url":
                out.append(value)
            elif kind == "apple":
                out += [f"https://music.apple.com/{cc}/album/{value}" for cc in ("us", "gb")]
            elif kind == "deezer-track":
                track = self.deezer.get(f"{DEEZER}track/{value}") or {}
                dz = (track.get("album") or {}).get("id")
                if dz:
                    out.append(f"https://www.deezer.com/album/{dz}")
            elif kind == "discogs":
                out.append(f"https://www.discogs.com/release/{value}")
        return out

    def identify(self, album):
        """(result, failed attempts): the first rung whose release passes."""
        tried, failed = set(), []
        def go(rids, rung):
            return self.best(album, [r for r in rids if r], rung, tried, failed)

        steps = []
        if album["mb_album"]:
            steps.append(("musicbrainz id", lambda: [album["mb_album"]]))
        if album["discogs"]:
            steps.append(("discogs id", lambda: self.url_releases(f"https://www.discogs.com/release/{album['discogs']}")))
        forms = barcode_forms(album["barcode"])
        if forms:
            steps.append(("barcode", lambda: self.plausible(
                album, self.search("barcode:(" + " OR ".join(forms) + ")"))))
        if any(t["isrc"] for t in album["tracks"]):
            steps.append(("isrc", lambda: self.isrc_releases(album)))
        if album["links"]:
            steps.append(("store link", lambda: [r for u in self.link_urls(album) for r in self.url_releases(u)][:5]))
        if album["discid"]:
            steps.append(("disc id", lambda: [r.get("id") for r in (self.site.get(
                f"{MB}discid/{album['discid']}", {"fmt": "json"}) or {}).get("releases") or []][:3]))
        if album["catno"]:
            steps.append(("catalogue number", lambda: self.plausible(album, self.search(
                f"catno:{q(album['catno'])}" + (f" AND label:{q(album['label'])}" if album["label"] else "")))))
        single = " AND primarytype:single" if is_single(album) else ""
        steps.append(("name search", lambda: self.plausible(album, [r for who in search_artists(album["artist"])[:2]
            for r in self.search(f"release:{q(plain_album(album['album']))} AND artist:{q(who)}{single}")
                     + (self.search(f"release:{q(plain_album(album['album']))} AND artist:{q(who)}")
                        if single else [])], min_score=80)))
        partial, extra = None, 0
        for rung, rids in steps:
            if partial:
                # an edition with more or fewer tracks was found: try one
                # more rung for yours, but never a name search over an ID
                if rung == "name search" or extra >= 1:
                    break
                extra += 1
            r, rel = go(rids(), rung)
            if r and r["how"] not in ("subset", "superset"):
                save_release("mbrel", r["id"], rel)
                return self.finish(r, rel), failed
            if r and not partial:
                partial = (r, rel)
        if partial:
            save_release("mbrel", partial[0]["id"], partial[1])
            return self.finish(*partial), failed
        return None, failed

    def from_discogs(self, album, d, failed):
        """After Discogs found the album and MusicBrainz didn't: the releases
        MusicBrainz links to that Discogs release, or to its master."""
        tried = set()
        rids = self.url_releases(f"https://www.discogs.com/release/{d['id']}")
        if not rids and d.get("master"):
            data = self.site.get(f"{MB}url", {"resource": f"https://www.discogs.com/master/{d['master']}",
                                              "inc": "release-group-rels", "fmt": "json"}) or {}
            for rg in [(x.get("release_group") or {}).get("id") for x in data.get("relations") or []][:1]:
                if rg:
                    browse = self.site.get(f"{MB}release", {"release-group": rg, "fmt": "json", "limit": 25}) or {}
                    rids = self.plausible(album, browse.get("releases") or [])
        r, rel = self.best(album, [x for x in rids if x], "discogs link", tried, failed)
        if not r:
            return None
        save_release("mbrel", r["id"], rel)
        return self.finish(r, rel)

    def isrc_releases(self, album):
        """The releases a few of the tracks' recordings share, the likeliest first."""
        isrcs = [t["isrc"] for t in album["tracks"] if t["isrc"]]
        picks = [isrcs[0]] + ([isrcs[len(isrcs) // 2]] if len(isrcs) > 2 else [])
        shared, info = None, {}
        for code in picks:
            if shared is not None and len(shared) <= 5:
                break                    # the first ISRC narrowed it down enough
            data = self.site.get(f"{MB}isrc/{code}", {"inc": "releases", "fmt": "json"}) or {}
            recs = data.get("recordings") or []
            if recs and not any(r.get("releases") for r in recs):
                for rec in recs[:2]:      # the JSON ISRC lookup can leave the releases out
                    browse = self.site.get(f"{MB}release", {"recording": rec.get("id"), "fmt": "json",
                                                            "limit": 25}) or {}
                    rec["releases"] = browse.get("releases") or []
            rels = [rel for rec in recs for rel in rec.get("releases") or []]
            info.update({rel["id"]: rel for rel in rels})
            ids = {rel["id"] for rel in rels}
            shared = ids if shared is None else (shared & ids or shared)
        if not shared:
            return []
        title, n = clean_title(album["album"]), len(album["tracks"])
        def rank(i):
            rel = info.get(i) or {}
            count = rel.get("track-count") or sum(m.get("track-count", 0) for m in rel.get("media") or [])
            return (clean_title(rel.get("title", "")) != title, abs(count - n) if count else 99,
                    rel.get("status", "Official") != "Official", i)
        return sorted(shared, key=rank)[:3]

    def finish(self, r, release):
        """Add what the release group knows: its Wikidata item and, if the
        release itself has none, its Discogs master. These come with the
        release lookup; only a release saved by an older version needs the
        group looked up on its own."""
        data = (release or {}).get("release-group") or {}
        if "relations" not in data and r.get("rg"):
            data = self.site.get(f"{MB}release-group/{r['rg']}", {"inc": "url-rels", "fmt": "json"}) or {}
        if data:
            for rel in data.get("relations") or []:
                if rel.get("type") == "wikidata":
                    m = re.search(r"(Q\d+)", (rel.get("url") or {}).get("resource", ""))
                    if m:
                        r["wikidata"] = m.group(1)
            master = discogs_links(data.get("relations")).get("master")
            if master:
                r["discogs"].setdefault("master", master)
        return r

def barcode_forms(b):
    b = re.sub(r"\D", "", b or "")
    if not b:
        return []
    forms = {b, b.lstrip("0")}
    if len(b) == 12:
        forms.add("0" + b)
    return sorted(f for f in forms if len(f) >= 8)

def q(s):
    """A quoted phrase for a MusicBrainz search."""
    return '"' + re.sub(r'(["\\])', r"\\\1", s or "") + '"'


# ================================================================ Discogs
def mmss(s):
    m = re.match(r"^(?:(\d+):)?(\d+):(\d{2})$", (s or "").strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

def discogs_edition(rel):
    """e.g. "Down In Albion · 2005 · 2×CD (Album, Deluxe Edition) · UK"."""
    fmts = []
    for f in rel.get("formats") or []:
        qty = f.get("qty") or "1"
        name = (f"{qty}×" if qty not in ("", "1") else "") + (f.get("name") or "")
        desc = [d for d in f.get("descriptions") or [] if d]
        fmts.append(name + (f" ({', '.join(desc)})" if desc else ""))
    return " · ".join(x for x in (rel.get("title") or "", str(rel.get("year") or "") if rel.get("year") else "",
                                 " + ".join(fmts), rel.get("country") or "") if x)

def discogs_tracks(rel):
    """A release's tracks. Headings are skipped; an "index" track (a long piece
    listed with its parts, common on vinyl) counts as one track, as it is on a
    download."""
    return [t for t in rel.get("tracklist") or [] if t.get("type_", "track") in ("track", "index")]

ODD_EDITION = re.compile(r"promo|unofficial|test pressing|white label|sampler|bootleg|advance|acetate|"
                         r"transcription|club edition|misprint", re.I)

def version_rank(v):
    """Lower is plainer: an official album on CD, vinyl or as files, earliest
    first. Promos, bootlegs, test pressings and cassettes go to the back,
    because the edition is printed on the page."""
    fmt = " ".join([v.get("format") or ""] + list(v.get("major_formats") or []))
    odd = bool(ODD_EDITION.search(fmt)) or (v.get("status") or "Accepted") not in ("Accepted", "")
    # CDs first: they usually have the same track list as a download, where
    # vinyl often splits or drops tracks; then files, then vinyl, then the rest
    kind = (0 if re.search(r"\bCD\b", fmt) else 1 if re.search(r"\bfile\b", fmt, re.I)
            else 2 if re.search(r"vinyl|\bLP\b", fmt, re.I)
            else 4 if re.search(r"cassette|8-track|reel|minidisc", fmt, re.I) else 3)
    year = re.match(r"\d{4}", str(v.get("released") or "")) or None
    return (odd, kind, int(year.group(0)) if year else 9999)

def edition_year(album):
    """The year of the edition the files come from, when the titles say so:
    "America (2003 Remaster)" -> 2003. None otherwise."""
    years = re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b[^()\[\]]{0,20}?(?:remaster|edition|reissue|version|mix)",
                       " ".join([album["album"]] + [t["title"] for t in album["tracks"]]), re.I)
    return int(max(set(years), key=years.count)) if years else None

class Discogs:
    def __init__(self, site):
        self.site = site

    def attempt(self, album, rid, rung, seen, need_artist=False):
        if not rid or rid in seen:
            return None
        # a name search must match the artist's name; a discography doesn't
        # need to, since the artist was picked by ID ("Sean Ono Lennon" is
        # "Sean Lennon" on Discogs)
        need_artist = (need_artist or rung == "name search") and rung != "artist discography"
        seen.add(rid)
        rel = saved_release("dcrel", rid) or self.site.get(f"{DISCOGS}releases/{rid}")
        if not rel:
            return None
        tracks = discogs_tracks(rel)
        remote = {"tracks": [{"i": i, "len": mmss(t.get("duration")), "title": t.get("title", ""),
                              "position": t.get("position", ""), "isrcs": set()} for i, t in enumerate(tracks)],
                  "artists": [a.get("anv") or a.get("name", "") for a in rel.get("artists") or []]
                             + [a.get("name", "") for a in rel.get("artists") or []],
                  "title": rel.get("title", "")}
        ok, why, how, pairs = check(album, remote, strong=not need_artist, need_artist=need_artist)
        if ok:
            save_release("dcrel", rid, rel)
        return {"ok": ok, "why": why, "how": how, "rung": rung, "id": rid, "title": rel.get("title"),
                "master": rel.get("master_id"), "edition": discogs_edition(rel), "release_tracks": len(tracks),
                "artists": [{"id": a.get("id"), "name": a.get("name")} for a in rel.get("artists") or []],
                "tracks": {str(a["i"]): {"position": b["position"]} for a, b in pairs}}

    def best(self, album, rids, rung, seen, failed, need_artist=False):
        partial = None
        for rid in rids:
            r = self.attempt(album, rid, rung, seen, need_artist)
            if not r:
                continue
            if not r["ok"]:
                failed.append(r)
            elif r["how"] not in ("subset", "superset"):
                return r
            elif not partial:
                partial = r
        return partial

    def master_releases(self, master_id, year=None):
        """The master's main release, then its plainest editions; editions
        from the year the files' titles name ("2003 Remaster") first."""
        master = self.site.get(f"{DISCOGS}masters/{master_id}") or {}
        # CD editions asked for by name: a famous album can have hundreds of
        # editions, and the first page of them is all 1970s vinyl
        versions = {}
        if year:
            versions = self.site.get(f"{DISCOGS}masters/{master_id}/versions",
                                     {"per_page": 50, "released": year}) or {}
        if not versions.get("versions"):
            versions = self.site.get(f"{DISCOGS}masters/{master_id}/versions", {"per_page": 50, "format": "CD"}) or {}
        if not versions.get("versions"):
            versions = self.site.get(f"{DISCOGS}masters/{master_id}/versions", {"per_page": 50}) or {}
        def rank(v):
            odd, kind, y = version_rank(v)
            return (odd, year is not None and y != year, kind, y)
        ranked = sorted(versions.get("versions") or [], key=rank)
        main = master.get("main_release")
        main_v = next((v for v in versions.get("versions") or [] if v.get("id") == main), None)
        rids = [] if main_v is not None and version_rank(main_v)[0] else [main]
        if year and ranked and rank(ranked[0])[1] is False:
            rids = []        # an edition of that year goes ahead of the original
        return [r for r in dict.fromkeys(rids + [v.get("id") for v in ranked][:2] + [main]) if r][:3]

    def identify(self, album, links, known_artists=(), sibling_titles=()):
        """(result, failed attempts), from the best evidence down."""
        seen, failed = set(), []
        steps = []
        if album["discogs"]:
            steps.append(("discogs id", lambda: [int(album["discogs"])]))
        if links.get("release"):
            steps.append(("musicbrainz link", lambda: [links["release"]]))
        if links.get("master"):
            steps.append(("musicbrainz master", lambda: self.master_releases(links["master"], edition_year(album))))
        for form in barcode_forms(album["barcode"])[:2]:
            steps.append(("barcode", lambda form=form: [h.get("id") for h in (self.site.get(
                f"{DISCOGS}database/search", {"barcode": form, "type": "release", "per_page": 5}) or {}
            ).get("results") or []][:2]))
        if album["catno"]:
            steps.append(("catalogue number", lambda: [h.get("id") for h in (self.site.get(
                f"{DISCOGS}database/search", {"catno": album["catno"], "artist": album["artist"],
                                              "type": "release", "per_page": 5}) or {}
            ).get("results") or []][:3]))
        partial, extra = None, 0
        for rung, rids in steps:
            if partial:
                if extra >= 1:
                    break                # one more rung for an exact edition, then settle
                extra += 1
            r = self.best(album, rids(), rung, seen, failed)
            if r and r["how"] not in ("subset", "superset"):
                return r, failed
            partial = partial or r
        if partial:
            return partial, failed
        title = plain_album(album["album"])
        for who in search_artists(album["artist"])[:2]:
            params = {"artist": who, "release_title": title, "per_page": 5}
            if is_single(album):
                params["format"] = "Single"      # a single's title is often an album track's too
            found = self.site.get(f"{DISCOGS}database/search", params) or {}
            if not found.get("results") and "format" in params:
                found = self.site.get(f"{DISCOGS}database/search", dict(params, format=None)) or {}
            r = self.best(album, self.candidates(found.get("results") or []), "name search", seen, failed, True)
            if r:
                return r, failed
        # last: the artist's own discography, for releases the search doesn't
        # find (artist known by another name, or titles spelt differently)
        # Which Discogs artist is yours? Best from your other albums by them
        # already identified; otherwise, of up to five artists with exactly that
        # name (Discogs has dozens of "Eliza"s), the one whose discography holds
        # the most of your albums by them. A discography is one request.
        listings = {}
        def listing(artist_id):
            if artist_id not in listings:
                listings[artist_id] = (self.site.get(f"{DISCOGS}artists/{artist_id}/releases",
                                                     {"per_page": 100, "sort": "year"}) or {}).get("releases") or []
            return listings[artist_id]
        artist_ids = list(dict.fromkeys(known_artists))[:2]
        if not artist_ids:
            who = search_artists(album["artist"])[-1]
            found = ((self.site.get(f"{DISCOGS}database/search", {"q": who, "type": "artist", "per_page": 25})
                      or {}).get("results") or [])
            same_name = [a["id"] for a in found if fold(who) == fold(a.get("title", ""))][:5]
            mine = [title] + [t for t in sibling_titles if t != album["album"]]
            def overlap(artist_id):
                titles = [x.get("title", "") for x in listing(artist_id) if x.get("role", "Main") == "Main"]
                return sum(1 for t in mine if any(same_album(t, x) for x in titles))
            scored = sorted(((overlap(i), i) for i in same_name), key=lambda x: -x[0])
            artist_ids = [i for n, i in scored if n][:1]
        for artist_id in artist_ids:
            hits = [x for x in listing(artist_id)
                    if x.get("role", "Main") == "Main" and same_album(title, x.get("title", ""))]
            r = self.best(album, self.candidates(hits), "artist discography", seen, failed, True)
            if r:
                return r, failed
        return None, failed

    def candidates(self, hits):
        """Release IDs from search or discography results: a release as it
        is, a master by its main release. At most three."""
        out = []
        for h in hits[:3]:
            if h.get("type") == "master":
                out.append(h.get("main_release") or (self.site.get(f"{DISCOGS}masters/{h.get('id')}") or {})
                           .get("main_release"))
            else:
                out.append(h.get("id"))
        return [r for r in out if r]


# ================================================================ saved results
def record_path(album):
    name = ab.safe_name(album["key"])
    return CACHE / f"{name}.json" if name else None

def library():
    """What the last full scan found: {"keys": [...], "albums": {key: {...}}}."""
    return (ab.load_json(LIBRARY) if LIBRARY.exists() else None) or {}

def current_keys():
    """The albums in the library at the last full scan, or None if never."""
    data = ab.load_json(LIBRARY) if LIBRARY.exists() else None
    return set(data["keys"]) if data and data.get("keys") else None

def load(album):
    """The saved record for an album (a scan() entry), or None."""
    path = record_path(album)
    return ab.load_json(path) if path else None

def needs_lookup(album, rec, refresh=False, retry=False, token=None):
    if refresh or not rec or rec.get("format") != FORMAT or rec.get("sig") != signature(album):
        return True
    if token and not rec.get("discogs_tried"):
        return True                       # a Discogs token has been added since
    if rec.get("mb") and (rec.get("discogs") or not rec.get("discogs_tried")):
        return False
    stale = time.time() - (rec.get("checked") or 0) > RETRY_DAYS * 86400
    return retry or stale


# ================================================================ the run
def identify_all(albums, token, refresh=False, retry=False, progress=True):
    """Look up every album that needs it. MusicBrainz and Discogs run side by
    side, Discogs a step behind (it uses the links MusicBrainz finds); each
    keeps to its own rate limit, and Discogs is never asked twice at once."""
    todo = [a for a in albums if needs_lookup(a, load(a), refresh, retry, token)]
    if not todo:
        return {}
    mb_site, deezer = Site(1.1), Site(0.2)
    mb = MusicBrainz(mb_site, deezer)
    dc = Discogs(Site(1.1, {"Authorization": f"Discogs token={token}"})) if token else None
    done_mb, lock = {}, threading.Lock()
    # Discogs artist IDs already known for each folder artist, from albums identified before,
    # and each folder artist's album titles (to tell same-named artists apart)
    known, titles = {}, {}
    for a in albums:
        titles.setdefault(a["folder_artist"], []).append(plain_album(a["album"]))
    for a in albums:
        for art in ((load(a) or {}).get("discogs") or {}).get("artists") or []:
            if art.get("id") and art["id"] not in (194, 355):
                known.setdefault(a["folder_artist"], []).append(art["id"])
    stats = {"mb": 0, "dc": 0}

    def run_mb():
        for album in todo:
            r, failed = mb.identify(album)
            with lock:
                done_mb[album["key"]] = (r, failed)
            stats["mb"] += 1

    def run_dc():
        for album in todo:
            while album["key"] not in done_mb:
                time.sleep(0.3)
            r, failed = done_mb[album["key"]]
            rec = {"format": FORMAT, "sig": signature(album), "checked": int(time.time()),
                   "key": album["key"], "mb": r, "mb_failed": failed[:5]}
            if dc:
                d, dfailed = dc.identify(album, (r or {}).get("discogs") or {}, known.get(album["folder_artist"], ()),
                                         titles.get(album["folder_artist"], ()))
                for art in (d or {}).get("artists") or []:
                    if art.get("id"):
                        known.setdefault(album["folder_artist"], []).append(art["id"])
                rec.update(discogs=d, discogs_failed=dfailed[:5], discogs_tried=True)
                if d and not r:
                    found = mb.from_discogs(album, d, failed)
                    if found:
                        rec.update(mb=found, mb_failed=[])
            path = record_path(album)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                ab.save_json(path, rec)
            stats["dc"] += 1

    if progress:
        minutes = len(todo) * (4 if dc else 2.5) / 60
        print(f"Identifying {len(todo)} albums (about {max(1, round(minutes))} min)"
              + ("" if dc else "; no Discogs token in the settings file, so MusicBrainz only") + ".")
    threads = [threading.Thread(target=run_mb, daemon=True), threading.Thread(target=run_dc, daemon=True)]
    for t in threads:
        t.start()
    shown = -1
    while any(t.is_alive() for t in threads):
        time.sleep(1)
        if progress and stats["dc"] != shown:      # only when it changes, so a log isn't one line a second
            shown = stats["dc"]
            print(f"\r  {shown}/{len(todo)} albums done", end="", flush=True)
    if progress:
        print()
        print(f"  {mb_site.count} MusicBrainz, {dc.site.count if dc else 0} Discogs and {deezer.count} Deezer"
              f" requests ({(mb_site.count + (dc.site.count if dc else 0)) / len(todo):.1f} per album)")
    return {a["key"]: load(a) for a in todo}

def write_missing(albums):
    lines, count = [], 0
    for a in albums:
        rec = load(a) or {}
        gaps = [s for s, k in (("MusicBrainz", "mb"), ("Discogs", "discogs")) if not rec.get(k)
                and (k == "mb" or rec.get("discogs_tried"))]
        if gaps:
            count += 1
            ids = [k for k, v in (("barcode", a["barcode"]), ("ISRC", any(t["isrc"] for t in a["tracks"])),
                                  ("store link", a["links"]), ("catalogue number", a["catno"])) if v]
            lines.append(f"{a['key']}  (not on {' or '.join(gaps)}; tags have {', '.join(ids) or 'no IDs'})")
            for site, k in (("MusicBrainz", "mb_failed"), ("Discogs", "discogs_failed")):
                for f in rec.get(k) or []:
                    lines.append(f"    {site} [{f.get('rung')}] {f.get('edition') or f.get('title') or f.get('id')}:"
                                 f" {f.get('why')}")
    MISSING_LIST.write_text(
        "Albums not identified. Tagging them in Picard (with its audio scan) adds MusicBrainz IDs,\n"
        "which the next run picks up. Under each: the editions that were tried and why they didn't match.\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return count

def main(argv=None):
    conf = ab.settings()
    drive = (conf.get("ipod drive") or "G:").rstrip("\\/")
    default_music = conf.get("music folder", "").rstrip("\\/") or f"{drive}\\Music"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_root", nargs="?", default=default_music)
    ap.add_argument("--only", help='just one artist, or "Artist - Album"')
    ap.add_argument("--refresh", action="store_true", help="look everything up again")
    ap.add_argument("--retry-not-found", action="store_true", help="look again where nothing was found")
    ap.add_argument("--discogs-token", default=conf.get("discogs token") or os.environ.get("DISCOGS_TOKEN"))
    args = ap.parse_args(argv)
    music = Path(args.music_root)
    if not music.is_dir():
        print(f"Can't find {music}")
        return 1
    print(f"Reading tags in {music}...")
    albums = scan(music, args.only)
    identify_all(albums, args.discogs_token, args.refresh, args.retry_not_found)
    if not args.only:
        # the albums in the library now: later steps leave out records of
        # albums since deleted or renamed, so nothing links to them
        ab.save_json(LIBRARY, {"checked": int(time.time()), "keys": sorted(a["key"] for a in albums),
                               "albums": {a["key"]: {
                                   "artist": a["artist"], "album": a["album"], "folder": a["folder"],
                                   "tracks": [[t["disc"], t["num"], t["title"]] for t in a["tracks"]],
                                   "tag_credits": a["tag_credits"]} for a in albums}})
    recs = [load(a) or {} for a in albums]
    mb_n = sum(1 for r in recs if r.get("mb"))
    dc_n = sum(1 for r in recs if r.get("discogs"))
    missing = write_missing(albums) if not args.only else 0
    print(f"{len(albums)} albums: {mb_n} on MusicBrainz"
          + (f", {dc_n} on Discogs" if args.discogs_token else "")
          + (f". {missing} not fully identified, listed in \"{MISSING_LIST.name}\"." if missing else "."))
    return 0

if __name__ == "__main__":
    sys.exit(main())
