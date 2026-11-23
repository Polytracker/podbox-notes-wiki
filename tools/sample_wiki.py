#!/usr/bin/env python3
"""A sample /Notes wiki laid out as the notes-wiki scraper will write it
(claude/notes-wiki-design.md), for testing the viewer in the simulator.

The words come from the test disk's /Artwork (ipod-liner-notes' real
scraped text); the credits and the key people's short bios are written by
hand for the sample. Banners are cut at 320x132 from the test disk's own
pictures. Usage: sample_wiki.py <unzipped test disk> <out dir>
"""
import os, sys
from PIL import Image

TD, OUT = sys.argv[1], sys.argv[2]
NOTES = os.path.join(OUT, "Notes")
SMALL = bool(int(os.environ.get("SMALL", "1")))   # <small> marks


def small(s):
    return "<small>%s</small>" % s if SMALL else s


def P(name, label=None):
    return "[%s](People/%s)" % (label or name, name)


def A(page, label):
    return "[%s](Albums/%s)" % (label, page)


def write(rel, text):
    path = os.path.join(NOTES, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip("\n") + "\n")


def artwork(rel):
    """The text of an /Artwork file: (title, facts, paragraphs, review lines,
    sources line)"""
    lines = open(os.path.join(TD, "Artwork", rel), encoding="utf-8").read().split("\n")
    body, review, sources, heading = [], [], "", None
    sections = {}
    for ln in lines[3:]:
        if not ln.strip():
            continue
        if ln.startswith("# "):
            t = ln[2:]
            if "Wikipedia" in t or "CC BY" in t:
                sources = t
            elif "/" in t and "·" in t:
                review.append(t)
            else:
                heading = t
                sections[heading] = []
            continue
        (sections[heading] if heading else body).append(ln)
    return lines[0], lines[1], body, sections, review, sources


def banner(src, dst, face_top=False):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    # fill 320x132: scale to width 320 (cover) or cut a band
    scale = 320 / w
    im = im.resize((320, max(132, round(h * scale))), Image.LANCZOS)
    top = 0 if face_top else (im.size[1] - 132) // 2
    if face_top:
        top = min(im.size[1] - 132, im.size[1] // 6)
    im = im.crop((0, top, 320, top + 132))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, "JPEG", quality=88, progressive=False, optimize=True)


# ---- albums --------------------------------------------------------------

