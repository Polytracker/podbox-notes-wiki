"""Album and Bio pages' Full sections, and the chart line (point 12).

Two switches in the settings file, Basic the default for both:

  album pages = basic     full adds Background, Recording, Composition,
                          Title and artwork, the whole Critical reception, Legacy
  bio pages   = basic     full adds Early life, Musical style, Legacy

The sections are taken from the English Wikipedia article the page's text
already comes from, in the article's order, each whole under its own `##`.
A page that would pass PAGE_MAX has its longest section cut at a paragraph
end first, again and again, so no section disappears. An article with none
of them gives the introduction only, as Basic does.

The chart line is always on: the album's highest UK and US chart places and
its highest certification in either, read from the article's own chart and
certification templates (an album whose places are only in prose gets none).

Articles are saved in notes wiki\\articles, read again after a year.
"""
import re
import time

from . import ab
import liner_notes as ln
import translate as tr

from .lookups import CACHE, _age_days

ARTICLES = CACHE / "articles"
REFRESH_DAYS = 365

# (heading shown, heading words); matched in this order of preference, shown in the article's
ALBUM_FULL = [("Background", r"background|conception|origins?|history"),
              ("Recording", r"recording|production|sessions?"),
              ("Composition", r"composition|music(al)? style|^music$|lyrics|themes?|^style$|songwriting|lyrical"),
              ("Title and artwork", r"artwork|cover|packaging|title"),
              ("Critical reception", r"reception|critical response|reviews?"),
              ("Legacy", r"legacy|influence|retrospective|reappraisal")]
ALBUM_NOT = re.compile(r"release|commercial|sales|chart|certif|reissue|re-release|remaster|tour|aftermath|"
                       r"track ?listing|personnel|credits|accolades|awards|references|notes|footnotes|"
                       r"see also|external|further|bibliography|songs|promotion|singles|controvers", re.I)
BIO_FULL = [("Early life", r"early (life|years)|childhood|^background$|formation|beginnings"),
            ("Musical style", r"musical style|^style|artistry|^sound|influences and style|musicianship"),
            ("Legacy", r"legacy|influence|impact")]
BIO_NOT = re.compile(r"career|history|personal life|members|discography|awards|tours|filmography|"
                     r"references|notes|see also|external|further", re.I)
# Composition's song-by-song parts are left out: only its own text, never its subsections
OWN_TEXT_ONLY = {"Composition"}


def setting(conf, name):
    return "full" if (conf.get(name) or "").strip().lower() == "full" else "basic"


# ---------------------------------------------------------------- articles
def _path(title):
    return ARTICLES / f"{ab.safe_name(title) or 'x'}.json"


def saved(title):
    return ab.load_json(_path(title)) if title else None


def fetch(titles, session, say=lambda s: None):
    """Each article's plain text and source, saved; a year before asking again.
    One request an article (Wikipedia gives whole articles one at a time)."""
    ARTICLES.mkdir(parents=True, exist_ok=True)
    due = [t for t in dict.fromkeys(titles) if t and _age_days(saved(t) or {}) >= REFRESH_DAYS]
    say(f"{len(titles) - len(due)} articles saved, {len(due)} to read")
    for n, t in enumerate(due, 1):
        try:
            text, wt = ln.wiki_article(t, session)
        except ab.NET_ERRORS as e:
            ab.problem(t, e)
            continue
        if text or wt:
            ab.save_json(_path(t), {"title": t, "text": text, "wikitext": wt,
                                    "fetched": time.strftime("%Y-%m-%d")})
    return due


ARTICLE_IN_CREDIT = re.compile(r'Wikipedia article "([^"]+)"')


def album_article(notes):
    """The English article an album's notes came from, from their credit line."""
    if not notes or not (notes.get("source") or "").startswith("wikipedia"):
        return ""
    m = None
    for m in ARTICLE_IN_CREDIT.finditer(notes.get("notes") or ""):
        pass
    return m.group(1) if m else ""


def bio_article(meta):
    if not meta or meta.get("bio_source") != "wikipedia" or (meta.get("bio_lang") or "en") != "en":
        return ""
    return meta.get("bio_title") or ""


# ---------------------------------------------------------------- sections
HEAD = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)


def outline(text):
    """[(level, heading, own text)] of an article's plain text with == headings ==,
    the lead as (1, "", text)."""
    out, at, level, head = [], 0, 1, ""
    for m in HEAD.finditer(text or ""):
        out.append((level, head, text[at:m.start()]))
        level, head, at = len(m.group(1)), m.group(2), m.end()
    out.append((level, head, text[at:]))
    return out


def paras(body):
    return [p.strip() for p in re.split(r"\n+", body or "")
            if len(p.strip()) > 40 and not p.strip().startswith(("Main article", "See also", "Further information"))]


