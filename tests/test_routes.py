import concurrent.futures
import unittest
from unittest.mock import patch

import main
from catalog import load_registry
from refresh_catalog import Topic


class FeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()

    def test_catalog_has_exact_contiguous_slot_count_and_no_cache(self):
        with patch("requests.sessions.Session.request") as external:
            response = self.client.get("/catalog.json")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual((data["version"], data["count"]), (1, len(load_registry())))
        self.assertEqual([topic["id"] for topic in data["topics"]], [f"q{i}" for i in range(39)])
        for topic in data["topics"]:
            self.assertTrue(topic["name"])
            self.assertEqual(topic["clips"], sorted(set(topic["clips"])))
            self.assertTrue(all(type(slot) is int and 0 <= slot < data["count"] for slot in topic["clips"]))
        self.assertGreater(response.get_json()["count"], 0)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        external.assert_not_called()

    def test_stable_slots_redirect_to_registered_video_without_external_lookup(self):
        ids = load_registry()
        with patch("requests.sessions.Session.request") as external:
            for slot in (0, len(ids) - 1, 0):
                response = self.client.get(f"/clip/{slot}")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], f"https://www.youtube.com/watch?v={ids[slot]}")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        external.assert_not_called()

    def test_invalid_slot_is_404_and_cannot_become_arbitrary_redirect(self):
        for slot in ("-1", "not-a-number", str(len(main.CLIP_IDS)), "9999999999999999999"):
            with self.subTest(slot=slot):
                response = self.client.get(f"/clip/{slot}?url=https://evil.test/")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("Location", response.headers)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = self.client.get("/clip/0?url=https://evil.test/&v=ZZZZZZZZZZZ")
        self.assertEqual(response.headers["Location"], f"https://www.youtube.com/watch?v={main.CLIP_IDS[0]}")

    def test_concurrent_requests_keep_identical_slot_identity(self):
        def request_clip(index):
            slot = index % len(main.CLIP_IDS)
            with main.app.test_client() as client:
                response = client.get(f"/clip/{slot}")
                return slot, response.status_code, response.headers["Location"]

        with patch("requests.sessions.Session.request") as external:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(request_clip, range(40)))
        for slot, status, location in results:
            self.assertEqual(status, 302)
            self.assertEqual(location, f"https://www.youtube.com/watch?v={main.CLIP_IDS[slot]}")
        external.assert_not_called()

    def test_legacy_random_endpoint_uses_local_catalog_without_network(self):
        selected = main.CLIP_IDS[0]
        with patch("requests.sessions.Session.request") as external, patch("main.random.choice", return_value=selected):
            response = self.client.get("/shorts?v=2&i=0")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"https://www.youtube.com/watch?v={selected}")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        external.assert_not_called()

    def test_empty_catalog_returns_unavailable_without_unrelated_fallback_video(self):
        with patch("main.CLIP_IDS", ()):
            response = self.client.get("/shorts?v=2")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Location", response.headers)

    def test_topics_keep_stable_slots_and_empty_topics_do_not_fall_back_to_all(self):
        document = {"clips": ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"],
                    "clip_topics": {"BBBBBBBBBBB": ["q0", "q1"], "AAAAAAAAAAA": ["q1"]}}
        result = main.build_topic_catalog(document, [Topic("q0", "one", "one"), Topic("q1", "two", "two"), Topic("q2", "empty", "empty")])
        self.assertEqual(result, [{"id": "q0", "name": "one", "clips": [1]},
                                  {"id": "q1", "name": "two", "clips": [0, 1]},
                                  {"id": "q2", "name": "empty", "clips": []}])


if __name__ == "__main__":
    unittest.main()
