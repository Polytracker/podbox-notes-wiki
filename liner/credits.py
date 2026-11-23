"""
credits.py -- the Credits page in PodBox's liner notes viewer.

For every album ids.py has identified, it writes one file into the iPod's
Artwork\\Credits folder:

  <Album Artist> - <Album>.txt

The page lists who played, produced, engineered and wrote the album, in five
groups: Musicians, Producers, Engineers, Songwriters and Credited (everyone
else). Each group comes whole from one source, never mixed: your files' own
credit tags if they have any for that group, otherwise whichever of
MusicBrainz and Discogs covers more of your album in it (each person and
role counts for the share of your tracks it's on, so a band credited
throughout outweighs guests on a single track). The page names the
edition its credits are for, and how its tracks compare with yours, so you
know what you're reading. Credits for tracks you don't have are left out;
credits for only some of your tracks say which ("Drums [2, 5-7]", drawn
on the iPod as small grey numbers).

At the end of each file is a hidden "#links" section for the page's Other
Appearances list (Select on the Credits page): the people credited here who
are also on other albums in your library. A band's own members aren't
listed for the band's other albums (that would be every one of them), but
anyone else is: a band's producer leads to the other albums they produced. People are matched by
their MusicBrainz or Discogs ID, never by name. Someone credited on one site
and on another album through the other site is joined only when MusicBrainz
links the two.

Run ids.py first; this reuses the releases it saved, so it needs few
requests. Files you've edited yourself are never overwritten, and nothing is
ever deleted. If the Credits page is switched off on the iPod (Settings >
Appearance > Viewers), this does nothing.

Usage:
  python credits.py                              the iPod in the settings file
  python credits.py --only "Radiohead - OK Computer"
  python credits.py --ipod "credits test"        write to a test folder, not the iPod
"""
from __future__ import annotations

import argparse, re, sys, time, unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import artist_bios as ab
    import ids
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to ids.py, artist_bios.py and art_fetch.py, and run: "
          "pip install requests pillow mutagen opencv-python")
    sys.exit(1)

CACHE = ab.CACHE.parent / "credits"
LINK_ROWS = 40                               # an Other Appearances list, at most
VARIOUS_DC = {194, 355}                      # Discogs "Various", "Unknown Artist"
MEMBER_TYPES = {"member of band", "is person", "collaboration", "subgroup"}


# ---------------------------------------------------------------- small helpers
def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = re.sub(r"\s*\(\d+\)$", "", s)                  # Discogs "Tom Smith (2)"
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def dc_name(s):
    """A Discogs name without its "(2)" for same-named people."""
    return re.sub(r"\s*\(\d+\)$", "", s or "").strip()

def cap(s):
    return s[:1].upper() + s[1:] if s else s



# ---------------------------------------------------------------- roles
# MusicBrainz names some jobs by the work alone: "recording" on its own
# reads like the recording itself, so these get the name of the job.
MB_NAMES = {"recording": "recording engineer", "audio": "audio engineer",
            "sound": "sound engineer", "balance": "balance engineer",
            "mix": "mixing", "programming": "programming"}

# Discogs says "Recorded By"; the page uses the same words as MusicBrainz,
# so the two sources read alike on one page.
DC_NAMES = {"recorded by": "Recording engineer", "mixed by": "Mixing",
            "mastered by": "Mastering"}

def mb_role(r):
    """ "Guitar", "Lead vocals", "Executive producer", "Mix" from a MusicBrainz relationship."""
    t = (r.get("type") or "").lower()
    attrs = [a for a in r.get("attributes") or [] if a not in ("additional", "guest", "solo")]
    extra = [a for a in r.get("attributes") or [] if a in ("additional", "guest", "solo")]
    if t == "instrument":
        role = ", ".join(attrs) or "instruments"
    elif t == "vocal":
        role = ", ".join(attrs) or "vocals"
    elif t in ("performer", "performing orchestra"):
        role = ", ".join(attrs) or "performer"
    else:
        role = " ".join(attrs + [MB_NAMES.get(t, t)])   # "executive producer", "assistant recording engineer"
    role = role.replace("co producer", "co-producer")
    if "solo" in extra:
        role += " solo"
    lead = [a for a in extra if a != "solo"]           # "Additional bass guitar", "Guest piano"
    if lead:
        role = " ".join(lead) + " " + role[:1].lower() + role[1:]
    return cap(role)

