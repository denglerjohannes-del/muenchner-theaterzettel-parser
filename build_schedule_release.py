#!/usr/bin/env python3
"""Build a reproducible annual Nationaltheater schedule from theater bills."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re


MONTHS = {"Januar": 1, "Februar": 2, "Jebruar": 2, "März": 3, "Maerz": 3, "April": 4,
          "Mai": 5, "Juni": 6, "Inni": 6, "Juli": 7, "August": 8, "Angust": 8, "Auguft": 8, "Jugust": 8, "September": 9, "FSeptember": 9, "Feptember": 9,
          "Oktober": 10, "November": 11, "Dezember": 12}
WEEKDAYS = {"Montag": 0, "Dienstag": 1, "Mittwoch": 2, "Donnerstag": 3,
            "Freitag": 4, "Samstag": 5, "Samflag": 5, "Saftmag": 5, "Famstag": 5, "Hamstag": 5,
            "Sonntag": 6, "Fonntag": 6, "Fountag": 6, "Fonutag": 6, "Sountag": 6}
SUBSCRIPTION_PREFIX_RE = re.compile(
    r"^\s*(?:\d{1,3}\.?\s*)?Vor\S*\s*im\s+Jah\S*[- ]?Abonnem\S*.*?"
    r"(?:Abtheilung|Abth|A[o6]?th)\.?\s*(?:I{1,3}|1{1,3})\.?\s*"
    r"(?:(?:statt|ftatt|flatt|faft)\s*(?:I{1,3}|1{1,3})\.?\s*)?",
    re.IGNORECASE,
)
TIME_ONLY_RE = re.compile(
    r"^\s*(?:[\d¹½/]+\s*)?[Uu]hr\b(?:\s*,?\s*Ende\s*(?:gegen|nach|um)?\s*"
    r"[\d¹½/\s]+\s*[Uu]hr)?\.?\s*$",
    re.IGNORECASE,
)


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def clean_title(surface: str, aliases: dict[str, str]) -> tuple[str, str]:
    cleaned = surface.replace("ſ", "s")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n.,;/")
    return aliases.get(cleaned, cleaned), cleaned


def strip_formal_title_metadata(surface: str) -> tuple[str, str | None]:
    """Remove only recurring non-work display metadata, preserving its source elsewhere."""
    if TIME_ONLY_RE.fullmatch(surface):
        return "", "TIME_LINE_NOT_WORK_TITLE"
    stripped = SUBSCRIPTION_PREFIX_RE.sub("", surface, count=1).strip()
    if stripped != surface.strip():
        return stripped, "SUBSCRIPTION_PREFIX_NOT_WORK_TITLE"
    return surface, None


def validate_year_contract(candidates: list[dict], pages: list[dict], resolutions: dict, year: int) -> None:
    """Fail closed when independently supplied release inputs disagree on year."""
    candidate_years = {row.get("calendar_year") for row in candidates}
    page_years = {row.get("calendar_year") for row in pages}
    resolution_years = {dt.date.fromisoformat(row["resolved_date"]).year for row in resolutions.values()}
    if candidate_years != {year}:
        raise SystemExit(f"candidate calendar years {sorted(candidate_years, key=str)} do not equal --year {year}")
    if page_years != {year}:
        raise SystemExit(f"page-index calendar years {sorted(page_years, key=str)} do not equal --year {year}")
    if resolution_years and resolution_years != {year}:
        raise SystemExit(f"curated resolution years {sorted(resolution_years)} do not equal --year {year}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=pathlib.Path)
    parser.add_argument("curation", type=pathlib.Path)
    parser.add_argument("page_index", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source-volume", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--source-urn", required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    curation = json.loads(args.curation.read_text(encoding="utf-8"))
    date_overrides = curation["date_resolutions"]
    aliases = curation["title_aliases"]
    ignored_surfaces = curation.get("ignored_title_surfaces", {})
    title_group_overrides = curation.get("title_group_overrides", {})
    cancellations = curation.get("cancelled_dates", {})
    candidates = [json.loads(line) for line in args.candidates.read_text(encoding="utf-8").splitlines()]
    pages = [json.loads(line) for line in args.page_index.read_text(encoding="utf-8").splitlines()]
    validate_year_contract(candidates, pages, date_overrides, args.year)
    page_by_scan = {row["scan_index"]: row for row in pages}

    # A bill rejected by strict automatic indexing (for example because the
    # printed year itself is wrong) can be admitted only through an explicit,
    # image-bound curation record.  The source page provenance remains intact.
    for scan, addition in curation.get("manual_bill_additions", {}).items():
        page = page_by_scan[int(scan)]
        candidates.append({
            "calendar_year": args.year,
            "scan_index": int(scan),
            "printed_label": page["printed_label"],
            "image_id": page["image_id"],
            "canvas_id": page["canvas_id"],
            "ocr_url": page["ocr_url"],
            "hocr_sha256": page["hocr_sha256"],
            "venue_candidate": addition["venue"],
            "date_surface": addition["printed_surface"],
            "weekday_surface": addition["weekday_surface"],
            "day_candidate": addition["day_candidate"],
            "month_candidate": addition["month_candidate"],
            "title_groups": addition["title_groups"],
            "candidate_status": "CURATED_REVIEW_ADDITION",
            "candidate_only": True,
        })

    editions = []
    weekday_errors = []
    alias_applications = []
    ignored_components = []
    formal_metadata_removals = []
    title_group_override_applications = []
    for row in candidates:
        scan_key = str(row["scan_index"])
        if scan_key in date_overrides:
            resolved_date = dt.date.fromisoformat(date_overrides[scan_key]["resolved_date"])
            date_resolution = date_overrides[scan_key]["reason"]
        else:
            resolved_date = dt.date(args.year, MONTHS[row["month_candidate"]], row["day_candidate"])
            date_resolution = "DIRECT_FROM_BILL_HEADER"
            weekday = row["weekday_surface"].capitalize()
            if resolved_date.weekday() != WEEKDAYS[weekday]:
                weekday_errors.append({"scan_index": row["scan_index"], "date_surface": row["date_surface"]})
        override = title_group_overrides.get(scan_key)
        groups = row["title_groups"]
        if override:
            title_group_override_applications.append({
                "schema": "theaterzettel-title-group-override-application/1",
                "scan_index": row["scan_index"],
                "reason": override["reason"],
                "original_title_groups": groups,
                "replacement_title_surfaces": override["title_surfaces"],
            })
            groups = [{"title_surface_candidate": title, "bbox": None, "height_evidence": []}
                      for title in override["title_surfaces"]]
        titles = []
        for component_index, group in enumerate(groups, start=1):
            source_surface = group["title_surface_candidate"]
            title_surface, metadata_reason = strip_formal_title_metadata(source_surface)
            if metadata_reason:
                formal_metadata_removals.append({
                    "schema": "theaterzettel-formal-title-metadata-removal/1",
                    "scan_index": row["scan_index"],
                    "source_surface": source_surface,
                    "remaining_title_surface": title_surface,
                    "reason": metadata_reason,
                    "bbox": group["bbox"],
                    "height_evidence": group["height_evidence"],
                })
            if not title_surface:
                continue
            canonical, cleaned = clean_title(title_surface, aliases)
            if cleaned in ignored_surfaces:
                ignored = {
                    "schema": "theaterzettel-ignored-title-component/1",
                    "scan_index": row["scan_index"],
                    "source_surface": group["title_surface_candidate"],
                    "cleaned_surface": cleaned,
                    "reason": ignored_surfaces[cleaned],
                    "bbox": group["bbox"],
                    "height_evidence": group["height_evidence"],
                }
                ignored_components.append(ignored)
                continue
            if canonical != cleaned:
                alias_applications.append({
                    "scan_index": row["scan_index"], "source_surface": source_surface,
                    "cleaned_surface": cleaned, "canonical_title": canonical,
                })
            titles.append({
                "component_index": component_index,
                "source_surface": source_surface,
                "cleaned_surface": cleaned,
                "canonical_title": canonical,
                "bbox": group["bbox"],
                "height_evidence": group["height_evidence"],
            })
        editions.append({
            "schema": "theaterzettel-bill-edition/1",
            "calendar_year": args.year,
            "date": resolved_date.isoformat(),
            "date_surface": row["date_surface"],
            "date_resolution": date_resolution,
            "venue": row["venue_candidate"],
            "scan_index": row["scan_index"],
            "printed_label": row["printed_label"],
            "image_id": row["image_id"],
            "canvas_id": row["canvas_id"],
            "ocr_url": row["ocr_url"],
            "hocr_sha256": row["hocr_sha256"],
            "titles": titles,
            "evidence_state": "SCHEDULE_HIGH_CONFIDENCE_THEATER_BILL",
            "performed_confirmation_gate_required": False,
            "orchestra_service_inferred": False,
        })

    grouped = collections.defaultdict(list)
    for row in editions:
        grouped[(row["venue"], row["date"])].append(row)
    superseded = []
    cancelled_editions = []
    final_editions = []
    residenz_preserved = []
    for key, group in grouped.items():
        group.sort(key=lambda row: row["scan_index"])
        if key[0] != "NATIONALTHEATER":
            for row in group:
                row["edition_status"] = "PRESERVED_RESIDENZ_NOT_INTEGRATED"
                residenz_preserved.append(row)
            continue
        final = group[-1]
        final["earlier_scan_indices"] = [row["scan_index"] for row in group[:-1]]
        cancellation = cancellations.get(key[1])
        if cancellation:
            notice_page = page_by_scan[cancellation["notice_scan_index"]]
            final["edition_status"] = "CANCELLED_BY_EXPLICIT_NOTICE"
            final["cancellation_notice"] = {
                **cancellation,
                "notice_image_id": notice_page["image_id"],
                "notice_ocr_url": notice_page["ocr_url"],
                "notice_hocr_sha256": notice_page["hocr_sha256"],
            }
            cancelled_editions.append(final)
        else:
            final["edition_status"] = "FINAL_BILL_EDITION"
            final_editions.append(final)
        final_titles = [title["canonical_title"] for title in final["titles"]]
        for row in group[:-1]:
            row["edition_status"] = "SUPERSEDED_BY_LATER_BILL_EDITION"
            row["superseded_by_scan_index"] = final["scan_index"]
            row["programme_changed"] = [title["canonical_title"] for title in row["titles"]] != final_titles
            superseded.append(row)

    final_editions.sort(key=lambda row: (row["date"], row["venue"], row["scan_index"]))
    residenz_preserved.sort(key=lambda row: (row["date"], row["scan_index"]))
    editions.sort(key=lambda row: row["scan_index"])
    superseded.sort(key=lambda row: row["scan_index"])
    national = final_editions

    # Preserve every explicit cancellation/closure notice as its own source-
    # bound record.  Some notices occur in a previous day's footer and thus
    # have no bill edition on the closed date itself.
    cancellation_notices = []
    for date_iso, cancellation in sorted(cancellations.items()):
        notice_page = page_by_scan[cancellation["notice_scan_index"]]
        cancellation_notices.append({
            "schema": "theaterzettel-cancellation-or-closure-notice/1",
            "calendar_year": args.year,
            "date": date_iso,
            **cancellation,
            "notice_printed_label": notice_page["printed_label"],
            "notice_image_id": notice_page["image_id"],
            "notice_canvas_id": notice_page["canvas_id"],
            "notice_ocr_url": notice_page["ocr_url"],
            "notice_hocr_sha256": notice_page["hocr_sha256"],
            "nationaltheater_bill_existed_for_date": any(
                row["venue"] == "NATIONALTHEATER" and row["date"] == date_iso
                for row in editions
            ),
            "schedule_entry_excluded": True,
        })
    schedule = []
    occurrences = []
    for event_index, row in enumerate(national, start=1):
        event_id = f"NT-{args.year}-{event_index:03d}"
        schedule_row = {**row, "schema": "nationaltheater-schedule-entry/1", "event_id": event_id}
        schedule.append(schedule_row)
        for title in row["titles"]:
            occurrences.append({
                "schema": "nationaltheater-title-occurrence/1",
                "event_id": event_id,
                "date": row["date"],
                "scan_index": row["scan_index"],
                **title,
            })

    by_date = {row["date"]: row for row in schedule}
    ledger = []
    day = dt.date(args.year, 1, 1)
    while day.year == args.year:
        event = by_date.get(day.isoformat())
        date_iso = day.isoformat()
        ledger.append({
            "schema": "nationaltheater-day-ledger/1",
            "date": date_iso,
            "state": ("SCHEDULE_HIGH_CONFIDENCE" if event else
                      "KNOWN_CANCELLATION_OR_CLOSURE" if date_iso in cancellations else
                      "NO_NATIONALTHEATER_BILL_IN_VOLUME"),
            "event_id": event["event_id"] if event else None,
            "source_mode": "DAILY_THEATER_BILL_VOLUME",
        })
        day += dt.timedelta(days=1)

    frequencies = collections.Counter(row["canonical_title"] for row in occurrences)
    with (args.output_dir / f"NATIONALTHEATER_{args.year}_TITLE_FREQUENCY.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["canonical_title", "occurrences"])
        for title, count in sorted(frequencies.items(), key=lambda item: (-item[1], item[0])):
            writer.writerow([title, count])

    write_jsonl(args.output_dir / "SOURCE_BILL_EDITIONS.jsonl", editions)
    write_jsonl(args.output_dir / "RESIDENZTHEATER_BILL_EDITIONS_PRESERVED.jsonl", residenz_preserved)
    write_jsonl(args.output_dir / "SUPERSEDED_BILL_EDITIONS.jsonl", superseded)
    write_jsonl(args.output_dir / "CANCELLED_BILL_EDITIONS.jsonl", cancelled_editions)
    write_jsonl(args.output_dir / "KNOWN_CANCELLATION_OR_CLOSURE_NOTICES.jsonl", cancellation_notices)
    write_jsonl(args.output_dir / f"NATIONALTHEATER_{args.year}_SCHEDULE_ENTRIES.jsonl", schedule)
    write_jsonl(args.output_dir / f"NATIONALTHEATER_{args.year}_TITLE_OCCURRENCES.jsonl", occurrences)
    write_jsonl(args.output_dir / f"NATIONALTHEATER_{args.year}_DAY_LEDGER.jsonl", ledger)
    write_jsonl(args.output_dir / "TITLE_ALIAS_APPLICATIONS.jsonl", alias_applications)
    write_jsonl(args.output_dir / "IGNORED_TITLE_COMPONENTS.jsonl", ignored_components)
    write_jsonl(args.output_dir / "FORMAL_TITLE_METADATA_REMOVALS.jsonl", formal_metadata_removals)
    write_jsonl(args.output_dir / "TITLE_GROUP_OVERRIDES_APPLIED.jsonl", title_group_override_applications)

    excluded = []
    for scan, reason in curation["excluded_scans"].items():
        page = page_by_scan[int(scan)]
        excluded.append({"scan_index": int(scan), "reason": reason, "printed_label": page["printed_label"],
                         "ocr_url": page["ocr_url"], "hocr_sha256": page["hocr_sha256"]})
    write_jsonl(args.output_dir / "EXCLUDED_AND_ORCHESTRA_BACKLOG.jsonl", excluded)

    qa = {
        "schema": "theaterzettel-release-qa/1",
        "calendar_year": args.year,
        "weekday_errors_after_curation": weekday_errors,
        "all_candidates_have_titles": all(row["titles"] for row in editions),
        "unique_final_national_dates": len({row["date"] for row in national}) == len(national),
        "complete_day_ledger": len(ledger) == (dt.date(args.year + 1, 1, 1) - dt.date(args.year, 1, 1)).days
        and ledger[0]["date"] == f"{args.year}-01-01" and ledger[-1]["date"] == f"{args.year}-12-31",
        "latest_scan_selected_per_nationaltheater_date": all(
            row["scan_index"] == max(item["scan_index"] for item in grouped[(row["venue"], row["date"])])
            for row in final_editions
        ),
        "cancelled_dates_absent_from_schedule": all(date_iso not in by_date for date_iso in cancellations),
        "all_cancellation_notices_source_bound": all(
            row["notice_image_id"] and row["notice_ocr_url"] and row["notice_hocr_sha256"]
            for row in cancellation_notices
        ),
        "performed_confirmation_gate_required": False,
        "orchestra_service_inferred": False,
    }
    summary = {
        "schema": "theaterzettel-schedule-release-summary/1",
        "calendar_year": args.year,
        "source_volume": args.source_volume,
        "source_mode": "DAILY_THEATER_BILL_VOLUME",
        "bill_editions": len(editions),
        "residenztheater_bill_editions_preserved_not_integrated": len(residenz_preserved),
        "nationaltheater_bill_editions": sum(row["venue"] == "NATIONALTHEATER" for row in editions),
        "nationaltheater_schedule_days": len(schedule),
        "nationaltheater_title_occurrences": len(occurrences),
        "nationaltheater_distinct_canonical_titles": len(frequencies),
        "superseded_bill_editions": len(superseded),
        "superseded_with_programme_change": sum(row["programme_changed"] for row in superseded),
        "cancelled_bill_editions": len(cancelled_editions),
        "known_cancellation_or_closure_dates": len(cancellation_notices),
        "date_resolutions": len(date_overrides),
        "title_alias_applications": len(alias_applications),
        "ignored_nonwork_title_components": len(ignored_components),
        "formal_title_metadata_removals": len(formal_metadata_removals),
        "title_group_override_applications": len(title_group_override_applications),
        "day_ledger_rows": len(ledger),
        "excluded_or_backlog_pages": len(excluded),
        "release_state": "SCHEDULE_HIGH_CONFIDENCE_THEATER_BILL",
        "performed_confirmation_gate_required": False,
        "orchestra_service_inferred": False,
    }
    (args.output_dir / "QA_RESULTS.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "PROVENANCE.json").write_text(json.dumps({
        "schema": "theaterzettel-release-provenance/1",
        "calendar_year": args.year,
        "candidates_sha256": digest(args.candidates),
        "curation_sha256": digest(args.curation),
        "page_index_sha256": digest(args.page_index),
        "source_manifest": args.source_manifest,
        "source_urn": args.source_urn,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    required_true = [qa["all_candidates_have_titles"], qa["unique_final_national_dates"],
                     qa["complete_day_ledger"], qa["latest_scan_selected_per_nationaltheater_date"],
                     qa["cancelled_dates_absent_from_schedule"],
                     qa["all_cancellation_notices_source_bound"]]
    if weekday_errors or not all(required_true):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
