"""Load API keys from the repo's git-ignored .env without printing them."""

import os

from .config import REPO

KEYS = ("TYPESAFE_API_KEY", "ANTHROPIC_API_KEY")


def load_env(path=REPO / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name in KEYS and value and not os.environ.get(name):
            os.environ[name] = value


def key_status():
    """Presence only; never the value."""
    load_env()
    return {name: bool(os.environ.get(name)) for name in KEYS}


def require(name):
    load_env()
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set. Paste it into {REPO / '.env'} (git-ignored).")
    return value
