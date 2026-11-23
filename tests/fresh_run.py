"""A first run on a computer that has never run this or ipod-liner-notes,
with every site out of reach: run as its own process by test_fresh.py, so
the scripts find an empty folder for their saved data when they're imported.

  fresh_run.py <empty folder>
"""
import os, sys, time, wave
from pathlib import Path

ROOT = Path(sys.argv[1])
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(ROOT / "config")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests                                    # noqa: E402


def offline(*a, **k):
    raise requests.ConnectionError("no network in this test")


requests.Session.request = offline
requests.get = requests.post = offline
time.sleep = lambda s: None                         # the scripts wait before retrying

from mutagen.wave import WAVE                       # noqa: E402
from mutagen.id3 import TIT2, TALB, TPE1, TPE2, TRCK   # noqa: E402

for artist, album, titles in (("Steely Dan", "Aja", ["Black Cow", "Aja"]),
                              ("R.E.M.", "Murmur", ["Radio Free Europe"])):
    folder = ROOT / "Music" / artist / album
    folder.mkdir(parents=True)
    for n, t in enumerate(titles, 1):
        p = folder / f"{n:02d} {t}.wav"
        w = wave.open(str(p), "wb")
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
        w.close()
        f = WAVE(p)
        f.add_tags()
        for frame in (TIT2(encoding=3, text=t), TALB(encoding=3, text=album), TPE1(encoding=3, text=artist),
                      TPE2(encoding=3, text=artist), TRCK(encoding=3, text=str(n))):
            f.tags.add(frame)
        f.save()

import notes_wiki                                   # noqa: E402
sys.exit(notes_wiki.main(["--music", str(ROOT / "Music"), "--out", str(ROOT / "out"), "--no-banners"]))
