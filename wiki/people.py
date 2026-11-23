"""Who gets a page, and where it is (design point 6 and 7).

- Every library artist has a page, People/<album artist>, named exactly as
  the album artist tag is, since the viewer finds it by that name.
- Key people are chosen per album by fixed rules (KEY_RULES), the rules
  tools/wiki_count.py counted. Never the album's own artist, nor a company.
- A key person gets a page when they're key on two or more library albums,
  or when a bio is found for them (`has_bio`, from lookups.py).
- A name two people with pages share takes a qualifier on the one who
  isn't a library artist: the first 8 characters of their MusicBrainz ID.
"""
import re
from collections import defaultdict

from . import md
from .graph import mb_id, dc_id
import credits as cr

ENGINEER = re.compile(r"engineer|recorded|record|mix", re.I)
NOT_ENGINEER = re.compile(r"assist|master|tape|lacquer|transfer|edit|second|additional", re.I)
ARRANGER = re.compile(r"arrang|conduct|orchestrat", re.I)
COVER = re.compile(r"design|photo|cover|art direction|artwork|illustrat|painting|sleeve", re.I)
EXEC = re.compile(r"executive", re.I)
COMPANY = re.compile(r"\b(productions?|records|recordings|studios?|music|publishing|ltd|inc|llc|"
                     r"gmbh|entertainment|management|label)\b\.?$", re.I)

RULES = ("producers", "engineers", "arrangers and conductors", "songwriters on 2+ tracks",
         "core players (half the tracks)", "band members", "cover design and photography",
         "on 2+ library albums")


def plain_roles(role_texts):
    """people_rows()'s role texts without their track numbers, at most three."""
    out = []
    for g in role_texts:
        for r in re.sub(r"\s*\[[^\]]*\]$", "", g).split(", "):
            if r and r not in out:
                out.append(r)
    return out


class Wiki:
    """Who has a page and where.

    artist_page[album artist tag]   its place
    root_page[root]                 a person's place, library artists included
    key[k]                          [(root, roles)] the album's Key People, in order
    keyed[root]                     the albums they're key on
    lib_root[root]                  the album artist tag a root's page is
    """


def library_artist_roots(g, lib):
    """Each root credited as an album's artist whose name is that album's
    album artist tag: their page is the library artist's."""
    out = {}
    for k, roots in g.release_artists.items():
        tag = lib[k]["artist"]
        for r in roots:
            if cr.fold(g.name.get(r, "")) == cr.fold(tag) or len(roots) == 1:
                out.setdefault(r, tag)
    return out


def key_people(g, lib):
    """{album: [(root, roles)]}, and {root: {albums}} with every rule's albums."""
    albums_of = defaultdict(set)
    for k, groups in g.chosen.items():
        for _, creds in groups.values():
            for c in creds:
                albums_of[g.same.find(c[0])].add(k)
    lib_roots = library_artist_roots(g, lib)
    per_album, keyed = {}, defaultdict(set)
    for k, groups in g.chosen.items():
        n = len(lib[k]["tracks"]) or 1
        own = g.release_artists.get(k, set())
        band = set().union(*(g.members.get(b, set()) for b in own)) if own else set()
        solo = not any(((g.mbart.get(r[1]) if r[0] == "mb" else None) or {}).get("type") == "Group"
                       for r in own)
        why = defaultdict(set)
        writes, plays = defaultdict(int), defaultdict(set)
        roles = defaultdict(list)
        order = []
        for group in ids_groups():
            if group not in groups:
                continue
            for pid, name, texts in cr.people_rows(groups[group][1], lib[k]):
                root = g.same.find(pid)
                if root not in order:
                    order.append(root)
                roles[root] += [r for r in plain_roles(texts) if r not in roles[root]]
            for pid, name, shown, role, grp, tracks in groups[group][1]:
                root = g.same.find(pid)
                if root in own:
                    continue
                if grp == "Producers" and not EXEC.search(role):
                    why[root].add("producers")
                if grp == "Engineers" and ENGINEER.search(role) and not NOT_ENGINEER.search(role):
                    why[root].add("engineers")
                if ARRANGER.search(role):
                    why[root].add("arrangers and conductors")
                if COVER.search(role):
                    why[root].add("cover design and photography")
                if grp == "Songwriters":
                    writes[root] = n if tracks is None else max(writes[root], 0) + len(tracks)
                if grp == "Musicians":
                    plays[root] |= set(range(n)) if tracks is None else tracks
        for root, w in writes.items():
            if w > 1 and root not in band:
                why[root].add("songwriters on 2+ tracks")
        if solo:
            for root, t in plays.items():
                if len(t) * 2 >= n and root not in band:
                    why[root].add("core players (half the tracks)")
        for root in order:
            if root in band:
                why[root].add("band members")
            if len(albums_of[root]) >= 2 and root not in own:
                why[root].add("on 2+ library albums")
        chosen = []
        for root in order:
            if not why[root] or root in own:
                continue
            if root not in lib_roots and COMPANY.search(g.name.get(root, "")):
                continue
            chosen.append((root, roles[root][:3]))
            keyed[root].add(k)
        per_album[k] = chosen
    return per_album, keyed, albums_of