def dc_role(role):
    """Discogs writes "Guitar [Electric]" and "Recorded By"; the page says
    "Guitar (Electric)" and "Recording engineer". What's in brackets keeps its
    capitals ("Synthesizer (Moog)")."""
    base = re.sub(r"\s*\[.*", "", role.strip()).lower()
    if base in DC_NAMES:
        # "Mixed By [Assistant Mix Engineer]" → "Assistant mixing engineer"
        inner = re.findall(r"\[([^\]]*)\]", role)
        name = DC_NAMES[base]
        rest = inner[0].strip() if inner else ""
        if rest.lower().startswith("assistant"):
            name = "Assistant " + name[:1].lower() + name[1:]
            if not name.endswith("engineer"):
                name += " engineer"                       # "Assistant mixing engineer"
            rest = rest[len("assistant"):].strip()
        if rest and not re.search(r"engineer|" + base.split()[0][:4], rest, re.I):
            name += f" ({rest})"                          # "Recording engineer (Additional Strings)"
        return cap(name)

    def bracket(m):
        # a note that only says the role again goes: "Engineer [Engineered By]",
        # "Backing Vocals [Background Vocals]", "Bass [Live Bass]"
        inner = m.group(1).strip()
        same_start = base and inner.lower().startswith(base[:5])
        same_end = base and inner.lower().split()[-1:] == base.split()[-1:]
        return "" if same_start or same_end else f" ({inner})"
    role = re.sub(r"\s*\[([^\]]*)\]", bracket, role.strip())
    role = re.sub(r"(?<=[\s-])By\b", "by", role)
    return cap(role)


# ---------------------------------------------------------------- credits from each source
# A credit is (pid, name, shown, role, group, tracks): pid is ("mb", id),
# ("dc", id) or ("tag", folded name); tracks is the set of your tracks (by
# their place in the folder) it's for, or None for all of them.

def mb_credits(rel, rec):
    """The credits on a saved MusicBrainz release, for your tracks only."""
    by_recording = defaultdict(set)
    for i, t in (rec.get("tracks") or {}).items():
        if t.get("recording"):
            by_recording[t["recording"]].add(int(i))
    out = []

    def add(rels, tracks):
        for r in rels or []:
            if r.get("target-type") == "work":
                add((r.get("work") or {}).get("relations"), tracks)
                continue
            a = r.get("artist") or {}
            if r.get("target-type") != "artist" or not a.get("id") or a["id"] == ids.VARIOUS:
                continue
            out.append((("mb", a["id"]), a.get("name", ""), r.get("target-credit") or a.get("name", ""),
                        mb_role(r), ids.mb_group(r.get("type")), tracks))

    add(rel.get("relations"), None)
    for medium in rel.get("media") or []:
        for t in medium.get("tracks") or []:
            rid = (t.get("recording") or {}).get("id")
            mine = by_recording.get(rid)
            if mine:
                add((t.get("recording") or {}).get("relations"), set(mine))
    return out

def dc_positions(rel):
    """Every track position on a Discogs release in order, index tracks' parts included."""
    out = []
    for t in rel.get("tracklist") or []:
        if t.get("position"):
            out.append(t["position"])
        for s in t.get("sub_tracks") or []:
            if s.get("position"):
                out.append(s["position"])
    return out

