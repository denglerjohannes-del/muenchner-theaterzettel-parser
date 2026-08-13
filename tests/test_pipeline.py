import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX = load("index_hocr")
EXTRACT = load("extract_programme_candidates")
BIND = load("bind_scan_labels")


def hocr(lines):
    body = []
    for i, (bbox, surface) in enumerate(lines):
        body.append(f'<span class="ocr_line" id="l{i}" title="bbox {bbox}">{surface}</span>')
    return ("<html><body>" + "".join(body) + "</body></html>").encode()


class PipelineTests(unittest.TestCase):
    def test_manifest_binding_keeps_printed_label_and_scan_id_separate(self):
        payload = {"sequences": [{"canvases": [{
            "label": "17 (0023)",
            "@id": "https://example.test/canvas/23",
            "images": [{"resource": {"@id": "https://example.test/bsb12345678_00023/full/full/0/default.jpg"}}],
            "seeAlso": {"@id": "https://example.test/ocr/23"},
        }]}]}
        row = BIND.bind_manifest(payload)[0]
        self.assertEqual(row["scan_index"], 1)
        self.assertEqual(row["printed_label"], "17 (0023)")
        self.assertEqual(row["image_id"], "bsb12345678_00023")

    def test_bbox_lines_and_national_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "0005.hocr"
            path.write_bytes(hocr([
                ("300 400 1000 550", "Königl. Hof- und"),
                ("1500 400 2300 550", "National-Theater"),
                ("800 780 1700 850", "Montag den 1. Januar 1877."),
                ("650 1050 2100 1400", "Die Folkunger."),
            ]))
            lines = INDEX.parse_lines(path)
            venue, _ = INDEX.classify_venue(lines)
            self.assertEqual(venue, "NATIONALTHEATER")
            self.assertEqual(lines[-1]["height"], 350)

    def test_residenz_ocr_alias_is_narrowly_bound(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "K.Nesidenz-", "bbox": [0, 300, 500, 500]},
            {"surface": "Theater.", "bbox": [600, 300, 1000, 500]},
        ])
        self.assertEqual(venue, "RESIDENZTHEATER")

    def test_residenz_ocr_aliases_from_next_volume(self):
        for surface in ("K.Nendenz-", "K.Neñdenz-", "K.Mesidenz-", "K.Nefidenz-"):
            with self.subTest(surface=surface):
                venue, _ = INDEX.classify_venue([
                    {"surface": surface, "bbox": [0, 300, 500, 500]},
                    {"surface": "Theater.", "bbox": [600, 300, 1000, 500]},
                ])
                self.assertEqual(venue, "RESIDENZTHEATER")

    def test_date_pattern_is_bound_to_explicit_year(self):
        pattern = INDEX.compile_date_re(1878)
        self.assertIsNotNone(pattern.search("Freitag den 4. Januar 1878."))
        self.assertIsNone(pattern.search("Freitag den 4. Januar 1877."))
        self.assertIsNotNone(pattern.search("Freitag den 4. Januar."))
        self.assertIsNotNone(pattern.search("Mittwoch, 28. Auguft."))
        self.assertIsNotNone(pattern.search("Saftmag den 30. November 1878."))

    def test_large_genre_word_can_be_a_display_title(self):
        for surface in ("Die Bauernkomödie.", "Ein Lustspiel."):
            with self.subTest(surface=surface):
                row = {"surface": surface, "bbox": [500, 1100, 2000, 1440], "height": 340}
                self.assertTrue(EXTRACT.is_display_title(row, 900, 0))

    def test_footer_preview_is_outside_title_band(self):
        title = {"surface": "Euryanthe.", "bbox": [800, 1100, 1800, 1450], "height": 350}
        footer = {"surface": "Aus dem Repertoir-Entwurf", "bbox": [200, 3300, 2200, 3350], "height": 50}
        self.assertTrue(EXTRACT.is_display_title(title, 900, 0))
        self.assertFalse(EXTRACT.is_display_title(footer, 900, 0))

    def test_change_notice_is_not_a_title(self):
        notice = {"surface": "Wegen Unpäßlichkeit statt der angezeigten Oper", "bbox": [200, 1050, 2200, 1230], "height": 180}
        self.assertFalse(EXTRACT.is_display_title(notice, 900, 0))

    def test_hierauf_splits_display_groups(self):
        rows = [
            {"surface": "Die Dienstboten.", "bbox": [700, 1400, 1900, 1650], "height": 250},
            {"surface": "Die einzige Tochter.", "bbox": [700, 1750, 1900, 2000], "height": 250},
        ]
        markers = [{"surface": "Hierauf:", "bbox": [1000, 1680, 1400, 1730], "height": 50}]
        groups = EXTRACT.group_titles(rows, markers)
        self.assertEqual([row["title_surface_candidate"] for row in groups], ["Die Dienstboten.", "Die einzige Tochter."])


if __name__ == "__main__":
    unittest.main()
