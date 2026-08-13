#!/usr/bin/env python3
"""Bindet gedruckte Seitenlabels exakt an IIIF-Scans, Bild-IDs und OCR-URLs."""

import argparse
import json
import re
from pathlib import Path

IMAGE_ID = re.compile(r"/([^/]+?_[0-9]{5})(?:/|$)")


def bind_manifest(payload):
    canvases = payload.get("sequences", [{}])[0].get("canvases", [])
    rows = []
    for scan_index, canvas in enumerate(canvases, 1):
        resources = canvas.get("images") or []
        resource_id = resources[0].get("resource", {}).get("@id", "") if resources else ""
        match = IMAGE_ID.search(resource_id)
        see_also = canvas.get("seeAlso") or {}
        if isinstance(see_also, list):
            see_also = see_also[0] if see_also else {}
        rows.append({
            "scan_index": scan_index,
            "printed_label": canvas.get("label"),
            "canvas_id": canvas.get("@id"),
            "image_id": match.group(1) if match else None,
            "ocr_url": see_also.get("@id"),
        })
    if not rows or any(row["scan_index"] != index for index, row in enumerate(rows, 1)):
        raise RuntimeError("IIIF-Scanfolge fehlt oder ist nicht lueckenlos")
    if len({row["image_id"] for row in rows if row["image_id"]}) != sum(bool(row["image_id"]) for row in rows):
        raise RuntimeError("doppelte Bild-ID im IIIF-Manifest")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = bind_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"scans": len(rows), "first": rows[0], "last": rows[-1]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