ALBUMS = [
    dict(artist="Joni Mitchell", album="Mingus", dir="Joni Mitchell/1979 - Mingus",
         art="Notes/Joni Mitchell - Mingus.txt", year=1979, label="Asylum",
         tracks=["Happy Birthday 1975 (rap)", "God Must Be a Boogie Man",
                 "Funeral (rap)", "A Chair in the Sky",
                 "The Wolf That Lives in Lindsey", "I's a Muggin' (rap)",
                 "Sweet Sucker Dance", "Coin in the Pocket (rap)",
                 "The Dry Cleaner from Des Moines", "Lucky (rap)",
                 "Goodbye Pork Pie Hat"], length=37,
         key=[("Charles Mingus", "composer"), ("Jaco Pastorius", "bass"),
              ("Wayne Shorter", "soprano saxophone"),
              ("Herbie Hancock", "electric piano"),
              ("Peter Erskine", "drums"), ("Henry Lewy", "engineer")],
         credits={
             "Musicians": [("Joni Mitchell", "vocals, guitar", None),
                           ("Jaco Pastorius", "bass, horn arrangement", None),
                           ("Wayne Shorter", "soprano saxophone", None),
                           ("Herbie Hancock", "electric piano", None),
                           ("Peter Erskine", "drums", None),
                           ("Don Alias", "congas", None),
                           ("Emil Richards", "percussion", None)],
             "Producers": [("Joni Mitchell", "producer", None)],
             "Engineers": [("Henry Lewy", "engineer", None)],
             "Songwriters": [("Charles Mingus", "music", "2, 4, 7, 9, 11"),
                             ("Joni Mitchell", "lyrics", None)],
             "Credited": [("Joni Mitchell", "cover painting", None)]},
         notes={2: "The first of the six tunes Mingus sent, which he called *Joni I*. Mitchell's words come from his autobiography, *Beneath the Underdog*.",
                4: "Mingus's last composition. Mitchell wrote the words after his death, from his point of view in the hospital.",
                10: "A few seconds of Mingus himself, taped by Mitchell, talking about luck, between the album's songs.",
                11: "Mingus's elegy for Lester Young, from *Mingus Ah Um* (1959), with words Mitchell wrote for this album."}),
    dict(artist="Yes", album="Close to the Edge (Deluxe Edition)",
         dir="Yes/1972 - Close to the Edge",
         art="Notes/Yes - Close to the Edge (Deluxe Edition).txt", year=1972,
         label="Atlantic", length=65,
         tracks=["Close to the Edge", "And You and I", "Siberian Khatru",
                 "America", "Total Mass Retain", "And You and I (alternate version)",
                 "Siberian Khatru (early rough mix)"],
         key=[("Eddy Offord", "producer, engineer"), ("Jon Anderson", "vocals"),
              ("Steve Howe", "guitars"), ("Chris Squire", "bass"),
              ("Rick Wakeman", "keyboards"), ("Bill Bruford", "drums"),
              ("Roger Dean", "cover design")],
         credits={
             "Musicians": [("Jon Anderson", "vocals", None),
                           ("Steve Howe", "guitars, vocals", None),
                           ("Chris Squire", "bass, vocals", None),
                           ("Rick Wakeman", "keyboards", None),
                           ("Bill Bruford", "drums, percussion", None)],
             "Producers": [("Eddy Offord", "producer", None),
                           ("Yes", "producer", None)],
             "Engineers": [("Eddy Offord", "engineer", None)],
             "Credited": [("Roger Dean", "cover design, logo", None)]},
         notes={}),
    dict(artist="Radiohead", album="Kid A", dir="Radiohead/2000 - Kid A",
         art="Notes/Radiohead - Kid A.txt", year=2000, label="Parlophone",
         length=47,
         tracks=["Everything in Its Right Place", "Kid A", "The National Anthem",
                 "How to Disappear Completely", "Treefingers", "Optimistic",
                 "In Limbo", "Idioteque", "Morning Bell",
                 "Motion Picture Soundtrack", "Untitled"],
         key=[("Nigel Godrich", "producer, engineer"), ("Thom Yorke", "vocals"),
              ("Jonny Greenwood", "guitar, ondes Martenot"),
              ("Colin Greenwood", "bass"), ("Ed O'Brien", "guitar"),
              ("Philip Selway", "drums"), ("Stanley Donwood", "artwork")],
         credits={
             "Musicians": [("Thom Yorke", "vocals, guitar, keyboards", None),
                           ("Jonny Greenwood", "guitar, ondes Martenot, keyboards", None),
                           ("Colin Greenwood", "bass, synthesiser", None),
                           ("Ed O'Brien", "guitar, effects", None),
                           ("Philip Selway", "drums, percussion", None)],
             "Producers": [("Nigel Godrich", "producer", None),
                           ("Radiohead", "producer", None)],
             "Engineers": [("Nigel Godrich", "engineer, mixing", None)],
             "Credited": [("Stanley Donwood", "artwork", None)]},
         notes={1: "Opens on a Prophet-5 played by Yorke, his voice cut up and looped by Jonny Greenwood.",
                11: "The few seconds of noise after *Motion Picture Soundtrack*, left off the track list."}),
    dict(artist="Talk Talk", album="The Colour of Spring",
         dir="Talk Talk/1986 - The Colour of Spring",
         art="Notes/Talk Talk - The Colour of Spring.txt", year=1986,
         label="EMI", length=46,
         tracks=["Happiness Is Easy", "I Don't Believe in You",
                 "Life's What You Make It", "April 5th", "Living in Another World",
                 "Give It Up", "Chameleon Day", "Time It's Time"],
         key=[("Tim Friese-Greene", "producer, keyboards"),
              ("Mark Hollis", "vocals"), ("Lee Harris", "drums"),
              ("Paul Webb", "bass"), ("Steve Winwood", "organ"),
              ("James Marsh", "cover painting")],
         credits={
             "Musicians": [("Mark Hollis", "vocals, guitar, piano", None),
                           ("Lee Harris", "drums", None),
                           ("Paul Webb", "bass", None),
                           ("Tim Friese-Greene", "keyboards", None),
                           ("Steve Winwood", "organ", "3, 5"),
                           ("Danny Thompson", "double bass", "4"),
                           ("David Rhodes", "guitar", "1, 6"),
                           ("Morris Pert", "percussion", None)],
             "Producers": [("Tim Friese-Greene", "producer", None)],
             "Songwriters": [("Mark Hollis", "", None),
                             ("Tim Friese-Greene", "", None)],
             "Credited": [("James Marsh", "cover painting", None)]},
         notes={}),
]

# Who has a page (the closed system): library artists, and the key people
# the sample gives a bio
PAGES = {"Joni Mitchell", "Yes", "Radiohead", "Talk Talk", "Jaco Pastorius",
         "Wayne Shorter", "Nigel Godrich", "Eddy Offord", "Tim Friese-Greene",
         "Jon Anderson", "Mark Hollis"}


def link(name):
    return P(name) if name in PAGES else name


