"""Deterministic entity extraction from a fixed lexicon (no model involved).

Entities are product features, plans and devices named in the text. The list is
small and auditable; it is a transparent baseline, not an exhaustive NER.
"""

import re

LEXICON = {
    "Premium": r"premium",
    "Free tier": r"free (?:version|tier|plan|account|users?)",
    "Family plan": r"family (?:plan|premium|account)",
    "Duo": r"\bduo\b",
    "Student plan": r"student (?:plan|premium|discount)",
    "Shuffle": r"shuffl\w*",
    "Queue": r"\bqueue\w*",
    "Playlists": r"play ?lists?",
    "Library": r"\blibrary\b",
    "Liked songs": r"liked songs",
    "Lyrics": r"\blyrics?\b",
    "Podcasts": r"podcasts?",
    "Audiobooks": r"audio ?books?",
    "Radio": r"\bradio\b",
    "DJ": r"\bdj\b",
    "Wrapped": r"\bwrapped\b",
    "Discover Weekly": r"discover weekly",
    "Daily Mix": r"daily mix",
    "Downloads": r"download\w*",
    "Offline mode": r"offline",
    "Ads": r"\bads?\b|advert\w*|commercials?",
    "Search": r"\bsearch\w*",
    "Android Auto": r"android auto",
    "Bluetooth": r"bluetooth",
    "Chromecast": r"chromecast",
    "Smartwatch": r"wear ?os|smart ?watch|galaxy watch",
    "Widget": r"\bwidget",
    "Lock screen": r"lock ?screen",
    "Sleep timer": r"sleep timer",
    "Equalizer": r"equali[sz]er",
    "Spotify Connect": r"spotify connect",
    "Login": r"\blog ?in\b|\bsign ?in\b|password",
    "Customer support": r"customer (?:service|support)|\bsupport team",
}
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in LEXICON.items()]


def extract(text):
    return [name for name, pattern in _COMPILED if pattern.search(text)]
