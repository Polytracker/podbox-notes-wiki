# PodBox Notes Wiki

Writes a whole wiki of Markdown pages for the PodBox **Liner Notes and
Biographies** viewer: a page for every artist and album in your library,
its credits, its tracks' notes and the key people who made it, linked to
one another. Without it the viewer shows only the pages you write by hand.

It is a separate project from
[ipod-liner-notes](https://github.com/Polytracker/ipod-liner-notes), which
writes the files for Polytracker's own Liner Notes build. What this
project needs from there is copied here; that project is never changed by
this one.

## Status

Under construction. The scraper itself is not written yet. The PodBox
firmware side is on the `notes-wiki` branch of
[Polytracker/podbox](https://github.com/Polytracker/podbox/tree/notes-wiki).

## What is here so far

| File | What it does |
| --- | --- |
| `tools/wiki_count.py` | Counts how many pages your library would get, from what ipod-liner-notes has already saved on this PC. Makes no requests and writes nothing to the iPod. For now it runs from the ipod-liner-notes folder, as it reads that project's modules and saved data; it moves to this project's own copies when the scraper is written |
| `tools/sample_wiki.py` | A small sample wiki for the PodBox simulator, written as the scraper will write pages, from the simulator test disk's albums |
| `tools/big_wiki.py` | A generated wiki of about 10,000 pages, for timing the viewer's page index |