def album_page(a):
    title, facts, body, sections, review, sources = artwork(a["art"])
    page = "%s - %s" % (a["artist"], a["album"])
    n = len(a["tracks"])
    sub = "*%s · %d · %s · %d tracks · %d min*" % (
        P(a["artist"]), a["year"], a["label"], n, a["length"])
    out = [small(sub), ""]
    out += body[:1] + [""]
    if len(body) > 1:
        out += ["## Background", ""] + [p + "\n" for p in body[1:]]
    for h, ps in sections.items():
        out += ["## " + h.capitalize(), ""] + [p + "\n" for p in ps]
    if review:
        out += [small("*" + " · ".join(review) + "*"), ""]
    out += ["## Key People", ""]
    out += ["%s *%s*" % (link(nm), role) for nm, role in a["key"]]
    out += [""]
    notes = sorted(a["notes"])
    out += ["## Tracks", "{{tracks%s}}" % ("|notes=" + ",".join(map(str, notes))
                                          if notes else ""), ""]
    out += [small("*" + sources + "*")]
    write("Albums/%s.md" % page, "\n".join(out))

    # Credits
    c = ["---", "album: %s" % page, "---",
         small("*Original release, %s, %d*" % (a["label"], a["year"])), ""]
    for group, rows in a["credits"].items():
        c += ["## " + group, ""]
        for nm, role, tr in rows:
            r = role + (" [%s]" % tr if tr else "")
            c.append("%s *%s*" % (link(nm), r) if r else link(nm))
        c.append("")
    c.append(small("*Credits from MusicBrainz, retrieved 14 Nov 2026*"))
    write("Albums/%s - Credits.md" % page, "\n".join(c))

    # Tracks, when any have a write-up
    if notes:
        t = ["---", "album: %s" % page, "---", "{{contents|style=inline}}", ""]
        for k in notes:
            t += ["## %d. %s" % (k, a["tracks"][k - 1]), a["notes"][k], ""]
        write("Albums/%s - Tracks.md" % page, "\n".join(t))

    # Banner: a band across the middle of the full-size cover
    d = os.path.join(TD, "Music", a["dir"])
    cover = [f for f in os.listdir(d) if f.lower() in ("cover.jpg", "folder.jpg")][0]
    banner(os.path.join(d, cover), os.path.join(NOTES, "Albums", page + ".jpg"))


STUDIO = {
    "Joni Mitchell": [("Song to a Seagull", 1968), ("Clouds", 1969),
                      ("Ladies of the Canyon", 1970), ("Blue", 1971),
                      ("For the Roses", 1972), ("Court and Spark", 1974),
                      ("The Hissing of Summer Lawns", 1975), ("Hejira", 1976),
                      ("Don Juan's Reckless Daughter", 1977), ("Mingus", 1979),
                      ("Wild Things Run Fast", 1982), ("Dog Eat Dog", 1985),
                      ("Chalk Mark in a Rain Storm", 1988),
                      ("Night Ride Home", 1991), ("Turbulent Indigo", 1994),
                      ("Taming the Tiger", 1998), ("Both Sides Now", 2000),
                      ("Travelogue", 2002), ("Shine", 2007)],
    "Radiohead": [("Pablo Honey", 1993), ("The Bends", 1995),
                  ("OK Computer", 1997), ("Kid A", 2000), ("Amnesiac", 2001),
                  ("Hail to the Thief", 2003), ("In Rainbows", 2007),
                  ("The King of Limbs", 2011), ("A Moon Shaped Pool", 2016)],
    "Talk Talk": [("The Party's Over", 1982), ("It's My Life", 1984),
                  ("The Colour of Spring", 1986), ("Spirit of Eden", 1988),
                  ("Laughing Stock", 1991)],
    "Yes": [("Yes", 1969), ("Time and a Word", 1970), ("The Yes Album", 1971),
            ("Fragile", 1971), ("Close to the Edge", 1972),
            ("Tales from Topographic Oceans", 1973), ("Relayer", 1974),
            ("Going for the One", 1977), ("Tormato", 1978), ("Drama", 1980),
            ("90125", 1983), ("Big Generator", 1987), ("Union", 1991),
            ("Talk", 1994), ("Open Your Eyes", 1997), ("The Ladder", 1999),
            ("Magnification", 2001), ("Fly from Here", 2011),
            ("Heaven & Earth", 2014), ("The Quest", 2021),
            ("Mirror to the Sky", 2023), ("Aurora", 2026)],
}
OWNED = {("Joni Mitchell", "Mingus"): "Joni Mitchell - Mingus",
         ("Radiohead", "Kid A"): "Radiohead - Kid A",
         ("Talk Talk", "The Colour of Spring"): "Talk Talk - The Colour of Spring",
         ("Yes", "Close to the Edge"): "Yes - Close to the Edge (Deluxe Edition)"}
