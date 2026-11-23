"""
wiki_count.py -- how big the notes wiki would be, from what's already saved.

A quick count for the notes wiki (the PodBox notes viewer's /Notes pages):
how many pages of each kind your library would get, how many people would
be "key people" under each rule, and how that compares with the viewer's
page index (2,048 pages, 64 KB of file paths).

It makes no requests and writes nothing to the iPod. It reads only what
ids.py, credits.py, link_dryrun.py and track_notes.py have already saved on
this PC, so the counts are as good as those runs: albums they never reached
are counted as having no credits or track notes. Results go to
"Wiki count report.txt" beside this file.

Usage:
  python wiki_count.py
"""
from __future__ import annotations

import re, sys, time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import ids
    import artist_bios as ab
    import link_dryrun as ld
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to ids.py, artist_bios.py and link_dryrun.py.")
    sys.exit(1)

REPORT = HERE / "Wiki count report.txt"
TRACKS_CACHE = ab.CACHE.parent / "tracks" / "albums"

# The viewer's page index (apps-ipod/viewers/notes_viewer/notes_files.c)
INDEX_PAGES = 2048
INDEX_POOL = 64 * 1024

# Rough file sizes, for the disk estimate
SIZE = {"bio": 3000, "album": 3500, "credits": 3000, "tracks": 5000,
        "appearances": 2000, "person": 1500, "banner": 20000}

ENGINEER = re.compile(r"engineer|recorded|record|mix", re.I)
NOT_ENGINEER = re.compile(r"assist|master|tape|lacquer|transfer|edit|second|additional", re.I)
ARRANGER = re.compile(r"arrang|conduct|orchestrat", re.I)
COVER = re.compile(r"design|photo|cover|art direction|artwork|illustrat|painting|sleeve", re.I)
EXEC = re.compile(r"executive", re.I)


def saved(kind, rid):
    return ids.saved_release(kind, rid, max_days=None) if rid else None


def track_count(item, n_tracks):
    """How many of the album's tracks a credit covers: all for a credit on
    the release; one for a track's own; a Discogs "tracks A1 to A3, B2"
    counted roughly."""
    if item is None:
        return n_tracks
    if not str(item).startswith("tracks "):
        return 1
    n = 0
    for part in str(item)[7:].split(","):
        n += 3 if re.search(r"\bto\b|-|–", part) else 1
    return min(n, n_tracks)


