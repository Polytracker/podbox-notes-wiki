"""Who is credited where across the library.

This is the middle of ipod-liner-notes' credits.py main(), taken out so the
wiki can use what it works out rather than the file it writes: each
album's credits, each group from one source (credits.choose()); which
MusicBrainz and Discogs entries are one person; the library's bands and
their members; and every album each person is on.

With `mb` None it makes no requests and uses only what earlier runs saved,
expired or not.
"""
from collections import Counter, defaultdict

from . import ab                     # noqa: F401  (sets up liner/ first)
import credits as cr
import ids


def saved_or_fetch(site, kind, key, url, params=None):
    if site is None:
        return ids.saved_release(kind, key, max_days=None)
    return cr.fetch(site, kind, key, url, params)


def same_from_saved(dc_ids):
    """confirm_same() without requests: the Discogs links earlier runs saved."""
    links_to = defaultdict(set)
    for d in dc_ids:
        saved = ids.saved_release("dcurl", d, max_days=None)
        links_to[d].update((saved or {}).get("mb") or [])
    return links_to


class Graph:
    """What credits.py works out, kept:

    chosen[k]           {group: (source, [credit])}, a credit being
                        (pid, name, shown, role, group, tracks or None)
    same                which IDs are one person (find() gives the root)
    release_artists[k]  the roots credited as the album's artist
    members[band root]  the roots of its members (MusicBrainz)
    member_rels[band]   MusicBrainz's member relations, for the Members list
    appear[root][k]     {(role, tracks or None)}: everywhere a person is
    insiders[k]         the album's artist and its members
    name[root]          the name shown most often for them
    mbart[mbid]         the saved MusicBrainz artist, for library artists
    mbrel[k], dcrel[k]  the saved releases
    """


def build(lib, records, mb=None, dc=None, progress=print):
    g = Graph()
    keys = sorted(records)
    g.mbrel, g.dcrel = {}, {}
    for k in keys:
        r = records[k]
        if (r.get("mb") or {}).get("id"):
            g.mbrel[k] = saved_or_fetch(mb, "mbrel", r["mb"]["id"], f"{ids.MB}release/{r['mb']['id']}",
                                        {"inc": ids.LOOKUP_INC, "fmt": "json"})
        if (r.get("discogs") or {}).get("id"):
            g.dcrel[k] = saved_or_fetch(dc, "dcrel", r["discogs"]["id"],
                                        f"{ids.DISCOGS}releases/{r['discogs']['id']}")

    # -- each album's credits, as its Credits page shows them
    g.chosen = {}
    for k in keys:
        sources = [("tags", cr.tag_credits(lib[k]))]
        if g.mbrel.get(k):
            sources.append(("MusicBrainz", cr.mb_credits(g.mbrel[k], records[k].get("mb") or {})))
        if g.dcrel.get(k):
            sources.append(("Discogs", cr.dc_credits(g.dcrel[k], records[k].get("discogs") or {})))
        g.chosen[k] = cr.choose(sources, len(lib[k]["tracks"]))

    # -- who's who
    g.same = same = cr.Same()
    release_artist_of = defaultdict(set)
    for k in keys:
        for a in (records[k].get("mb") or {}).get("artists") or []:
            if a.get("id") and a["id"] != ids.VARIOUS:
                release_artist_of[("mb", a["id"])].add(k)
        for a in (records[k].get("discogs") or {}).get("artists") or []:
            if a.get("id") and a["id"] not in cr.VARIOUS_DC:
                release_artist_of[("dc", a["id"])].add(k)
    lib_artists = sorted({p[1] for p in release_artist_of if p[0] == "mb"})
    member_of = defaultdict(set)
    g.mbart, g.member_rels = {}, defaultdict(list)
    for a in lib_artists:
        data = saved_or_fetch(mb, "mbart", a, f"{ids.MB}artist/{a}", {"inc": "url-rels+artist-rels", "fmt": "json"})
        g.mbart[a] = data
        for d in cr.discogs_artist_ids(data):
            same.join(("mb", a), d)
        for r in (data or {}).get("relations") or []:
            if r.get("target-type") == "artist" and r.get("type") in cr.MEMBER_TYPES \
                    and (r.get("artist") or {}).get("id"):
                member_of[("mb", r["artist"]["id"])].add(("mb", a))
                if r.get("type") == "member of band" and r.get("direction") == "backward":
                    g.member_rels[a].append(r)

    shown = [(k, c) for k in keys for _, creds in g.chosen[k].values() for c in creds]
    by_name = defaultdict(set)
    albums_of = defaultdict(set)
    for k, c in shown:
        by_name[cr.fold(c[1])].add(c[0])
        albums_of[c[0]].add(k)
    candidates = {n: ps for n, ps in by_name.items()
                  if any(p[0] == "mb" for p in ps) and any(p[0] == "dc" for p in ps)
                  and len(set().union(*[albums_of[p] for p in ps])) > 1}
    dc_wanted = {p[1] for ps in candidates.values() for p in ps if p[0] == "dc"}
    links_to = cr.confirm_same(mb, dc_wanted, same) if mb else same_from_saved(dc_wanted)
    for ps in candidates.values():
        for d in (p for p in ps if p[0] == "dc"):
            for m in links_to.get(d[1], ()):
                if ("mb", m) in ps:
                    same.join(("mb", m), d)
    names_seen = defaultdict(set)              # a site's name, and as credited on each album
    for k, c in shown:
        for n in {c[1], c[2]}:
            if n:
                names_seen[cr.fold(n)].add(c[0])
    join_by_artist(same, names_seen, albums_of, lib)

    # -- where each person appears
    g.appear = defaultdict(lambda: defaultdict(set))
    for k, c in shown:
        g.appear[same.find(c[0])][k].add((c[3], frozenset(c[5]) if c[5] is not None else None))
    g.release_artists = defaultdict(set)
    for pid, ks in release_artist_of.items():
        r = same.find(pid)
        for k in ks:
            g.release_artists[k].add(r)
        if r in g.appear:
            for k in ks:
                g.appear[r][k].add(("Album artist", None))
    g.members = defaultdict(set)
    for person, bands in member_of.items():
        r = same.find(person)
        for b in bands:
            g.members[same.find(b)].add(r)
        if r in g.appear:
            for b in bands:
                for k in release_artist_of.get(b, ()):
                    g.appear[r][k].add((f"Member of {lib[k]['artist']}", None))
    g.insiders = defaultdict(set)
    for k, roots in g.release_artists.items():
        g.insiders[k] |= roots
        for b in roots:
            g.insiders[k] |= g.members.get(b, set())

    # -- the name each person is shown by
    names = defaultdict(Counter)
    for k, c in shown:
        names[same.find(c[0])][c[2] or c[1]] += 1
    for a, data in g.mbart.items():
        if data and data.get("name"):
            names[same.find(("mb", a))][data["name"]] += 100
    g.name = {r: c.most_common(1)[0][0] for r, c in names.items()}
    return g