def pick(text, wanted, never):
    """[(shown heading, [paragraphs])] in the article's order: each top-level
    section (with its subsections, unless OWN_TEXT_ONLY) whose heading matches
    one of `wanted` and none of `never`; each wanted heading used once."""
    out, used = [], set()
    secs = outline(text)
    i = 0
    while i < len(secs):
        level, head, body = secs[i]
        if not head:                            # the lead: the page's own introduction
            i += 1
            continue
        j = i + 1
        while j < len(secs) and secs[j][0] > level:
            j += 1                              # its subsections
        if level == 2 and head:
            for shown, words in wanted:
                if shown in used or not re.search(words, head, re.I):
                    continue
                if never.search(head) and not re.search(r"reception|review", head, re.I):
                    continue
                ps = paras(body)
                if shown not in OWN_TEXT_ONLY:
                    for sub in secs[i + 1:j]:
                        if not never.search(sub[1]):
                            ps += paras(sub[2])
                if ps:
                    out.append((shown, ps))
                    used.add(shown)
                break
        i = j
    return out


def fit(sections, room):
    """The sections, the longest cut at a paragraph end until they fit `room` bytes."""
    secs = [(h, list(ps)) for h, ps in sections]
    size = lambda: sum(len(h) + 8 + sum(len(p.encode("utf-8")) + 2 for p in ps) for h, ps in secs)
    while size() > room:
        h, ps = max(secs, key=lambda s: sum(len(p) for p in s[1]))
        if len(ps) <= 1:
            break
        ps.pop()
    while size() > room and secs:
        secs.pop()                           # a page of one huge paragraph each: the last goes
    return secs


def album_full(title):
    a = saved(title)
    return pick(a.get("text"), ALBUM_FULL, ALBUM_NOT) if a else []


def bio_full(title):
    a = saved(title)
    return pick(a.get("text"), BIO_FULL, BIO_NOT) if a else []


def credit(title, part="excerpts"):
    a = saved(title) or {}
    return tr.credit("wikipedia", title=title, part=part, date=a.get("fetched"))[2:]


# ---------------------------------------------------------------- the chart line
UK_CHARTS = {"uk2", "uk", "ukalbums", "official charts", "uk albums"}
US_CHARTS = {"billboard200", "billboard 200", "us", "usbillboard200"}
CERT_RANK = {"silver": 1, "gold": 2, "platinum": 3, "diamond": 4}
REGION = {"united kingdom": "UK", "uk": "UK", "united states": "US", "us": "US", "usa": "US"}


def _params(body):
    """A template's parameters: (positional list, named dict)."""
    pos, named = [], {}
    for part in body.split("|")[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            named[k.strip().lower()] = v.strip()
        else:
            pos.append(part.strip())
    return pos, named


def _templates(wt, name):
    for m in re.finditer(r"\{\{\s*" + name + r"\s*\|([^{}]*(?:\{\{[^{}]*\}\}[^{}]*)*)\}\}", wt or "", re.I):
        yield "x|" + re.sub(r"\{\{[^{}]*\}\}", "", m.group(1))


def peaks(wt):
    """{"UK": n, "US": n}, the highest place found in {{Album chart}} rows."""
    out = {}
    for body in _templates(wt, r"Album ?chart"):
        pos, named = _params(body)
        if len(pos) < 2:
            continue
        chart = pos[0].strip().lower()
        where = "UK" if chart in UK_CHARTS else "US" if chart in US_CHARTS else None
        m = re.match(r"\d+", pos[1])
        if where and m:
            n = int(m.group())
            if n > 0 and (where not in out or n < out[where]):
                out[where] = n
    return out


def best_cert(wt):
    """The highest certification in the UK or US: (times, award, region), or None."""
    best = None
    for body in _templates(wt, r"Certification Table Entry"):
        _, named = _params(body)
        region = REGION.get((named.get("region") or "").strip().lower())
        award = (named.get("award") or "").strip().lower()
        if not region or award not in CERT_RANK:
            continue
        times = named.get("number") or "1"
        times = int(times) if times.isdigit() else 1
        key = (CERT_RANK[award], times)
        if best is None or key > best[0]:
            best = (key, times, award.title(), region)
    return best[1:] if best else None


def chart_line(title):
    """"No. 1 UK · No. 1 US · 14× Platinum US", or the parts found, or ""."""
    a = saved(title)
    if not a:
        return ""
    wt = a.get("wikitext") or ""
    p, c = peaks(wt), best_cert(wt)
    parts = [f"No. {p[w]} {w}" for w in ("UK", "US") if w in p]
    if c:
        times, award, region = c
        parts.append(f"{times}× {award} {region}" if times > 1 else f"{award} {region}")
    return " · ".join(parts)
