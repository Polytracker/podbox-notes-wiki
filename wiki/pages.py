"""The pages, as claude/notes-wiki-design.md lays them out.

  Albums/<artist> - <album>.md                    Album page (point 3)
  Albums/<artist> - <album> - Credits.md          Credits
  Albums/<artist> - <album> - Other Appearances.md
  Albums/<artist> - <album> - Tracks.md           or Tracks 1 to 3
  People/<name>.md                                Bio (point 5)

Every link names its page's place, and goes only to a page this run
writes. Names of people with pages are linked in running text too, the
first time each appears on a page (`Linker`). Each page records the places
it names in running text, for the Mentioned In lists, which are added last.
"""
import re
from collections import defaultdict

from . import md
from . import ab
from . import graph
from . import show
from . import full
from . import lookups
import credits as cr
import ids
import translate as tr

PAGE_MAX = 30 * 1024        # the viewer reads 32 KB of a page; room for its pieces
TRACK_PARTS = 3             # the viewer looks for "- Tracks", or "- Tracks 1" to "3"
MENTIONS_MAX = 100
ALBUM_MARK = "◉"       # ◉
TRACK_MARK = "♪"       # ♪


class Page:
    def __init__(self, place, kind, subject=None):
        self.place, self.kind, self.subject = place, kind, subject
        self.lines = []
        self.named = set()          # places named in its running text
        self.banner = None          # (bytes, centre) of the picture to cut it from

    def text(self):
        out = "\n".join(self.lines).strip("\n") + "\n"
        out = re.sub(r"\n{3,}", "\n\n", out)
        # a heading sits straight on what follows it, on every page alike (Joe, 26 Nov)
        return re.sub(r"^(## [^\n]*)\n\n(?=[^\n#])", r"\1\n", out, flags=re.M)


# ---------------------------------------------------------------- links in running text
class Linker:
    """Links the names of people with pages where they come up in text.
    Only names of two words or more, matched with their capitals, so a
    band called Yes or Air isn't found in every sentence."""
    def __init__(self, names):
        self.place = {}
        for name, place in names.items():
            if len(name.split()) >= 2 and len(name) <= 80:
                self.place.setdefault(name, place)
        alts = sorted(self.place, key=len, reverse=True)
        self.re = re.compile(r"(?<![\w])(" + "|".join(map(re.escape, alts)) + r")(?![\w])") if alts else None

    def line(self, s, page):
        """One paragraph, escaped, with each name not yet linked on `page` linked."""
        if not self.re:
            return md.text(s)
        out, at = [], 0
        for m in self.re.finditer(s):
            place = self.place[m.group(1)]
            if place in page.named or place == page.place:
                continue
            out.append(md.text(s[at:m.start()]))
            out.append(md.link(m.group(1), place))
            page.named.add(place)
            at = m.end()
        out.append(md.text(s[at:]))
        return "".join(out)