def main():
    records = ld.load_records()
    lib = ids.library().get("albums") or {}
    if not records or not lib:
        print("Nothing identified yet. Run ids.py first.")
        return 1
    albums = sorted(k for k in records if k in lib)

    # -- what's saved
    mbrel = {k: saved("mbrel", (records[k].get("mb") or {}).get("id")) for k in albums}
    dcrel = {k: saved("dcrel", (records[k].get("discogs") or {}).get("id")) for k in albums}
    lib_artists = sorted({a["id"] for k in albums for a in (records[k].get("mb") or {}).get("artists") or []
                          if a.get("id") and a["id"] != ids.VARIOUS})
    mbart = {a: saved("mbart", a) for a in lib_artists}
    have_art = sum(1 for v in mbart.values() if v)

    # -- each album's credits, each group from the source that credits more people in it
    credits = {}
    for k in albums:
        m = ld.mb_people(mbrel[k]) if mbrel[k] else []
        d = ld.dc_people(dcrel[k]) if dcrel[k] else []
        rows = []
        for group in ids.GROUPS:
            ms = [r for r in m if r[5] == group]
            ds = [r for r in d if r[5] == group]
            n_m, n_d = len({(r[0], r[4]) for r in ms}), len({(r[0], r[4]) for r in ds})
            if n_m or n_d:
                rows += ms if n_m >= n_d else ds
        credits[k] = rows

    # -- the same person on both sites, through MusicBrainz's Discogs links (saved only)
    same = ld.Same()
    for a, data in mbart.items():
        for d in ld.discogs_artist_ids(data):
            same.join(("mb", a), d)
    for k, rows in credits.items():
        for pid, *_ in rows:
            if pid[0] == "dc":
                s = ids.saved_release("dcurl", pid[1], max_days=None)
                for a in (s or {}).get("mb") or []:
                    same.join(("mb", a), pid)

    # -- album artists, bands and their members
    release_artists = defaultdict(set)                 # album -> {root}
    for k in albums:
        for a in (records[k].get("mb") or {}).get("artists") or []:
            if a.get("id") and a["id"] != ids.VARIOUS:
                release_artists[k].add(same.find(("mb", a["id"])))
        for a in (records[k].get("discogs") or {}).get("artists") or []:
            if a.get("id") and a["id"] not in ld.VARIOUS_DC:
                release_artists[k].add(same.find(("dc", a["id"])))
    library_artist_roots = set().union(*release_artists.values()) if release_artists else set()
    is_group = {same.find(("mb", a)): (data or {}).get("type") == "Group"
                for a, data in mbart.items() if data}
    members = defaultdict(set)                         # band root -> {member root}
    for a, data in mbart.items():
        for r in (data or {}).get("relations") or []:
            if r.get("target-type") == "artist" and r.get("type") == "member of band" \
                    and (r.get("artist") or {}).get("id"):
                members[same.find(("mb", a))].add(same.find(("mb", r["artist"]["id"])))

    # -- names, and the albums each person is on
    shown = defaultdict(set)
    albums_of = defaultdict(set)
    for k, rows in credits.items():
        for pid, name, sh, *_ in rows:
            root = same.find(pid)
            shown[root].add(name)
            albums_of[root].add(k)

    # -- key people, per album and per rule
    RULES = ("producers", "engineers", "arrangers and conductors", "songwriters on 2+ tracks",
             "core players (half the tracks)", "band members", "cover design and photography",
             "on 2+ library albums")
    key = {r: defaultdict(set) for r in RULES}         # rule -> root -> {album}
    band_member_data = 0
    for k in albums:
        n_tracks = len(lib[k].get("tracks") or []) or 1
        own = release_artists[k]
        band_members = set().union(*(members.get(b, set()) for b in own)) if own else set()
        if band_members:
            band_member_data += 1
        solo = not any(is_group.get(b) for b in own)
        cover = defaultdict(set)                       # root -> {track}
        writes = defaultdict(int)
        for pid, name, sh, note, role, group, track in credits[k]:
            root = same.find(pid)
            if root in own:
                continue
            if group == "Producers" and not EXEC.search(role):
                key["producers"][root].add(k)
            if group == "Engineers" and ENGINEER.search(role) and not NOT_ENGINEER.search(role):
                key["engineers"][root].add(k)
            if ARRANGER.search(role):
                key["arrangers and conductors"][root].add(k)
            if COVER.search(role):
                key["cover design and photography"][root].add(k)
            if group == "Songwriters":
                writes[root] += track_count(track, n_tracks)
            if group == "Musicians":
                cover[root].add(track)
        for root, n in writes.items():
            if n > 1 and root not in band_members:
                key["songwriters on 2+ tracks"][root].add(k)
        if solo:
            for root, tracks in cover.items():
                n = n_tracks if None in tracks else sum(track_count(t, n_tracks) for t in tracks)
                if n * 2 >= n_tracks and root not in band_members:
                    key["core players (half the tracks)"][root].add(k)
        for m in band_members:
            key["band members"][m].add(k)
    for root, ks in albums_of.items():
        if len(ks) >= 2:
            key["on 2+ library albums"][root] = set(ks)

    keyed = defaultdict(set)                           # root -> {album it's key on}
    for r in RULES:
        for root, ks in key[r].items():
            keyed[root] |= ks
    new_people = {r for r in keyed if r not in library_artist_roots}
    definite = {r for r in new_people if len(keyed[r]) >= 2}
    to_check = new_people - definite

    # -- pages
    artists = sorted({lib[k]["artist"] for k in albums if lib[k].get("artist")})
    with_credits = [k for k in albums if credits[k]]
    with_tracks = []
    tracks_known = TRACKS_CACHE.exists()
    for k in albums:
        seen = ab.load_json(TRACKS_CACHE / f"{ab.safe_name(k)}.json") if tracks_known else None
        if seen and any(t.get("paras") for t in (seen.get("tracks") or {}).values()):
            with_tracks.append(k)
    with_appearances = []
    for k in with_credits:
        own = release_artists[k]
        band = set().union(*(members.get(b, set()) for b in own)) if own else set()
        roots = {same.find(r[0]) for r in credits[k]} - own - band
        if any(len(albums_of[r]) >= 2 for r in roots):
            with_appearances.append(k)

    counts = {
        "Bio (library artists)": len(artists),
        "Album": len(albums),
        "Credits": len(with_credits),
        "Tracks": len(with_tracks),
        "Other Appearances": len(with_appearances),
        "Bio (key people, sure)": len(definite),
    }
    least = sum(counts.values())
    most = least + len(to_check)

    # -- names two people with pages would share
    def label(root):
        ns = sorted(shown.get(root) or {str(root)}, key=len)
        return ns[0]
    names = defaultdict(set)
    for r in new_people:
        names[ld.fold(label(r))].add(r)
    for a in artists:
        names[ld.fold(a)].add(("artist", a))
    clashes = {n: rs for n, rs in names.items() if len(rs) > 1}

    # -- the page index
    def path_len(rel):
        return len(f"/Notes/{rel}.md".encode("utf-8")) + 1
    pool = sum(path_len(f"People/{a}") for a in artists)
    pool += sum(path_len(f"Albums/{k}") for k in albums)
    pool += sum(path_len(f"Albums/{k} - Credits") for k in with_credits)
    pool += sum(path_len(f"Albums/{k} - Tracks") for k in with_tracks)
    pool += sum(path_len(f"Albums/{k} - Other Appearances") for k in with_appearances)
    per_person = sum(path_len(f"People/{label(r)}") for r in new_people) / max(1, len(new_people))
    pool_least = pool + per_person * len(definite)
    pool_most = pool + per_person * len(new_people)

    disk = (SIZE["bio"] + SIZE["banner"]) * len(artists) + SIZE["album"] * len(albums) \
        + SIZE["credits"] * len(with_credits) + SIZE["tracks"] * len(with_tracks) \
        + SIZE["appearances"] * len(with_appearances)

    # -- the report
    lines = []
    add = lines.append
    add(f"Notes wiki size, {time.strftime('%d %b %Y %H:%M')}")
    add("")
    add(f"Library: {len(albums)} albums by {len(artists)} album artists")
    add(f"Saved data used: credits for {len(with_credits)} albums "
        f"({sum(1 for v in mbrel.values() if v)} MusicBrainz releases, {sum(1 for v in dcrel.values() if v)} Discogs); "
        f"{have_art} of {len(lib_artists)} library artists looked up (band members and solo/band)"
        + ("" if tracks_known else "; track notes not run yet, so no Tracks pages counted"))
    add("")
    add("Pages")
    for name, n in counts.items():
        add(f"  {name:36} {n:6}")
    add(f"  {'Bio (key people, if a bio is found)':36} {len(to_check):6}   (key on one album: a page only if a bio is found)")
    add(f"  {'Total':36} {least:6} to {most}")
    add("")
    add("Key people by rule (people not already library artists; one person can be under several rules)")
    for r in RULES:
        people = {p for p in key[r] if p not in library_artist_roots}
        add(f"  {r:36} {len(people):6}")
    add(f"  {'all rules together':36} {len(new_people):6}   ({len(definite)} key on 2+ albums, {len(to_check)} on one)")
    if not have_art:
        add("  (band members and the solo/band test need link_dryrun.py's artist lookups: run it once for those)")
    add("")
    add(f"Names two people with pages share (need a qualifier): {len(clashes)}")
    for n, rs in sorted(clashes.items())[:30]:
        add(f"  {n}: {len(rs)}")
    if len(clashes) > 30:
        add(f"  ... and {len(clashes) - 30} more")
    add("")
    add("The viewer's page index")
    add(f"  pages:      {least} to {most} of {INDEX_PAGES}" + ("   OVER" if most > INDEX_PAGES else ""))
    add(f"  path bytes: {pool_least / 1024:.0f} to {pool_most / 1024:.0f} KB of {INDEX_POOL // 1024} KB"
        + ("   OVER" if pool_most > INDEX_POOL else ""))
    add("  Pages past either limit are left out of the index: they exist on the disk but nothing links to them.")
    add("")
    add(f"Disk, roughly: {disk / 1024 / 1024:.0f} MB for library artists and albums (banners included), "
        f"plus {SIZE['person'] * len(definite) / 1024 / 1024:.1f} to {SIZE['person'] * len(new_people) / 1024 / 1024:.1f} MB for key people")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved as {REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
