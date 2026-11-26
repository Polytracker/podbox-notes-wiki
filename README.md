# PodBox Notes Wiki

Writes a whole wiki of Markdown pages for the PodBox **Liner Notes and
Biographies** viewer: a page for every artist and album in your library,
its credits, its tracks' notes and the key people who made it, linked to
one another. Without it the viewer shows only the pages you write by hand.

It is a separate project from
[ipod-liner-notes](https://github.com/Polytracker/ipod-liner-notes), which
writes the files for Polytracker's own Liner Notes build. The lookups are
copied from there (`liner/`); that project is never changed by this one.

The viewer side is on the `notes-wiki` branch of
[Polytracker/podbox](https://github.com/Polytracker/podbox/tree/notes-wiki):
the wiki needs that build.

## Running it

On a Windows PC with Python 3.10 or later, the iPod plugged in:

```powershell
pip install requests pillow mutagen numpy opencv-python-headless
python notes_wiki.py
```

The first run looks everything up and takes hours for a large library;
later runs ask only about what's new or due, and cut only the banners whose
pictures changed. Track notes are looked up alongside the rest, their
progress in `Track notes log.txt`. Stop it at any point and run
it again to carry on.

| Option | Does |
| --- | --- |
| `--offline` | Writes the pages from what earlier runs saved, asking nothing online |
| `--dry-run` | Says what it would write, and writes nothing |
| `--out FOLDER` | Writes `Notes` into that folder instead of onto the iPod |
| `--no-banners` | Text only, no pictures |
| `--music FOLDER` | The music folder, if not the one in the settings file |

Settings -- the iPod's drive, the music folder, how often to look again,
how much of each article the album and Bio pages take (`album pages` and
`bio pages`: `basic`, or `full` for the article's Background, Recording,
Composition, artwork, whole reception and Legacy sections; Early life,
Musical style and Legacy for a Bio), and the Last.fm, Discogs
and DeepL keys -- are in `Notes Wiki settings.txt`.
Each key adds a source; without them the program still runs, with
Wikipedia, MusicBrainz and your files' own tags. Put keys in a file of
their own beside it, `Notes Wiki keys.txt`, one a line as in the settings
file (`discogs token = ...`): git never uploads it and an update never
overwrites it.

## What it writes

Everything goes in `/Notes` on the iPod:

| File | Page |
| --- | --- |
| `People/<Artist>.md` and `.jpg` | An artist's Bio: their bio, members, studio albums, other albums you have, albums they're credited on, pages that mention them |
| `People/<Name>.md` and `.jpg` | A key person: a producer, engineer, session player and so on, with the albums of yours they worked on. Their photo comes from their Wikidata picture, else Discogs, always by their own ID, never by name |
| `Albums/<Artist> - <Album>.md` and `.jpg` | The album: its facts with its highest UK and US chart places and certification, a strip of links to its other pages, its notes, critics' scores, key people and tracks with their play counts |
| `Albums/<Artist> - <Album> - Credits.md` | Everyone credited, by group |
| `Albums/<Artist> - <Album> - Other Appearances.md` | The people on it who are on other albums of yours |
| `Albums/<Artist> - <Album> - Tracks.md` | Notes on its tracks, one section each |
| `.notes-wiki` | Tells the player a program wrote the wiki |

An album's pages start with a strip of links in small text, **Bio ·
Album · Tracks · Credits** (only those that exist; the one you're on is
dimmed): below the facts on the album page, at the top of the others.
Credits always go at the foot of a page: the text's source, then the
photo's.

**Track notes** come from each song's Wikipedia article. Where the album's
Wikidata entry doesn't lead to one, the song is looked for by its title and
the album's artist (songs only, never an album of the same name), and its
article must pass the same checks; Last.fm is only asked after that. Every
track found that way, and every Last.fm write-up left with the reason, is
listed in `Tracks by title.txt` after each run.

A key person gets a page when they're key on two or more of your albums,
or when a proper bio is found for them; everyone else stays plain text.
Two people of one name are told apart by a code after the name in the
file, `John Smith (a1b2c3d4).md`, which the player doesn't show.

**Pages you edit are kept.** A page or banner is replaced only while it is
still the one this program last wrote. Nothing is ever deleted: a page for
an album you've since taken off stays until you delete it.

**Pages of your own** go beside the music, not in `/Notes`: with
`.notes-wiki` there, the player finds pages in `/Notes` only by the links
this program writes. See the PodBox notes guide.

## Saved data

The lookups save what they find in `%APPDATA%\RockboxArtistArt`, the same
folder ipod-liner-notes uses, so anything either has already looked up is
not asked for again. This project's own lookups are in its `notes wiki`
folder there.

## Other tools

| File | What it does |
| --- | --- |
| `tools/check_banners.py` | Checks every banner in `G:\Notes` is one the player draws straight from the file (320 x 132, baseline JPEG, the page's exact name). Reads only |
| `tools/why_track.py` | Why tracks' notes came from Last.fm rather than Wikipedia, and what a title search would find. Reads only |
| `tools/why_photo.py` | Why people pages have no photo, by cause, and what each photo source would give. Reads only |
| `tools/wiki_count.py` | Counts how many pages your library would get, from what ipod-liner-notes has saved. Runs from the ipod-liner-notes folder |
| `tools/sim_wiki.py` | A wiki for the PodBox simulator, from its test disk, made by this program's own page writer |
| `tools/sample_wiki.py` | The hand-written sample wiki the viewer was first tested with |
| `tools/big_wiki.py` | About 10,000 generated pages, for timing the viewer |

`DEVELOPING.md` is for changing the program.
