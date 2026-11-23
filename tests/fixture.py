"""A small saved library for the tests, as the copied scripts would have left
it: three albums, their releases, bios, notes, track notes, credits, and
the wiki's own lookups. Nothing here touches the network.

Call make() before importing wiki: the scripts work out where their saved
data lives when they're imported.
"""
import io, json, os, tempfile
from pathlib import Path


def make():
    root = Path(tempfile.mkdtemp())
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    os.environ["APPDATA"] = str(root / "config")
    return root


def jpg(w, h, colour=(120, 60, 30)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, "JPEG")
    return out.getvalue()


SD, JM = "sd-0001", "jm-0001"
GADD, KATZ, NICHOLS, BECKER, FAGEN = "gadd-0001", "katz-0001", "nich-0001", "beck-0001", "fage-0001"
JACO, SMITH_A, SMITH_B = "jaco-0001", "aaaa1111-smith", "bbbb2222-smith"


def rel(artist, name, typ, attrs=(), target=None):
    return {"target-type": "artist", "type": typ, "attributes": list(attrs),
            "artist": {"id": artist, "name": name}, "target-credit": target or ""}


def release(rid, title, artist, n, relations, track_rels):
    media = [{"format": "CD", "tracks": [
        {"recording": {"id": f"{rid}-r{i}", "relations": track_rels.get(i, [])}} for i in range(n)]}]
    return {"id": rid, "title": title, "date": "1977", "country": "US", "media": media,
            "relations": relations, "artist-credit": [{"artist": {"id": artist}}],
            "release-group": {"id": f"rg-{rid}", "first-release-date": "1977-09-23",
                              "primary-type": "Album", "secondary-types": []}}


ALBUMS = {
    "Steely Dan - Aja": dict(artist="Steely Dan", album="Aja", mbid=SD, rid="rel-aja", year="1977",
                             titles=["Black Cow", "Aja", "Deacon Blues", "Peg", "Home at Last",
                                     "I Got the News", "Josie"],
                             rels=[rel(KATZ, "Gary Katz", "producer"),
                                   rel(NICHOLS, "Roger Nichols", "recording"),
                                   rel(SMITH_A, "John Smith", "mix")],
                             track_rels={1: [rel(GADD, "Steve Gadd", "instrument", ["drums"])],
                                         4: [rel(GADD, "Steve Gadd", "instrument", ["drums"])],
                                         0: [rel(BECKER, "Walter Becker", "instrument", ["bass"])]}),
    "Steely Dan - Gaucho": dict(artist="Steely Dan", album="Gaucho", mbid=SD, rid="rel-gau", year="1980",
                                titles=["Babylon Sisters", "Hey Nineteen", "Glamour Profession", "Gaucho",
                                        "Time Out of Mind", "My Rival", "Third World Man"],
                                rels=[rel(KATZ, "Gary Katz", "producer"),
                                      rel(NICHOLS, "Roger Nichols", "recording")],
                                track_rels={2: [rel(GADD, "Steve Gadd", "instrument", ["drums"])]}),
    "Joni Mitchell - Mingus": dict(artist="Joni Mitchell", album="Mingus", mbid=JM, rid="rel-min", year="1979",
                                   titles=["Happy Birthday 1975 (rap)", "God Must Be a Boogie Man",
                                           "Funeral (rap)", "A Chair in the Sky"],
                                   rels=[rel(JACO, "Jaco Pastorius", "instrument", ["bass"]),
                                         rel(SMITH_B, "John Smith", "photography"),
                                         rel(GADD, "Steve Gadd", "instrument", ["drums"])],
                                   track_rels={}),
}