# ---------------------------------------------------------------- what the pages are made from
class Library:
    """Everything the pages are written from: the library, what the lookups
    saved, who is who and who has a page."""
    def __init__(self, lib, records, g, w, notes, tracks, bios, people, discs, folders):
        self.lib, self.records, self.g, self.w = lib, records, g, w
        self.notes = notes          # album key -> liner_notes.py's saved record
        self.tracks = tracks        # album key -> track_notes.py's saved record
        self.bios = bios            # album artist tag -> artist_bios.py's saved record
        self.people = people        # root -> lookups.person()'s record
        self.discs = discs          # album artist tag -> lookups.discographies() list
        self.folders = folders      # folder -> liner_notes.py's saved tags
        self.full_album = self.full_bio = False   # point 12: Basic unless the settings say Full
        names = {}
        for tag, place in w.artist_page.items():
            names[tag] = place
        for root, place in w.root_page.items():
            names.setdefault(g.name.get(root, ""), place)
        self.linker = Linker(names)
        places = defaultdict(set)
        for n, place in names.items():
            places[cr.fold(n)].add(place)
        for r, place in w.root_page.items():
            places[cr.fold(g.name.get(r, ""))].add(place)
        self.by_name = {n: next(iter(ps)) for n, ps in places.items() if len(ps) == 1}
        self.tag_of_root = w.lib_root
        self.canon = getattr(w, "canon", None) or {t: t for t in w.artist_page}
        self.roots_of_tag = defaultdict(set)
        for r, t in w.lib_root.items():
            self.roots_of_tag[self.canon.get(t, t)].add(r)
        self.by_artist = defaultdict(list)
        for k in sorted(lib, key=lambda k: (self.year(k) or "9999", cr.fold(lib[k]["album"]))):
            self.by_artist[self.canon.get(lib[k]["artist"], lib[k]["artist"])].append(k)
        for tag, c in self.canon.items():        # a spelling's bio or list serves them all
            if not self.bios.get(c) and self.bios.get(tag):
                self.bios[c] = self.bios[tag]
            if not self.discs.get(c) and self.discs.get(tag):
                self.discs[c] = self.discs[tag]

    def album_place(self, k):
        return md.album_place(self.lib[k]["artist"], self.lib[k]["album"])

    def person(self, root, name):
        """A person's name, linked when they have a page."""
        place = self.w.root_page.get(root)
        if not place and root[0] == "tag":       # credited by the files' tags: no ID, so by name,
            place = self.by_name.get(cr.fold(name))      # when only one page has it
        return md.link(name, place) if place else md.text(name)

    def year(self, k):
        y = (self.notes.get(k) or {}).get("year")
        if y:
            return str(y)
        rg = ((self.g.mbrel.get(k) or {}).get("release-group") or {})
        return ab.year((rg.get("first-release-date") or "")[:4])

    def title(self, k):
        return self.lib[k]["album"]

    def multi_disc(self, k):
        return len({t[0] for t in self.lib[k]["tracks"]}) > 1

    def track_label(self, k, i):
        return cr.track_label(self.lib[k])(i)


def body(lib, page, text):
    """Saved text from the copied scripts -- paragraphs one a line, "# " lines
    for headings, scores and the source -- as the page's lines. Returns the
    source line."""
    source = ""
    for line in (text or "").split("\n"):
        line = tr.plain(line).strip()
        if not line:
            continue
        if line.startswith("# "):
            t = line[2:]
            if re.search(r"Wikipedia|Last\.fm|Discogs|CC BY", t):
                source = t
            elif " · " in t and re.search(r"\d", t):
                page.lines += [md.note(md.text(t)), ""]
            else:
                page.lines += ["", f"## {md.text(t[:1].upper() + t[1:])}", ""]
            continue
        page.lines += [lib.linker.line(line, page), ""]
    return source


FULL_ROOM = PAGE_MAX - 6 * 1024     # left for the facts, strip, Key People and the track list


def full_body(lib, page, notes, secs, article):
    """Full: the introduction from the saved notes, then the article's chosen
    sections, each under its own heading, the review scores after Critical
    reception. Returns the source line."""
    intro, scores, lead = [], "", True
    for line in (notes or "").split("\n"):
        line = tr.plain(line).strip()
        if line.startswith("# "):
            t = line[2:]
            if " · " in t and re.search(r"\d", t) and not re.search(r"Wikipedia|Last\.fm|CC BY", t):
                scores = t
            lead = False                       # past the introduction: the section replaces the rest
            continue
        if line and lead:
            intro.append(line)
    room = FULL_ROOM - sum(len(x.encode("utf-8")) + 2 for x in intro)
    for x in intro:
        page.lines += [lib.linker.line(x, page), ""]
    for head, paras in full.fit(secs, room):
        page.lines += ["", f"## {md.text(head)}", ""]
        for x in paras:
            page.lines += [lib.linker.line(x, page), ""]
        if head == "Critical reception" and scores:
            page.lines += [md.note(md.text(scores)), ""]
            scores = ""
    if scores:
        page.lines += [md.note(md.text(scores)), ""]
    return full.credit(article)


