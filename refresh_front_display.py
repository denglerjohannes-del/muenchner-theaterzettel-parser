#!/usr/bin/env python3
"""Refresh only the front-display portion of an existing compiled expert layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from theater_expert_layer import key, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", required=True, type=Path)
    parser.add_argument("--display-authority", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    layer = json.loads(args.layer.read_text(encoding="utf-8"))
    display = json.loads(args.display_authority.read_text(encoding="utf-8"))
    contextual: dict[str, dict] = {}
    dated: dict[str, list[dict]] = {}
    for mapping in display.get("contextualTitleMappings", []):
        record = {
            "modern": mapping["modern"],
            "historicalPreferred": mapping.get("historicalPreferred"),
            "creator": mapping.get("creator"),
            "source": args.display_authority.name,
        }
        if mapping.get("authorityUrl"):
            record["authorityUrl"] = mapping["authorityUrl"]
        if mapping.get("notBefore"):
            record["notBefore"] = mapping["notBefore"]
        if mapping.get("notAfter"):
            record["notAfter"] = mapping["notAfter"]
        for variant in sorted({mapping["modern"], *mapping.get("variants", [])}, key=key):
            alias_key = f'{mapping["category"]}|{key(variant)}'
            if mapping.get("notBefore") or mapping.get("notAfter"):
                dated.setdefault(alias_key, []).append(record)
            else:
                contextual[alias_key] = record

    layer["contextualAliases"] = contextual
    layer["datedContextualAliases"] = dated
    layer["datedWorkOverrides"] = display.get("datedWorkOverrides", {})
    layer["nonWorkMetadataPatterns"] = display.get("nonWorkMetadataPatterns", [])
    layer["historicalSurfaceCorrections"] = display.get("historicalSurfaceCorrections", {})
    layer.setdefault("provenance", {})["frontDisplayAuthority"] = {
        "file": args.display_authority.name,
        "sha256": sha256(args.display_authority),
    }
    args.output.write_text(json.dumps(layer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "contextualAliases": len(contextual),
        "datedContextualAliases": len(dated),
        "datedWorkOverrides": len(layer["datedWorkOverrides"]),
        "displayAuthoritySha256": layer["provenance"]["frontDisplayAuthority"]["sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
