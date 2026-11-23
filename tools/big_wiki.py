#!/usr/bin/env python3
"""A generated wiki of about N pages for timing the page index: the sample
wiki (sample_wiki.py) plus made-up albums, artists and people, and two
Credits-sized test pages on Mingus that link 200 people, one with
labelled links and one with plain [Name] links. Usage:
big_wiki.py <sample Notes dir> <out Notes dir> [pages]"""
import os, random, shutil, sys

SRC, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 10000
random.seed(7)
SYL = "ka lo mi ra te su vo na pe di zo ru ha be ti mo la ne si go".split()


def name(words=2):
    return " ".join("".join(random.choice(SYL) for _ in range(random.randint(2, 3))).capitalize()
                    for _ in range(words))


shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(SRC, OUT)
people, albums, artists = [], [], []
n_alb, n_art = N * 15 // 100, N * 8 // 100
n_people = N - 3 * n_alb - n_art
for _ in range(n_art):
    artists.append(name())
for i in range(n_alb):
    albums.append("%s - %s" % (random.choice(artists), name(random.randint(1, 3))))
seen = set()
while len(people) < n_people:
    p = name()
    if p not in seen:
        seen.add(p)
        people.append(p)
para = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
        "tempor incididunt ut labore et dolore magna aliqua. " * 6).strip()


def w(rel, text):
    with open(os.path.join(OUT, rel), "w", encoding="utf-8") as f:
        f.write(text)


for p in people:
    al = random.choice(albums)
    w("People/%s.md" % p, "<small>*Session player · Somewhere · b. 1950*</small>\n\n%s\n\n"
      "## Worked on\n\n[%s](Albums/%s) *drums*\n" % (para[:400], al.split(" - ", 1)[1], al))
for a in artists:
    w("People/%s.md" % a, "<small>*Rock · Somewhere · 1970–*</small>\n\n%s\n" % para)
for al in albums:
    ar, t = al.split(" - ", 1)
    crew = random.sample(people, 30)
    w("Albums/%s.md" % al, "<small>*[%s](People/%s) · 1977 · Label*</small>\n\n%s\n\n%s\n\n"
      "## Key People\n\n%s\n" % (ar, ar, para, para,
                                   "\n".join("[%s](People/%s) *bass*" % (c, c) for c in crew[:8])))
    w("Albums/%s - Credits.md" % al, "---\nalbum: %s\n---\n## Musicians\n\n%s\n" % (
        al, "\n".join("[%s](People/%s) *guitar*" % (c, c) for c in crew)))
    w("Albums/%s - Other Appearances.md" % al, "---\nalbum: %s\n---\n%s\n" % (
        al, "\n\n".join("**[%s](People/%s)** *bass*\n◉ [%s](Albums/%s) *drums*" % (
            c, c, al.split(" - ", 1)[1], al) for c in crew[:10])))

crew = random.sample(people, 200)
m = "Joni Mitchell - Mingus"
w("Albums/%s - Labelled.md" % m, "---\nalbum: %s\n---\n## Musicians\n\n%s\n" % (
    m, "\n".join("[%s](People/%s) *guitar*" % (c, c) for c in crew)))
w("Albums/%s - Plain.md" % m, "---\nalbum: %s\n---\n## Musicians\n\n%s\n" % (
    m, "\n".join("[%s] *guitar*" % c for c in crew)))
print(sum(len(f) for _, _, f in os.walk(OUT)), "files")
