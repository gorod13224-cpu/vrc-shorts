import json
import tempfile
import unittest
from pathlib import Path

from catalog import (SLOT_CAPACITY, append_urls, import_file, load_registry, load_registry_document,
                     video_id_from_url, write_registry, write_registry_document)


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


class RegistryDocumentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.registry = Path(self.folder.name) / "clips.json"
        self.document = {
            "version": 1,
            "clips": ["AAAAAAAAAAA", "BBBBBBBBBBB"],
            "clip_topics": {"AAAAAAAAAAA": ["q0", "q26"], "BBBBBBBBBBB": ["q27"]},
            "extra_metadata": {"description": "Keep future metadata", "flags": [True, None, 3]},
        }
        write_registry_document(self.registry, self.document)

    def test_document_and_legacy_list_apis_both_load_without_metadata_loss(self):
        self.assertEqual(load_registry_document(self.registry), self.document)
        self.assertEqual(load_registry(self.registry), self.document["clips"])
        legacy = Path(self.folder.name) / "legacy.json"
        write_registry_document(legacy, {"version": 1, "clips": ["AAAAAAAAAAA"]})
        self.assertEqual(load_registry_document(legacy), {"version": 1, "clips": ["AAAAAAAAAAA"]})

    def test_list_write_preserves_associations_and_unknown_metadata(self):
        write_registry(self.registry, self.document["clips"] + ["CCCCCCCCCCC"])
        expected = dict(self.document, clips=["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])
        self.assertEqual(load_registry_document(self.registry), expected)
        self.assertEqual(self.document["clips"], ["AAAAAAAAAAA", "BBBBBBBBBBB"])

    def test_import_reordering_duplicates_and_removal_never_change_topics_or_slots(self):
        source = Path(self.folder.name) / "urls.txt"
        source.write_text("https://youtu.be/BBBBBBBBBBB\nhttps://youtu.be/CCCCCCCCCCC\n"
                          "https://youtube.com/shorts/AAAAAAAAAAA\nhttps://youtu.be/CCCCCCCCCCC\n", encoding="utf-8")
        self.assertEqual(import_file(source, self.registry), (1, 3))
        expected = dict(self.document, clips=["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"])
        self.assertEqual(load_registry_document(self.registry), expected)
        after = self.registry.read_bytes()
        # Removing or reordering input only changes the source file, never assigned slots/topics.
        source.write_text("https://youtu.be/CCCCCCCCCCC\nhttps://youtu.be/BBBBBBBBBBB\n"
                          "https://youtu.be/BBBBBBBBBBB\n", encoding="utf-8")
        self.assertEqual(import_file(source, self.registry), (0, 3))
        self.assertEqual(self.registry.read_bytes(), after)

    def test_invalid_topic_documents_are_rejected_before_replacing_any_bytes(self):
        invalid = [
            None, [], {"CCCCCCCCCCC": ["q0"]},
            {"AAAAAAAAAAA": "q0"}, {"AAAAAAAAAAA": None},
            {"AAAAAAAAAAA": ["q0", "q0"]}, {"AAAAAAAAAAA": [0]},
            {"AAAAAAAAAAA": ["q-1"]}, {"AAAAAAAAAAA": ["q01"]},
            {"AAAAAAAAAAA": ["q1\n"]}, {"AAAAAAAAAAA": ["topic0"]},
        ]
        original = self.registry.read_bytes()
        for associations in invalid:
            with self.subTest(associations=associations), self.assertRaises(ValueError):
                write_registry_document(self.registry, dict(self.document, clip_topics=associations))
            self.assertEqual(self.registry.read_bytes(), original)
            self.assertEqual(list(Path(self.folder.name).glob("*.tmp")), [])

    def test_existing_invalid_metadata_is_rejected_by_both_load_apis_and_import(self):
        broken = dict(self.document, clip_topics={"AAAAAAAAAAA": ["q0", "q0"]})
        self.registry.write_text(json.dumps(broken), encoding="utf-8")
        source = Path(self.folder.name) / "urls.txt"
        source.write_text("https://youtu.be/CCCCCCCCCCC\n", encoding="utf-8")
        original = self.registry.read_bytes()
        for action in (load_registry_document, load_registry):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                action(self.registry)
        with self.assertRaises(ValueError):
            import_file(source, self.registry)
        self.assertEqual(self.registry.read_bytes(), original)

    def test_list_write_cannot_orphan_existing_topic_associations(self):
        original = self.registry.read_bytes()
        with self.assertRaisesRegex(ValueError, "unregistered video ID"):
            write_registry(self.registry, ["AAAAAAAAAAA"])
        self.assertEqual(self.registry.read_bytes(), original)

    def test_empty_associations_and_future_canonical_topic_ids_are_valid(self):
        document = dict(self.document, clip_topics={"AAAAAAAAAAA": [], "BBBBBBBBBBB": ["q27", "q8192"]})
        write_registry_document(self.registry, document)
        self.assertEqual(load_registry_document(self.registry), document)


if __name__ == "__main__":
    unittest.main()
