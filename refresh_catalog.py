"""Discover explicit YouTube Shorts and append new stable slots off the request path."""

import argparse
from copy import deepcopy
from contextlib import ExitStack
from dataclasses import dataclass
from itertools import zip_longest
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from catalog import REGISTRY_PATH, SLOT_CAPACITY, VIDEO_ID, load_registry_document, video_id_from_url, write_registry_document


CONFIG_PATH = Path(__file__).with_name("feed_sources.json")
SEARCH_URL = "https://www.youtube.com/results"
CURATED_URL = "https://raw.githubusercontent.com/gorod13224-cpu/vr-shorts-data/main/shorts_urls.txt"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_ADDITIONS = 20
FULL_SCAN_MAX_ADDITIONS = 200
TOPIC_ID = re.compile(r'q(?:0|[1-9][0-9]*)\Z')
INITIAL_DATA = re.compile(r'(?:\b(?:var\s+)?ytInitialData\s*|window\["ytInitialData"\]\s*)=\s*')
AD_CONTAINERS = frozenset({
    "adSlotRenderer", "adSlotAndLayoutItemRenderer", "adPlacements", "playerAds", "adSlots",
    "promotedVideoRenderer", "promotedSparklesWebRenderer", "promotedSparklesTextSearchRenderer",
    "inFeedAdLayoutRenderer", "inStreamAdRenderer", "displayAdRenderer", "mastheadAdRenderer",
    "actionCompanionAdRenderer", "adLayoutMetadata", "adMetadata", "adPlaybackContext",
})


class RefreshError(ValueError):
    """A failed source or concurrent change must not rewrite the registry."""


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    query: str


@dataclass(frozen=True)
class SourceConfig:
    topics: tuple[Topic, ...]
    queries_per_run: int
    max_additions: int
    include_curated_source: bool

    @property
    def queries(self):
        return tuple(topic.query for topic in self.topics)


def load_config(path=CONFIG_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise RefreshError("Unsupported feed source config version")
    definitions = data.get("topics")
    if definitions is None and isinstance(data.get("search_queries"), list):
        # Compatibility for local configs; production stores explicit, never-reused IDs.
        definitions = [{"id": f"q{i}", "query": query,
                        "name": query.replace("#shorts", "").strip() if isinstance(query, str) else ""}
                       for i, query in enumerate(data["search_queries"])]
    if not isinstance(definitions, list) or not 1 <= len(definitions) <= 100:
        raise RefreshError("Use 1–100 topic definitions")
    topics = []
    for item in definitions:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not TOPIC_ID.fullmatch(item["id"])
                or any(not isinstance(item.get(key), str) or not item[key].strip() or len(item[key]) > 160 for key in ("name", "query"))):
            raise RefreshError("Each topic needs a stable qN id, nonempty name and search query (max 160 characters)")
        topics.append(Topic(item["id"], item["name"].strip(), item["query"].strip()))
    if len({topic.id for topic in topics}) != len(topics):
        raise RefreshError("Topic IDs must be unique")
    count, limit = data.get("queries_per_run"), data.get("max_additions")
    if type(count) is not int or not 1 <= count <= 8:
        raise RefreshError("queries_per_run must be between 1 and 8")
    if type(limit) is not int or not 1 <= limit <= MAX_ADDITIONS:
        raise RefreshError(f"max_additions must be between 1 and {MAX_ADDITIONS}")
    curated = data.get("include_curated_source")
    if type(curated) is not bool:
        raise RefreshError("include_curated_source must be a boolean")
    return SourceConfig(tuple(topics), count, limit, curated)


def select_queries(config, now):
    return [topic.query for topic in select_topics(config, now)]


