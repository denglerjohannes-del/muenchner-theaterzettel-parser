#!/usr/bin/env python3
"""Fetch every official hOCR resource declared by a IIIF Presentation v2 manifest.

The fetch is resumable, content-addressed in its receipt, and deliberately keeps
small/blank OCR responses: an empty verso is source evidence too.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import time
import urllib.request


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_one(item: dict, output_dir: pathlib.Path, retries: int) -> dict:
    scan_index = item["scan_index"]
    target = output_dir / f"{scan_index:04d}.hocr"
    url = item["ocr_url"]
    if target.exists():
        data = target.read_bytes()
        return {**item, "bytes": len(data), "sha256": sha256(data), "status": "REUSED"}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "muenchner-theaterzettel-parser/0.1"})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            target.write_bytes(data)
            return {**item, "bytes": len(data), "sha256": sha256(data), "status": "FETCHED"}
        except Exception as exc:  # network errors need bounded retries
            last_error = repr(exc)
            time.sleep(min(attempt * 0.5, 3.0))
    return {**item, "bytes": 0, "sha256": None, "status": "FAILED", "error": last_error}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    parser.add_argument("receipt", type=pathlib.Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=4)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    canvases = manifest["sequences"][0]["canvases"]
    items = []
    for scan_index, canvas in enumerate(canvases, start=1):
        see_also = canvas.get("seeAlso")
        if isinstance(see_also, list):
            see_also = next((x for x in see_also if "hocr" in x.get("format", "").lower()), None)
        if not see_also or not see_also.get("@id"):
            raise SystemExit(f"scan {scan_index}: no hOCR resource in manifest")
        items.append({
            "scan_index": scan_index,
            "printed_label": canvas.get("label"),
            "canvas_id": canvas.get("@id"),
            "image_url": canvas["images"][0]["resource"]["@id"],
            "ocr_url": see_also["@id"],
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda item: fetch_one(item, args.output_dir, args.retries), items))
    results.sort(key=lambda row: row["scan_index"])

    failed = [row for row in results if row["status"] == "FAILED"]
    receipt = {
        "schema": "iiif-hocr-acquisition-receipt/1",
        "manifest_sha256": sha256(args.manifest.read_bytes()),
        "declared_scans": len(items),
        "files_present": len(results) - len(failed),
        "bytes": sum(row["bytes"] for row in results),
        "failed": len(failed),
        "items": results,
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("declared_scans", "files_present", "bytes", "failed")}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