def ids_groups():
    import ids
    return ids.GROUPS


def qualifier(g, root):
    m = mb_id(g, root)
    if m:
        return m[:8]
    d = dc_id(g, root)
    return f"d{d}" if d else None


def assign(g, lib, has_bio=lambda root: False):
    """Who has a page, and the place of each."""
    w = Wiki()
    w.key, w.keyed, w.albums_of = key_people(g, lib)
    w.lib_root = library_artist_roots(g, lib)
    w.artist_page, w.canon, first = {}, {}, {}
    for k in sorted(lib):
        tag = lib[k]["artist"]
        key = md.file_name(tag).casefold()     # the iPod's disk doesn't tell capitals apart
        first.setdefault(key, tag)
        w.canon[tag] = first[key]
        w.artist_page.setdefault(tag, md.person_place(first[key]))
    taken = {md.file_name(t).casefold(): t for t in w.artist_page}
    # spellings sharing a page that the sites say are different artists
    roots_of = defaultdict(set)
    for r, t in w.lib_root.items():
        roots_of[t].add(r)
    spellings = defaultdict(list)
    for t, c in w.canon.items():
        spellings[c].append(t)
    w.case_clashes = [sorted(ts) for ts in spellings.values() if len(ts) > 1
                      and all(roots_of[ts[0]].isdisjoint(roots_of[t]) and roots_of[t] for t in ts[1:])
                      and roots_of[ts[0]]]
    by_fold = {cr.fold(t): w.canon[t] for t in w.artist_page}
    for r in w.keyed:
        # a key person named as a library artist, credited on an album that
        # artist's name is in, is that artist (MF DOOM, Jimi Hendrix, Brian Eno
        # on "Brian Eno, David Byrne"): their artist page, not a second one
        tag = by_fold.get(cr.fold(g.name.get(r, "")))
        if r not in w.lib_root and tag and any(cr.fold(tag) in cr.fold(lib[k]["artist"])
                                               for k in w.albums_of.get(r, ()) if k in lib):
            w.lib_root[r] = tag

    people = [r for r in w.keyed if r not in w.lib_root and r[0] != "tag"
              and (len(w.keyed[r]) >= 2 or has_bio(r))]
    by_file = defaultdict(list)
    for r in people:
        by_file[md.file_name(g.name.get(r, "")).casefold()].append(r)
    w.root_page = {r: w.artist_page[t] for r, t in w.lib_root.items()}
    for name, rs in by_file.items():
        if not name:
            continue
        clash = len(rs) > 1 or name in taken
        for r in rs:                         # (a credit from the files' tags, with no ID, isn't
                                             # someone else: it links to the page of that name)
            shown = g.name[r]
            if clash:
                q = qualifier(g, r)
                if not q:
                    continue                 # no ID to tell them apart: no page
                shown = f"{shown} ({q})"
            place = md.person_place(shown)
            if md.path_ok(place):
                w.root_page[r] = place
    return w
