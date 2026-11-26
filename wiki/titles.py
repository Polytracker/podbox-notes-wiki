"""Track write-ups found by title (point 13).

track_notes.py (copied from ipod-liner-notes, unchanged) finds an album's
songs only through the album's Wikidata item. The check of 26 Nov found two
ways that misses: the item lists a song by an entry that has no English
article while the song's own entry has one (150 of the 165 Last.fm
write-ups, All My Loving among them), and songs the item doesn't list at all
(about 360 more tracks). And three albums have a Wikidata item that wasn't
linked.

So, after track_notes.py, for each track without a Wikipedia write-up:
  1. an album with no item: its item looked for by title among the album
     artist's albums (exact title); its songs then found as track_notes.py
     finds them
  2. a song of the track's title performed by the album's artist (P175),
     a song or single only, never an album of the same name

All of an artist's songs and albums come from one Wikidata query (fifty
artists a query), the articles' openings twenty at a time: minutes for a
whole library, where a search a track took an hour.
and its article put through track_notes.py's own checks (track_notes(),
usable(), fill_out()). A write-up found this way replaces a Last.fm one.

Saved in notes wiki\\tracks by title; an album is asked again after 180
days, or when track_notes.py looks it up again. Its saved data is never
written to: the pages merge the two. "Tracks by title.txt" lists every
track the search filled, and every Last.fm write-up left with the
Wikipedia reason.
"""
import re
import time

from . import ab
from . import show
import ids
import liner_notes as ln
import track_notes as tn

from .lookups import CACHE

SAVED = CACHE / "tracks by title"
RECHECK_DAYS = 180
VERSION = 2
REPORT = "Tracks by title.txt"
# What counts as a song: song, single, musical work or composition, instrumental
SONG_TYPES = {"Q7366", "Q134556", "Q105543609", "Q207628", "Q2188189", "Q1428060"}
NOT_SONG = re.compile(r"\((?:[^)]*\b)?(album|EP|mixtape|soundtrack|film|band|musician|singer)\)$", re.I)


ARTISTS_A_QUERY = 50


def catalogue(qids, session):
    """{artist item: {"songs": [(item, title, article)], "albums": [(item, title)]}}
    for many artists, ARTISTS_A_QUERY a Wikidata query: every song, single or
    musical work they performed (P175), and every album, with its English
    article. None for a batch Wikidata didn't answer."""
    from .lookups import sparql
    out = {}
    song_types = " ".join("wd:" + t for t in sorted(SONG_TYPES))
    album_types = " ".join("wd:" + t for t in sorted(ln.ALBUM_TYPES))
    for n in range(0, len(qids), ARTISTS_A_QUERY):
        batch = [q for q in qids[n:n + ARTISTS_A_QUERY] if re.fullmatch(r"Q\d+", q or "")]
        if not batch:
            continue
        query = ("SELECT ?artist ?item ?kind ?label ?article WHERE { "
                 f"VALUES ?artist {{ {' '.join('wd:' + q for q in batch)} }} "
                 "?item wdt:P175 ?artist . "
                 f"{{ VALUES ?t {{ {song_types} }} ?item wdt:P31 ?t . BIND(\"song\" AS ?kind) }} UNION "
                 f"{{ VALUES ?t {{ {album_types} }} ?item wdt:P31 ?t . BIND(\"album\" AS ?kind) }} "
                 "OPTIONAL { ?item rdfs:label ?label . FILTER(lang(?label) = \"en\" || lang(?label) = \"mul\") } "
                 "OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } }")
        r = sparql(session, query)
        if r is None or not r.ok:
            for q in batch:
                out[q] = None
            continue
        found = {q: {"songs": {}, "albums": {}} for q in batch}
        for b in (r.json().get("results") or {}).get("bindings") or []:
            v = {k: x.get("value", "") for k, x in b.items()}
            q, item = v["artist"].rsplit("/", 1)[-1], v["item"].rsplit("/", 1)[-1]
            if q not in found:
                continue
            article = ""
            if v.get("article"):
                import urllib.parse
                article = urllib.parse.unquote(v["article"].rsplit("/wiki/", 1)[-1]).replace("_", " ")
            rec = found[q][v["kind"] + "s"].setdefault(item, {"label": "", "article": ""})
            rec["label"] = rec["label"] or v.get("label") or ""
            rec["article"] = rec["article"] or article
        for q, f in found.items():
            out[q] = {"songs": [(i, r["label"], r["article"]) for i, r in f["songs"].items()],
                      "albums": [(i, r["label"] or tn.bare(r["article"])) for i, r in f["albums"].items()]}
    return out


def _titles(label, article):
    return [ids.clean_title(n) for n in (tn.bare(article), label) if n]


def songs_called(cat, title):
    """The English articles of the artist's songs with this title, never an
    album's, a film's or a band's."""
    want = ids.clean_title(title)
    return list(dict.fromkeys(a for _, label, a in (cat or {}).get("songs", [])
                              if a and not NOT_SONG.search(a) and want in _titles(label, a)))


def album_called(cat, album):
    want = ids.clean_title(ids.plain_album(album))
    for item, label in (cat or {}).get("albums", []):
        if want in _titles(label, ""):
            return item
    return None


def _wiki(t):
    return bool(t and t.get("paras") and (t.get("source") or "").startswith("wikipedia"))


def written(article, album, intros, session):
    """(paragraphs, "") from the article when track_notes.py's checks pass,
    else ([], why): the same checks, and filling out, track_notes() makes."""
    lead = intros.get(article, "")
    why = tn.usable(lead, album["artist"], need=0, album=album["album"])
    if why:
        return [], why
    text, part = tn.fill_out(lead, article, session)
    why = tn.usable(text, album["artist"], album=album["album"])
    return ([], why) if why else (tn.english_paras(text, part, article), "")