# ---------------------------------------------------------------- the album's pages
def album_facts(lib, k):
    """artist · year · label · tracks · length, the artist a link (point 3)."""
    a = lib.lib[k]
    meta = lib.notes.get(k) or {}
    seen = (lib.folders.get(a.get("folder")) or {}).get("info") or {}
    n = len(a["tracks"])
    parts = [md.link(a["artist"], lib.w.artist_page.get(a["artist"])),
             md.text(lib.year(k)), md.text(seen.get("label") or meta.get("label") or ""),
             f"{n} track{'s' if n != 1 else ''}",
             f"{meta['minutes']} min" if meta.get("minutes") else "",
             md.text(full.chart_line(full.album_article(meta)))]
    return " · ".join(p for p in parts if p)


def track_notes(lib, k):
    """{track place: paragraphs} for the tracks with a write-up."""
    out = {}
    for i, t in ((lib.tracks.get(k) or {}).get("tracks") or {}).items():
        if t.get("paras") and int(i) < len(lib.lib[k]["tracks"]):
            out[int(i)] = t["paras"]
    return out


def album_page(lib, k):
    p = Page(lib.album_place(k), "album", k)
    p.lines += [md.note(album_facts(lib, k)), ""]
    meta = lib.notes.get(k) or {}
    article = full.album_article(meta) if lib.full_album else ""
    secs = full.album_full(article) if article else []
    if secs:
        source = full_body(lib, p, meta.get("notes"), secs, article)
    else:
        source = body(lib, p, meta.get("notes"))
    key = lib.w.key.get(k) or []
    if key:
        p.lines += ["", "## Key People", ""]
        for root, roles in key:
            name = lib.g.name.get(root, "")
            p.lines.append(" ".join(x for x in (lib.person(root, name), md.dim(md.text(", ".join(roles)))) if x))
        p.lines.append("")
    with_notes = sorted({lib.lib[k]["tracks"][i][1] for i in track_notes(lib, k)})
    opts = ("|group=disc" if lib.multi_disc(k) else "") + \
        ("|notes=" + ",".join(map(str, with_notes)) if with_notes else "") + "|show=plays"
    p.lines += ["", "## Tracks", "{{tracks%s}}" % opts, ""]
    if source:
        p.lines.append(md.note(md.text(source)))
    return p


def other_rows(lib, root, k):
    """credits.link_rows(), kept as data: [(album, track place or None, roles)]."""
    g, this_artist = lib.g, cr.fold(lib.lib[k]["artist"])
    rows = []
    def order(k2):
        a = lib.lib[k2]
        return (cr.fold(a["artist"]) == this_artist, cr.fold(a["artist"]), cr.fold(a["album"]))
    for k2 in sorted(g.appear.get(root, {}), key=order):
        if k2 == k or k2 not in lib.lib:
            continue
        if cr.fold(lib.lib[k2]["artist"]) == this_artist and root in g.insiders.get(k2, ()):
            continue
        how = g.appear[root][k2]
        whole = any(t is None for _, t in how)
        tracks = set().union(*[t or set() for _, t in how])
        roles = list(dict.fromkeys(r for r, _ in how))
        if not whole and 0 < len(tracks) <= 3:
            for i in sorted(tracks):
                rows.append((k2, i, [r for r, t in how if t and i in t][:3]))
        else:
            rows.append((k2, None, roles[:3] + (["…"] if len(roles) > 3 else [])))
    return rows[:cr.LINK_ROWS]


def track_piece(lib, k2, i):
    """{{track}} for track place i of album k2: a link to it, played from its page."""
    a = lib.lib[k2]
    disc, num, title = a["tracks"][i]
    if re.search(r"[|{}]", a["artist"] + a["album"]):
        return md.text(title)
    d = f"|disc={disc}" if lib.multi_disc(k2) else ""
    return "{{track|number=%d%s|album=%s - %s}}" % (num, d, a["artist"], a["album"])


def appearances(lib, k):
    """[(root, name, roles here, rows)] for the people on album k found elsewhere."""
    out, done = [], set()
    for group in ids.GROUPS:
        if group not in lib.g.chosen.get(k, {}):
            continue
        for pid, name, texts in cr.people_rows(lib.g.chosen[k][group][1], lib.lib[k]):
            root = lib.g.same.find(pid)
            if pid[0] == "tag" or root in done:
                continue
            done.add(root)
            rows = other_rows(lib, root, k)
            if rows:
                from .people import plain_roles
                out.append((root, name, plain_roles(texts)[:3], rows))
    return out


