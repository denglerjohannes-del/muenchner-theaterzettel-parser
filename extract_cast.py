#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrahiert Besetzung und gedruckte Urheberzeile aus Muenchner Theaterzettel-hOCR.

Vertrag wie im uebrigen Parser:
- Rolle und Darsteller werden ueber bbox-Geometrie gepaart, nie ueber die
  XML-Reihenfolge; im Fliesstext stehen sie mal vor-, mal nacheinander;
- die Namensspalte wird an der gedruckten Anrede erkannt, nicht an einer festen
  x-Schwelle, weil der Satzspiegel je Jahrgang wandert;
- Punktfuehrungen, Preistabellen und die Fussvorschau werden ausgeschlossen;
- Ausgabe sind Kandidaten mit Herkunft (Scan, bbox, hOCR-SHA-256), keine Identitaeten.
"""
import re,json,sys,hashlib,pathlib,collections
from lxml import html

BBOX=re.compile(r'bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)')
ANREDE=re.compile(r'^\s*(Herr|Herrn|Hr\.|Frau|Fr\.|Fräulein|Fraeulein|Frl\.|Fräul\.|Mad\.|Mad|Mde\.|Mlle\.|Dlle\.|Dem\.)\s*',re.I)
# OCR-Varianten der Anrede aus Fraktur
ANREDE_OCR=re.compile(r'^\s*(Herr|Hr\.|Frau|Fräulein|Frl\.|Mad\.|Dlle\.|Fran|Frrr|Feer|Oerr|Errt|Freu|Arau|Fränlein|Fraulein|Grünlein|Schullein|Erl\.|Fel\.)\s*',re.I)
BEGINN=re.compile(r'^\s*Personen\s*[:.]?\s*$|^\s*Personen\s*[:.]',re.I)
# Umlaute sind in Fraktur-OCR unzuverlaessig; die Abbruchmarken duerfen nicht daran haengen.
ENDE=re.compile(r'('
 r'Preise?\s+d(?:er|\.)\s*Pl[aäe]e?tz|Preise?\s+der\s+Pl|'          # Preise der Plaetze
 r'\bPreise\b[^|]{0,30}\bfl\b|'                                       # Preise ... fl.
 r'Der\s+Anfang|Anfang\s+(?:um|ist|gegen)|'
 r'Kassen?[=\- ]?Er[oö]e?ffnung|Kasse\s+wird|'
 r'Ende\s+(?:gegen|um|nach)|'
 r'Repertoir|N[aä]e?chste\s+Vorstellung|Zu\s+dieser\s+Vorstellung|'
 r'Billets?\b|Tages[=\- ]?Kasse|Vormerkungen|Abonnement\s+ist\s+aufgehoben'
 r')',re.I)
FUEHRUNG=re.compile(r'^[\s.,;:•·\-–—_]*$')
GATTUNG=r'(?:Lustspiel|Schauspiel|Trauerspiel|Posse|Oper|Operette|Ballet|Ballett|Singspiel|Drama|Charakterbild|Volksstück|Zauberposse|Melodram|Divertissement|Pantomime|Vaudeville|Liederposse|Genrebild|Familiengemälde|Original-?Lustspiel|Sittengemälde)'
URHEBERZEILE=re.compile(r'('+GATTUNG+r'[^|]{0,110}?\b(?:von|nach|Text von|Musik von)\s+[^|]{0,60})',re.I)

def zeilen(pfad):
    doc=html.fromstring(pathlib.Path(pfad).read_bytes())
    out=[]
    for pos,n in enumerate(doc.xpath("//*[contains(concat(' ',normalize-space(@class),' '),' ocr_line ')]")):
        t=' '.join(''.join(n.itertext()).split())
        m=BBOX.search(n.get('title',''))
        if t and m:
            b=[int(x) for x in m.groups()]
            out.append({'i':pos,'bbox':b,'y':(b[1]+b[3])//2,'x':b[0],'text':t})
    return out

def block(ls):
    """Grenzt den aktuellen Besetzungsblock ein: ab 'Personen:' bis zur Preis-/Fusszeile."""
    start=None
    for l in ls:
        if BEGINN.search(l['text']): start=l; break
    if start is None: return [],None
    unten=[l for l in ls if l['y']>=start['y']]
    ende=None
    for l in sorted(unten,key=lambda l:l['y']):
        if l['y']>start['y']+40 and ENDE.search(l['text']): ende=l['y']; break
    if ende: unten=[l for l in unten if l['y']<ende]
    return [l for l in unten if not FUEHRUNG.match(l['text'])],start

def paare(bl):
    """Paart Darsteller und Rolle ueber Zeilenhoehe. Namensspalte an der Anrede erkannt."""
    namen=[l for l in bl if ANREDE_OCR.match(l['text'])]
    rollen=[l for l in bl if l not in namen and len(l['text'])>3 and not BEGINN.search(l['text'])]
    if not namen: return []
    # x-Schwerpunkt der Namensspalte; Rollen liegen typischerweise links davon
    nx=sorted(l['x'] for l in namen); mid=nx[len(nx)//2]
    out=[]
    benutzt=set()
    for n in sorted(namen,key=lambda l:l['y']):
        kand=[r for r in rollen if id(r) not in benutzt and abs(r['y']-n['y'])<=90]
        # bevorzugt links stehende Rollen; sonst die naechstliegende
        kand.sort(key=lambda r:(0 if r['x']<mid-40 else 1, abs(r['y']-n['y'])))
        rolle=kand[0] if kand else None
        if rolle: benutzt.add(id(rolle))
        name=ANREDE_OCR.sub('',n['text']).strip(' .,;:')
        anrede=(ANREDE_OCR.match(n['text']).group(1) or '').strip()
        if len(name)<2: continue
        out.append({'anrede':anrede,'darsteller_oberflaeche':name,
            'rolle_oberflaeche':(rolle['text'].strip(' .,;:') if rolle else None),
            'name_bbox':n['bbox'],'rolle_bbox':rolle['bbox'] if rolle else None,
            'abstand_y':abs(rolle['y']-n['y']) if rolle else None})
    return out

def urheberzeile(ls,grenze_y):
    """Sucht die gedruckte Gattungs- und Urheberzeile oberhalb des Besetzungsblocks."""
    kand=[l for l in ls if grenze_y is None or l['y']<grenze_y]
    kand=sorted(kand,key=lambda l:l['y'])
    # zuerst zeilenweise, dann ueber zwei zusammengezogene Zeilen (Umbruch im Satz)
    for l in kand:
        m=URHEBERZEILE.search(l['text'])
        if m: return m.group(1).strip()
    for a,b in zip(kand,kand[1:]):
        m=URHEBERZEILE.search(a['text']+' '+b['text'])
        if m: return m.group(1).strip()
    return None

def verarbeite(jahr,bsb,scan,pfad):
    roh=pathlib.Path(pfad).read_bytes(); sha=hashlib.sha256(roh).hexdigest()
    ls=zeilen(pfad)
    if not ls: return None
    bl,start=block(ls)
    uz=urheberzeile(ls,start['y'] if start else None)
    bes=paare(bl) if bl else []
    return {'jahr':jahr,'bsb':bsb,'scan_index':scan,'hocr_sha256':sha,
        'canvas_url':'https://www.digitale-sammlungen.de/de/view/%s?page=%d'%(bsb,scan),
        'ocr_url':'https://api.digitale-sammlungen.de/ocr/%s/%d'%(bsb,scan),
        'urheberzeile_gedruckt':uz,'besetzung':bes,
        'besetzung_gefunden':len(bes),'personenrubrik':bool(start),
        'schema':'theaterzettel-besetzung-candidate/1','candidate_only':True}

if __name__=='__main__':
    jahr,bsb,hocrdir,candfile,out=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5]
    scans=[json.loads(l)['scan_index'] for l in open(candfile,encoding='utf-8')]
    rows=[]
    for s in scans:
        p=pathlib.Path(hocrdir)/('%04d.hocr'%s)
        if not p.exists(): continue
        r=verarbeite(int(jahr),bsb,s,str(p))
        if r: rows.append(r)
    pathlib.Path(out).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    n=len(rows); mitb=sum(1 for r in rows if r['besetzung_gefunden']); mitu=sum(1 for r in rows if r['urheberzeile_gedruckt'])
    rel=sum(r['besetzung_gefunden'] for r in rows)
    mitrolle=sum(1 for r in rows for b in r['besetzung'] if b['rolle_oberflaeche'])
    print(json.dumps({'jahr':int(jahr),'zettel':n,'mit_besetzung':mitb,'mit_urheberzeile':mitu,
        'besetzungsrelationen':rel,'davon_mit_rolle':mitrolle},ensure_ascii=False,indent=1))
