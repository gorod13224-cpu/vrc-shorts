import json
import tempfile
import unittest
from pathlib import Path

from catalog import SLOT_CAPACITY, append_urls, import_file, load_registry, video_id_from_url, write_registry


class CatalogImportTests(unittest.TestCase):
    def test_supported_youtube_links_resolve_to_one_id(self):
        links = [
            "https://www.youtube.com/watch?v=Abc_def-123&t=5",
            "https://youtube.com/shorts/Abc_def-123",
            "https://m.youtube.com/shorts/Abc_def-123?feature=share",
            "https://youtu.be/Abc_def-123?si=ignored",
        ]
        self.assertEqual({video_id_from_url(value) for value in links}, {"Abc_def-123"})

    def test_untrusted_or_ambiguous_links_are_rejected(self):
        links = [
            "http://www.youtube.com/watch?v=Abc_def-123",
            "https://www.youtube.com.evil.test/watch?v=Abc_def-123",
            "https://evil.test/shorts/Abc_def-123",
            "https://user@youtube.com/watch?v=Abc_def-123",
            "https://@youtube.com/watch?v=Abc_def-123",
            "https://youtube.com:443/watch?v=Abc_def-123",
            "https://youtube.com:0/watch?v=Abc_def-123",
            "https://youtube.com/watch?v=Abc_def-123&v=Abc_def-456",
            "https://youtube.com/shorts/Abc_def-123/extra",
            "https://youtu.be/too-short",
            "https://youtube.com/watch?v=Abc%26def-12",
        ]
        for link in links:
            with self.subTest(link=link), self.assertRaises(ValueError):
                video_id_from_url(link)

    def test_reordering_removal_and_duplicates_never_reassign_slots(self):
        existing = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
        incoming = [
            "https://youtu.be/CCCCCCCCCCC",
            "https://youtu.be/DDDDDDDDDDD",
            "https://youtube.com/shorts/AAAAAAAAAAA",
            "https://youtu.be/DDDDDDDDDDD",
        ]
        result = append_urls(existing, incoming)
        self.assertEqual(result, existing + ["DDDDDDDDDDD"])
        self.assertEqual(existing, ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])

    def test_file_import_is_idempotent_and_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / "clips.json"
            source = Path(folder) / "urls.txt"
            source.write_text("# curated videos\nhttps://youtu.be/AAAAAAAAAAA\n\nhttps://youtu.be/BBBBBBBBBBB\n", encoding="utf-8-sig")
            self.assertEqual(import_file(source, registry), (2, 2))
            original = registry.read_bytes()
            self.assertEqual(import_file(source, registry), (0, 2))
            self.assertEqual(registry.read_bytes(), original)
            self.assertEqual(load_registry(registry), ["AAAAAAAAAAA", "BBBBBBBBBBB"])

    def test_failed_import_does_not_partially_write_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / "clips.json"
            source = Path(folder) / "urls.txt"
            write_registry(registry, ["AAAAAAAAAAA"])
            original = registry.read_bytes()
            source.write_text("https://youtu.be/BBBBBBBBBBB\nhttps://evil.test/not-youtube\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Input line 2"):
                import_file(source, registry)
            self.assertEqual(registry.read_bytes(), original)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_capacity_overflow_does_not_write_registry(self):
        existing = [f"{number:011d}" for number in range(SLOT_CAPACITY)]
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / "clips.json"
            source = Path(folder) / "urls.txt"
            write_registry(registry, existing)
            original = registry.read_bytes()
            source.write_text("https://youtu.be/ZZZZZZZZZZZ\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capacity"):
                import_file(source, registry)
            self.assertEqual(registry.read_bytes(), original)

    def test_invalid_registry_is_rejected_instead_of_shifting_ids(self):
        bad = [
            {"version": 2, "clips": ["AAAAAAAAAAA"]},
            {"version": True, "clips": ["AAAAAAAAAAA"]},
            {"version": 1, "clips": ["AAAAAAAAAAA", "AAAAAAAAAAA"]},
            {"version": 1, "clips": ["invalid"]},
            {"version": 1, "clips": None},
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clips.json"
            for registry in bad:
                with self.subTest(registry=registry):
                    path.write_text(json.dumps(registry), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_registry(path)


if __name__ == "__main__":
    unittest.main()