def other_appearances_page(lib, k, people):
    p = Page(lib.album_place(k) + " - Other Appearances", "appearances", k)
    p.lines += md.front(f"{lib.lib[k]['artist']} - {lib.lib[k]['album']}")
    for root, name, roles, rows in people:
        start = len(p.lines)
        p.lines.append(" ".join(x for x in (f"**{lib.person(root, name)}**",
                                            md.dim(md.text(", ".join(roles)))) if x))
        for k2, i, how in rows:
            role = md.dim(md.text(", ".join(how)))
            if i is None:
                item = f"{ALBUM_MARK} {md.link(lib.title(k2), lib.album_place(k2))}"
            else:
                item = f"{TRACK_MARK} {track_piece(lib, k2, i)}"
            p.lines.append(" ".join(x for x in (item, role) if x))
        p.lines.append("")
        if len(p.text().encode("utf-8")) > PAGE_MAX:
            del p.lines[start:]
            break
    return p


def status_line(n):
    """The Credits page's line about Other Appearances, short (Joe, 26 Nov)."""
    if n == 0:
        return "No one here appears elsewhere"
    return "1 person appears elsewhere" if n == 1 else f"{n} people appear elsewhere"


def credits_page(lib, k, people):
    rec, a = lib.records.get(k) or {}, lib.lib[k]
    chosen = lib.g.chosen.get(k) or {}
    p = Page(lib.album_place(k) + " - Credits", "credits", k)
    p.lines += md.front(f"{a['artist']} - {a['album']}")
    status = status_line(len(people))
    if people:
        status = md.link(status, lib.album_place(k) + " - Other Appearances")
    p.lines.append(md.small(status if people else md.dim(md.text(status))))
    used = [s for s in ("MusicBrainz", "Discogs") if s in {s for s, _ in chosen.values()}]
    editions = {"MusicBrainz": ids.mb_edition(lib.g.mbrel[k]) if lib.g.mbrel.get(k) else "",
                "Discogs": ids.discogs_edition(lib.g.dcrel[k]) if lib.g.dcrel.get(k) else ""}
    for src in used:
        found = rec.get("mb" if src == "MusicBrainz" else "discogs") or {}
        edition = cr.plain_edition(editions.get(src) or found.get("edition") or found.get("title") or "",
                                   a["album"])
        if edition:
            lead = "Edition:" if len(used) == 1 else f"{src} edition:"
            extra = ids.tracks_note({"tracks": a["tracks"]}, found)
            p.lines.append(md.note(md.text(" · ".join(x for x in (f"{lead} {edition}", extra) if x))))
    for group in ids.GROUPS:
        if group not in chosen:
            continue
        p.lines += ["", f"## {group}", ""]
        for pid, name, texts in cr.people_rows(chosen[group][1], a):
            root = lib.g.same.find(pid)
            if root in lib.g.insiders.get(k, ()):
                texts = whole_album(texts)
            p.lines.append(" ".join(x for x in (lib.person(root, name), md.dim(md.text(cr.roles_text(texts)))) if x))
    p.lines += ["", md.note(md.text(cr.sources_line(chosen)))]
    return p


