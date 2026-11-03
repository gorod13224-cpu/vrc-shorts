import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests

from catalog import SLOT_CAPACITY, load_registry, load_registry_document, write_registry, write_registry_document
from refresh_catalog import (CURATED_URL, MAX_RESPONSE_BYTES, RefreshError, fetch_text,
                             load_config, parse_short_ids, refresh_registry, select_queries)


def short(clip, url=None):
    return {"shortsLockupViewModel": {"onTap": {"innertubeCommand": {
        "reelWatchEndpoint": {"videoId": clip},
        "commandMetadata": {"webCommandMetadata": {"url": url or "/shorts/" + clip,
                                                     "webPageType": "WEB_PAGE_TYPE_SHORTS"}},
    }}}}


def page(*nodes):
    return '<html><script>var ytInitialData = ' + json.dumps({"contents": list(nodes)}) + ';</script></html>'


class ShortsDiscoveryTests(unittest.TestCase):
    def test_only_explicit_shorts_are_accepted_not_ordinary_video_ids_or_titles(self):
        html = page({"videoRenderer": {"videoId": "LONGVIDEO01", "title": "#shorts"}},
                    {"videoId": "UNRELATED01"}, short("AAAAAAAAAAA"), short("AAAAAAAAAAA"))
        self.assertEqual(parse_short_ids(html), ["AAAAAAAAAAA"])

    def test_legacy_reel_requires_matching_navigation_endpoint(self):
        legacy = {"reelItemRenderer": {"videoId": "BBBBBBBBBBB",
                  "navigationEndpoint": {"reelWatchEndpoint": {"videoId": "BBBBBBBBBBB"}}}}
        self.assertEqual(parse_short_ids(page(legacy)), ["BBBBBBBBBBB"])
        legacy["reelItemRenderer"]["navigationEndpoint"]["reelWatchEndpoint"]["videoId"] = "CCCCCCCCCCC"
        with self.assertRaises(RefreshError):
            parse_short_ids(page(legacy))

    def test_video_renderer_requires_both_explicit_shorts_overlay_and_matching_reel_endpoint(self):
        video = {"videoRenderer": {"videoId": "BBBBBBBBBBB",
                 "thumbnailOverlays": [{"thumbnailOverlayTimeStatusRenderer": {"style": "SHORTS"}}],
                 "navigationEndpoint": {"reelWatchEndpoint": {"videoId": "BBBBBBBBBBB"},
                    "commandMetadata": {"webCommandMetadata": {"url": "/shorts/BBBBBBBBBBB"}}}}}
        self.assertEqual(parse_short_ids(page(video)), ["BBBBBBBBBBB"])
        video["videoRenderer"]["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"]["style"] = "DEFAULT"
        with self.assertRaises(RefreshError):
            parse_short_ids(page(video))
        video["videoRenderer"]["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"]["style"] = "SHORTS"
        video["videoRenderer"]["videoId"] = "CCCCCCCCCCC"
        with self.assertRaises(RefreshError):
            parse_short_ids(page(video))

    def test_ad_or_promoted_ancestor_never_imports_nested_shorts(self):
        containers = ["adSlotRenderer", "adSlotAndLayoutItemRenderer", "adPlacements", "playerAds",
                      "promotedVideoRenderer", "inFeedAdLayoutRenderer", "promotedSparklesWebRenderer"]
        html = page(*( {key: {"content": short("BBBBBBBBBBB")}} for key in containers), short("AAAAAAAAAAA"))
        self.assertEqual(parse_short_ids(html), ["AAAAAAAAAAA"])
        root = {"adPlacements": [short("BBBBBBBBBBB")], "contents": [short("AAAAAAAAAAA")]}
        self.assertEqual(parse_short_ids("var ytInitialData = " + json.dumps(root)), ["AAAAAAAAAAA"])

    def test_explicit_ad_flags_on_shorts_nodes_are_rejected(self):
        ad = short("BBBBBBBBBBB")
        ad["shortsLockupViewModel"]["isAd"] = True
        sponsored = {"isSponsored": True, "contents": short("CCCCCCCCCCC")}
        metadata = short("DDDDDDDDDDD")
        metadata["shortsLockupViewModel"]["adMetadata"] = {"content": "advertisement"}
        self.assertEqual(parse_short_ids(page(ad, sponsored, metadata, short("AAAAAAAAAAA"))), ["AAAAAAAAAAA"])

    def test_mismatched_watch_or_untrusted_navigation_urls_are_not_imported(self):
        nodes = [short("AAAAAAAAAAA", "/shorts/BBBBBBBBBBB"),
                 short("AAAAAAAAAAA", "/watch?v=AAAAAAAAAAA"),
                 short("AAAAAAAAAAA", "https://evil.test/shorts/AAAAAAAAAAA"),
                 short("not-valid")]
        with self.assertRaises(RefreshError):
            parse_short_ids(page(*nodes))

    def test_nested_json_strings_and_window_assignment_do_not_break_parser(self):
        html = page({"title": "braces } { and escaped \"quotes\"", "nested": [short("AAAAAAAAAAA")]})
        html = html.replace("var ytInitialData =", 'window["ytInitialData"] =')
        self.assertEqual(parse_short_ids(html), ["AAAAAAAAAAA"])

    def test_bad_metadata_consent_and_malformed_pages_fail_cleanly(self):
        malformed = short("AAAAAAAAAAA")
        malformed["shortsLockupViewModel"]["onTap"]["innertubeCommand"]["commandMetadata"] = None
        for html in ("<html>Before you continue</html>", "var ytInitialData = {bad", page(malformed), page()):
            with self.subTest(html=html), self.assertRaises(RefreshError):
                parse_short_ids(html)

    def test_fetch_has_timeout_no_redirects_and_a_bounded_response(self):
        response = Mock(status_code=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [b"abc"]
        session = Mock()
        session.get.return_value = response
        self.assertEqual(fetch_text(session, "https://www.youtube.com/results"), "abc")
        self.assertEqual(session.get.call_args.kwargs["timeout"], (5, 15))
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        response.status_code = 302
        with self.assertRaisesRegex(RefreshError, "HTTP 302"):
            fetch_text(session, "https://www.youtube.com/results")
        response.status_code = 200
        response.iter_content.return_value = [b"x" * (MAX_RESPONSE_BYTES + 1)]
        with self.assertRaisesRegex(RefreshError, "size limit"):
            fetch_text(session, "https://www.youtube.com/results")


class RefreshRegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.registry = Path(self.folder.name) / "clips.json"
        self.config = Path(self.folder.name) / "sources.json"
        write_registry(self.registry, ["AAAAAAAAAAA"])
        self.configure()

    def configure(self, queries=None, limit=20, curated=False):
        self.config.write_text(json.dumps({"version": 1, "search_queries": queries or ["#shorts memes"],
                                          "queries_per_run": 2, "max_additions": limit,
                                          "include_curated_source": curated}), encoding="utf-8")

    def refresh(self, fetch, **kwargs):
        return refresh_registry(self.registry, self.config, fetch=fetch, now=0, **kwargs)

    def test_append_is_capped_and_never_reassigns_existing_slots(self):
        candidates = [f"{number:011d}" for number in range(40)]
        report = self.refresh(lambda *args: page(short("AAAAAAAAAAA"), *(short(clip) for clip in candidates)))
        self.assertEqual(report["added"], 20)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA"] + candidates[:20])

    def test_duplicate_only_refresh_keeps_exact_registry_bytes(self):
        write_registry_document(self.registry, {"version": 1, "clips": ["AAAAAAAAAAA"], "clip_topics": {"AAAAAAAAAAA": ["q0"]}})
        original = self.registry.read_bytes()
        report = self.refresh(lambda *args: page(short("AAAAAAAAAAA")))
        self.assertEqual(report["status"], "no_new_clips")
        self.assertEqual(self.registry.read_bytes(), original)

    def test_searches_are_interleaved_for_topic_diversity(self):
        self.configure(["one", "two"])
        def fetch(url, params=None):
            ids = ["BBBBBBBBBBB", "CCCCCCCCCCC"] if params["search_query"].endswith("one") else ["DDDDDDDDDDD", "EEEEEEEEEEE"]
            return page(*(short(clip) for clip in ids))
        self.refresh(fetch)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA", "BBBBBBBBBBB", "DDDDDDDDDDD", "CCCCCCCCCCC", "EEEEEEEEEEE"])

    def test_failed_queries_do_not_prevent_a_valid_source_but_are_reported(self):
        self.configure(["broken", "valid"])
        def fetch(url, params=None):
            if params["search_query"].endswith("broken"):
                raise requests.Timeout("source timeout")
            return page(short("BBBBBBBBBBB"))
        report = self.refresh(fetch)
        self.assertEqual(report["successful_searches"], 1)
        self.assertEqual(len(report["source_errors"]), 1)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA", "BBBBBBBBBBB"])

    def test_all_failed_or_empty_discovery_keeps_bytes_even_with_valid_curated_list(self):
        self.configure(curated=True)
        original = self.registry.read_bytes()
        def fetch(url, params=None):
            return "https://youtu.be/BBBBBBBBBBB" if url == CURATED_URL else "<html>blocked</html>"
        with self.assertRaisesRegex(RefreshError, "Every Shorts discovery source failed"):
            self.refresh(fetch)
        self.assertEqual(self.registry.read_bytes(), original)

    def test_curated_source_only_appends_and_invalid_curated_batch_is_discarded(self):
        self.configure(curated=True)
        def fetch(url, params=None):
            return "https://youtu.be/BBBBBBBBBBB\nhttps://youtu.be/AAAAAAAAAAA" if url == CURATED_URL else page(short("CCCCCCCCCCC"))
        self.refresh(fetch)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])
        def bad_source(url, params=None):
            return "https://youtu.be/DDDDDDDDDDD\nhttps://evil.test/nope" if url == CURATED_URL else page(short("EEEEEEEEEEE"))
        report = self.refresh(bad_source)
        self.assertEqual(len(report["source_errors"]), 1)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC", "EEEEEEEEEEE"])

    def test_capacity_caps_new_slots_but_existing_clips_can_gain_topics(self):
        existing = [f"{number:011d}" for number in range(SLOT_CAPACITY - 1)]
        write_registry(self.registry, existing)
        report = self.refresh(lambda *args: page(short("BBBBBBBBBBB"), short("CCCCCCCCCCC")))
        self.assertEqual(report["added"], 1)
        self.assertEqual(load_registry(self.registry), existing + ["BBBBBBBBBBB"])
        report = self.refresh(lambda *args: page(short("00000000000"), short("CCCCCCCCCCC")))
        self.assertEqual(report["added"], 0)
        self.assertEqual(report["topic_associations_added"], 1)
        self.assertEqual(load_registry_document(self.registry)["clip_topics"]["00000000000"], ["q0"])
        original = self.registry.read_bytes()
        report = self.refresh(lambda *args: page(short("00000000000")))
        self.assertEqual(report["status"], "capacity_reached")
        self.assertEqual(self.registry.read_bytes(), original)

    def test_concurrent_registry_edit_is_never_overwritten(self):
        def fetch(*args):
            write_registry(self.registry, ["AAAAAAAAAAA", "USEREDIT001"])
            return page(short("BBBBBBBBBBB"))
        with self.assertRaisesRegex(RefreshError, "concurrent edits"):
            self.refresh(fetch)
        self.assertEqual(load_registry(self.registry), ["AAAAAAAAAAA", "USEREDIT001"])

    def test_dry_run_does_not_write_any_registry_bytes(self):
        original = self.registry.read_bytes()
        report = self.refresh(lambda *args: page(short("BBBBBBBBBBB")), dry_run=True)
        self.assertEqual(report["added"], 1)
        self.assertTrue(report["dry_run"])
        self.assertEqual(self.registry.read_bytes(), original)

    def test_editable_config_rotates_queries_and_enforces_limits(self):
        self.configure(["one", "two", "three"])
        config = load_config(self.config)
        self.assertEqual(select_queries(config, 0), ["one", "two"])
        self.assertEqual(select_queries(config, 3600), ["three", "one"])
        self.configure(limit=21)
        with self.assertRaisesRegex(RefreshError, "max_additions"):
            load_config(self.config)

    def test_old_slots_gain_topics_without_count_or_order_changes(self):
        self.configure(["one", "two"])
        report = self.refresh(lambda *args: page(short("AAAAAAAAAAA")))
        self.assertEqual((report["added"], report["topic_associations_added"]), (0, 2))
        document = load_registry_document(self.registry)
        self.assertEqual(document["clips"], ["AAAAAAAAAAA"])
        self.assertEqual(document["clip_topics"], {"AAAAAAAAAAA": ["q0", "q1"]})

    def test_full_scan_visits_all_topics_and_has_explicit_200_slot_ceiling(self):
        self.configure([f"topic{i}" for i in range(10)])
        calls = []
        def fetch(url, params=None):
            calls.append(params["search_query"])
            return page(*(short(f"{number:011d}") for number in range(250)))
        report = self.refresh(fetch, full_scan=True, max_additions=200)
        self.assertEqual(len(calls), 10)
        self.assertEqual(report["added"], 200)
        document = load_registry_document(self.registry)
        self.assertEqual(document["clips"][0], "AAAAAAAAAAA")
        self.assertEqual(document["clip_topics"]["00000000000"], [f"q{i}" for i in range(10)])
        with self.assertRaisesRegex(RefreshError, "between 1 and 20"):
            self.refresh(fetch, max_additions=200)

    def test_refresh_preserves_other_metadata_and_existing_topic_memberships(self):
        write_registry_document(self.registry, {"version": 1, "clips": ["AAAAAAAAAAA"],
                                               "clip_topics": {"AAAAAAAAAAA": ["q26"]}, "custom": {"keep": True}})
        self.refresh(lambda *args: page(short("AAAAAAAAAAA")))
        document = load_registry_document(self.registry)
        self.assertEqual(document["custom"], {"keep": True})
        self.assertEqual(document["clip_topics"]["AAAAAAAAAAA"], ["q26", "q0"])


if __name__ == "__main__":
    unittest.main()