def dc_track_list(spec, order):
    """ "A1 to A3, B2" -> ["A1", "A2", "A3", "B2"], or None if it can't be read."""
    out = []
    for part in re.split(r"\s*[,&]\s*", spec.strip()):
        if not part:
            continue
        ends = re.split(r"\s+to\s+|\s*[-–]\s*(?=[A-Za-z]?\d)", part)
        if len(ends) == 2 and ends[0] in order and ends[1] in order:
            a, b = order.index(ends[0]), order.index(ends[1])
            out += order[min(a, b):max(a, b) + 1]
        elif part in order:
            out.append(part)
        else:
            return None
    return out

def dc_credits(rel, rec):
    """The credits on a saved Discogs release, for your tracks only."""
    by_position = defaultdict(set)
    for i, t in (rec.get("tracks") or {}).items():
        if t.get("position"):
            by_position[t["position"]].add(int(i))
    order = dc_positions(rel)
    # an index track's parts count as the index track
    for t in rel.get("tracklist") or []:
        mine = by_position.get(t.get("position") or "")
        for s in t.get("sub_tracks") or []:
            if mine and s.get("position"):
                by_position[s["position"]] |= mine
    out = []

    def add(people, tracks):
        for a in people or []:
            if not a.get("id") or a["id"] in VARIOUS_DC:
                continue
            these = tracks
            if tracks is None and (a.get("tracks") or "").strip():
                listed = dc_track_list(a["tracks"], order)
                if listed is not None:
                    these = set().union(*[by_position.get(p, set()) for p in listed]) if listed else set()
                    if not these:
                        continue                         # only on tracks you don't have
            for role in re.split(r",\s*(?![^\[]*\])", a.get("role") or ""):
                if role.strip():
                    out.append((("dc", a["id"]), dc_name(a.get("name")), dc_name(a.get("anv") or a.get("name")),
                                dc_role(role), ids.dc_group(role), these))

    add(rel.get("extraartists"), None)
    for t in rel.get("tracklist") or []:
        mine = by_position.get(t.get("position") or "")
        if mine:
            add(t.get("extraartists"), set(mine))
        for s in t.get("sub_tracks") or []:
            sub = by_position.get(s.get("position") or "")
            if sub:
                add(s.get("extraartists"), set(sub))
    return out

def tag_credits(album):
    return [(("tag", fold(who)), who, who, cap(role), group, {i})
            for who, role, group, i in album.get("tag_credits") or []]


# ---------------------------------------------------------------- choosing and laying out
def coverage(creds, n_tracks):
    """How much of your album a source's credits cover: each different
    person+role counts for the share of your tracks it's on (1 for the whole
    album), so a band credited throughout outweighs guests on one track."""
    spans = {}
    for c in creds:
        key = (c[0], c[3])
        if c[5] is None or spans.get(key, set()) is None:
            spans[key] = None
        else:
            spans[key] = spans.get(key, set()) | c[5]
    if not n_tracks:
        return float(len(spans))
    return sum(1.0 if t is None else min(1.0, len(t) / n_tracks) for t in spans.values())

def choose(sources, n_tracks=0, weighted=True):
    """{group: (source name, credits)}: your tags for a group if they have
    any, else the site whose credits in it cover more of your album
    (weighted=False: the site with more different person+role pairs)."""
    out = {}
    for group in ids.GROUPS:
        best = None
        for name, creds in sources:
            mine = [c for c in creds if c[4] == group]
            if not mine:
                continue
            if name == "tags":                       # the files' own say comes first
                best = (name, mine, float("inf"))
                break
            score = coverage(mine, n_tracks) if weighted else float(len({(c[0], c[3]) for c in mine}))
            if best is None or score > best[2] + 1e-9:
                best = (name, mine, score)
        if best:
            out[group] = best[:2]
    return out

def track_label(album):
    """Your track at place i, as the page names it: "5", or "2-5" on a multi-disc album."""
    tracks = album["tracks"]
    multi = len({t[0] for t in tracks}) > 1
    return lambda i: f"{tracks[i][0]}-{tracks[i][1]}" if multi else str(tracks[i][1])

