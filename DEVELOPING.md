# Developing the notes wiki

For someone changing the program. `README.md` is for someone running it.

## The parts

| Part | What it is |
| --- | --- |
| `notes_wiki.py` | The run: the lookups, then the pages |
| `liner/` | ipod-liner-notes' lookups, copied unchanged (`liner/PROVENANCE.md` says from which commit) |
| `wiki/md.py` | The Markdown the viewer reads, and its file names |
| `wiki/graph.py` | Who is credited where: the middle of `credits.py`'s `main()`, kept as data |
| `wiki/people.py` | Key people, who gets a page, and each page's file |
| `wiki/lookups.py` | Studio albums (Wikidata for everyone in one query, then MusicBrainz, then Discogs), and key people's bios many at a time: Wikidata by MusicBrainz ID (a query for hundreds), Wikipedia's openings 20 at a time, Last.fm and Discogs by ID for the rest, pictures from Wikimedia Commons |
| `wiki/pages.py` | The pages |
| `wiki/write.py` | Banners, and writing `/Notes` |

The copied scripts stay as they are, so a fix made in ipod-liner-notes is
taken by copying the file again. Anything this project needs goes in
`wiki/`. A change that can only be made in `liner/` is listed in
`PROVENANCE.md` with its reason.

## The run

1. The copied scripts, as ipod-liner-notes runs them: `ids.py`,
   `artist_bios.py`, `liner_notes.py`, `track_notes.py`, `credits.py`.
   Their own files go into `%APPDATA%\RockboxArtistArt\notes wiki\liner
   files`, never onto the iPod; what matters is what they save.
2. `graph.build()` reads the saved releases and works out each album's
   credits and who is who.
3. Key people (`people.key_people()`), and `lookups.people()` for them all.
4. `people.assign()`: who has a page, and where.
5. `lookups.discographies()`: studio albums, Wikidata first, then MusicBrainz, then Discogs.
6. `pages.all_pages()`, then `Writer` puts each page and banner; a key person's picture
   (`lookups.photo()`) is fetched only for those who get a page.

`--offline` skips step 1 and every request in steps 2 to 5.

## The contract with the viewer

The pages are the viewer's input, as its guide
(`docs/podbox/notes-guide.md` on the podbox `notes-wiki` branch) describes.
These are the rules a change here can break:

- **File names** follow scraper mode's rule (`md.file_name()`): each of
  `\ / : * ? " < > |` becomes `_`, dots and spaces at the end go. An
  album's page is `<album artist> - <album>`, each part by the rule on its
  own, from the tags exactly, since that is how the viewer finds it.
- **Every link names its page's place** (`md.link()`), as
  `[label](<People/Name>)`, and goes only to a page this run writes. The
  viewer doesn't check a link until it's followed, so a link to a page
  that isn't written leads nowhere. A place over 128 bytes, or with an
  unmatched bracket, is written as plain text.
- **Words from the lookups are escaped** (`md.text()`): `*`, `_`, `[`, `]`,
  backslash, backtick and `{{`, and `#`, `>`, `-`, `+` or `1.` at a line's
  start.
- **A page stays under 30 KB**: the viewer reads 32 KB of one. Tracks
  pages split into `Tracks 1` to `Tracks 3`; Other Appearances stops at
  the last person who fits.
- **Track headings** are `## <number>. <title>`, the title as tagged, or
  the viewer won't land on them. `{{tracks|notes=...}}` gives track
  numbers, the same on every disc.
- **Banners** are 320 x 132 baseline JPEGs, drawn straight from the file.
  The page's name is set over their lower 40 pixels, so faces are kept
  above that.

## Tests

```
python -m pytest -q tests liner/tests
```

`tests/fixture.py` writes a small saved library in a temporary folder;
`tests/test_wiki.py` writes the wiki from it and checks the pages. No
network. Add a test for any change to what's written onto the iPod.

To see the pages on the simulator: `tools/sim_wiki.py <simdisk> <out>`,
then copy `<out>/Notes` onto the simulator's disk.

## Being a good client

The copied scripts' rules hold for the lookups here too: MusicBrainz and
Discogs through `ids.Site` (1.1 s apart, retried when busy), and the
`User-Agent` naming the project.

Commits are authored as `Polytracker <Polytracker@users.noreply.github.com>`.
