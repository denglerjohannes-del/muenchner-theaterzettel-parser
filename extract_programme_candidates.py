#!/usr/bin/env python3
"""Extract source-bound programme-title candidates from indexed theater bills.

This intentionally stops at candidates.  Large display lines carry programme
titles reliably in this volume; change notices and footer previews are kept out
by layout and lexical anchors.  Consecutive display lines are grouped into one
title surface (for example 'Ein toller Tag / Figaros Hochzeit').
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re


BLOCK_RE = re.compile(
    r"(?:Vorstellung|Abonnement|Wegen\b|statt\b|angezeig|angekündig|"
    r"^Anfang\b|^Ende\b|Personen\b|Per.onen\b|Scene gesetzt|Scene gesezt|"
    r"Preise\b|Kasse\b|Eintritt\b|Repertoir|Repertoire|Unpäßlich|"
    r"Unpählich|beurlaubt|Gastspiel|Gaftspiel|\bAnla.|Majestät|Majeftät|"
    r"Hofschauspielers|Anzeiger|für heute|Zur Feier|Königl\.|National-Theater|Residenz|München|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)", re.I
)
GENRE_RE = re.compile(
    r"(?:Oper|Lustspiel|Trauerspiel|Schauspiel|Posse|Ballet|Ballett|"
    r"Vaudeville|Volksstück|Festspiel|Melodram|Schwank|dramatisch|"
    r"Sing.?spiel|Komödie|Tragödie|Dichtung|Gedicht)\b", re.I
)
PUNCT_ONLY_RE = re.compile(r"^[\W_\d]+$", re.UNICODE)


def is_display_title(row: dict, date_bottom: int, change_notice_bottom: int) -> bool:
    surface = row["surface"].strip()
    top = row["bbox"][1]
    if not (max(date_bottom, change_notice_bottom) < top < 3100 and row["height"] >= 140):
        return False
    if len(surface) < 3 or PUNCT_ONLY_RE.match(surface):
        return False
    if BLOCK_RE.search(surface) or GENRE_RE.search(surface):
        return False
    return True


def group_titles(rows: list[dict], break_markers: list[dict]) -> list[dict]:
    rows = sorted(rows, key=lambda row: (row["bbox"][1], row["bbox"][0]))
    groups = []
    for row in rows:
        marker_between = bool(groups) and any(
            groups[-1]["bbox"][1] < marker["bbox"][1] <= row["bbox"][1] + 10
            for marker in break_markers
        )
        if groups and not marker_between and row["bbox"][1] - groups[-1]["bbox"][3] <= 150:
            group = groups[-1]
            group["lines"].append(row["surface"])
            group["bbox"][0] = min(group["bbox"][0], row["bbox"][0])
            group["bbox"][2] = max(group["bbox"][2], row["bbox"][2])
            group["bbox"][3] = max(group["bbox"][3], row["bbox"][3])
            group["height_evidence"].append(row["height"])
        else:
            groups.append({
                "lines": [row["surface"]],
                "bbox": list(row["bbox"]),
                "height_evidence": [row["height"]],
            })
    for group in groups:
        group["title_surface_candidate"] = " ".join(group.pop("lines"))
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_index", type=pathlib.Path)
    parser.add_argument("physical_lines", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pages = [json.loads(line) for line in args.page_index.read_text(encoding="utf-8").splitlines()]
    by_scan = collections.defaultdict(list)
    for line in args.physical_lines.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by_scan[row["scan_index"]].append(row)

    bills = []
    for page in pages:
        if page["classification"] != "PRIMARY_BILL_CANDIDATE":
            continue
        date = page["date_candidates_above_y1600"][0]
        page_lines = sorted(by_scan[page["scan_index"]], key=lambda row: (row["bbox"][1], row["bbox"][0]))
        preliminary_title_tops = [
            row["bbox"][1] for row in page_lines
            if row["bbox"][1] > date["bbox"][3]
            and row["height"] >= 190
            and not BLOCK_RE.search(row["surface"])
            and not GENRE_RE.search(row["surface"])
            and not PUNCT_ONLY_RE.match(row["surface"].strip())
        ]
        preliminary_title_top = min(preliminary_title_tops, default=3100)
        change_notice_bottom = 0
        in_change_notice = False
        change_notice_lines = 0
        for row in page_lines:
            if row["bbox"][1] <= date["bbox"][3]:
                continue
            if row["bbox"][1] < preliminary_title_top and re.search(r"\bWegen\b", row["surface"], re.I):
                in_change_notice = True
            if in_change_notice:
                if change_notice_lines and row["height"] >= 190 and not re.search(r"[„”\"]", row["surface"]):
                    change_notice_bottom = min(change_notice_bottom, row["bbox"][1] - 1)
                    break
                change_notice_bottom = max(change_notice_bottom, row["bbox"][3])
                change_notice_lines += 1
                if ":" in row["surface"] or re.search(r"[”\"]\s*:?\s*$", row["surface"]):
                    change_notice_bottom = min(change_notice_bottom, preliminary_title_top - 1)
                    break
                if change_notice_lines >= 5:
                    break
        display_rows = [
            row for row in page_lines
            if is_display_title(row, date["bbox"][3], change_notice_bottom)
        ]
        break_markers = [
            row for row in page_lines
            if date["bbox"][3] < row["bbox"][1] < 3100
            and re.search(r"(?:^|\b)(?:Hierauf|Zum Schlusse|Sodann)\b", row["surface"], re.I)
        ]
        title_groups = group_titles(display_rows, break_markers)
        bills.append({
            "schema": "theaterzettel-programme-candidate/1",
            "scan_index": page["scan_index"],
            "printed_label": page["printed_label"],
            "image_id": page["image_id"],
            "canvas_id": page["canvas_id"],
            "ocr_url": page["ocr_url"],
            "hocr_sha256": page["hocr_sha256"],
            "venue_candidate": page["venue_candidate"],
            "date_surface": date["surface"],
            "weekday_surface": date["weekday_surface"],
            "day_candidate": date["day"],
            "month_candidate": date["month"],
            "title_groups": title_groups,
            "candidate_status": "EXTRACTED" if title_groups else "NO_DISPLAY_TITLE_HOLD",
            "candidate_only": True,
        })

    (args.output_dir / "PROGRAMME_CANDIDATES.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in bills), encoding="utf-8"
    )
    holds = [row for row in bills if row["candidate_status"] != "EXTRACTED"]
    counts = collections.Counter(len(row["title_groups"]) for row in bills)
    summary = {
        "schema": "theaterzettel-programme-candidate-summary/1",
        "bills": len(bills),
        "nationaltheater_bills": sum(row["venue_candidate"] == "NATIONALTHEATER" for row in bills),
        "residenztheater_bills": sum(row["venue_candidate"] == "RESIDENZTHEATER" for row in bills),
        "title_groups": sum(len(row["title_groups"]) for row in bills),
        "title_groups_per_bill": {str(key): value for key, value in sorted(counts.items())},
        "no_display_title_holds": len(holds),
        "hold_scan_indices": [row["scan_index"] for row in holds],
    }
    (args.output_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