MEMBERS = {
    "Yes": [("Jon Anderson", "vocals", "1968–1980, 1983–2004"),
            ("Chris Squire", "bass", "1968–2015"),
            ("Steve Howe", "guitars", "1970–1981, 1990–1992, 1995–"),
            ("Rick Wakeman", "keyboards", "1971–1974, 1976–1980"),
            ("Bill Bruford", "drums", "1968–1972, 1990–1992")],
    "Radiohead": [("Thom Yorke", "vocals, guitar, keyboards", "1985–"),
                  ("Jonny Greenwood", "guitar, keyboards", "1985–"),
                  ("Colin Greenwood", "bass", "1985–"),
                  ("Ed O'Brien", "guitar", "1985–"),
                  ("Philip Selway", "drums", "1985–")],
    "Talk Talk": [("Mark Hollis", "vocals, guitar, piano", "1981–1991"),
                  ("Lee Harris", "drums", "1981–1991"),
                  ("Paul Webb", "bass", "1981–1990")],
}


def bio_page(artist):
    title, facts, body, sections, review, sources = artwork("Bios/%s.txt" % artist)
    out = [small("*" + facts + "*"), ""]
    out += [p + "\n" for p in body[:1]]
    if artist in MEMBERS:
        out += ["## Members", ""]
        out += ["%s *%s, %s*" % (link(nm), r, y) for nm, r, y in MEMBERS[artist]]
        out.append("")
    out += ["## Studio Albums", ""]
    for t, y in STUDIO[artist]:
        own = OWNED.get((artist, t))
        out.append("%s *%d*" % (A(own, t) if own else t, y))
    out += ["", small("*" + sources + "*")]
    write("People/%s.md" % artist, "\n".join(out))
    banner(os.path.join(TD, "Artwork", "Bios", artist + ".jpg"),
           os.path.join(NOTES, "People", artist + ".jpg"), face_top=True)


KEY = {
    "Jaco Pastorius": ("Bass · Norristown · 1951–1987",
                       "John Francis Anthony Pastorius III was an American jazz bassist, known for his work with Weather Report from 1976 to 1981 and for a fretless sound that changed how the electric bass was played.",
                       [("Joni Mitchell - Mingus", "Mingus", "bass, horn arrangement")]),
    "Wayne Shorter": ("Saxophone · Newark · 1933–2023",
                      "Wayne Shorter was an American saxophonist and composer, a member of Art Blakey's Jazz Messengers and Miles Davis's second great quintet, and a founder of Weather Report.",
                      [("Joni Mitchell - Mingus", "Mingus", "soprano saxophone")]),
    "Nigel Godrich": ("Producer · London · b. 1971",
                      "Nigel Godrich is an English record producer and engineer, known for his work with Radiohead since *OK Computer*, and with Beck, Paul McCartney and Roger Waters.",
                      [("Radiohead - Kid A", "Kid A", "producer, engineer, mixing")]),
    "Eddy Offord": ("Producer · London · b. 1947",
                    "Eddy Offord is an English record producer and engineer, best known for producing Yes's albums from *The Yes Album* to *Relayer*, and for work with Emerson, Lake & Palmer.",
                    [("Yes - Close to the Edge (Deluxe Edition)", "Close to the Edge (Deluxe Edition)", "producer, engineer")]),
    "Tim Friese-Greene": ("Producer, keyboards · London · b. 1956",
                          "Tim Friese-Greene is an English producer, songwriter and multi-instrumentalist, who wrote and produced Talk Talk's albums from *It's My Life* to *Laughing Stock* with Mark Hollis.",
                          [("Talk Talk - The Colour of Spring", "The Colour of Spring", "producer, keyboards")]),
    "Jon Anderson": ("Vocals · Accrington · b. 1944",
                     "Jon Anderson is an English singer and songwriter, a founder of Yes and its lead singer through most of its history.",
                     [("Yes - Close to the Edge (Deluxe Edition)", "Close to the Edge (Deluxe Edition)", "vocals")]),
    "Mark Hollis": ("Vocals · London · 1955–2019",
                    "Mark Hollis was an English musician and songwriter, the singer and main songwriter of Talk Talk, whose last albums are counted among the first post-rock records.",
                    [("Talk Talk - The Colour of Spring", "The Colour of Spring", "vocals, guitar, piano")]),
}


def key_page(name):
    facts, intro, worked = KEY[name]
    out = [small("*" + facts + "*"), "", intro, "", "## Worked on", ""]
    out += ["%s *%s*" % (A(p, t), r) for p, t, r in worked]
    out += ["", small("*Written by hand for the sample wiki*")]
    write("People/%s.md" % name, "\n".join(out))


for a in ALBUMS:
    album_page(a)
for ar in STUDIO:
    bio_page(ar)
for k in KEY:
    key_page(k)
print("pages:", sum(len(f) for _, _, f in os.walk(NOTES)))