def select_topics(config, now):
    count = min(config.queries_per_run, len(config.topics))
    start = (int(now // 1800) * count) % len(config.topics)
    return [config.topics[(start + index) % len(config.topics)] for index in range(count)]


def walk_objects(value):
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node.get("isAd") is True or node.get("isSponsored") is True:
                continue
            yield node
            # Skip complete promoted/ad subtrees while retaining adjacent organic results.
            pending.extend(value for key, value in reversed(list(node.items())) if key not in AD_CONTAINERS)
        elif isinstance(node, list):
            pending.extend(reversed(node))


def short_endpoint_id(command):
    if not isinstance(command, dict):
        return None
    endpoint = command.get("reelWatchEndpoint")
    if not isinstance(endpoint, dict):
        return None
    clip = endpoint.get("videoId")
    if not isinstance(clip, str) or not VIDEO_ID.fullmatch(clip):
        return None
    outer_metadata = command.get("commandMetadata", {})
    if not isinstance(outer_metadata, dict):
        return None
    metadata = outer_metadata.get("webCommandMetadata", {})
    if not isinstance(metadata, dict):
        return None
    url = metadata.get("url")
    if url is not None:
        if not isinstance(url, str):
            return None
        absolute = "https://www.youtube.com" + url if url.startswith("/") else url
        try:
            if not urlsplit(absolute).path.startswith("/shorts/") or video_id_from_url(absolute) != clip:
                return None
        except ValueError:
            return None
    page_type = metadata.get("webPageType")
    if page_type is not None and page_type != "WEB_PAGE_TYPE_SHORTS":
        return None
    return clip


def organic_renderer(node):
    return (isinstance(node, dict) and not AD_CONTAINERS.intersection(node)
            and node.get("isAd") is not True and node.get("isSponsored") is not True)


def has_shorts_overlay(renderer):
    overlays = renderer.get("thumbnailOverlays", [])
    if not isinstance(overlays, list):
        return False
    for overlay in overlays:
        status = overlay.get("thumbnailOverlayTimeStatusRenderer") if isinstance(overlay, dict) else None
        if isinstance(status, dict) and status.get("style") == "SHORTS":
            return True
    return False


def parse_short_ids(html):
    """Only recognized Shorts renderer + reel endpoints count; ordinary videos do not."""
    found = []
    known = set()
    decoder = json.JSONDecoder()
    for match in INITIAL_DATA.finditer(html):
        try:
            data, _ = decoder.raw_decode(html[match.end():].lstrip())
        except (ValueError, RecursionError):
            continue
        if not isinstance(data, dict):
            continue
        for node in walk_objects(data):
            clip = None
            modern = node.get("shortsLockupViewModel")
            if organic_renderer(modern):
                tap = modern.get("onTap")
                if isinstance(tap, dict):
                    clip = short_endpoint_id(tap.get("innertubeCommand"))
            legacy = node.get("reelItemRenderer")
            if clip is None and organic_renderer(legacy):
                endpoint_id = short_endpoint_id(legacy.get("navigationEndpoint"))
                if legacy.get("videoId") == endpoint_id:
                    clip = endpoint_id
            video = node.get("videoRenderer")
            if clip is None and organic_renderer(video) and has_shorts_overlay(video):
                endpoint_id = short_endpoint_id(video.get("navigationEndpoint"))
                if video.get("videoId") == endpoint_id:
                    clip = endpoint_id
            if clip and clip not in known:
                known.add(clip)
                found.append(clip)
    if not found:
        raise RefreshError("No explicit Shorts found (empty, blocked or changed YouTube response)")
    return found


def parse_curated_ids(text):
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            result.append(video_id_from_url(value))
        except ValueError as error:
            raise RefreshError(f"Invalid curated source line {number}: {error}") from error
    if not result:
        raise RefreshError("Curated source is empty")
    return list(dict.fromkeys(result))


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    })
    retries = Retry(total=2, connect=2, read=2, status=2, backoff_factor=.5,
                    status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), respect_retry_after_header=False)
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def fetch_text(session, url, params=None):
    with session.get(url, params=params, timeout=(5, 15), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise RefreshError(f"Source returned HTTP {response.status_code}")
        parts = []
        length = 0
        for part in response.iter_content(chunk_size=65536):
            length += len(part)
            if length > MAX_RESPONSE_BYTES:
                raise RefreshError("Source response exceeded the size limit")
            parts.append(part)
        return b"".join(parts).decode("utf-8-sig")


def refresh_registry(registry_path=REGISTRY_PATH, config_path=CONFIG_PATH, *, fetch=None, now=None, dry_run=False,
                     full_scan=False, max_additions=None):
    config = load_config(config_path)
    registry = Path(registry_path)
    original_bytes = registry.read_bytes()
    document = load_registry_document(registry)
    existing = document["clips"]
    maximum = FULL_SCAN_MAX_ADDITIONS if full_scan else MAX_ADDITIONS
    addition_limit = max_additions if max_additions is not None else (maximum if full_scan else config.max_additions)
    if type(addition_limit) is not int or not 1 <= addition_limit <= maximum:
        raise RefreshError(f"max_additions must be between 1 and {maximum} for this scan mode")
    report = {"before_count": len(existing), "after_count": len(existing), "capacity": SLOT_CAPACITY,
              "added": 0, "topic_associations_added": 0, "successful_searches": 0, "source_errors": [],
              "dry_run": dry_run, "full_scan": full_scan}
    with ExitStack() as stack:
        if fetch is None:
            session = stack.enter_context(create_session())
            fetch = lambda url, params=None: fetch_text(session, url, params)
        curated = []
        if config.include_curated_source:
            try:
                curated = parse_curated_ids(fetch(CURATED_URL))
            except (requests.RequestException, ValueError, UnicodeError) as error:
                report["source_errors"].append(f"Curated source: {error}")
        searches = []
        selected = config.topics if full_scan else select_topics(config, time.time() if now is None else now)
        for topic in selected:
            query = topic.query
            search_query = query if "#shorts" in query.lower() else "#shorts " + query
            try:
                searches.append((topic, parse_short_ids(fetch(SEARCH_URL, {"search_query": search_query}))))
                report["successful_searches"] += 1
            except (requests.RequestException, ValueError, UnicodeError) as error:
                report["source_errors"].append(f"Search {query!r}: {error}")
    if not searches:
        raise RefreshError("Every Shorts discovery source failed; registry retained. " + "; ".join(report["source_errors"]))
    # Interleave searches so the first topic cannot consume every new slot.
    discovered = [clip for group in zip_longest(*(clips for _, clips in searches)) for clip in group if clip is not None]
    appended = []
    known = set(existing)
    limit = min(addition_limit, SLOT_CAPACITY - len(existing))
    for clip in curated + discovered if limit > 0 else []:
        if clip not in known:
            known.add(clip)
            appended.append(clip)
            if len(appended) >= limit:
                break
    memberships = deepcopy(document.get("clip_topics", {}))
    associated = 0
    for topic, clips in searches:
        for clip in clips:
            if clip not in known:
                continue
            names = memberships.setdefault(clip, [])
            if topic.id not in names:
                names.append(topic.id)
                associated += 1
    if registry.read_bytes() != original_bytes:
        raise RefreshError("Registry changed during refresh; refusing to overwrite concurrent edits")
    if (appended or associated) and not dry_run:
        updated = deepcopy(document)
        updated.update(clips=existing + appended, clip_topics=memberships)
        write_registry_document(registry, updated)
    status = "updated" if appended or associated else "no_new_clips"
    if not appended and not associated and len(existing) >= SLOT_CAPACITY:
        status = "capacity_reached"
    report.update(status=status, added=len(appended), topic_associations_added=associated,
                  after_count=len(existing) + len(appended))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Report candidates without changing the registry")
    parser.add_argument("--full-scan", action="store_true", help="Scan every configured topic (manual backfill)")
    parser.add_argument("--max-additions", type=int, help="At most 20 normally, or 200 with --full-scan")
    args = parser.parse_args()
    try:
        report = refresh_registry(args.registry, args.config, dry_run=args.dry_run,
                                  full_scan=args.full_scan, max_additions=args.max_additions)
    except (OSError, ValueError, requests.RequestException) as error:
        parser.exit(1, f"Refresh failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