def ids_of(g):
    """{root: {"mb": [...], "dc": [...]}}: every MusicBrainz and Discogs ID of
    each person, worked out once from the who's-who table and kept."""
    if getattr(g, "_ids", None) is None:
        g._ids = {}
        for x in list(g.same.up):
            if x[0] in ("mb", "dc"):
                g._ids.setdefault(g.same.find(x), {"mb": [], "dc": []})[x[0]].append(x[1])
    return g._ids


def join_by_artist(same, by_name, albums_of, lib):
    """One name (a site's own, or as an album credits them: Discogs' "Phil
    Selway" is credited "Philip Selway"), one MusicBrainz entry and one
    Discogs entry still apart, both credited on albums by the same album
    artist: one person. An album's
    credits come from one site or the other, so a band member is often
    MusicBrainz's on one album and Discogs' on the next, and the two sites
    don't always link their entries. Two entries on the same site stay two
    people, as that site says they are."""
    for ps in by_name.values():
        mbs = {same.find(p) for p in ps if p[0] == "mb"}
        dcs = [p for p in ps if p[0] == "dc" and same.find(p) not in mbs]
        if not mbs or not dcs:
            continue
        def artists(roots):
            return {lib[k]["artist"] for p in ps if same.find(p) in roots for k in albums_of[p]}
        for d in dcs:
            theirs = artists({same.find(d)})
            match = [m for m in mbs if artists({m}) & theirs]
            if len(match) == 1:
                same.join(match[0], d)


def mb_id(g, root):
    """A MusicBrainz ID for the person, if any of their entries has one."""
    if root[0] == "mb":
        return root[1]
    found = (ids_of(g).get(root) or {}).get("mb")
    return found[0] if found else None


def dc_id(g, root):
    if root[0] == "dc":
        return root[1]
    found = (ids_of(g).get(root) or {}).get("dc")
    return found[0] if found else None