def run(lib, session, say=show.info, quiet=False):
    """Looks up the albums due, all at once; everything is saved."""
    SAVED.mkdir(parents=True, exist_ok=True)
    due = []
    for k, album in sorted(lib.items()):
        name = ab.safe_name(k)
        if not name:
            continue
        # an album track_notes.py saved nothing for (no Wikidata item, no Last.fm) is searched too
        seen = ab.load_json(tn.CACHE / "albums" / f"{name}.json") or {}
        mine = ab.load_json(SAVED / f"{name}.json") or {}
        fresh = mine.get("version") == VERSION and mine.get("after") == seen.get("checked") and \
            time.time() - mine.get("checked", 0) < RECHECK_DAYS * 86400
        if not fresh:
            due.append((k, album, seen, name, (tn.artist_ids(album["artist"]) or {}).get("wikidata")))
    say(f"{len(lib) - len(due)} albums already searched, {len(due)} to search")
    if not due:
        return
    cats = catalogue(sorted({q for *_, q in due if q}), session)
    # what each track could be written from
    plans, articles = [], set()
    for k, album, seen, name, q in due:
        cat = cats.get(q) if q else None
        if q and cat is None:
            continue                                   # Wikidata didn't answer: next run
        q_album, found, songs = None, {}, {}
        if not seen.get("wikidata") and cat:
            q_album = album_called(cat, album["album"])
            if q_album:
                songs = tn.song_items(tn.album_songs(q_album, session), session)
                found = tn.match_tracks(album["tracks"], songs)
        tracks = {}
        for i, (_, _, title) in enumerate(album["tracks"]):
            if _wiki((seen.get("tracks") or {}).get(str(i))):
                continue
            first = tn.enwiki(songs[found[i]]) if i in found and tn.enwiki(songs[found[i]]) else ""
            cands = list(dict.fromkeys(([first] if first else []) + songs_called(cat, title)))
            tracks[str(i)] = (cands, bool(first))
            articles.update(cands)
        plans.append((k, album, seen, name, q, q_album, tracks))
    intros = {}
    articles = sorted(articles)
    bar = show.Bar("Song articles", len(articles)) if not quiet else None
    for n in range(0, len(articles), 20):
        intros.update(ln.wiki_summaries(articles[n:n + 20], session))
        if bar:
            bar.update(len(articles[n:n + 20]))
    if bar:
        bar.close(f"{len(intros):,} read")
    for k, album, seen, name, q, q_album, tracks in plans:
        out = {}
        for i, (cands, from_album) in tracks.items():
            why = "no song of that title by the artist on Wikidata" if q else "the artist has no Wikidata item"
            for article in cands:
                try:
                    paras, why = written(article, album, intros, session)
                except ab.NET_ERRORS as e:
                    ab.problem(k, e)
                    paras, why = [], "Wikipedia didn't answer"
                if paras:
                    out[i] = {"paras": paras, "source": "wikipedia", "article": article,
                              "how": "album found by title" if from_album and article == cands[0]
                              else "title search"}
                    break
            else:
                out[i] = {"paras": [], "why": why}
        ab.save_json(SAVED / f"{name}.json", {"version": VERSION, "after": seen.get("checked"),
                                              "checked": int(time.time()), "album item": q_album,
                                              "tracks": out})


def merged(k, seen):
    """track_notes.py's saved record for album k with the title search's
    write-ups in: each replaces nothing or a Last.fm write-up, never a
    Wikipedia one. A copy: the saved record isn't changed."""
    name = ab.safe_name(k)
    mine = ab.load_json(SAVED / f"{name}.json") if name else None
    if not mine:
        return seen
    out = dict(seen or {})       # nothing saved by track_notes.py: the search's alone
    tracks = dict(out.get("tracks") or {})
    for i, t in (mine.get("tracks") or {}).items():
        if t.get("paras") and not _wiki(tracks.get(i)):
            tracks[i] = t
    out["tracks"] = tracks
    return out


def report(lib, folder):
    """Every track the title search filled, and every Last.fm write-up left
    with the reason Wikipedia wasn't used, in folder/REPORT."""
    filled, lastfm = [], []
    for k, album in sorted(lib.items()):
        name = ab.safe_name(k)
        seen = (ab.load_json(tn.CACHE / "albums" / f"{name}.json") if name else None) or {}
        mine = (ab.load_json(SAVED / f"{name}.json") if name else None) or {}
        for i, t in sorted((merged(k, seen).get("tracks") or {}).items(), key=lambda x: int(x[0])):
            if int(i) >= len(album["tracks"]):
                continue
            title = album["tracks"][int(i)][2]
            if t.get("how"):
                filled.append(f"{k}: \"{title}\" from \"{t['article']}\" ({t['how']})")
            elif (t.get("source") or "").startswith("last.fm"):
                why = ((mine.get("tracks") or {}).get(i) or {}).get("why") or t.get("why") or "not searched yet"
                lastfm.append(f"{k}: \"{title}\": {why}")
    (folder / REPORT).write_text(
        f"Track write-ups found by title: {len(filled)}\n\n" + "\n".join(filled) +
        f"\n\n\nWrite-ups still from Last.fm, and why Wikipedia wasn't used: {len(lastfm)}\n\n" +
        "\n".join(lastfm) + "\n", encoding="utf-8")
    return len(filled), len(lastfm)
