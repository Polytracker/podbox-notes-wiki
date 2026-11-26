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
| `wiki/lookups.py` | Studio albums (Wikidata for everyone in one query, then MusicBrainz, then Discogs), and key people's bios many at a time: Wikidata by MusicBrainz ID (a query for hundreds), Wikipedia's openings 20 at a time, Last.fm and Discogs by ID for the rest; key people's photos, by ID, from Wikimedia Commons, then Discogs (`photo()`, its source kept for the credit) |
| `wiki/titles.py` | Track write-ups found by title (and an album's Wikidata item by title) where `track_notes.py`'s album entry missed them; saved apart and merged into the pages, never into the copied scripts' saved data |
| `wiki/full.py` | The articles behind the album and Bio pages, saved whole: the Full sections (`album pages`, `bio pages`), the page trimmed to fit, and the chart line read from `{{Album chart}}` and `{{Certification Table Entry}}` |
| `wiki/pages.py` | The pages, the strip of an album's pages, and the credits at each page's foot |
| `wiki/write.py` | Banners, and writing `/Notes` |
| `wiki/show.py` | How the run looks: the banner, stage headings, progress bars, the spinner and colours (plain lines when the output goes to a file; `NO_COLOR=1` turns colour off) |

The copied scripts stay as they are, so a fix made in ipod-liner-notes is
taken by copying the file again. Anything this project needs goes in
`wiki/`. A change that can only be made in `liner/` is listed in
`PROVENANCE.md` with its reason.

## The run

1. `ids.py`, then the other copied scripts as ipod-liner-notes runs them:
   `artist_bios.py`, `liner_notes.py`, `credits.py` one after another (they
   ask MusicBrainz, one request a second in all), with `track_notes.py`
   alongside as a process of its own (Wikidata, Wikipedia, Last.fm only; its
   output in `Track notes log.txt`). Their own files go into
   `%APPDATA%\RockboxArtistArt\notes wiki\liner files`, never onto the iPod;
   what matters is what they save.
2. In a background thread, Wikidata and Wikipedia only, one request at a time:
   `titles.run()` (track write-ups found by title: all the artists' songs in a
   Wikidata query per 50 artists) and `full.fetch()` (the albums' articles,
   and the artists' when `bio pages = full`).
3. Meanwhile: `graph.build()` reads the saved releases and works out each
   album's credits and who is who; key people (`people.key_people()`) and
   `lookups.people()` for them all; `people.assign()`, who has a page and where;
   `lookups.discographies()`, studio albums; and `lookups.photo()` for each key
   person who gets a page (Wikimedia Commons, then Discogs), before the pages,
   so a page can credit its photo.
4. The background thread is waited for, then `pages.all_pages()`, and `Writer`
   puts each page and banner. A banner is cut again only when the picture it
   comes from changed (judged by its files' names, sizes and dates, kept in
   `written.json`) or the banner is gone; raise `BANNER_VERSION` when
   `write.banner()` changes. `titles.report()` writes `Tracks by title.txt`.

`--offline` skips steps 1 and 2 and every request in step 3.

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
`tests/test_wiki.py` writes the wiki from it and checks the pages;
`tests/test_titles.py` and `tests/test_photos.py` stand in for Wikidata,
Wikipedia and the photo sites. No network. Add a test for any change to
what's written onto the iPod.

Run the tests in a copy of the repository without `Notes Wiki keys.txt`:
nothing in them should touch it, and on 26 Nov one did (now fixed).

To see the pages on the simulator: `tools/sim_wiki.py <simdisk> <out>`,
then copy `<out>/Notes` onto the simulator's disk.

## Being a good client

The copied scripts' rules hold for the lookups here too: MusicBrainz and
Discogs through `ids.Site` (1.1 s apart, retried when busy), and the
`User-Agent` naming the project.

Commits are authored as `Polytracker <Polytracker@users.noreply.github.com>`.