def tracks_pages(lib, k):
    """The Tracks page, or Tracks 1 to 3 when it would pass the read limit."""
    a, notes = lib.lib[k], track_notes(lib, k)
    if not notes:
        return []
    sections = []
    for i in sorted(notes):
        disc, num, title = a["tracks"][i]
        lines = [f"## {num}. {md.text(title)}"]
        source = ""
        for para in notes[i]:
            if para.startswith("# "):
                source = para[2:]
            elif para.strip():
                lines.append(para)
                lines.append("")
        if source:
            lines.append(md.note(md.text(source)))
        sections.append((disc, "\n".join(lines).rstrip("\n") + "\n"))
    head = "\n".join(md.front(f"{a['artist']} - {a['album']}") + [""])
    parts, cur, size = [], [], len(head)
    for disc, s in sections:
        n = len(s.encode("utf-8")) + 16
        if cur and size + n > PAGE_MAX:
            parts.append(cur)
            cur, size = [], len(head)
        cur.append((disc, s))
        size += n
    if cur:
        parts.append(cur)
    multi = lib.multi_disc(k)
    pages = []
    for n, part in enumerate(parts[:TRACK_PARTS], 1):
        name = " - Tracks" if len(parts) == 1 else f" - Tracks {n}"
        p = Page(lib.album_place(k) + name, "tracks", k)
        p.lines += head.split("\n")
        disc_now = None
        for disc, s in part:
            if multi and disc != disc_now:
                p.lines += [f"# Disc {disc}", ""]
                disc_now = disc
            for line in s.split("\n"):
                plain = line and not line.startswith(("## ", "<small>"))
                p.lines.append(lib.linker.line(tr.plain(line), p) if plain else line)
        pages.append(p)
    if len(parts) > TRACK_PARTS:
        show.warn(f"{k}: the track notes fill more than {TRACK_PARTS} pages; the rest are left out")
    return pages


# ---------------------------------------------------------------- people
TRACKS = re.compile(r"\s*\[[^\]]*\]$")


def whole_album(texts):
    """people_rows()'s role texts without their track numbers, each role once.
    For the album's own artist and band members: sites often credit their
    playing on a few tracks only, which reads as if they sat the rest out."""
    out = []
    for t in texts:
        for r in TRACKS.sub("", t).split(", "):
            if r and r not in out:
                out.append(r)
    return [", ".join(out)] if out else []


def roles_on(lib, root, k):
    """A person's roles on an album, with tracks when it isn't the whole album,
    and never for the album's own artist and band."""
    how = lib.g.appear.get(root, {}).get(k) or set()
    if root in lib.g.insiders.get(k, ()):
        how = {(r, None) for r, _ in how}
    every = set(range(len(lib.lib[k]["tracks"])))
    on = {}
    for role, tracks in how:
        have = on.get(role, set())
        on[role] = None if tracks is None or have is None else have | set(tracks)
    spans = defaultdict(list)
    for role, tracks in on.items():
        span = "" if tracks is None or tracks >= every else \
            cr.track_ranges(tracks, cr.track_label(lib.lib[k]))
        spans[span].append(role)
    return ", ".join(", ".join(rs) + (f" [{s}]" if s else "") for s, rs in spans.items())


def album_line(lib, k, extra=""):
    return " ".join(x for x in (md.link(lib.title(k), lib.album_place(k)),
                                md.dim(md.text(" · ".join(x for x in (lib.year(k), extra) if x)))) if x)


def member_lines(lib, tag):
    """A band's members from MusicBrainz, with instrument and years, one a line."""
    out = []
    for root in lib.roots_of_tag.get(tag, ()):
        mbs = [root[1]] if root[0] == "mb" else (graph.ids_of(lib.g).get(root) or {}).get("mb", [])
        for mb in mbs:
            seen = {}
            for r in lib.g.member_rels.get(mb, []):
                who = r["artist"]
                sub = seen.setdefault(who["id"], {"name": r.get("target-credit") or who.get("name") or "",
                                                  "attrs": [], "spans": []})
                sub["attrs"] += [x for x in r.get("attributes") or [] if x not in sub["attrs"]
                                 and x not in ("original", "founder")]
                b, e = ab.year(r.get("begin")), ab.year(r.get("end"))
                if b or e:
                    sub["spans"].append(f"{b}–{e}" if b != e else b)
            for mid, s in seen.items():
                root2 = lib.g.same.find(("mb", mid))
                about = ", ".join(x for x in (", ".join(s["attrs"]), ", ".join(sorted(set(s["spans"])))) if x)
                out.append(" ".join(x for x in (lib.person(root2, s["name"]), md.dim(md.text(about))) if x))
    return out


