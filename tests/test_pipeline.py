import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX = load("index_hocr")
EXTRACT = load("extract_programme_candidates")
BIND = load("bind_scan_labels")
RELEASE = load("build_schedule_release")
REVIEW = load("generate_review_queue")
FETCH = load("fetch_hocr")
SOURCE_DATES = load("source_filename_dates")


def hocr(lines):
    body = []
    for i, (bbox, surface) in enumerate(lines):
        body.append(f'<span class="ocr_line" id="l{i}" title="bbox {bbox}">{surface}</span>')
    return ("<html><body>" + "".join(body) + "</body></html>").encode()


class PipelineTests(unittest.TestCase):
    def test_source_filename_date_range_is_not_exact_day(self):
        row = SOURCE_DATES.parse_temporal_prefix("1837.01.12.:29_1.jpg")
        self.assertIsNone(row["date"])
        self.assertEqual(row["date_start"], "1837-01-12")
        self.assertEqual(row["date_end"], "1837-01-29")
        self.assertEqual(row["temporal_precision"], "DATE_RANGE_OR_SERIES")

    def test_source_filename_exact_day_and_partial_month(self):
        exact = SOURCE_DATES.parse_temporal_prefix("1875.08.24.jpg")
        partial = SOURCE_DATES.parse_temporal_prefix("1856.03.00.jpg")
        self.assertEqual(exact["date"], "1875-08-24")
        self.assertEqual(exact["temporal_precision"], "DAY")
        self.assertIsNone(partial["date"])
        self.assertEqual(partial["month"], 3)
        self.assertEqual(partial["temporal_precision"], "MONTH")

    def test_retry_after_numeric_and_exponential_backoff(self):
        self.assertEqual(FETCH.retry_after_seconds("12"), 12.0)
        self.assertIsNone(FETCH.retry_after_seconds("not-a-date"))
        with mock.patch.object(FETCH.random, "uniform", return_value=0.0):
            self.assertEqual(FETCH.retry_delay(3, None, 2.0, 60.0), 8.0)
            self.assertEqual(FETCH.retry_delay(2, "20", 2.0, 60.0), 20.0)
            self.assertEqual(FETCH.retry_delay(9, None, 2.0, 60.0), 60.0)

    def test_rate_limit_reset_accepts_delta_or_epoch(self):
        self.assertEqual(FETCH.rate_limit_reset_seconds("86400"), 86400.0)
        with mock.patch.object(FETCH.time, "time", return_value=1_000_000.0):
            self.assertEqual(FETCH.rate_limit_reset_seconds("1000120"), 120.0)
        self.assertIsNone(FETCH.rate_limit_reset_seconds("unknown"))

    def test_request_pacer_shares_daily_quota_deferral(self):
        pacer = FETCH.RequestPacer(0.0)
        self.assertEqual(pacer.deferred_seconds(), 0.0)
        pacer.defer_for(30.0)
        self.assertGreater(pacer.deferred_seconds(), 29.0)

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
        for surface in ("K.Nendenz-", "K.Neñdenz-", "K.Mesidenz-", "K.Nefidenz-", "K.Vesidenz-"):
            with self.subTest(surface=surface):
                venue, _ = INDEX.classify_venue([
                    {"surface": surface, "bbox": [0, 300, 500, 500]},
                    {"surface": "Theater.", "bbox": [600, 300, 1000, 500]},
                ])
                self.assertEqual(venue, "RESIDENZTHEATER")

    def test_truncated_national_theater_header(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "Königl. Hof- und", "bbox": [0, 300, 500, 500]},
            {"surface": "National-Thear", "bbox": [600, 300, 1000, 500]},
        ])
        self.assertEqual(venue, "NATIONALTHEATER")

    def test_large_format_venue_band_can_begin_below_y1000(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "München.", "bbox": [1400, 200, 2200, 350]},
            {"surface": "K. Hof- und National-Theater.", "bbox": [400, 1196, 3300, 1450]},
        ])
        self.assertEqual(venue, "NATIONALTHEATER")

    def test_role_name_below_date_does_not_create_second_venue(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "National-Theater.", "bbox": [1400, 450, 2200, 600]},
            {"surface": "Sonntag den 28. März 1880.", "bbox": [800, 730, 1600, 810]},
            {"surface": "Ulrich von Rudenz, sein Neffe", "bbox": [200, 1490, 900, 1540]},
        ])
        self.assertEqual(venue, "NATIONALTHEATER")

    def test_repertoire_retrospective_is_not_a_venue_header(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "Rückblick auf die Repertoire grösserer Bühnen", "bbox": [0, 100, 2000, 200]},
            {"surface": "München K. Hof- und National-Theater", "bbox": [0, 500, 2000, 600]},
        ])
        self.assertIsNone(venue)

    def test_date_pattern_is_bound_to_explicit_year(self):
        pattern = INDEX.compile_date_re(1878)
        self.assertIsNotNone(pattern.search("Freitag den 4. Januar 1878."))
        self.assertIsNone(pattern.search("Freitag den 4. Januar 1877."))
        self.assertIsNotNone(pattern.search("Freitag den 4. Januar."))
        self.assertIsNotNone(pattern.search("Mittwoch, 28. Auguft."))
        self.assertIsNotNone(pattern.search("Saftmag den 30. November 1878."))
        self.assertIsNotNone(pattern.search("Fonntag den 28. September 1878."))
        self.assertIsNotNone(pattern.search("Famstag den 27. Dezember 1878."))
        self.assertIsNotNone(pattern.search("Mittwoch den 20.. Oktober 1878."))
        self.assertIsNotNone(pattern.search("München, Freitag den 1. November 1878."))
        self.assertIsNotNone(pattern.search("Mündjen, Sonntag den 19. Februar 1878."))
        self.assertIsNotNone(pattern.search("Müuchen, Dienstag den 1. März 1878."))
        self.assertIsNotNone(pattern.search("München, Mittwoch den 1. Inni 1878."))
        self.assertIsNotNone(pattern.search("München, Fonutag den 28. August 1878."))
        self.assertIsNotNone(pattern.search("München, Freitag den 30. FSeptember 1878."))
        self.assertIsNone(pattern.search("Rückblick vom Montag den 1. bis Sonntag den 7. Januar 1878."))

    def test_date_pattern_accepts_1883_place_and_month_ocr(self):
        pattern = INDEX.compile_date_re(1883)
        self.assertIsNotNone(pattern.search("UMünchen, Dienstag den 7. Angust 1883."))
        self.assertIsNotNone(pattern.search("Blünchen, Dienstag den 25. Feptember 1883."))
        self.assertIsNotNone(pattern.search("Wündjen, Freitag den 24. Jugust 1883."))

    def test_venue_classifier_accepts_votional_ocr(self):
        venue, _ = INDEX.classify_venue([
            {"surface": "K. Hof- & Votional-Theater.", "bbox": [0, 0, 1000, 100]},
            {"surface": "München, Montag den 26. Februar 1883.", "bbox": [0, 120, 1000, 220]},
        ])
        self.assertEqual(venue, "NATIONALTHEATER")

    def test_split_weekday_and_date_header(self):
        pattern = INDEX.compile_date_re(1879)
        hits = INDEX.find_date_hits([
            {"surface": "Montag", "bbox": [1000, 700, 1600, 900], "height": 200, "line_order": 1},
            {"surface": "den 15. Dezember 1879.", "bbox": [400, 920, 2200, 1140], "height": 220, "line_order": 2},
        ], pattern)
        self.assertEqual([(row["day"], row["month"]) for row in hits], [(15, "Dezember")])

    def test_large_genre_word_can_be_a_display_title(self):
        for surface in ("Die Bauernkomödie.", "Ein Lustspiel."):
            with self.subTest(surface=surface):
                row = {"surface": surface, "bbox": [500, 1100, 2000, 1440], "height": 340}
                self.assertTrue(EXTRACT.is_display_title(row, 900, 0))

    def test_release_title_cleaning_preserves_source_but_applies_alias(self):
        canonical, cleaned = RELEASE.clean_title("  Fauft. ", {"Fauft": "Faust"})
        self.assertEqual(cleaned, "Fauft")
        self.assertEqual(canonical, "Faust")

    def test_formal_subscription_prefix_is_removed_but_title_remains(self):
        surface = "48. Vorft.im Jahres-Abonnem.d. Abth. II. ftatt I. Der Freischük."
        title, reason = RELEASE.strip_formal_title_metadata(surface)
        self.assertEqual(title, "Der Freischük.")
        self.assertEqual(reason, "SUBSCRIPTION_PREFIX_NOT_WORK_TITLE")

    def test_time_only_display_line_is_not_a_work_title(self):
        title, reason = RELEASE.strip_formal_title_metadata("7 Uhr, Ende gegen 10 Uhr.")
        self.assertEqual(title, "")
        self.assertEqual(reason, "TIME_LINE_NOT_WORK_TITLE")

    def test_release_year_contract_fails_closed(self):
        with self.assertRaises(SystemExit):
            RELEASE.validate_year_contract(
                [{"calendar_year": 1878}], [{"calendar_year": 1879}], {}, 1878
            )
        RELEASE.validate_year_contract(
            [{"calendar_year": 1878}], [{"calendar_year": 1878}],
            {"1": {"resolved_date": "1878-01-01"}}, 1878
        )

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

    def test_review_queue_unifies_holds_components_suspicious_surfaces_and_editions(self):
        pages = [
            {"calendar_year": 1880, "scan_index": 1, "printed_label": "(0001)",
             "classification": "REVIEW_HOLD", "venue_candidate": None, "top_evidence": ["Concert"]},
            {"calendar_year": 1880, "scan_index": 2, "printed_label": "(0002)",
             "classification": "PRIMARY_BILL_CANDIDATE", "venue_candidate": "NATIONALTHEATER"},
            {"calendar_year": 1880, "scan_index": 3, "printed_label": "(0003)",
             "classification": "PRIMARY_BILL_CANDIDATE", "venue_candidate": "NATIONALTHEATER"},
        ]
        candidates = [
            {"calendar_year": 1880, "scan_index": 2, "printed_label": "(0002)",
             "venue_candidate": "NATIONALTHEATER", "month_candidate": "Januar", "day_candidate": 2,
             "title_groups": [{"title_surface_candidate": "Herr Gast."},
                              {"title_surface_candidate": "Die Braut."}]},
            {"calendar_year": 1880, "scan_index": 3, "printed_label": "(0003)",
             "venue_candidate": "NATIONALTHEATER", "month_candidate": "Januar", "day_candidate": 2,
             "title_groups": [{"title_surface_candidate": "Wilhelm Tell."}]},
        ]
        rows = REVIEW.build_review_rows(pages, candidates, 1880)
        classes = [row["review_class"] for row in rows]
        self.assertEqual(classes.count("STRUCTURAL_REVIEW_HOLD"), 1)
        self.assertEqual(classes.count("MULTI_COMPONENT_PROGRAMME"), 1)
        self.assertEqual(classes.count("SUSPICIOUS_DISPLAY_SURFACE"), 1)
        self.assertEqual(classes.count("PARALLEL_BILL_EDITIONS"), 1)
        self.assertEqual(classes.count("RARE_TITLE_SURFACE_INVENTORY"), 1)
        parallel = next(row for row in rows if row["review_class"] == "PARALLEL_BILL_EDITIONS")
        self.assertEqual(parallel["reasons"], ["PROGRAMME_CHANGED"])
        rare = next(row for row in rows if row["review_class"] == "RARE_TITLE_SURFACE_INVENTORY")
        self.assertIn("Herr Gast.", rare["title_surfaces"])

    def test_review_queue_flags_non_latin_ocr(self):
        self.assertIn("NON_LATIN_OCR_CHARACTERS", REVIEW.suspicious_reasons("રહે શેહ"))


if __name__ == "__main__":
    unittest.main()
