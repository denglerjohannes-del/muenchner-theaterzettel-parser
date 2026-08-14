#!/usr/bin/env python3
"""Generate one deterministic review queue from indexed theater-bill data."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import pathlib
import re
import unicodedata

from ocr_calendar import MONTHS


LEXICAL_REVIEW = re.compile(
    r"\b(?:Gast|Geburtstag|Namensfe(?:s|f)t|"
    r"zum Besten|Concert|Konzert|bleiben geschlossen|Gesam(?:m|mt)-?Gastspiel|"
    r"Zum \d+\. Male|Zum ersten Male wiederholt)\b",
    re.IGNORECASE,
)
PERSON_REVIEW = re.compile(
    r"\b(?:der\s+)?Frau\s+[A-ZÄÖÜ][\w-]+|\b(?:Herrn?|Fräulein|Frl\.?)\s+[A-ZÄÖÜ][\w-]+"
)
TIME_REVIEW = re.compile(r"\b\d{1,2}\s*Uhr\b", re.IGNORECASE)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def title_surfaces(candidate: dict) -> list[str]:
    return [group["title_surface_candidate"].strip() for group in candidate["title_groups"]]


def contains_non_latin_letters(surface: str) -> bool:
    for character in surface:
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        if "LATIN" not in name:
            return True
    return False


def suspicious_reasons(surface: str) -> list[str]:
    reasons = []
    if len(surface) > 90:
        reasons.append("UNUSUALLY_LONG_DISPLAY_SURFACE")
    if LEXICAL_REVIEW.search(surface) or PERSON_REVIEW.search(surface):
        reasons.append("PERSON_EVENT_OR_OCCASION_LEXEME")
    if TIME_REVIEW.search(surface):
        reasons.append("TIME_EXPRESSION_IN_DISPLAY_SURFACE")
    if contains_non_latin_letters(surface):
        reasons.append("NON_LATIN_OCR_CHARACTERS")
    if surface.count("(") != surface.count(")") or surface.count("[") != surface.count("]"):
        reasons.append("UNBALANCED_BRACKETS")
    return reasons


def resolved_date(candidate: dict, year: int) -> str:
    month = MONTHS.get(candidate["month_candidate"])
    if month is None:
        raise ValueError(
            f"scan {candidate['scan_index']}: unknown month surface "
            f"{candidate['month_candidate']!r}; extend the MONTHS table deliberately"
        )
    return dt.date(year, month, candidate["day_candidate"]).isoformat()


def build_review_rows(pages: list[dict], candidates: list[dict], year: int) -> list[dict]:
    candidate_years = {row.get("calendar_year") for row in candidates}
    page_years = {row.get("calendar_year") for row in pages}
    if candidate_years != {year} or page_years != {year}:
        raise ValueError(f"year contract failed: pages={page_years}, candidates={candidate_years}, requested={year}")

    rows = []
    for page in pages:
        if page["classification"] != "REVIEW_HOLD":
            continue
        rows.append({
            "schema": "theaterzettel-review-queue-item/1",
            "review_class": "STRUCTURAL_REVIEW_HOLD",
            "calendar_year": year,
            "scan_indices": [page["scan_index"]],
            "printed_labels": [page["printed_label"]],
            "venue": page.get("venue_candidate"),
            "date": None,
            "title_surfaces": [],
            "reasons": ["PAGE_INDEX_REVIEW_HOLD"],
            "evidence": page.get("top_evidence", [])[:12],
        })

    by_date = collections.defaultdict(list)
    surface_sources = collections.defaultdict(set)
    for candidate in candidates:
        scan = candidate["scan_index"]
        surfaces = title_surfaces(candidate)
        for surface in surfaces:
            surface_sources[surface].add(scan)
        date_iso = resolved_date(candidate, year)
        by_date[(candidate["venue_candidate"], date_iso)].append(candidate)
        if len(surfaces) > 1:
            rows.append({
                "schema": "theaterzettel-review-queue-item/1",
                "review_class": "MULTI_COMPONENT_PROGRAMME",
                "calendar_year": year,
                "scan_indices": [scan],
                "printed_labels": [candidate["printed_label"]],
                "venue": candidate["venue_candidate"],
                "date": date_iso,
                "title_surfaces": surfaces,
                "reasons": [f"{len(surfaces)}_DISPLAY_TITLE_GROUPS"],
                "evidence": [],
            })
        for surface in surfaces:
            reasons = suspicious_reasons(surface)
            if not reasons:
                continue
            rows.append({
                "schema": "theaterzettel-review-queue-item/1",
                "review_class": "SUSPICIOUS_DISPLAY_SURFACE",
                "calendar_year": year,
                "scan_indices": [scan],
                "printed_labels": [candidate["printed_label"]],
                "venue": candidate["venue_candidate"],
                "date": date_iso,
                "title_surfaces": [surface],
                "reasons": reasons,
                "evidence": [],
            })

    for (venue, date_iso), editions in by_date.items():
        if len(editions) < 2:
            continue
        editions.sort(key=lambda row: row["scan_index"])
        programmes = [title_surfaces(row) for row in editions]
        rows.append({
            "schema": "theaterzettel-review-queue-item/1",
            "review_class": "PARALLEL_BILL_EDITIONS",
            "calendar_year": year,
            "scan_indices": [row["scan_index"] for row in editions],
            "printed_labels": [row["printed_label"] for row in editions],
            "venue": venue,
            "date": date_iso,
            "title_surfaces": programmes,
            "reasons": ["PROGRAMME_CHANGED" if any(programme != programmes[-1] for programme in programmes[:-1])
                        else "SAME_PROGRAMME_REPRINT"],
            "evidence": [],
        })

    rare = sorted(
        ({"title_surface": surface, "scan_indices": sorted(scans)}
         for surface, scans in surface_sources.items() if len(scans) == 1),
        key=lambda row: row["title_surface"],
    )
    if rare:
        rows.append({
            "schema": "theaterzettel-review-queue-item/1",
            "review_class": "RARE_TITLE_SURFACE_INVENTORY",
            "calendar_year": year,
            "scan_indices": sorted({scan for item in rare for scan in item["scan_indices"]}),
            "printed_labels": [],
            "venue": None,
            "date": None,
            "title_surfaces": [item["title_surface"] for item in rare],
            "reasons": ["EXACT_SOURCE_SURFACE_OCCURS_ON_ONE_CANDIDATE_BILL"],
            "evidence": rare,
        })

    rows.sort(key=lambda row: (row["scan_indices"][0], row["review_class"], row["scan_indices"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_index", type=pathlib.Path)
    parser.add_argument("candidates", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pages = read_jsonl(args.page_index)
    candidates = read_jsonl(args.candidates)
    rows = build_review_rows(pages, candidates, args.year)
    (args.output_dir / "REVIEW_QUEUE.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )

    frequency = collections.Counter(
        surface for candidate in candidates for surface in title_surfaces(candidate)
    )
    with (args.output_dir / "TITLE_SURFACE_FREQUENCY.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title_surface", "candidate_occurrences"])
        for surface, count in sorted(frequency.items(), key=lambda item: (-item[1], item[0])):
            writer.writerow([surface, count])

    classes = collections.Counter(row["review_class"] for row in rows)
    summary = {
        "schema": "theaterzettel-review-queue-summary/1",
        "calendar_year": args.year,
        "review_items": len(rows),
        "review_classes": dict(sorted(classes.items())),
        "distinct_scans_in_queue": len({scan for row in rows for scan in row["scan_indices"]}),
        "direct_review_scans_excluding_rare_inventory": len({
            scan for row in rows if row["review_class"] != "RARE_TITLE_SURFACE_INVENTORY"
            for scan in row["scan_indices"]
        }),
        "candidate_bills": len(candidates),
        "decision_automation_applied": False,
        "purpose": "ONE_BOUNDED_HUMAN_REVIEW_PASS_BEFORE_CURATION",
    }
    (args.output_dir / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
