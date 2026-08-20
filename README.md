# Münchner Theaterzettel-Parser

Deterministisches Referenzwerkzeug für gebundene Jahrgänge der Münchner Theaterzettel. An den vollständigen BSB-Jahrgängen 1877–1883 validiert.

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
# alternativ die dig19-Engine (strikter Transport, content-addressierter Cache;
# erfordert das dig19-Paket aus dem Digitalisate-Repo auf sys.path):
python3 fetch_hocr.py IIIF_MANIFEST.json hocr HOCR_ACQUISITION_RECEIPT.json --engine dig19
python3 index_hocr.py hocr SCAN_LABEL_BINDING.jsonl index --year 1878
python3 extract_programme_candidates.py index/PAGE_INDEX.jsonl index/PHYSICAL_LINES.jsonl candidates
python3 generate_review_queue.py index/PAGE_INDEX.jsonl candidates/PROGRAMME_CANDIDATES.jsonl review --year 1878
python3 build_schedule_release.py candidates/PROGRAMME_CANDIDATES.jsonl CURATION.json index/PAGE_INDEX.jsonl release \
  --year 1878 --source-volume bsb11362379 \
  --source-manifest https://api.digitale-sammlungen.de/iiif/presentation/v2/bsb11362379/manifest \
  --source-urn urn:nbn:de:bvb:12-bsb11362379-2
