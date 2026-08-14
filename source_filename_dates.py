#!/usr/bin/env python3
"""Parse archival filename date prefixes without collapsing ranges into days.

This helper is deliberately source-agnostic.  It returns temporal access
metadata only; a filename never proves that the named event or service occurred.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path


DATE_RE = re.compile(r"^(?P<y>\d{4})\.(?P<m>\d{2})\.(?P<d>\d{2})")
RANGE_RE = re.compile(r"^(?P<y>\d{4})\.(?P<m>\d{2})\.(?P<d>\d{2})\.?:(?P<tail>\d{2})(?P<more>[._:]?.*)")
YEAR_RE = re.compile(r"^(?P<y>\d{4})")
MONTH_RE = re.compile(r"^\d{4}[.]?(?P<m>\d{2})(?:[.]00|\b)")
SEASON_RE = re.compile(r"^(?P<y>\d{4}):(?P<y2>\d{2})")


def parse_temporal_prefix(filename: str) -> dict:
    """Return a fail-closed temporal classification for one basename."""
    name = Path(filename).name
    result = {
        "filename": name,
        "date": None,
        "date_start": None,
        "date_end": None,
        "year": None,
        "month": None,
        "temporal_precision": "UNRESOLVED",
        "date_parse_status": "NO_LEADING_DATE",
    }
    range_match = RANGE_RE.match(name)
    date_match = DATE_RE.match(name)
    if range_match:
        year = int(range_match["y"])
        month = int(range_match["m"])
        result.update(year=year, month=month, temporal_precision="DATE_RANGE_OR_SERIES", date_parse_status="PARSED_DATE_RANGE_OR_SERIES")
        try:
            result["date_start"] = dt.date(year, month, int(range_match["d"])).isoformat()
            if not range_match["more"] or re.fullmatch(r"(?:_[0-9]+)?[.]?jpg", range_match["more"], re.IGNORECASE):
                result["date_end"] = dt.date(year, month, int(range_match["tail"])).isoformat()
        except ValueError:
            result["date_parse_status"] = "INVALID_DATE_RANGE_OR_SERIES"
        return result
    if date_match:
        year = int(date_match["y"])
        month = int(date_match["m"])
        result.update(year=year, month=month)
        try:
            result.update(date=dt.date(year, month, int(date_match["d"])).isoformat(), temporal_precision="DAY", date_parse_status="PARSED_LEADING_DATE")
            return result
        except ValueError:
            result["date_parse_status"] = "PARTIAL_OR_INVALID_NUMERIC_DATE"

    season_match = SEASON_RE.match(name)
    year_match = YEAR_RE.match(name)
    month_match = MONTH_RE.match(name)
    if season_match:
        result.update(year=int(season_match["y"]), temporal_precision="SEASON", date_parse_status="PARSED_SEASON_RANGE")
    elif year_match:
        result["year"] = int(year_match["y"])
        if month_match and 1 <= int(month_match["m"]) <= 12:
            result.update(month=int(month_match["m"]), temporal_precision="MONTH", date_parse_status="PARSED_MONTH_ONLY")
        else:
            result.update(temporal_precision="YEAR", date_parse_status="PARSED_YEAR_ONLY")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filenames", nargs="+")
    args = parser.parse_args()
    for filename in args.filenames:
        print(json.dumps(parse_temporal_prefix(filename), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
