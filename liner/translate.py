"""
translate.py -- notes and bios in other languages, for artists who don't
write in English.

Text is sent to DeepL only when it isn't English, judged twice: by where it
came from (Japanese Wikipedia, Last.fm's Japanese notes) and by the text
itself, so a source that answers in English is never translated. Every
translation is kept on this computer, so a yearly recheck sends only text
that has changed. Without a key in the settings file nothing is translated.
"""
from __future__ import annotations

import hashlib, json, re, time

import requests

NAMES = {"ja": "Japanese", "ko": "Korean", "zh": "Chinese", "fr": "French", "es": "Spanish",
         "it": "Italian", "de": "German", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish"}

# Wikidata's items for languages and countries, to the language's code
LANG_ITEMS = {"Q5287": "ja", "Q9176": "ko", "Q7850": "zh", "Q150": "fr", "Q1321": "es", "Q652": "it",
              "Q188": "de", "Q5146": "pt", "Q7411": "nl", "Q9027": "sv", "Q1860": "en"}
COUNTRY_LANG = {"Q17": "ja", "Q884": "ko", "Q148": "zh", "Q865": "zh", "Q8646": "zh", "Q142": "fr",
                "Q29": "es", "Q96": "es", "Q414": "es", "Q298": "es", "Q38": "it", "Q183": "de",
                "Q40": "de", "Q155": "pt", "Q45": "pt", "Q30": "en", "Q145": "en", "Q16": "en",
                "Q408": "en", "Q27": "en", "Q664": "en"}

ENGLISH_WORDS = set("the and of to in is was a his her their with for on by as from that it "
                    "album band song songs released record which were has had are this its".split())


def script_language(text):
    """"ja", "ko" or "zh" from the characters themselves, else None."""
    kana = len(re.findall(r"[぀-ヿ]", text))
    hangul = len(re.findall(r"[가-힯]", text))
    han = len(re.findall(r"[一-鿿]", text))
    if kana >= 3:
        return "ja"
    if hangul >= 3:
        return "ko"
    if han >= 5:
        return "zh"
    return None


def looks_english(text):
    """Whether a Latin-script text reads as English: common English words make
    up a good share of it."""
    if script_language(text):
        return False
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if len(words) < 8:
        return True
    return sum(w in ENGLISH_WORDS for w in words) / len(words) >= 0.12


def needs_translation(text, lang):
    """Text fetched in language `lang` that really is in another language."""
    if not text or lang == "en":
        return False
    found = script_language(text)
    if found:
        return True
    return lang not in ("ja", "ko", "zh") and not looks_english(text)


def artist_language(ent):
    """The language an artist works in, from their Wikidata item: the
    languages they speak or write, else their country. None for English or
    unknown."""
    def ids(prop):
        out = []
        for c in (ent.get("claims") or {}).get(prop, []):
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(v, dict) and v.get("id"):
                out.append(v["id"])
        return out
    for prop in ("P1412", "P103", "P407"):
        langs = [LANG_ITEMS[i] for i in ids(prop) if i in LANG_ITEMS]
        if langs:
            return None if "en" in langs else langs[0]
    for prop in ("P495", "P27", "P17"):
        langs = [COUNTRY_LANG[i] for i in ids(prop) if i in COUNTRY_LANG]
        if langs:
            return None if "en" in langs else langs[0]
    return None


class Translator:
    """DeepL, with every result kept in a file so it is never paid for twice.
    A free key ends ":fx" and uses DeepL's free address."""

    def __init__(self, key, cache_path, session=None):
        self.key = (key or "").strip()
        self.cache_path = cache_path
        self.session = session or requests.Session()
        self.off = not self.key
        try:
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def __bool__(self):
        return not self.off

    def translate(self, paras, lang):
        """English for a list of paragraphs, or None when translation is off
        or DeepL refused (no allowance left, a bad key)."""
        if self.off or not paras:
            return None
        keys = [hashlib.sha1(f"{lang}\n{p}".encode("utf-8")).hexdigest() for p in paras]
        todo = [(k, p) for k, p in zip(keys, paras) if k not in self.cache]
        if todo:
            host = "api-free.deepl.com" if self.key.endswith(":fx") else "api.deepl.com"
            try:
                r = self.session.post(f"https://{host}/v2/translate", timeout=30,
                                      headers={"Authorization": f"DeepL-Auth-Key {self.key}"},
                                      data=[("text", p) for _, p in todo]
                                      + [("source_lang", lang.upper()), ("target_lang", "EN-GB")])
            except requests.RequestException as e:
                print(f"     deepl: {e}")
                return None
            if r.status_code in (403, 456):
                print("     deepl: " + ("the key was refused - check `deepl key` in the settings file"
                                       if r.status_code == 403 else
                                       "this month's free allowance is used up") + "; no more translations this run")
                self.off = True
                return None
            if not r.ok:
                print(f"     deepl: HTTP {r.status_code}")
                return None
            for (k, _), t in zip(todo, r.json().get("translations") or []):
                self.cache[k] = t.get("text", "")
            self.save()
        out = [plain(self.cache.get(k, "")) for k in keys]
        return out if all(out) else None

    def save(self):
        tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_path)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

def plain(text):
    """DeepL sometimes marks titles in italics with asterisks ("*OK Computer*");
    the iPod would show the asterisks, so they go (also from saved translations)."""
    return re.sub(r"(?<![\w*])\*{1,2}([^*\n]+?)\*{1,2}(?![\w*])", r"\1", text)

def retrieved(date=None):
    """", retrieved 14 Nov 2026" for a YYYY-MM-DD date (default today), or "" for none."""
    date = date or time.strftime("%Y-%m-%d")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date)
    return f", retrieved {int(m[3])} {MONTHS[int(m[2]) - 1]} {m[1]}" if m else ""

def credit(source, lang=None, title=None, part="introduction", date=None):
    """The quiet last line naming where the text came from, as its licence asks,
    and when it was taken (`date` as YYYY-MM-DD, default today). For Wikipedia,
    `part` is "introduction" (the whole lead) or "excerpts" (the lead and a
    paragraph from further down)."""
    when = retrieved(date)
    if source.startswith("wikipedia"):
        foreign = lang and lang != "en"
        # another language's title would be in a script the iPod's font may lack
        article = (f"{NAMES.get(lang, lang)} Wikipedia article" if foreign
                   else "Wikipedia article" + (f" \"{title}\"" if title else ""))
        what = f"excerpts from the {article}" if part == "excerpts" else f"the introduction to the {article}"
        if foreign:
            line = "Machine-translated " + (what if part == "excerpts" else f"from {what}")
        else:
            line = what[0].upper() + what[1:] if part == "excerpts" else f"From {what}"
        return f"# {line}, CC BY-SA 4.0{when}"
    if source.startswith("last"):
        if lang and lang != "en":
            return f"# Machine-translated from Last.fm ({NAMES.get(lang, lang)}), CC BY-SA{when}"
        return f"# From Last.fm, CC BY-SA{when}"
    if source.startswith("discogs"):
        return f"# From Discogs{when}"
    return ""