python3 -m unittest discover -v
```

## Theater-Expertenschicht

`theater_expert_layer.py` kompiliert historische Titelvarianten, moderne
Werktitel, Gattungen und bekannte Urheber aus versionierten Fachregistern.
Die Darstellung verwendet den modernen kanonischen Titel als Haupttitel und
erhält die gedruckte Form getrennt als historischen Untertitel, etwa
`Don Giovanni` / `Don Juan` und `La traviata` / `Violetta`. Unspezifische
Catch-all-Werte wie `other` oder `Sonstiges` werden nicht veröffentlicht.
Explizite historische Ereignisformen (etwa Maskenball, Pantomime oder Prolog)
haben Vorrang vor bloßer Titelähnlichkeit. Nicht auflösbare Kandidaten bleiben
im internen Prüfbestand und gelangen nicht als erfundene Kategorie oder
Urheberangabe in den Kalender.

Die versionierte `resources/front_display_authority.json` ergänzt
gattungsgebundene, kollisionssichere Werkidentitäten. So erscheinen
`Così fan tutte` / `Weibertreue`, `Le nozze di Figaro` / `Die Hochzeit des
Figaro` und `I Capuleti e i Montecchi` / `Die Montechi und die Capuleti`, ohne
das Schauspiel `Romeo und Julia` umzubenennen. Datumsgebundene Bildkorrekturen
bleiben als solche ausgewiesen. Der Compiler sortiert alle Variantenschlüssel
deterministisch; zwei identische Läufe müssen denselben SHA-256 erzeugen.
Die kuratierte `resources/supplemental_work_authority.json` ist derselben
Expertenschicht einverleibt und genügt als positiver Fronttitelbeleg, wenn
Gattung und Urheber gemeinsam gebunden sind. Stabile Druckformeln ohne
Werkcharakter, derzeit insbesondere „Vorstellung im Jahres-Abonnement“, werden
als versionierte Nichtwerk-Regeln kompiliert und nicht als Titel publiziert.

Für ergänzende Archivbestände mit Datumspräfixen steht außerdem
`source_filename_dates.py` bereit. Das Hilfswerkzeug trennt exakte Tage,
Monats-/Jahresangaben, Spielzeiten und Bereiche. Insbesondere wird ein Name wie
`1837.01.12.:29_1.jpg` nicht zum vermeintlichen Einzeltag 12. Januar verkürzt.
Dateinamen bleiben Findmittel und sind kein Aufführungs- oder Dienstbeweis.

Bei gedrosselten Quellservern respektiert der Downloader `Retry-After`, nutzt
exponentielle Pausen mit Jitter und taktet alle Worker gemeinsam. Für einen
schonenden Langlauf kann die Rate weiter abgesenkt werden, etwa mit
`--workers 2 --request-spacing 1.5 --retries 8`; bereits vorhandene Dateien
werden dabei geprüft und wiederverwendet. Ein ausgeschöpftes Tageskontingent
mit langem `X-RateLimit-Reset` wird als `DEFERRED_RATE_LIMIT` quittiert, statt
den Quellserver zwecklos weiter abzufragen; diese Information stoppt zugleich
alle Worker des laufenden Abrufs.

Die Scanbindung verhindert die Verwechslung gedruckter Seitenzahlen mit IIIF-Scan-IDs. Der Downloader ist resumierbar und quittiert jede Datei per SHA-256. Kleine OCR-Antworten leerer Rückseiten bleiben erhalten. Der Indexer verlangt das Kalenderjahr ausdrücklich über `--year`; damit kann ein Jahrgang nicht versehentlich mit dem Datumsvertrag eines anderen verarbeitet werden. `index_hocr.py` klassifiziert National- und Residenztheater getrennt; Konzert, Gärtnerplatz und interne Wochenpläne bleiben Review-Fälle.

`generate_review_queue.py` bündelt Struktur-Holds, Mehrkomponentenprogramme,
verdächtige Personen-/Anlass-/Zeitzeilen, parallele Zettelfassungen und ein
einziges Inventar der nur einmal vorkommenden Titeloberflächen in einen
begrenzten Review-Durchgang. Es trifft keine inhaltliche Entscheidung und
löscht nichts; die Auflösung bleibt explizite, reversible Kuration.

## Referenzbefunde

| Jahr | BSB-Band | Scans | physische OCR-Zeilen | automatisch erkannte Zettel | Titel-Holds |
|---:|---|---:|---:|---:|---:|
| 1877 | `bsb11349688` | 772 | 31.224 | 369 | 0 |
| 1878 | `bsb11362379` | 714 | 36.092 | 361 | 0 |
| 1879 | `bsb11380789` | 780 | 39.869 | 383 | 0 |
| 1880 | `bsb11455085` | 746 | 31.851 | 365 | 0 |
| 1881 | `bsb11455086` | 746 | 33.001 | 364 | 0 |
| 1882 | `bsb11455087` | 762 | 32.661 | 372 | 0 |
| 1883 | `bsb11455088` | 902 | 37.023 | 433 | 0 |

Die Kurationsentscheidungen bleiben Forschungsdaten des jeweiligen Jahrgangs. Der allgemeine Release-Bauer liest sie nur ein, bindet seltene manuelle Ergänzungen, komplexe Titelgruppen und ausdrückliche Absagen an konkrete Quellenseiten und erzeugt daraus Spielplan, Tagesledger, Titelhäufigkeiten, frühere und abgesagte Zettelfassungen sowie Provenienz deterministisch. Automatische Ausgangsgruppen bleiben bei einer Korrektur vollständig erhalten.

Ausdrückliche Absagen und Schließungen werden zusätzlich in
`KNOWN_CANCELLATION_OR_CLOSURE_NOTICES.jsonl` quellengebunden erhalten. Das gilt
auch für Hinweise im Fuß eines Vortagszettels, bei denen am geschlossenen Tag
selbst kein eigener Zettel existiert.

## Besetzung und gedruckte Urheberzeile

`extract_cast.py` liest aus denselben hOCR-Seiten die `Personen:`-Rubrik und die
gedruckte Gattungs- und Urheberzeile.

```bash
python3 extract_cast.py 1870 bsb10623143 hocr candidates/PROGRAMME_CANDIDATES.jsonl BESETZUNG_1870.jsonl
```

Rolle und Darsteller stehen auf dem Zettel in zwei Spalten, im OCR-Fliesstext aber
alternierend und mal in der einen, mal in der anderen Reihenfolge. Die Paarung laeuft
deshalb ueber die Zeilenhoehe, nicht ueber die XML-Reihenfolge. Die Namensspalte wird
an der gedruckten Anrede erkannt (`Herr`, `Frau`, `Fraeulein`, samt der haeufigen
Frakturverlesungen `Fran`, `Frrr`, `Fraenlein`), nicht an einer festen x-Schwelle,
weil der Satzspiegel je Jahrgang wandert. Der Block endet an der Preistabelle, der
Anfangszeit oder der Fussvorschau; die Abbruchmarken sind umlautunabhaengig gefasst,
weil Fraktur-OCR gerade dort unzuverlaessig ist. Punktfuehrungen werden verworfen.

Referenzbefund 1869-1872 (Baende bsb10317349, bsb10623143, bsb10935158, bsb10935159):

| | |
|---|---:|
| ausgewertete Zettel | 1.303 |
| davon mit Besetzung | 1.275 (98 %) |
| Besetzungsrelationen | 19.314 |
| davon mit Rollenangabe | 17.904 |
| Zettel mit gedruckter Urheberzeile | 1.193 (92 %) |
| verschiedene Darsteller-Oberflaechen | 594 |

Neunzig Prozent der Relationen entfallen auf 96 Namensoberflaechen — die
Identitaetsarbeit ist damit begrenzt und planbar.

Die Ausgabe ist ausdruecklich Kandidatenmaterial: Anrede, Namensoberflaeche und
Rollenoberflaeche bleiben getrennt und an Scan, bbox und hOCR-SHA-256 gebunden.
Es werden keine Personenidentitaeten gebildet.
