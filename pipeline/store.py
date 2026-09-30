"""Durable file helpers: atomic JSON writes and append-only JSONL with fsync."""

import gzip
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    """Write via a temp file and rename so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # A crash can truncate only the final line; anything earlier is corruption.
                rest = f.read()
                if rest.strip():
                    raise ValueError(f"{path}:{number}: corrupt JSONL line")
                return


class JsonlAppender:
    """Append-only JSONL writer. flush() fsyncs so saved progress survives a crash."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._repair_tail()
        self.f = self.path.open("a", encoding="utf-8")

    def _repair_tail(self):
        # Drop a partial last line left by a hard kill so later appends stay parseable.
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb+") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) == b"\n":
                return
            data = self.path.read_bytes()
            cut = data.rfind(b"\n") + 1
            f.truncate(cut)

    def write(self, obj):
        self.f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")

    def flush(self):
        self.f.flush()
        os.fsync(self.f.fileno())

    def close(self):
        self.flush()
        self.f.close()
