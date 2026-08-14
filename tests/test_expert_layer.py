import json
import tempfile
import unittest
from pathlib import Path

from theater_expert_layer import category, compile_layer, key, semantic_category

class ExpertLayerTest(unittest.TestCase):
    def test_semantic_event_categories_override_empty_catchalls(self):
        self.assertIsNone(category("Sonstiges"))
        self.assertEqual(semantic_category({}, {"titleHistorical": "Masken-Ball"}, None), "Ball/Redoute")
        self.assertEqual(semantic_category({"notes": "Typ Pantomime (nicht unknown)"}, {"titleHistorical": "Arlequins Abentheuer"}, None), "Pantomime")

    def test_historical_glossary_categories(self):
        self.assertEqual(category("curiosity"), "Kuriositätenschau")
        self.assertEqual(category("zauberposse"), "Zauberposse")
        self.assertIsNone(category("Noch nicht bestimmt"))

    def test_modern_title_preserves_historical_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            titles = root / "titles.json"
            works = root / "works.jsonl"
            register = root / "register.json"
            titles.write_text(json.dumps({"bestaetigteMappings": [{"moderneForm": "Don Giovanni", "historischeVarianten": ["Don Juan"]}]}), encoding="utf-8")
            works.write_text(json.dumps({"titel": "Don Juan", "varianten": ["Don Juan"], "gattung": "opera", "komponist_autor": "W. A. Mozart"}) + "\n", encoding="utf-8")
            register.write_text(json.dumps({"events": [{"date": "1825-01-01", "canonicalWorks": [{"titleCanonical": "Don Juan", "titleHistorical": "Don Juan", "eventCategory": "Oper"}]}]}), encoding="utf-8")
            layer = compile_layer(titles, works, [register])
            self.assertEqual(layer["modernAliases"][key("Don Juan")], "Don Giovanni")
            self.assertEqual(layer["dateWorks"]["1825-01-01"][0]["canonical"], "Don Giovanni")
            self.assertEqual(layer["dateWorks"]["1825-01-01"][0]["historical"], "Don Juan")

    def test_contextual_operatic_titles_do_not_overwrite_spoken_drama(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            titles = root / "titles.json"
            works = root / "works.jsonl"
            display = root / "display.json"
            titles.write_text(json.dumps({"bestaetigteMappings": []}), encoding="utf-8")
            works.write_text(
                json.dumps({"titel": "Romeo und Julia", "varianten": ["Romeo und Julia"], "gattung": "schauspiel", "komponist_autor": "William Shakespeare"}) + "\n",
                encoding="utf-8",
            )
            display.write_text(json.dumps({"contextualTitleMappings": [
                {"category": "Oper", "modern": "Così fan tutte", "historicalPreferred": "Weibertreue", "variants": ["So machen's Alle"]},
                {"category": "Oper", "modern": "I Capuleti e i Montecchi", "variants": ["Die Montechi und die Capuleti"]},
            ]}), encoding="utf-8")
            layer = compile_layer(titles, works, [], display)
            cosi_key = "Oper|" + key("So machen's Alle")
            self.assertEqual(layer["contextualAliases"][cosi_key]["modern"], "Così fan tutte")
            self.assertEqual(layer["contextualAliases"][cosi_key]["historicalPreferred"], "Weibertreue")
            self.assertEqual(layer["contextualAliases"][f"Oper|{key('Die Montechi und die Capuleti')}"]["modern"], "I Capuleti e i Montecchi")
            self.assertNotIn(f"Schauspiel|{key('Romeo und Julia')}", layer["contextualAliases"])


if __name__ == "__main__": unittest.main()
