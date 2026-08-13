#!/usr/bin/env python3
"""Turn BSB hOCR pages into a compact, source-bound theater-bill page index."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from lxml import html


BBOX_RE = re.compile(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
MONTH_RE = re.compile(
    r"\b(?:Januar|Februar|Jebruar|März|Maerz|April|Mai|Juni|Juli|August|Auguft|Jugust|"
    r"September|Oktober|November|Dezember)\b", re.I
)
WEEKDAY_PATTERN = (
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Samflag|Saftmag|Famstag|Hamstag|"
    r"Sonntag|Fonntag|Fountag|Sountag"
)
WEEKDAY_ONLY_RE = re.compile(rf"^\s*(?:{WEEKDAY_PATTERN})\s*$", re.I)


def compile_date_re(year: int) -> re.Pattern:
    """Build the bill-header date pattern for one explicitly selected year."""
    return re.compile(
        r"^\s*(?:M[üu]nchen[,.]?\s+)?[|—–-]*\s*"
        rf"\b({WEEKDAY_PATTERN})\b"
        r".*?\b(?:den\s+)?(\d{1,2})\.{0,2}\s+"
        r"(Januar|Februar|Jebruar|März|Maerz|April|Mai|Juni|Juli|August|Auguft|Jugust|September|Oktober|November|Dezember)"
        rf"(?:\s+{year}\b|(?!\s+\d{{4}}\b))", re.I
    )


def clean_text(node) -> str:
    return " ".join("".join(node.itertext()).split())


def parse_lines(path: pathlib.Path) -> list[dict]:
    data = path.read_bytes()
    doc = html.fromstring(data)
    result = []
    for pos, node in enumerate(doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' ocr_line ')]")):
        text = clean_text(node)
        match = BBOX_RE.search(node.get("title", ""))
        if not text or not match:
            continue
        bbox = [int(value) for value in match.groups()]
        result.append({
            "line_order": pos,
            "bbox": bbox,
            "height": bbox[3] - bbox[1],
            "surface": text,
        })
    return result


def classify_venue(lines: list[dict]) -> tuple[str | None, list[str]]:
    # Large-format guest-performance bills can place the venue band below
    # y=1000 while the current date still begins above y=1600.  Keep both
    # header classifiers on the same bounded top-of-page coordinate contract.
    possible_date_y = [row["bbox"][1] for row in lines
                       if row["bbox"][1] < 1600 and MONTH_RE.search(row["surface"])
                       and re.search(r"\d{1,2}", row["surface"])]
    header_limit = min(1600, min(possible_date_y) + 250) if possible_date_y else 1600
    top = [row["surface"] for row in lines if row["bbox"][1] < header_limit]
    joined = " ".join(top)
    evidence = []
    if re.search(r"Rückblick\s+auf\s+die\s+Repertoire.*Bühnen", joined, re.I):
        return None, top
    has_theater = bool(re.search(r"\bThea(?:ter|r)\b", joined, re.I))
    if has_theater and re.search(r"\b(?:National|lational)\b", joined, re.I):
        evidence.append("NATIONALTHEATER")
    # The official OCR regularly reads the initial R as N/K/V and separates
    # the printed line break around the hyphen.  The distinctive compound and
    # the following 'Theater' remain required, so this stays narrowly bound.
    if has_theater and re.search(r"\b(?:Residenz|[RNKM][a-zäöüßñſ]{0,8}denz)\b", joined, re.I):
        evidence.append("RESIDENZTHEATER")
    if len(evidence) == 1:
        return evidence[0], top
    return None, top


def find_date_hits(lines: list[dict], date_re: re.Pattern) -> list[dict]:
    """Find one-line dates plus the recurring split weekday/date header."""
    top = sorted((row for row in lines if row["bbox"][1] <= 1600), key=lambda row: (row["bbox"][1], row["bbox"][0]))
    hits = []
    for row in top:
        match = date_re.search(row["surface"])
        if match:
            hits.append({"weekday_surface": match.group(1), "day": int(match.group(2)),
                         "month": match.group(3), **row})
    if hits:
        return hits
    for first, second in zip(top, top[1:]):
        if not WEEKDAY_ONLY_RE.match(first["surface"]):
            continue
        if second["bbox"][1] - first["bbox"][3] > 120 or not re.match(r"^\s*den\b", second["surface"], re.I):
            continue
        combined = f"{first['surface']} {second['surface']}"
        match = date_re.search(combined)
        if match:
            bbox = [min(first["bbox"][0], second["bbox"][0]), first["bbox"][1],
                    max(first["bbox"][2], second["bbox"][2]), second["bbox"][3]]
            hits.append({"weekday_surface": match.group(1), "day": int(match.group(2)),
                         "month": match.group(3), "line_order": first["line_order"], "bbox": bbox,
                         "height": bbox[3] - bbox[1], "surface": combined})
    return hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hocr_dir", type=pathlib.Path)
    parser.add_argument("binding", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    parser.add_argument("--year", type=int, required=True, help="calendar year printed by this bound volume")
    args = parser.parse_args()
    if not 1000 <= args.year <= 2999:
        parser.error("--year must be a four-digit calendar year")
    date_re = compile_date_re(args.year)

    bindings = {
        row["scan_index"]: row
        for row in (json.loads(line) for line in args.binding.read_text(encoding="utf-8").splitlines())
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    physical_lines = []
    for path in sorted(args.hocr_dir.glob("*.hocr")):
        scan_index = int(path.stem)
        lines = parse_lines(path)
        binding = bindings[scan_index]
        venue, top_evidence = classify_venue(lines)
        date_hits = find_date_hits(lines, date_re)
        content_lines = [row for row in lines if len(row["surface"]) > 1]
        page = {
            "schema": "theaterzettel-page-index/1",
            "calendar_year": args.year,
            "scan_index": scan_index,
            "printed_label": binding.get("printed_label"),
            "image_id": binding.get("image_id"),
            "canvas_id": binding.get("canvas_id"),
            "ocr_url": binding.get("ocr_url"),
            "hocr_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "hocr_bytes": path.stat().st_size,
            "physical_line_count": len(lines),
            "content_line_count": len(content_lines),
            "venue_candidate": venue,
            "date_candidates_above_y1600": date_hits,
            "top_evidence": top_evidence,
            "classification": (
                "PRIMARY_BILL_CANDIDATE" if venue and len(date_hits) == 1 else
                "REVIEW_HOLD" if venue or date_hits else
                "NON_BILL_OR_BLANK"
            ),
        }
        pages.append(page)
        for row in lines:
            physical_lines.append({
                "schema": "theaterzettel-hocr-physical-line/1",
                "scan_index": scan_index,
                "image_id": binding.get("image_id"),
                "hocr_sha256": page["hocr_sha256"],
                **row,
            })

    (args.output_dir / "PAGE_INDEX.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in pages), encoding="utf-8"
    )
    (args.output_dir / "PHYSICAL_LINES.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in physical_lines), encoding="utf-8"
    )
    classes = sorted({row["classification"] for row in pages})
    venues = sorted({row["venue_candidate"] for row in pages if row["venue_candidate"]})
    summary = {
        "schema": "theaterzettel-page-index-summary/1",
        "calendar_year": args.year,
        "scans": len(pages),
        "physical_lines": len(physical_lines),
        "classifications": {key: sum(row["classification"] == key for row in pages) for key in classes},
        "venues": {key: sum(row["venue_candidate"] == key for row in pages) for key in venues},
        "primary_candidates_by_venue": {
            key: sum(row["classification"] == "PRIMARY_BILL_CANDIDATE" and row["venue_candidate"] == key for row in pages)
            for key in venues
        },
        "pages_with_multiple_top_date_candidates": sum(len(row["date_candidates_above_y1600"]) > 1 for row in pages),
    }
    (args.output_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
