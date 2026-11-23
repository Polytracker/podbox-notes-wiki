#!/usr/bin/env python3
"""A wiki for the PodBox simulator, written by the scraper's own page writer.

From the simulator test disk: the albums and their tags are read from its
Music folder as ids.py reads them, and the bios and album notes are its
/Artwork text (ipod-liner-notes' real scraped words). What the test disk
doesn't have -- releases, credits, key people's bios, discographies -- is
made up here in the shape the lookups save, from the sample wiki's hand
credits. Two credits are invented so people appear on more than one album:
Danny Thompson on Mingus and Nigel Godrich on The Colour of Spring.

Usage: sim_wiki.py <simulator disk> <out dir>
Writes <out dir>/Notes, scraper marker included. Nothing is fetched.
"""
import hashlib, os, re, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"]

import wiki                                    # noqa: E402,F401
from wiki import ab                            # noqa: E402
import ids                                     # noqa: E402

DISK, OUT = Path(sys.argv[1]), Path(sys.argv[2])


def mbid(name):
    return hashlib.md5(name.encode()).hexdigest()[:8] + "-0000-0000-0000-000000000000"


CREDITS = {   # album tag -> [(name, MusicBrainz type, attributes, tracks or None)]
    "Mingus": [("Jaco Pastorius", "instrument", ["bass"], None),
               ("Wayne Shorter", "instrument", ["soprano saxophone"], None),
               ("Herbie Hancock", "instrument", ["electric piano"], None),
               ("Peter Erskine", "instrument", ["drums"], None),
               ("Don Alias", "instrument", ["congas"], None),
               ("Danny Thompson", "instrument", ["double bass"], None),
               ("Joni Mitchell", "producer", [], None),
               ("Henry Lewy", "recording", [], None),
               ("Charles Mingus", "composer", [], None)],
    "Close to the Edge (Deluxe Edition)": [
               ("Jon Anderson", "vocal", ["lead vocals"], None),
               ("Steve Howe", "instrument", ["guitar"], None),
               ("Chris Squire", "instrument", ["bass guitar"], None),
               ("Rick Wakeman", "instrument", ["keyboard"], None),
               ("Bill Bruford", "instrument", ["drums"], None),
               ("Eddy Offord", "producer", [], None),
               ("Eddy Offord", "recording", [], None),
               ("Roger Dean", "design", [], None)],
    "Kid A": [("Thom Yorke", "vocal", ["lead vocals"], None),
              ("Jonny Greenwood", "instrument", ["guitar", "ondes Martenot"], None),
              ("Colin Greenwood", "instrument", ["bass guitar"], None),
              ("Ed O'Brien", "instrument", ["guitar"], None),
              ("Philip Selway", "instrument", ["drums"], None),
              ("Nigel Godrich", "producer", [], None),
              ("Nigel Godrich", "mix", [], None),
              ("Stanley Donwood", "design", [], None)],
    "The Colour of Spring": [
              ("Mark Hollis", "vocal", ["lead vocals"], None),
              ("Lee Harris", "instrument", ["drums"], None),
              ("Paul Webb", "instrument", ["bass guitar"], None),
              ("Tim Friese-Greene", "instrument", ["keyboard"], None),
              ("Steve Winwood", "instrument", ["organ"], None),
              ("Danny Thompson", "instrument", ["double bass"], None),
              ("Tim Friese-Greene", "producer", [], None),
              ("Nigel Godrich", "mix", [], None),
              ("James Marsh", "illustration", [], None)],
}
MEMBERS = {"Yes": ["Jon Anderson", "Chris Squire", "Steve Howe", "Rick Wakeman", "Bill Bruford"],
           "Radiohead": ["Thom Yorke", "Jonny Greenwood", "Colin Greenwood", "Ed O'Brien", "Philip Selway"],
           "Talk Talk": ["Mark Hollis", "Lee Harris", "Paul Webb"]}
STUDIO = {"Radiohead": [("Pablo Honey", 1993), ("The Bends", 1995), ("OK Computer", 1997), ("Kid A", 2000),
                        ("Amnesiac", 2001), ("Hail to the Thief", 2003), ("In Rainbows", 2007),
                        ("The King of Limbs", 2011), ("A Moon Shaped Pool", 2016)],
          "Talk Talk": [("The Party's Over", 1982), ("It's My Life", 1984), ("The Colour of Spring", 1986),
                        ("Spirit of Eden", 1988), ("Laughing Stock", 1991)]}
KEY_BIOS = {
    "Jaco Pastorius": "John Francis Anthony Pastorius III was an American jazz bassist. He was a member of "
                      "Weather Report from 1976 to 1981. He worked with Joni Mitchell on four albums.",
    "Nigel Godrich": "Nigel Godrich is an English record producer and engineer. He is best known for his work "
                     "with Radiohead, with whom he has worked since 1994. He also works with Beck.",
    "Danny Thompson": "Daniel Thompson was an English double bassist. He was a founder of Pentangle. "
                      "He played on records by John Martyn, Nick Drake and Talk Talk.",
}
# The test disk has one track of each album, so each note is for it
TRACK_NOTES = {"Mingus": {0: "A few seconds of Charles Mingus himself, taped by Joni Mitchell, talking about luck."},
               "Kid A": {0: "The few seconds of noise after Motion Picture Soundtrack, left off the track list."},
               "Close to the Edge (Deluxe Edition)": {
                   0: "Chris Squire's bass line runs through the whole song, in 7/4 for most of it."}}

