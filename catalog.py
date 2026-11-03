"""Append-only video registry shared by the server and the import command."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


CATALOG_VERSION = 1
SLOT_CAPACITY = 1024
REGISTRY_PATH = Path(__file__).with_name("clips.json")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


def video_id_from_url(value):
    """Accept YouTube watch/Shorts or youtu.be links, never arbitrary targets."""
    parsed = urlsplit(value.strip())
    if (parsed.scheme != "https" or parsed.username is not None
            or parsed.password is not None or parsed.port is not None):
        raise ValueError("Use an HTTPS YouTube URL without credentials or a port")
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.removeprefix("/")
    elif host in YOUTUBE_HOSTS and parsed.path == "/watch":
        values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        candidate = values[0] if len(values) == 1 else ""
    elif host in YOUTUBE_HOSTS and parsed.path.startswith("/shorts/"):
        candidate = parsed.path[len("/shorts/"):]
    else:
        raise ValueError("Only YouTube watch, Shorts and youtu.be links are accepted")
    if not VIDEO_ID.fullmatch(candidate):
        raise ValueError("Expected an eleven-character YouTube video ID")
    return candidate


def validate_clips(clips):
    if not isinstance(clips, list) or len(clips) > SLOT_CAPACITY:
        raise ValueError(f"Registry must contain at most {SLOT_CAPACITY} clips")
    if any(not isinstance(clip, str) or not VIDEO_ID.fullmatch(clip) for clip in clips):
        raise ValueError("Registry contains an invalid YouTube video ID")
    if len(clips) != len(set(clips)):
        raise ValueError("A video ID may have only one stable slot")
    return clips


def load_registry(path=REGISTRY_PATH):
    with Path(path).open(encoding="utf-8") as source:
        registry = json.load(source)
    if not isinstance(registry, dict) or type(registry.get("version")) is not int or registry["version"] != CATALOG_VERSION:
        raise ValueError("Unsupported clip registry version")
    return validate_clips(registry.get("clips"))


def append_urls(existing, lines):
    """Existing positions are retained even when the input is reordered or shorter."""
    clips = list(validate_clips(list(existing)))
    known = set(clips)
    for number, raw in enumerate(lines, 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            clip = video_id_from_url(value)
        except ValueError as error:
            raise ValueError(f"Input line {number}: {error}") from error
        if clip in known:
            continue
        if len(clips) >= SLOT_CAPACITY:
            raise ValueError(f"Import would exceed the {SLOT_CAPACITY}-slot player capacity")
        clips.append(clip)
        known.add(clip)
    return clips


def write_registry(path, clips):
    """Replace only a complete, validated registry; a failed import keeps the old file."""
    registry = {"version": CATALOG_VERSION, "clips": validate_clips(clips)}
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(registry, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_file(source_path, registry_path=REGISTRY_PATH):
    path = Path(registry_path)
    before = load_registry(path) if path.exists() else []
    with Path(source_path).open(encoding="utf-8-sig") as source:
        after = append_urls(before, source)
    if after != before or not path.exists():
        write_registry(path, after)
    return len(after) - len(before), len(after)
