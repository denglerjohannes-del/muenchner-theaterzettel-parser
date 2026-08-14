#!/usr/bin/env python3
"""Fetch every official hOCR resource declared by a IIIF Presentation v2 manifest.

The fetch is resumable, content-addressed in its receipt, and deliberately keeps
small/blank OCR responses: an empty verso is source evidence too.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import email.utils
import hashlib
import json
import pathlib
import random
import threading
import time
import urllib.error
import urllib.request


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RequestPacer:
    """Share a minimum request interval across all downloader threads."""

    def __init__(self, spacing: float) -> None:
        self.spacing = max(0.0, spacing)
        self.lock = threading.Lock()
        self.next_request = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_request - now)
            if delay:
                time.sleep(delay)
            self.next_request = time.monotonic() + self.spacing


def retry_after_seconds(value: str | None) -> float | None:
    """Parse Retry-After seconds or an RFC 2822 date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            return max(0.0, (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def rate_limit_reset_seconds(value: str | None) -> float | None:
    """Accept either delta-seconds or a Unix timestamp from X-RateLimit-Reset."""
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number > time.time():
        number -= time.time()
    return max(0.0, number)


def retry_delay(attempt: int, retry_after: str | None, base: float, maximum: float) -> float:
    server_delay = retry_after_seconds(retry_after)
    exponential = base * (2 ** max(0, attempt - 1))
    delay = max(exponential, server_delay or 0.0)
    jitter = random.uniform(0.0, min(1.0, delay * 0.1))
    return min(maximum, delay + jitter)


def fetch_one(
    item: dict,
    output_dir: pathlib.Path,
    retries: int,
    pacer: RequestPacer,
    base_backoff: float,
    max_backoff: float,
) -> dict:
    scan_index = item["scan_index"]
    target = output_dir / f"{scan_index:04d}.hocr"
    url = item["ocr_url"]
    if target.exists():
        data = target.read_bytes()
        return {**item, "bytes": len(data), "sha256": sha256(data), "status": "REUSED"}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            pacer.wait()
            req = urllib.request.Request(url, headers={"User-Agent": "muenchner-theaterzettel-parser/0.1"})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            target.write_bytes(data)
            return {**item, "bytes": len(data), "sha256": sha256(data), "status": "FETCHED"}
        except urllib.error.HTTPError as exc:
            last_error = repr(exc)
            reset = rate_limit_reset_seconds(exc.headers.get("X-RateLimit-Reset"))
            if (
                exc.code == 429
                and exc.headers.get("X-RateLimit-Remaining") == "0"
                and reset is not None
                and reset > max_backoff
            ):
                return {
                    **item,
                    "bytes": 0,
                    "sha256": None,
                    "status": "DEFERRED_RATE_LIMIT",
                    "error": last_error,
                    "rate_limit_reset_seconds": reset,
                }
            if attempt < retries:
                time.sleep(retry_delay(
                    attempt, exc.headers.get("Retry-After"), base_backoff, max_backoff
                ))
        except Exception as exc:  # network errors need bounded retries
            last_error = repr(exc)
            if attempt < retries:
                time.sleep(retry_delay(attempt, None, base_backoff, max_backoff))
    return {**item, "bytes": 0, "sha256": None, "status": "FAILED", "error": last_error}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("output_dir", type=pathlib.Path)
    parser.add_argument("receipt", type=pathlib.Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--request-spacing", type=float, default=0.5,
                        help="minimum seconds between requests across all workers")
    parser.add_argument("--base-backoff", type=float, default=2.0)
    parser.add_argument("--max-backoff", type=float, default=60.0)
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
    pacer = RequestPacer(args.request_spacing)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(
            lambda item: fetch_one(
                item, args.output_dir, args.retries, pacer,
                args.base_backoff, args.max_backoff,
            ),
            items,
        ))
    results.sort(key=lambda row: row["scan_index"])

    failed = [row for row in results if row["status"] not in {"FETCHED", "REUSED"}]
    deferred = [row for row in results if row["status"] == "DEFERRED_RATE_LIMIT"]
    receipt = {
        "schema": "iiif-hocr-acquisition-receipt/1",
        "manifest_sha256": sha256(args.manifest.read_bytes()),
        "declared_scans": len(items),
        "files_present": len(results) - len(failed),
        "bytes": sum(row["bytes"] for row in results),
        "failed": len(failed),
        "deferred_rate_limit": len(deferred),
        "items": results,
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in (
        "declared_scans", "files_present", "bytes", "failed", "deferred_rate_limit"
    )}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
