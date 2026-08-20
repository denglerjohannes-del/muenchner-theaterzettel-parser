import unittest, pathlib, tempfile, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import extract_cast as C

# Rolle links, Darsteller rechts; im Fliesstext alternierend und mit Punktfuehrung.
HOCR = """<html><body><div class='ocr_page' title='bbox 0 0 2800 4000'>
<span class='ocr_line' title='bbox 300 400 2400 460'>Lustspiel in vier Aufzuegen von Adolf Wilbrandt.</span>
<span class='ocr_line' title='bbox 300 900 700 950'>Personen:</span>
<span class='ocr_line' title='bbox 1900 1000 2400 1050'>Herr Herz.</span>
<span class='ocr_line' title='bbox 300 1005 1500 1055'>Sir Josuah Westcote, Baronet</span>
<span class='ocr_line' title='bbox 300 1120 1500 1170'>William, sein Sohn</span>
<span class='ocr_line' title='bbox 1900 1125 2400 1175'>Herr Rohde.</span>
<span class='ocr_line' title='bbox 1600 1130 1850 1170'>. . . . .</span>
<span class='ocr_line' title='bbox 300 1240 1500 1290'>Emma, dessen Frau</span>
<span class='ocr_line' title='bbox 1900 1245 2400 1295'>Frau Dahn-Hausmann.</span>
<span class='ocr_line' title='bbox 300 1800 2400 1860'>Preise der Plaetze: Eine Loge im III. Rang 7 fl.</span>
<span class='ocr_line' title='bbox 1900 1900 2400 1950'>Herr Niemand.</span>
</div></body></html>"""

class T(unittest.TestCase):
    def setUp(self):
        f = pathlib.Path(tempfile.mkdtemp()) / "0009.hocr"
        f.write_text(HOCR, encoding="utf-8")
        self.r = C.verarbeite(1870, "bsb00000000", 9, str(f))

    def test_urheberzeile_gedruckt(self):
        self.assertEqual(self.r["urheberzeile_gedruckt"],
                         "Lustspiel in vier Aufzuegen von Adolf Wilbrandt.")

    def test_paarung_ueber_geometrie(self):
        paare = {b["darsteller_oberflaeche"]: b["rolle_oberflaeche"] for b in self.r["besetzung"]}
        self.assertEqual(paare["Herz"], "Sir Josuah Westcote, Baronet")
        self.assertEqual(paare["Rohde"], "William, sein Sohn")
        self.assertEqual(paare["Dahn-Hausmann"], "Emma, dessen Frau")

    def test_preistabelle_beendet_den_block(self):
        """Nach der Preiszeile darf kein Darsteller mehr aufgenommen werden."""
        self.assertNotIn("Niemand", [b["darsteller_oberflaeche"] for b in self.r["besetzung"]])

    def test_punktfuehrung_ist_keine_rolle(self):
        for b in self.r["besetzung"]:
            if b["rolle_oberflaeche"] is None:
                continue  # ein Darsteller ohne lesbare Rolle ist zulaessig
            self.assertNotEqual(b["rolle_oberflaeche"].strip(" ."), "",
                                "Punktfuehrung darf nicht als Rolle durchgehen")

    def test_anrede_bleibt_getrennt(self):
        anreden = {b["anrede"] for b in self.r["besetzung"]}
        self.assertTrue(anreden <= {"Herr", "Frau", "Fräulein"})
        for b in self.r["besetzung"]:
            self.assertFalse(b["darsteller_oberflaeche"].startswith("Herr"))

    def test_herkunft_gebunden(self):
        for feld in ("hocr_sha256", "canvas_url", "ocr_url", "scan_index"):
            self.assertIn(feld, self.r)
        self.assertTrue(self.r["candidate_only"])
        self.assertTrue(all(b["name_bbox"] for b in self.r["besetzung"]))

if __name__ == "__main__":
    unittest.main()
