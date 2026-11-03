"""Append-only video registry shared by the server and the import command."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


CATALOG_VERSION = 1
SLOT_CAPACITY = 8192
REGISTRY_PATH = Path(__file__).with_name("clips.json")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
TOPIC_ID = re.compile(r"q(?:0|[1-9][0-9]*)\Z")
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


def validate_registry_document(registry):
    """Validate stable clips and optional associations without dropping other metadata."""
    if not isinstance(registry, dict) or type(registry.get("version")) is not int or registry["version"] != CATALOG_VERSION:
        raise ValueError("Unsupported clip registry version")
    clips = validate_clips(registry.get("clips"))
    if "clip_topics" in registry:
        associations = registry["clip_topics"]
        if not isinstance(associations, dict):
            raise ValueError("clip_topics must map registered video IDs to topic lists")
        known = set(clips)
        for clip, topics in associations.items():
            if not isinstance(clip, str) or clip not in known:
                raise ValueError("clip_topics contains an unregistered video ID")
            if (not isinstance(topics, list)
                    or any(not isinstance(topic, str) or not TOPIC_ID.fullmatch(topic) for topic in topics)):
                raise ValueError("Each clip_topics value must be a list of stable topic IDs (q0, q1, ...)")
            if len(topics) != len(set(topics)):
                raise ValueError("A clip may contain each stable topic ID only once")
    return registry


def load_registry_document(path=REGISTRY_PATH):
    with Path(path).open(encoding="utf-8") as source:
        registry = json.load(source)
    return validate_registry_document(registry)


def load_registry(path=REGISTRY_PATH):
    return load_registry_document(path)["clips"]


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
    """Replace the clip list while retaining existing associations and other metadata."""
    path = Path(path)
    registry = load_registry_document(path) if path.exists() else {"version": CATALOG_VERSION}
    registry["clips"] = validate_clips(clips)
    write_registry_document(path, registry)


def write_registry_document(path, document):
    """Atomically replace a complete, validated document; failure keeps the old file."""
    registry = validate_registry_document(document)
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
