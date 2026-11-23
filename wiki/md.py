"""The Markdown the viewer reads, and the names of its files.

The rules here are the viewer's (Polytracker/podbox `notes-wiki`,
`docs/podbox/notes-guide.md`, `notes_files.c` and `ts_text.c`):

- A page's file is named by scraper mode's rule: each of \\ / : * ? " < > |
  becomes _, and dots and spaces at the end go. An album's is
  "<album artist> - <album>", each name by the rule on its own, as the
  viewer builds it from the library.
- A link is [label](<place>), the place under /Notes without ".md". The
  viewer reads at most 128 bytes of a place, <> included, and a place
  ends at its first unmatched ")": a place that breaks either is written
  as plain text instead.
- A link's label loses * _ and `; square brackets in it would end it.
"""
import re

BAD = '\\/:*?"<>|'
ADDR_MAX = 128          # MD_ADDR_MAX in ts_text.c
PATH_MAX = 259          # MAX_PATH less its NUL: "/Notes/" + place + ".md"


def file_name(name):
    """A name as the viewer turns it into a file's name."""
    out = "".join("_" if c in BAD else c for c in name or "")
    return out.rstrip(". ")


def album_place(artist, album):
    return f"Albums/{file_name(artist)} - {file_name(album)}"


def person_place(name):
    return f"People/{file_name(name)}"


def place_ok(place):
    """Whether the viewer can open a link to this place."""
    depth = 0
    for c in place:
        depth += c == "("
        depth -= c == ")"
        if depth < 0:
            return False
    return (depth == 0 and len(f"<{place}>".encode("utf-8")) <= ADDR_MAX
            and len(f"/Notes/{place}.md".encode("utf-8")) <= PATH_MAX)


def path_ok(place):
    """Whether the player can open the file at all."""
    return len(f"/Notes/{place}.md".encode("utf-8")) <= PATH_MAX


ESCAPE = re.compile(r"([\\*_\[\]`])")
LINE_START = re.compile(r"^(\s*)(#|>|-|\+|\d+[.)](?=\s|$))")


def text(s):
    """Plain words, so nothing in them is read as a mark."""
    s = ESCAPE.sub(r"\\\1", s or "").replace("{{", "{\\{")
    return LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), s)


def label(s):
    return (s or "").replace("[", "(").replace("]", ")").replace("*", "") \
        .replace("_", " ").replace("`", "'").strip()


def link(words, place):
    """A link showing `words`, to the page at `place`; plain words when the
    viewer couldn't follow it."""
    if not place or not place_ok(place):
        return text(words)
    return f"[{label(words)}](<{place}>)"


def dim(s):
    return f"*{s}*" if s else ""


def small(s):
    return f"<small>{s}</small>" if s else ""


def note(s):
    """A small, dimmed line: sources, dates, editions."""
    return small(dim(s)) if s else ""


def front(album):
    """The front matter that makes a page one of an album's pages."""
    return ["---", f"album: {album}", "---"]