def track_ranges(places, label):
    """Places [0, 1, 2, 4] -> "1-3, 5" (by your track numbers)."""
    places = sorted(places)
    runs, start = [], None
    for n, p in enumerate(places):
        if start is None:
            start = p
        if n + 1 == len(places) or places[n + 1] != p + 1:
            runs.append(label(start) if start == p else f"{label(start)}\u2013{label(p)}")
            start = None
    return ", ".join(runs)

def people_rows(creds, album):
    """One row per person, in the source's order: (pid, name, ["Role (2, 5)", ...])."""
    every = set(range(len(album["tracks"])))
    label = track_label(album)
    order, names, roles = [], {}, defaultdict(dict)
    for pid, name, shown, role, group, tracks in creds:
        if pid not in names:
            order.append(pid)
            names[pid] = shown or name
        have = roles[pid].get(role, set())
        roles[pid][role] = None if tracks is None or have is None else have | tracks
    rows = []
    for pid in order:
        # roles on the same tracks share one set of numbers:
        # "Alto Saxophone, Flute (1, 7)", not "Alto Saxophone (1, 7), Flute (1, 7)"
        spans = {}
        for role, tracks in roles[pid].items():
            span = "" if tracks is None or tracks >= every else track_ranges(tracks, label)
            spans.setdefault(span, []).append(role)
        texts = [", ".join(rs) + (f" [{span}]" if span else "") for span, rs in spans.items()]
        rows.append((pid, names[pid], texts))
    return rows

def roles_text(groups):
    """A person's roles as the page writes them, joined by commas. Track
    numbers go in square brackets, which the viewer draws small and grey
    without the brackets, so the comma after them still reads as a break:
    "Backing vocals [3, 9], Performer, Lead vocals [3–5, 7–10]"."""
    return ", ".join(groups)


# ---------------------------------------------------------------- people across the library
class Same:
    """Which IDs are one person."""
    def __init__(self):
        self.up = {}
    def find(self, x):
        self.up.setdefault(x, x)
        while self.up[x] != x:
            self.up[x] = self.up[self.up[x]]
            x = self.up[x]
        return x
    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.up[max(a, b)] = min(a, b)

def discogs_artist_ids(mb_artist):
    out = set()
    for r in (mb_artist or {}).get("relations") or []:
        m = re.search(r"discogs\.com/artist/(\d+)", (r.get("url") or {}).get("resource") or "")
        if m:
            out.add(("dc", int(m.group(1))))
    return out

def fetch(site, kind, key, url, params=None):
    """A saved release or artist, else fetched and saved."""
    data = ids.saved_release(kind, key)
    if data is None and site is not None:
        data = site.get(url, params)
        ids.save_release(kind, key, data)
    return data

def confirm_same(mb, dc_ids, same):
    """Join each Discogs artist to the MusicBrainz artists that link to it,
    asking MusicBrainz about 100 Discogs artists per request."""
    links_to = defaultdict(set)
    to_ask = []
    for d in sorted(dc_ids):
        saved = ids.saved_release("dcurl", d)
        if saved is None:
            to_ask.append(d)
        else:
            links_to[d].update(saved.get("mb") or [])
    for n in range(0, len(to_ask), 100):
        batch = to_ask[n:n + 100]
        params = [("resource", f"https://www.discogs.com/artist/{d}") for d in batch]
        data = mb.get(f"{ids.MB}url", params + [("inc", "artist-rels"), ("fmt", "json")])
        if data is None:                  # nothing found, or the request failed: save nothing
            continue
        found = {d: [] for d in batch}
        for u in data.get("urls") or ([data] if data.get("resource") else []):
            m = re.search(r"discogs\.com/artist/(\d+)", u.get("resource") or "")
            if m and int(m.group(1)) in found:
                found[int(m.group(1))] = [r["artist"]["id"] for r in u.get("relations") or []
                                          if (r.get("artist") or {}).get("id")]
        for d, mbids in found.items():
            ids.save_release("dcurl", d, {"mb": mbids})
            links_to[d].update(mbids)
    return links_to

