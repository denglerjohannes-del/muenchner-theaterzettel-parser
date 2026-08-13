# Münchner Theaterzettel-Parser

Deterministisches Referenzwerkzeug für gebundene Jahrgänge der Münchner Theaterzettel. Entwickelt und am vollständigen BSB-Jahrgang 1877 (`bsb11349688`, 772 Scans) validiert.

## Wissenschaftlicher Vertrag

- bindet jeden OCR-Text über das IIIF-Manifest an Scan, Bild und gedrucktes Label;
- ordnet mehrspaltigen Satz über hOCR-`bbox`, nicht über die unzuverlässige XML-Reihenfolge;
- erkennt Datum und Haus im Zettelkopf;
- isoliert das aktuelle Programm vor Fußvorschau und Repertoire-Entwurf;
- erhält Mehrfachausgaben, `statt`-Änderungen und Mehrteiler, statt sie zu überschreiben;
- erzeugt Kandidaten, keine erfundenen Werkidentitäten oder Orchesterdienste.

Theaterzettel liefern hochkonfidente Spielplandaten. Ein zusätzliches tägliches `PERFORMED`-Gate ist nicht Bestandteil dieses Werkzeugs. Bekannte Abweichungen und frühere Zettelfassungen gehören in eine explizite Kurations- und Releasestufe.

## Ablauf

```bash
python3 bind_scan_labels.py IIIF_MANIFEST.json SCAN_LABEL_BINDING.jsonl
python3 fetch_hocr.py IIIF_MANIFEST.json hocr HOCR_ACQUISITION_RECEIPT.json
python3 index_hocr.py hocr SCAN_LABEL_BINDING.jsonl index
python3 extract_programme_candidates.py index/PAGE_INDEX.jsonl index/PHYSICAL_LINES.jsonl candidates
python3 -m unittest discover -v
```

Die Scanbindung verhindert die Verwechslung gedruckter Seitenzahlen mit IIIF-Scan-IDs. Der Downloader ist resumierbar und quittiert jede Datei per SHA-256. Kleine OCR-Antworten leerer Rückseiten bleiben erhalten. `index_hocr.py` klassifiziert National- und Residenztheater getrennt; Konzert, Gärtnerplatz und interne Wochenpläne bleiben Review-Fälle.

## Referenzbefund 1877

- 772/772 offizielle hOCR-Dateien, 0 Fehlabrufe
- 31.224 physische OCR-Zeilen
- 369 aktuelle Zettel der beiden königlichen Häuser
- 217 Nationaltheater- und 152 Residenztheater-Zettelfassungen
- 0 titelarme Zettel nach der deterministischen Kandidatenextraktion

Die Freigabedaten und Kurationsentscheidungen gehören bewusst nicht in dieses allgemeine Werkzeug. Sie sind Forschungsdaten des jeweiligen Jahrgangs.
