import concurrent.futures
import unittest
from unittest.mock import Mock, patch

import main
from catalog import load_registry


class FeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()

    def test_catalog_has_exact_contiguous_slot_count_and_no_cache(self):
        with patch("main.requests.get") as external:
            response = self.client.get("/catalog.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"version": 1, "count": len(load_registry())})
        self.assertGreater(response.get_json()["count"], 0)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        external.assert_not_called()

    def test_stable_slots_redirect_to_registered_video_without_external_lookup(self):
        ids = load_registry()
        with patch("main.requests.get") as external:
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

        with patch("main.requests.get") as external:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(request_clip, range(40)))
        for slot, status, location in results:
            self.assertEqual(status, 302)
            self.assertEqual(location, f"https://www.youtube.com/watch?v={main.CLIP_IDS[slot]}")
        external.assert_not_called()

    def test_legacy_random_endpoint_still_redirects_youtube_search_result(self):
        page = Mock(text='{"videoId":"AAAAAAAAAAA"}{"videoId":"too-short"}')
        with patch("main.requests.get", return_value=page) as search:
            response = self.client.get("/shorts?v=2&i=0")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://www.youtube.com/watch?v=AAAAAAAAAAA")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        search.assert_called_once()

    def test_legacy_endpoint_preserves_existing_fallback(self):
        with patch("main.requests.get", side_effect=main.requests.Timeout):
            response = self.client.get("/shorts?v=2")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
