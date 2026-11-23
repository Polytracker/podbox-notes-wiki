# Where these files come from

Copied unchanged from
[Polytracker/ipod-liner-notes](https://github.com/Polytracker/ipod-liner-notes)
at commit `71910b8` (23 Nov 2026): `ids.py`, `artist_bios.py`, `art_fetch.py`,
`liner_notes.py`, `track_notes.py`, `credits.py`, `translate.py` and
`tests/`. They do the lookups: which release each album is, the bios,
album notes, track notes, credits and photos. `wiki/` turns what they find
into the wiki's pages.

Keep them as they are, so a fix in ipod-liner-notes can be copied across
by copying the file again. A change this project needs goes in `wiki/`; a
change that can only be made here is listed below, with its reason.

`python -m pytest -q liner/tests` runs their own tests.

## Changes made here

None.