MB_TYPE = {"vocal": "vocal", "instrument": "instrument"}


def main():
    albums = ids.scan(DISK / "Music", quiet=True)
    lib = {}
    base = ab.CACHE.parent
    for d in ("notes", "tracks/albums", "notes wiki/people", "notes wiki/discographies"):
        (base / d).mkdir(parents=True, exist_ok=True)
    ids.CACHE.mkdir(parents=True, exist_ok=True)
    ab.CACHE.mkdir(parents=True, exist_ok=True)
    for a in albums:
        k = a["key"]
        lib[k] = {"artist": a["artist"], "album": a["album"], "folder": a["folder"],
                  "tracks": [[t["disc"], t["num"], t["title"]] for t in a["tracks"]],
                  "tag_credits": a["tag_credits"]}
        n, rid = len(a["tracks"]), mbid("release " + k)
        artist_id = mbid(a["artist"])
        rec = {"key": k, "mb": {"id": rid, "rg": "rg-" + rid, "artists": [{"id": artist_id, "name": a["artist"]}],
                                "tracks": {str(i): {"recording": f"{rid}-{i}"} for i in range(n)}}}
        ab.save_json(ids.CACHE / f"{ab.safe_name(k)}.json", rec)
        whole, per_track = [], {}
        for name, typ, attrs, tracks in CREDITS.get(a["album"], []):
            r = {"target-type": "artist", "type": typ, "attributes": attrs,
                 "artist": {"id": mbid(name), "name": name}, "target-credit": ""}
            if tracks is None:
                whole.append(r)
            else:
                for i in tracks:
                    if i < n:
                        per_track.setdefault(i, []).append(r)
        ids.save_release("mbrel", rid, {
            "id": rid, "title": a["album"], "country": "GB", "media": [{"format": "CD", "tracks": [
                {"recording": {"id": f"{rid}-{i}", "relations": per_track.get(i, [])}} for i in range(n)]}],
            "relations": whole, "release-group": {"id": "rg-" + rid, "primary-type": "Album"}})
        # the album's notes: the test disk's Notes file, as liner_notes.py saved it
        txt = DISK / "Artwork" / "Notes" / f"{ab.safe_name(k)}.txt"
        if txt.exists():
            lines = txt.read_text(encoding="utf-8").split("\n")
            facts = lines[1].split(" · ")
            year = next((p for p in facts if re.fullmatch(r"\d{4}", p)), "")
            minutes = next((p[:-4] for p in facts if p.endswith(" min")), "")
            label = facts[2] if len(facts) > 4 else ""
            ab.save_json(base / "notes" / f"{ab.safe_name(k)}.json", {
                "key": k, "notes": "\n".join(lines[3:]).strip(), "year": year, "label": label,
                "minutes": int(minutes) if minutes.isdigit() else None})
        tn = TRACK_NOTES.get(a["album"])
        if tn:
            ab.save_json(base / "tracks" / "albums" / f"{ab.safe_name(k)}.json", {"tracks": {
                str(i): {"paras": [t, "# Written by hand for the simulator wiki"], "source": "sample"}
                for i, t in tn.items()}})
        if a["artist"] in MEMBERS:
            ids.save_release("mbart", artist_id, {"id": artist_id, "name": a["artist"], "type": "Group",
                "relations": [{"target-type": "artist", "type": "member of band", "direction": "backward",
                               "attributes": [], "artist": {"id": mbid(m), "name": m}}
                              for m in MEMBERS[a["artist"]]]})
        if a["artist"] in STUDIO:
            ab.save_json(base / "notes wiki" / "discographies" / f"{artist_id}.json", {
                "fetched": "2026-11-23", "albums": [
                    {"id": ("rg-" + rid) if t in a["album"] else mbid(t), "title": t, "year": str(y)}
                    for t, y in STUDIO[a["artist"]]]})
    ab.save_json(ids.LIBRARY, {"keys": sorted(lib), "albums": lib})
    # artists' bios and photos, from the test disk's Bios
    for txt in (DISK / "Artwork" / "Bios").glob("*.txt"):
        lines = txt.read_text(encoding="utf-8").split("\n")
        credit = next((l for l in lines if l.startswith("# From")), "")
        title = re.search(r'"([^"]+)"', credit)
        ab.save_json(ab.CACHE / f"{txt.stem}.json", {
            "artist": lines[0], "subtitle": lines[1], "bio_source": "wikipedia", "bio_date": "2026-11-14",
            "bio_title": title.group(1) if title else lines[0], "photo_source": "theaudiodb thumb",
            "bio": "\n".join(l for l in lines[3:] if l.strip() and not l.startswith("# "))})
        jpg = txt.with_suffix(".jpg")
        if jpg.exists():
            (ab.CACHE / f"{txt.stem}.jpg").write_bytes(jpg.read_bytes())
    for name, bio in KEY_BIOS.items():
        ab.save_json(base / "notes wiki" / "people" / f"mb_{mbid(name)}.json", {
            "artist": name, "bio": bio, "bio_source": "lastfm", "subtitle": "", "fetched": "2026-11-23"})
    import notes_wiki
    return notes_wiki.main(["--offline", "--out", str(OUT)])


if __name__ == "__main__":
    sys.exit(main())