def artist_page(lib, tag):
    p = Page(lib.w.artist_page[tag], "artist", tag)
    meta = lib.bios.get(tag) or {}
    if meta.get("subtitle"):
        p.lines += [md.note(md.text(meta["subtitle"])), ""]
    if meta.get("bio") and meta.get("bio_source") != "facts":
        for para in tr.plain(meta["bio"]).split("\n"):
            if para.strip():
                p.lines += [lib.linker.line(para.strip(), p), ""]
    article = full.bio_article(meta) if lib.full_bio else ""
    secs = full.fit(full.bio_full(article), FULL_ROOM - 4 * 1024) if article else []
    for head, paras in secs:
        p.lines += ["", f"## {md.text(head)}", ""]
        for x in paras:
            p.lines += [lib.linker.line(x, p), ""]
    members = member_lines(lib, tag)
    if members:
        p.lines += ["## Members", ""] + members + [""]
        for line in members:
            for m in re.finditer(r"\(<([^>]+)>\)", line):
                p.named.add(m.group(1))
    owned = lib.by_artist.get(tag, [])
    rg_of = {((lib.records.get(k) or {}).get("mb") or {}).get("rg"): k for k in owned}
    rg_of.pop(None, None)
    by_title = {cr.fold(lib.title(k)): k for k in owned}
    studio = lib.discs.get(tag)
    listed = set()
    if studio:
        p.lines += ["## Studio Albums", ""]
        for rg in studio:
            k = rg_of.get(rg["id"]) or by_title.get(cr.fold(rg["title"]))
            if k:
                listed.add(k)
                p.lines.append(album_line(lib, k))
            else:
                p.lines.append(" ".join(x for x in (md.text(rg["title"]), md.dim(rg.get("year", ""))) if x))
        p.lines.append("")
    rest = [k for k in owned if k not in listed]
    if rest:
        p.lines += ["## Also in Your Library" if studio else "## Albums", ""]
        p.lines += [album_line(lib, k) for k in rest] + [""]
    roots = lib.roots_of_tag.get(tag, set())
    guest = sorted({k for r in roots for k in lib.g.appear.get(r, {})
                    if k in lib.lib and lib.canon.get(lib.lib[k]["artist"]) != tag},
                   key=lambda k: (lib.year(k) or "9999", cr.fold(lib.title(k))))
    if guest:
        p.lines += ["## Also Appears On", ""]
        for k in guest:
            role = "; ".join(roles_on(lib, r, k) for r in roots if k in lib.g.appear.get(r, {}))
            p.lines.append(album_line(lib, k, role))
        p.lines.append("")
    p.photo_credit = lookups.photo_credit(meta)
    if secs:
        p.source = full.credit(article)
    elif meta.get("bio") and meta.get("bio_source") != "facts":
        p.source = tr.credit(meta.get("bio_source") or "", meta.get("bio_lang"), meta.get("bio_title"),
                             date=meta.get("bio_date") or meta.get("fetched"))[2:]
    return p


def person_page(lib, root):
    place = lib.w.root_page[root]
    p = Page(place, "person", root)
    meta = lib.people.get(root) or {}
    worked = sorted((k for k in lib.g.appear.get(root, {}) if k in lib.lib),
                    key=lambda k: (lib.year(k) or "9999", cr.fold(lib.title(k))))
    role = ""
    counts = defaultdict(int)
    for k in worked:
        for r, _ in lib.g.appear[root][k]:
            counts[r] += 1
    if counts:
        role = max(counts, key=lambda r: (counts[r], -len(r)))
        role = role[:1].upper() + role[1:]
    facts = " · ".join(x for x in (role, meta.get("subtitle") or "") if x)
    if facts:
        p.lines += [md.note(md.text(facts)), ""]
    if meta.get("bio") and meta.get("bio_source") != "facts":
        for para in tr.plain(meta["bio"]).split("\n"):
            if para.strip():
                p.lines += [lib.linker.line(para.strip(), p), ""]
        p.source = tr.credit(meta.get("bio_source") or "", meta.get("bio_lang"), meta.get("bio_title"),
                             date=meta.get("bio_date") or meta.get("fetched"))[2:]
    p.photo_credit = lookups.photo_credit(meta)
    if worked:
        p.lines += ["## Worked On", ""]
        p.lines += [album_line(lib, k, roles_on(lib, root, k)) for k in worked] + [""]
    return p


