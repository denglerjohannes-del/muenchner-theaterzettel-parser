#!/usr/bin/env python3
"""Shared OCR calendar vocabulary for the theater-bill pipeline.

The 1877 volume's official OCR misreads month and weekday names in stable,
observed ways.  Those variant tables used to live in three modules at once
(index_hocr, build_schedule_release, generate_review_queue) and could drift;
this module is now the single source.  Extend a table only deliberately —
every variant is an observed OCR surface, not a guess.
"""

from __future__ import annotations

import re

MONTHS = {
    "Januar": 1, "Februar": 2, "Jebruar": 2, "März": 3, "Maerz": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Inni": 6, "Juli": 7, "August": 8, "Angust": 8,
    "Auguft": 8, "Jugust": 8, "September": 9, "FSeptember": 9, "Feptember": 9,
    "Oktober": 10, "November": 11, "Dezember": 12,
}
WEEKDAYS = {
    "Montag": 0, "Dienstag": 1, "Mittwoch": 2, "Donnerstag": 3,
    "Freitag": 4, "Samstag": 5, "Samflag": 5, "Saftmag": 5, "Famstag": 5,
    "Hamstag": 5, "Sonntag": 6, "Fonntag": 6, "Fountag": 6, "Fonutag": 6,
    "Sountag": 6,
}

MONTH_ALTERNATION = "|".join(MONTHS)
WEEKDAY_PATTERN = "|".join(WEEKDAYS)

MONTH_RE = re.compile(rf"\b(?:{MONTH_ALTERNATION})\b", re.I)
WEEKDAY_ONLY_RE = re.compile(rf"^\s*(?:{WEEKDAY_PATTERN})\s*$", re.I)
