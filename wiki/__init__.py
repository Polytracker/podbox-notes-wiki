"""The notes wiki: pages for the PodBox Liner Notes and Biographies viewer,
written from what the lookups in liner/ (copied from ipod-liner-notes) find.

  md        the Markdown the viewer reads: escapes, links, file names
  graph     who is credited where, and the same person across sites
  people    key people, who gets a page, and each page's file
  pages     the pages themselves
  lookups   the lookups ipod-liner-notes doesn't do: discographies, key
            people's bios
  write     /Notes on the iPod: the pages, banners and the marker
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINER = ROOT / "liner"
if str(LINER) not in sys.path:
    sys.path.insert(0, str(LINER))

import artist_bios as ab        # noqa: E402

SETTINGS = ROOT / "Notes Wiki settings.txt"
ab.SETTINGS = SETTINGS          # the copied scripts read their defaults from here
