"""Deterministic language grouping (no model). Used for reporting, and to pick translation candidates.

Groups:
  english             Latin script with a high share of common English words
  short_unrecognised  1-3 Latin words, none in the list (mostly English slang: "Op", "Gg")
  non_english_latin   Latin script, low share of common English words (Spanish, Tagalog, Hinglish, gibberish...)
  non_latin_script    mostly non-Latin letters (Devanagari, Bengali, Arabic, Cyrillic, CJK, stylised Unicode)
  no_letters          emoji, numbers or punctuation only
It is a heuristic for grouping and routing, not a language identifier; its error is part of what
the per-language verification report measures.
"""

import re
import unicodedata

from .store import canonical, sha256_text

COMMON_ENGLISH = frozenset("""
a about above actually add added after again ago all almost already also always am amazing an and annoying another any
anymore anything app apps are aren't around as ask at audio available awesome away awful back bad band be beautiful
because become been before being best better big bit boring both bought broken bug bugs but button buy by call can
cancel cancelled can't cannot cant car change changed cheap close come could couldn't crash crashed crashes crashing
data day days dear definitely did didn't didnt different do does doesn't doesnt doing don't done dont down download
downloaded downloading downloads during each easy either else end enjoy enough even ever every everyone everything
excellent experience family fantastic far fast favorite favourite feature features few find fine first fix fixed fixing
for free friends from full fun get gets getting give go goes going gone good got great had happy hard has hate have
haven't having he hear help her here hey his home hope how however i i'd i'll i'm i've if im in instead is isn't isnt it
it's its itself just keep keeps kind know last later least less let like liked listen listening little live long look
lot lots love loved lovely make makes many may maybe me mean minutes mode month months more most much music must my need
needs never new next nice no none not nothing now of off offline often ok okay old on once one only open or other others
our out over own paid pay paying people perfect phone play played player playing playlist playlists please podcast
podcasts poor premium pretty price problem problems quality random really reason recommend recommended right same say
says screen search second see seems service set should show shows shuffle since skip skips so some something song songs
soon sound spotify start started still stop stopped stops stupid subscription such super sure take than thank thanks
that that's the their them then there there's these they thing things think this those though through time times to
today too track tracks tried try trying turn two under unless until up update updated updates us use used useful user
users using very wait want wanted wants was wasn't way we well went were what when where which while who why will wish
with without won't wont work worked working works worse worst worth would wow wrong year years yes yet you your
""".split())

TRANSLATION_GROUPS = ("non_english_latin", "non_latin_script")
_WORD = re.compile(r"[a-z']+")


def group(text):
    latin = other = 0
    for ch in text:
        if ch.isalpha():
            if "LATIN" in unicodedata.name(ch, ""):
                latin += 1
            else:
                other += 1
    if latin + other == 0:
        return "no_letters"
    if other > latin:
        return "non_latin_script"
    words = _WORD.findall(text.lower())
    if not words:
        return "non_latin_script"
    hits = sum(w in COMMON_ENGLISH for w in words)
    if hits / len(words) >= 0.3 or (len(words) <= 2 and hits):
        return "english"
    if len(words) <= 3:
        return "short_unrecognised"
    return "non_english_latin"


def version():
    return sha256_text(canonical({"words": sorted(COMMON_ENGLISH), "rule": "ratio>=0.3 or (<=2 words and hit)",
                                  "groups": TRANSLATION_GROUPS}))[:10]