def link_rows(person_root, this_key, this_artist, appear, lib, insiders=None):
    """The hidden #links rows for one person: their other albums in your
    library (and tracks, when they're only on a few). The same artist's
    other albums count only for people who aren't the artist or one of its
    members (a band's producer, not the band), and come after other
    artists' albums."""
    insiders = insiders or {}
    rows = []
    def order(k):
        return (fold(lib[k]["artist"]) == this_artist, fold(lib[k]["artist"]), fold(lib[k]["album"]))
    for k2 in sorted(appear[person_root], key=order):
        if k2 == this_key:
            continue
        if fold(lib[k2]["artist"]) == this_artist and person_root in insiders.get(k2, ()):
            continue
        a2 = lib[k2]
        how = appear[person_root][k2]               # {(role, tracks or None)}
        tracks = set()
        whole = any(t is None for _, t in how)
        for _, t in how:
            tracks |= t or set()
        roles = list(dict.fromkeys(r for r, _ in how))
        role = ", ".join(roles[:3]) + (", \u2026" if len(roles) > 3 else "")
        if not whole and 0 < len(tracks) <= 3:
            for i in sorted(tracks):
                these = [r for r, t in how if t and i in t]
                rows.append(f"T\t{a2['artist']}\t{a2['album']}\t{a2['tracks'][i][2]}\t{', '.join(these[:3])}")
        else:
            rows.append(f"A\t{a2['artist']}\t{a2['album']}\t{role}")
    return rows[:LINK_ROWS]


# ---------------------------------------------------------------- the page
def status_line(n):
    if n == 0:
        return "No one here appears elsewhere in your library"
    if n == 1:
        return "1 person appears elsewhere in your library"
    return f"{n} people appear elsewhere in your library"

def sources_line(chosen):
    """ "Musicians and engineers from Discogs, producers from MusicBrainz",
    or "Credits from Discogs" when one source gave everything."""
    names = {"tags": "your files' tags", "MusicBrainz": "MusicBrainz", "Discogs": "Discogs"}
    by_src = defaultdict(list)
    for group in ids.GROUPS:
        if group in chosen:
            by_src[chosen[group][0]].append("other credits" if group == "Credited" else group.lower())
    if len(by_src) == 1:
        return f"Credits from {names[next(iter(by_src))]}"
    parts = []
    for src, groups in by_src.items():
        listed = groups[0] if len(groups) == 1 else ", ".join(groups[:-1]) + " and " + groups[-1]
        parts.append(f"{listed} from {names[src]}")
    return cap(", ".join(parts))

PLACES = {"XW": "Worldwide", "XE": "Europe", "XU": "", "XG": "", "": "",
          # MusicBrainz writes countries as ISO codes; Discogs already in words
          "GB": "UK", "US": "US", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
          "IE": "Ireland", "FR": "France", "DE": "Germany", "NL": "Netherlands",
          "BE": "Belgium", "LU": "Luxembourg", "CH": "Switzerland", "AT": "Austria",
          "IT": "Italy", "ES": "Spain", "PT": "Portugal", "SE": "Sweden", "NO": "Norway",
          "DK": "Denmark", "FI": "Finland", "IS": "Iceland", "PL": "Poland",
          "CZ": "Czechia", "HU": "Hungary", "GR": "Greece", "TR": "Turkey",
          "RU": "Russia", "UA": "Ukraine", "JP": "Japan", "KR": "South Korea",
          "CN": "China", "TW": "Taiwan", "HK": "Hong Kong", "SG": "Singapore",
          "IN": "India", "ID": "Indonesia", "MY": "Malaysia", "PH": "Philippines",
          "TH": "Thailand", "IL": "Israel", "ZA": "South Africa", "NG": "Nigeria",
          "BR": "Brazil", "AR": "Argentina", "MX": "Mexico", "CL": "Chile",
          "CO": "Colombia", "JM": "Jamaica", "YU": "Yugoslavia", "SU": "Soviet Union",
          "XC": "Czechoslovakia", "DD": "East Germany"}
