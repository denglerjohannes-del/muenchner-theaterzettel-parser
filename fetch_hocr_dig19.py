#!/usr/bin/env python3
"""dig19-acquisition engine for the hOCR fetch (migration design: repo issue #1).

dig19 provides the strict transport/store layer — response media-type check,
Content-Length and byte-limit enforcement, redirects disabled at the protocol
boundary, content-addressed blobs, single-writer canonical receipts.  This
module is deliberately a thin adapter: manifest items in, the same
``NNNN.hocr`` files and the same ``iiif-hocr-acquisition-receipt/1`` receipt
out as the legacy fetcher, so index_hocr and the whole curation/release
chain stay untouched.

Quota semantics differ intentionally: the legacy engine defers on rate-limit
signals, dig19 fails closed.  A quota failure is therefore a fast, explicit
run failure; re-running resumes from the content-addressed cache at no cost.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from fetch_hocr import RequestPacer

MEDIA_TYPE = "text/vnd.hocr+html"
RATE_CLASS = "ocr-daily-limited"
DEFAULT_CACHE_ROOT = pathlib.Path.home() / ".cache" / "theaterzettel-dig19-acquisition"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dig19():
    try:
        from dig19.acquisition import AcquisitionCache, AcquisitionError
        from dig19.iiif import PlannedRequest
    except ImportError as exc:
        raise SystemExit(
            "the dig19 engine requires the dig19 package (Digitalisate repo) "
            "on sys.path, e.g. pip install -e /path/to/Digitalisate"
        ) from exc
    return AcquisitionCache, AcquisitionError, PlannedRequest


def run(
    items: list[dict],
    manifest_path: pathlib.Path,
    output_dir: pathlib.Path,
    receipt_path: pathlib.Path,
    *,
    spacing: float = 0.5,
    cache_root: pathlib.Path = DEFAULT_CACHE_ROOT,
    transport=None,
    acquired_at_utc: str | None = None,
) -> dict:
    """Fetch all items through the dig19 cache and write the legacy receipt."""
    AcquisitionCache, AcquisitionError, PlannedRequest = _dig19()
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = AcquisitionCache(cache_root)
    pacer = RequestPacer(spacing)

    results = []
    for item in items:
        scan_index = item["scan_index"]
        target = output_dir / f"{scan_index:04d}.hocr"
        if target.exists():
            data = target.read_bytes()
            results.append({**item, "bytes": len(data), "sha256": _sha256(data), "status": "REUSED"})
            continue
        plan = PlannedRequest(item["ocr_url"], RATE_CLASS, MEDIA_TYPE)
        pacer.wait()
        try:
            receipt = cache.execute(
                plan,
                transport=transport,
                timeout_seconds=60,
                acquired_at_utc=acquired_at_utc,
            )
        except AcquisitionError as exc:
            results.append({**item, "bytes": 0, "sha256": None,
                            "status": "FAILED", "error": f"dig19-acquisition: {exc}"})
            continue
        data = (cache.root / receipt.blob_relative_path).read_bytes()
        if b"<" not in data[:1024] or b"ocr" not in data:
            # Same belt-and-braces content check as the legacy engine: a header
            # can lie; an error page must never become source evidence.
            results.append({**item, "bytes": 0, "sha256": None,
                            "status": "FAILED",
                            "error": f"dig19-acquisition: blob is not hOCR ({len(data)} bytes)"})
            continue
        # Materialize by copying, never by hardlink: dig19's safety contract
        # requires cached blobs to stay single-linked (nlink == 1), a link into
        # the output tree would break the next cache verification.
        target.write_bytes(data)
        results.append({**item, "bytes": receipt.byte_size,
                        "sha256": receipt.content_sha256, "status": "FETCHED"})

    failed = [row for row in results if row["status"] not in {"FETCHED", "REUSED"}]
    receipt = {
        "schema": "iiif-hocr-acquisition-receipt/1",
        "manifest_sha256": _sha256(pathlib.Path(manifest_path).read_bytes()),
        "declared_scans": len(items),
        "files_present": len(results) - len(failed),
        "bytes": sum(row["bytes"] for row in results),
        "failed": len(failed),
        "deferred_rate_limit": 0,
        "items": results,
    }
    pathlib.Path(receipt_path).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: receipt[k] for k in (
        "declared_scans", "files_present", "bytes", "failed", "deferred_rate_limit"
    )}, indent=2))
    if failed:
        raise SystemExit(1)
    return receipt
