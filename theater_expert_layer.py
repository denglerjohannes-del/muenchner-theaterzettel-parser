#!/usr/bin/env python3
"""Compile and query the reusable theatre glossary / work-authority layer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9äöüß]+", value))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category(value: str | None) -> str | None:
    if not value: return None
    raw = value.strip(); normalized = key(raw)
    direct = {
        "opera": "Oper", "oper": "Oper", "schauspiel": "Schauspiel",
        "ballet": "Ballett/Tanz", "ballett tanz": "Ballett/Tanz",
        "concert": "Konzert", "konzert": "Konzert", "mixed": "Gemischtes Programm",
        "gemischtes programm": "Gemischtes Programm", "curiosity": "Kuriositätenschau",
        "fest sonderveranstaltung": "Fest-/Sonderveranstaltung", "prolog": "Fest-/Sonderveranstaltung",
        "lustspiel": "Lustspiel", "trauerspiel": "Trauerspiel", "tragedy": "Tragödie",
        "posse": "Posse", "zauberposse": "Zauberposse", "schwank": "Schwank",
        "drama": "Drama", "charakterbild": "Charakterbild", "volksstück": "Volksstück",
        "vaudeville": "Vaudeville", "melodram": "Melodram", "zauberspiel": "Zauberspiel",
        "liederspiel": "Liederspiel", "pantomime": "Pantomime",
    }
    if normalized in {"unknown", "noch nicht bestimmt", "nicht näher bezeichnet", "unspecified", "other", "sonstiges"}: return None
    if normalized in direct: return direct[normalized]
    if "mundart" in normalized or "scene" in normalized: return "Schauspiel mit Musik"
    return raw


def semantic_category(event: dict, work: dict, fallback: str | None) -> str | None:
    """Resolve historically explicit event forms before generic authority lookup."""
    title = work.get("titleHistoricalDisplay") or work.get("titleHistorical") or work.get("titleCanonical") or ""
    context = " ".join(str(event.get(field) or "") for field in (
        "sourceProgramHistorical", "participantTextHistorical", "eventHeadingHistorical", "notes"
    ))
    probe = key(f"{title} {context}")
    title_key = key(title)
    if re.fullmatch(r"(?:der )?masken ball", title_key) or title_key == "jugend ball": return "Ball/Redoute"
    if "typ pantomime" in probe or "pantomime" in probe: return "Pantomime"
    if "prolog" in probe and ("fee des blumenreiches" in title_key or fallback is None): return "Fest-/Sonderveranstaltung"
    return fallback


def compile_layer(
    title_authority: Path,
    work_authority: Path,
    early_registers: list[Path],
    display_authority: Path | None = None,
    supplemental_authority: Path | None = None,
) -> dict:
    title_data = json.loads(title_authority.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    for mapping in title_data.get("bestaetigteMappings", []):
        modern = mapping["moderneForm"]
        aliases[key(modern)] = modern
        for variant in mapping.get("historischeVarianten", []): aliases[key(variant)] = modern

    works: dict[str, list[dict]] = {}
    with work_authority.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            record = {
                "canonical": aliases.get(key(item.get("titel", "")), item.get("titel")),
                "category": category(item.get("gattung")),
                "creator": item.get("komponist_autor") or None,
                "source": "werkautoritaet_final_1851_1869",
            }
            for variant in sorted({item.get("titel", ""), *item.get("varianten", [])}, key=key):
                variant_key = key(variant)
                if variant_key and record not in works.setdefault(variant_key, []): works[variant_key].append(record)

    supplemental_provenance = None
    supplemental_data: dict[str, dict] = {}
    if supplemental_authority:
        supplemental_data = json.loads(supplemental_authority.read_text(encoding="utf-8"))
        for authority_key, item in sorted(supplemental_data.items(), key=lambda pair: key(pair[0])):
            category_prefix, separator, title = authority_key.partition("|")
            if not separator:
                title = authority_key
            supplemental_category = category(item.get("category") or (category_prefix if separator else None))
            record = {
                "canonical": aliases.get(key(title), title),
                "category": supplemental_category,
                "creator": item.get("creator") or None,
                "source": supplemental_authority.name,
            }
            bucket = works.setdefault(key(title), [])
            existing = next((candidate for candidate in bucket if candidate.get("canonical") == record["canonical"] and candidate.get("category") == record["category"]), None)
            if existing:
                if not existing.get("creator") and record.get("creator"): existing["creator"] = record["creator"]
            else:
                bucket.append(record)
        supplemental_provenance = {"file": supplemental_authority.name, "sha256": sha256(supplemental_authority)}

    date_works: dict[str, list[dict]] = {}
    for path in early_registers:
        data = json.loads(path.read_text(encoding="utf-8"))
        for event in data.get("events", []):
            date = event.get("date")
            if not date: continue
            rows = []
            for work in event.get("canonicalWorks", []):
                historical = work.get("titleHistoricalDisplay") or work.get("titleHistorical") or work.get("titleCanonical")
                canonical = work.get("titleCanonical") or historical
                rows.append({
                    "historical": historical,
                    "canonical": aliases.get(key(canonical), canonical),
                    "category": semantic_category(event, work, category(work.get("eventCategory") or work.get("workTypeSource"))),
                    "creator": work.get("composerCanonical") or work.get("authorCanonical") or work.get("composerHistorical") or None,
                    "source": path.name,
                })
            if rows: date_works[date] = rows

    contextual_aliases: dict[str, dict] = {}
    dated_contextual_aliases: dict[str, list[dict]] = {}
    dated_overrides: dict[str, list[dict]] = {}
    nonwork_metadata_patterns: list[str] = []
    historical_surface_corrections: dict[str, str] = {}
    display_provenance = None
    if display_authority:
        display_data = json.loads(display_authority.read_text(encoding="utf-8"))
        for mapping in display_data.get("contextualTitleMappings", []):
            record = {
                "modern": mapping["modern"],
                "historicalPreferred": mapping.get("historicalPreferred"),
                "creator": mapping.get("creator"),
                "source": display_authority.name,
            }
            if mapping.get("authorityUrl"): record["authorityUrl"] = mapping["authorityUrl"]
            if mapping.get("notBefore"): record["notBefore"] = mapping["notBefore"]
            if mapping.get("notAfter"): record["notAfter"] = mapping["notAfter"]
            for variant in sorted({mapping["modern"], *mapping.get("variants", [])}, key=key):
                alias_key = f'{mapping["category"]}|{key(variant)}'
                if mapping.get("notBefore") or mapping.get("notAfter"):
                    dated_contextual_aliases.setdefault(alias_key, []).append(record)
                else:
                    contextual_aliases[alias_key] = record
        dated_overrides = display_data.get("datedWorkOverrides", {})
        nonwork_metadata_patterns = display_data.get("nonWorkMetadataPatterns", [])
        historical_surface_corrections = display_data.get("historicalSurfaceCorrections", {})
        display_provenance = {"file": display_authority.name, "sha256": sha256(display_authority)}

    provenance = {
        "titleAuthority": {"file": title_authority.name, "sha256": sha256(title_authority)},
        "workAuthority": {"file": work_authority.name, "sha256": sha256(work_authority)},
        "earlyRegisters": [{"file": p.name, "sha256": sha256(p)} for p in early_registers],
    }
    if display_provenance: provenance["frontDisplayAuthority"] = display_provenance
    if supplemental_provenance: provenance["supplementalWorkAuthority"] = supplemental_provenance

    return {
        "schema": "muenchner-theater-expert-layer/3",
        "policy": "Original-language canonical opera title in front; historical Munich title below; exact printed surface backstage; unresolved OCR fragments withheld.",
        "modernAliases": aliases,
        "contextualAliases": contextual_aliases,
        "datedContextualAliases": dated_contextual_aliases,
        "works": works,
        "dateWorks": date_works,
        "datedWorkOverrides": dated_overrides,
        "nonWorkMetadataPatterns": nonwork_metadata_patterns,
        "historicalSurfaceCorrections": historical_surface_corrections,
        "supplementalAuthorities": supplemental_data,
        "provenance": provenance,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title-authority", required=True, type=Path)
    parser.add_argument("--work-authority", required=True, type=Path)
    parser.add_argument("--display-authority", type=Path)
    parser.add_argument("--supplemental-authority", type=Path)
    parser.add_argument("--early-register", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    layer = compile_layer(args.title_authority, args.work_authority, args.early_register, args.display_authority, args.supplemental_authority)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(layer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"aliases": len(layer["modernAliases"]), "contextualAliases": len(layer["contextualAliases"]), "workVariants": len(layer["works"]), "datedEvents": len(layer["dateWorks"]), "datedOverrides": len(layer["datedWorkOverrides"])}, ensure_ascii=False))


if __name__ == "__main__": main()