FORMATS = {"Digital Media": "Digital", "File": "Digital"}

def plain_edition(edition, album_title):
    """ "OK Computer · 2016 · Digital Media · XW" (as ids.py writes it) ->
    "2016, Digital, Worldwide" (commas on the page: Scrim has no dot dividers):
    the title goes when it's the album's own (it's just above), and
    MusicBrainz's codes become words."""
    parts = [p.strip() for p in (edition or "").split(" · ")]
    if parts and fold(parts[0]) == fold(album_title):
        parts = parts[1:]
    out = []
    for p in parts:
        p = PLACES.get(p, p)
        p = re.sub(r"\b(Digital Media|File)\b", lambda m: FORMATS[m.group(1)], p)
        if p:
            out.append(p)
    return " \u00b7 ".join(out)

def page_text(key, album, rec, chosen, links, editions=None):
    """The Credits file. Lines starting "#" are drawn by the viewer in its
    own styles, not as written: "#facts" and "#status" as small grey lines
    under the title, "## Group" as a bold heading, "#sources" as the small
    grey line at the end; "#links" starts the hidden Other Appearances list.
    A person is "Name<TAB>Role, Role [2, 5], Role": what's in square
    brackets is track numbers, drawn small and grey."""
    lines = []
    used = [src for src in ("MusicBrainz", "Discogs") if src in {s for s, _ in chosen.values()}]
    for src in used:
        found = rec.get("mb" if src == "MusicBrainz" else "discogs") or {}
        edition = (editions or {}).get(src) or found.get("edition") or found.get("title") or ""
        note = ids.tracks_note({"tracks": album["tracks"]}, found)
        edition = plain_edition(edition, album["album"])
        if not edition:
            continue
        lead = "Edition:" if len(used) == 1 else f"{src} edition:"
        lines.append("#facts\t" + " \u00b7 ".join(x for x in (f"{lead} {edition}", note) if x))
    lines.append(f"#status\t{status_line(len(links))}")
    for group in ids.GROUPS:
        if group not in chosen:
            continue
        lines.append("")
        lines.append(f"## {group}")
        for _, name, roles in people_rows(chosen[group][1], album):
            lines.append(f"{name}\t{roles_text(roles)}")
    lines.append("")
    lines.append(f"#sources\t{sources_line(chosen)}")
    if links:
        lines.append("")
        lines.append("#links")
        for name, roles, rows in links:
            lines.append(f"P\t{name}\t{roles}")
            lines += rows
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the run
def main(argv=None):
    conf = ab.settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    drive = (conf.get("ipod drive") or "G:").rstrip("\\/")
    ap.add_argument("music_root", nargs="?", default=conf.get("music folder", "").rstrip("\\/") or f"{drive}\\Music",
                    help="the iPod's music folder (default: from the settings file)")
    ap.add_argument("--ipod", help="the iPod's own folder (default: the folder holding the music folder)")
    ap.add_argument("--only", action="append", default=[],
                    help='just this artist, or "Artist - Album" (can be given more than once)')
    ap.add_argument("--discogs-token", default=conf.get("discogs token"),
                    help="Discogs personal token, only needed if a saved release has expired")
    ap.add_argument("--compare", action="store_true",
                    help="list the groups whose source changes under the weighted rule, and write nothing")
    args = ap.parse_args(argv)

    music = Path(args.music_root)
    ipod = Path(args.ipod) if args.ipod else music.resolve().parent
    if not ab.ipod_page_on(ipod, "credits"):
        print("The Credits page is switched off on the iPod, so no credits are fetched.")
        return 0
    lib_all = ids.library()
    lib = lib_all.get("albums") or {}
    if not lib:
        print("Run ids.py first: it reads your albums and identifies them.")
        return 1
    records = load_records(lib)
    keys = sorted(records)
    print(f"{len(keys)} albums identified.")

    token = args.discogs_token
    mb = ids.Site(1.1)
    dc = ids.Site(1.1, {"Authorization": f"Discogs token={token}"}) if token else None

    # -- the releases ids.py saved (fetched again only if they've expired)
    mbrel, dcrel = {}, {}
    for n, k in enumerate(keys, 1):
        r = records[k]
        if (r.get("mb") or {}).get("id"):
            mbrel[k] = fetch(mb, "mbrel", r["mb"]["id"], f"{ids.MB}release/{r['mb']['id']}",
                             {"inc": ids.LOOKUP_INC, "fmt": "json"})
        if (r.get("discogs") or {}).get("id"):
            dcrel[k] = fetch(dc, "dcrel", r["discogs"]["id"], f"{ids.DISCOGS}releases/{r['discogs']['id']}")
        print(f"\r  releases {n}/{len(keys)}", end="", flush=True)
    print()

    # -- each album's page credits
    chosen, changes = {}, []
    for k in keys:
        sources = [("tags", tag_credits(lib[k]))]
        if mbrel.get(k):
            sources.append(("MusicBrainz", mb_credits(mbrel[k], records[k].get("mb") or {})))
        if dcrel.get(k):
            sources.append(("Discogs", dc_credits(dcrel[k], records[k].get("discogs") or {})))
        chosen[k] = choose(sources, len(lib[k]["tracks"]))
        if args.compare:
            before = choose(sources, len(lib[k]["tracks"]), weighted=False)
            for g in ids.GROUPS:
                if g in before and before[g][0] != chosen[k][g][0]:
                    changes.append((k, g, before[g][0], chosen[k][g][0],
                                    coverage(before[g][1], len(lib[k]["tracks"])),
                                    coverage(chosen[k][g][1], len(lib[k]["tracks"]))))

    if args.compare:
        lines = [f"Groups whose source changes when credits are weighted by how much of the album they cover: "
                 f"{len(changes)}, on {len({c[0] for c in changes})} albums.", ""]
        for k, g, a, b, ca, cb in changes:
            lines.append(f"{k}: {g} {a} -> {b}  (album covered {ca:.1f} -> {cb:.1f})")
        report = HERE / "Credits source changes.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines[:40]))
        print(f"\nAll of them in {report}. Nothing was written to the pages.")
        return 0

    # -- who's who: release artists, library bands' members, and the same
    #    person on both sites (confirmed through MusicBrainz's Discogs links)
    same = Same()
    release_artist_of = defaultdict(set)
    for k in keys:
        for a in (records[k].get("mb") or {}).get("artists") or []:
            if a.get("id") and a["id"] != ids.VARIOUS:
                release_artist_of[("mb", a["id"])].add(k)
        for a in (records[k].get("discogs") or {}).get("artists") or []:
            if a.get("id") and a["id"] not in VARIOUS_DC:
                release_artist_of[("dc", a["id"])].add(k)
    lib_artists = sorted({p[1] for p in release_artist_of if p[0] == "mb"})
    member_of = defaultdict(set)
    for n, a in enumerate(lib_artists, 1):
        data = fetch(mb, "mbart", a, f"{ids.MB}artist/{a}", {"inc": "url-rels+artist-rels", "fmt": "json"})
        for d in discogs_artist_ids(data):
            same.join(("mb", a), d)
        for r in (data or {}).get("relations") or []:
            if r.get("target-type") == "artist" and r.get("type") in MEMBER_TYPES and (r.get("artist") or {}).get("id"):
                member_of[("mb", r["artist"]["id"])].add(("mb", a))
        print(f"\r  library artists {n}/{len(lib_artists)}", end="", flush=True)
    print()

    shown = [(k, c) for k in keys for _, creds in chosen[k].values() for c in creds]
    by_name = defaultdict(set)
    albums_of = defaultdict(set)
    for k, c in shown:
        by_name[fold(c[1])].add(c[0])
        albums_of[c[0]].add(k)
    candidates = {n: ps for n, ps in by_name.items()
                  if any(p[0] == "mb" for p in ps) and any(p[0] == "dc" for p in ps)
                  and len(set().union(*[albums_of[p] for p in ps])) > 1}
    dc_wanted = {p[1] for ps in candidates.values() for p in ps if p[0] == "dc"}
    links_to = confirm_same(mb, dc_wanted, same)
    for ps in candidates.values():
        for d in (p for p in ps if p[0] == "dc"):
            for m in links_to.get(d[1], ()):
                if ("mb", m) in ps:
                    same.join(("mb", m), d)

    # -- where each person appears
    appear = defaultdict(lambda: defaultdict(set))       # root -> album -> {(role, tracks)}
    for k, c in shown:
        appear[same.find(c[0])][k].add((c[3], frozenset(c[5]) if c[5] is not None else None))
    for pid, ks in release_artist_of.items():
        r = same.find(pid)
        if r in appear:
            for k in ks:
                appear[r][k].add(("Album artist", None))
    for person, bands in member_of.items():
        r = same.find(person)
        if r in appear:
            for b in bands:
                for k in release_artist_of.get(b, ()):
                    appear[r][k].add((f"Member of {lib[k]['artist']}", None))

    # -- who is "inside" each album: its artist and the artist's members,
    #    whose own band's other albums aren't listed for them
    insiders = defaultdict(set)
    for pid, ks in release_artist_of.items():
        for k in ks:
            insiders[k].add(same.find(pid))
    for person, bands in member_of.items():
        for b in bands:
            for k in release_artist_of.get(b, ()):
                insiders[k].add(same.find(person))

    # -- write the pages
    out_dir = ipod / "Artwork" / "Credits"
    out_dir.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    only = {ab.norm(o) for o in args.only}
    counts = defaultdict(int)
    for k in keys:
        if only and not ({ab.norm(k), ab.norm(lib[k]["artist"])} & only):
            continue
        if not chosen[k]:
            counts["none"] += 1
            continue
        name = ab.safe_name(k)
        if not name:
            print(f"  {k}: skipped, the name is too long for the iPod to open")
            continue
        this_artist = fold(lib[k]["artist"])
        links, done = [], set()
        for group in ids.GROUPS:
            if group not in chosen[k]:
                continue
            for pid, pname, roles in people_rows(chosen[k][group][1], lib[k]):
                root = same.find(pid)
                if pid[0] == "tag" or root in done:
                    continue
                done.add(root)
                rows = link_rows(root, k, this_artist, appear, lib, insiders)
                if rows:
                    plain = [r for g in roles for r in re.sub(r"\s*\[[^\]]*\]$", "", g).split(", ")]
                    links.append((pname, ", ".join(list(dict.fromkeys(plain))[:3]), rows))
        editions = {"MusicBrainz": ids.mb_edition(mbrel[k]) if mbrel.get(k) else "",
                    "Discogs": ids.discogs_edition(dcrel[k]) if dcrel.get(k) else ""}
        text = page_text(k, lib[k], records[k], chosen[k], links, editions)
        mp = CACHE / f"{name}.json"
        meta = ab.load_json(mp) or {"key": k}
        res = ab.write_if_ours(out_dir / f"{name}.txt", text.encode("utf-8"), meta, "txt_sha1")
        ab.save_json(mp, meta)
        counts[res] += 1
        counts["linked"] += bool(links)
    print(f"Credits written or updated: {counts['written']}, unchanged: {counts['same']}, "
          f"kept as you left them: {counts['kept']}. No credits found: {counts['none']}. "
          f"Pages with Other Appearances: {counts['linked']}.")
    print(f"  {mb.count} MusicBrainz and {dc.count if dc else 0} Discogs requests")
    return 0

def load_records(lib):
    """ids.py's record for each album in the library now, by key."""
    out = {}
    for path in sorted(ids.CACHE.glob("*.json")):
        rec = ab.load_json(path)
        if rec and rec.get("key") in lib:
            out[rec["key"]] = rec
    return out

if __name__ == "__main__":
    sys.exit(main())