def write(root):
    """The saved data, under root/config/rockbox-artist-art."""
    import artist_bios as ab
    import ids
    base = ab.CACHE.parent
    lib = {}
    for k, a in ALBUMS.items():
        folder = root / "Music" / a["artist"] / a["album"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cover.jpg").write_bytes(jpg(600, 600))
        lib[k] = {"artist": a["artist"], "album": a["album"], "folder": str(folder),
                  "tracks": [[1, i + 1, t] for i, t in enumerate(a["titles"])], "tag_credits": []}
        n = len(a["titles"])
        rec = {"key": k, "mb": {"id": a["rid"], "rg": f"rg-{a['rid']}",
                                "artists": [{"id": a["mbid"], "name": a["artist"]}],
                                "tracks": {str(i): {"recording": f"{a['rid']}-r{i}"} for i in range(n)}}}
        ids.CACHE.mkdir(parents=True, exist_ok=True)
        ab.save_json(ids.CACHE / f"{ab.safe_name(k)}.json", rec)
        ids.save_release("mbrel", a["rid"], release(a["rid"], a["album"], a["mbid"], n, a["rels"], a["track_rels"]))
        notes = base / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        ab.save_json(notes / f"{ab.safe_name(k)}.json", {
            "key": k, "year": a["year"], "label": "ABC", "minutes": 40,
            "notes": f"{a['album']} is an album by {a['artist']}, with Steve Gadd and Gary Katz.\n"
                     "# Critical reception\nCritics liked it.\n# AllMusic 5/5 · Rolling Stone 4/5\n"
                     f"# From the introduction to the Wikipedia article \"{a['album']}\", CC BY-SA 4.0"})
    ids.save_release("mbart", SD, {"id": SD, "name": "Steely Dan", "type": "Group", "relations": [
        dict(rel(BECKER, "Walter Becker", "member of band", ["bass guitar", "guitar"]),
             direction="backward", begin="1972", end="2017"),
        dict(rel(FAGEN, "Donald Fagen", "member of band", ["keyboards", "lead vocals"]),
             direction="backward", begin="1972")]})
    ids.save_release("mbart", JM, {"id": JM, "name": "Joni Mitchell", "type": "Person", "relations": []})
    ab.save_json(ids.LIBRARY, {"keys": sorted(lib), "albums": lib})
    # track notes for Aja's title track
    (base / "tracks" / "albums").mkdir(parents=True, exist_ok=True)
    ab.save_json(base / "tracks" / "albums" / f"{ab.safe_name('Steely Dan - Aja')}.json", {"tracks": {
        "1": {"paras": ["Nearly eight minutes long, with Wayne Shorter on saxophone.",
                        "# From the introduction to the Wikipedia article \"Aja (song)\", CC BY-SA 4.0"],
              "source": "wikipedia"}}})
    # artist bios
    ab.CACHE.mkdir(parents=True, exist_ok=True)
    for name, bio in (("Steely Dan", "Steely Dan is an American rock band founded by Walter Becker and "
                                     "Donald Fagen. Their producer was Gary Katz."),
                      ("Joni Mitchell", "Joni Mitchell is a Canadian singer.")):
        ab.save_json(ab.CACHE / f"{name}.json", {"artist": name, "bio": bio, "bio_source": "wikipedia",
                                                 "bio_title": name, "bio_date": "2026-11-14",
                                                 "subtitle": "Rock · New York · 1972–",
                                                 "photo_source": "theaudiodb thumb"})
        (ab.CACHE / f"{name}.jpg").write_bytes(jpg(800, 500))
    # the wiki's own lookups
    wiki = base / "notes wiki"
    (wiki / "discographies").mkdir(parents=True, exist_ok=True)
    ab.save_json(wiki / "discographies" / f"{SD}.json", {"fetched": "2026-11-23", "albums": [
        {"id": "rg-x1", "title": "Can't Buy a Thrill", "year": "1972"},
        {"id": "rg-rel-aja", "title": "Aja", "year": "1977"},
        {"id": "rg-rel-gau", "title": "Gaucho", "year": "1980"}]})
    (wiki / "people").mkdir(parents=True, exist_ok=True)
    for mbid, name, bio, src in ((JACO, "Jaco Pastorius", "John Francis Anthony Pastorius III was an "
                                  "American jazz bassist. He played with Weather Report. He changed the bass.",
                                  "wikipedia"),
                                 (SMITH_A, "John Smith", "An engineer.", "lastfm"),
                                 (SMITH_B, "John Smith", "A photographer. Born in Leeds. Worked with Steely Dan.",
                                  "lastfm")):
        ab.save_json(wiki / "people" / f"mb_{mbid}.json", {"artist": name, "bio": bio, "bio_source": src,
                                                           "subtitle": "", "fetched": "2026-11-23"})
    return lib