def mentioned_in(pages):
    """Adds Mentioned In to each person's page: the pages whose text names them."""
    by_place = {p.place: p for p in pages}
    named_by = defaultdict(set)
    for p in pages:
        for place in p.named:
            if place in by_place and place != p.place:
                named_by[place].add(p.place)
    for p in pages:
        if p.kind in ("artist", "person"):
            listed = set(re.findall(r"\]\(<([^>]+)>\)", "\n".join(p.lines)))
            names = sorted((n for n in named_by.get(p.place, ()) if n not in listed),
                           key=lambda n: (by_place[n].kind != "artist", by_place[n].kind != "person",
                                          by_place[n].title.casefold()))[:MENTIONS_MAX]
            if names:
                p.lines += ["## Mentioned In", ""]
                for place in names:
                    other = by_place[place]
                    p.lines.append(md.link(other.title, place))
                p.lines.append("")
        source = getattr(p, "source", "")
        if source:
            p.lines.append(md.note(md.text(source)))
        photo = getattr(p, "photo_credit", "")
        if photo:                                   # credits always at the foot (Joe, 26 Nov)
            p.lines.append(md.note(md.text(photo)))


STRIP_DOT = " *·* "


def strip(lib, k, here, tracks, credits):
    """The album's pages as links in small capitals, under each page's title,
    in iPod Liner Notes' order: BIO · ALBUM · TRACKS · CREDITS (TRACKS 1,
    2… when split), only those that exist, the page it's on in plain white
    and not a link (Joe, 26 Nov). Other Appearances isn't in it: it follows
    on from Credits."""
    bio = lib.w.artist_page.get(lib.lib[k]["artist"])
    parts = []
    if bio and md.place_ok(bio):
        parts.append(("BIO", bio))
    parts.append(("ALBUM", lib.album_place(k)))
    for t in tracks:
        parts.append((t.place.rsplit(" - ", 1)[-1].upper(), t.place))
    if credits:
        parts.append(("CREDITS", credits.place))
    if len(parts) < 2:
        return ""
    return md.small(STRIP_DOT.join(name if place == here else md.link(name, place) for name, place in parts))


def add_strip(page, line):
    """The strip as the page's first line, right under its title. On an
    album page the facts line follows with no gap; on the others, after
    their front matter, a blank line."""
    if not line:
        return
    if page.lines[:1] == ["---"]:
        page.lines[3:3] = [line, ""]
    else:
        page.lines[0:0] = [line]


def all_pages(lib):
    """Every page, Mentioned In filled in."""
    pages = []
    for k in sorted(lib.lib):
        a = album_page(lib, k)
        a.title = lib.title(k)
        pages.append(a)
        people = appearances(lib, k)
        c = o = None
        if lib.g.chosen.get(k):
            c = credits_page(lib, k, people)
            c.title = f"{lib.title(k)} - Credits"
            pages.append(c)
            if people:
                o = other_appearances_page(lib, k, people)
                o.title = f"{lib.title(k)} - Other Appearances"
                pages.append(o)
        ts = tracks_pages(lib, k)
        for t in ts:
            t.title = f"{lib.title(k)} - {t.place.rsplit(' - ', 1)[-1]}"
            pages.append(t)
        add_strip(a, strip(lib, k, a.place, ts, c))
        for other in [c, o] + ts:
            if other is not None:
                add_strip(other, strip(lib, k, other.place, ts, c))
    for tag in sorted(set(lib.canon.values())):
        a = artist_page(lib, tag)
        a.title = tag
        pages.append(a)
    for root in sorted(lib.w.root_page, key=str):
        if root in lib.w.lib_root:
            continue
        pp = person_page(lib, root)
        pp.title = lib.g.name.get(root, "")
        pages.append(pp)
    mentioned_in(pages)
    return [p for p in pages if md.path_ok(p.place)]
