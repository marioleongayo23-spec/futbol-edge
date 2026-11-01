"""Pure tests for license validation; never query Wikimedia in CI."""
import importlib.util
from pathlib import Path
import unittest

P = Path(__file__).with_name("refresh_commons_catalog.py")
spec = importlib.util.spec_from_file_location("commons_media", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def entity(name="Lamine Yamal",filename="Lamine Yamal photo.jpg"):
    return {
        "labels":{"en":{"value":name}},
        "claims":{"P18":[{"rank":"normal","mainsnak":{
            "datavalue":{"type":"string","value":filename}}}]},
    }

def commons(license_url="https://creativecommons.org/licenses/by-sa/4.0/", author="Bryan Berlin"):
    return {"query":{"pages":{"12":{"imageinfo":[{
        "thumburl":"https://upload.wikimedia.org/wikipedia/commons/thumb/image.jpg",
        "descriptionurl":"https://commons.wikimedia.org/wiki/File:Lamine_Yamal_photo.jpg",
        "extmetadata":{
            "LicenseUrl":{"value":license_url},
            "LicenseShortName":{"value":"CC BY-SA 4.0"},
            "Attribution":{"value":author},
        },
    }]}}}}

class CatalogTests(unittest.TestCase):
    def test_unique_approved_identity_with_verified_license(self):
        seed={"players":[{"player":"Lamine Yamal","teams":["FC Barcelona"],"wikidata_qid":"Q113704154"}]}
        def fetch(url):
            if "wikidata.org" in url:return {"entities":{"Q113704154":entity()}}
            return commons()
        catalog,bad=m.build_entries(seed,fetch=fetch)
        self.assertEqual(len(catalog["entries"]),1)
        self.assertEqual(bad,[])
        self.assertEqual(catalog["entries"][0]["license"],"CC BY-SA 4.0")
        self.assertEqual(catalog["entries"][0]["author"],"Bryan Berlin")
        same,_=m.build_entries(seed,fetch=fetch,previous=catalog)
        self.assertEqual(same,catalog)

    def test_false_wikidata_id_never_mapped_to_player(self):
        seed={"players":[{"player":"Lamine Yamal","teams":["FC Barcelona"],"wikidata_qid":"Q113704154"}]}
        def fetch(url):
            if "wikidata.org" in url:return {"entities":{"Q113704154":entity(name="Unrelated footballer")}}
            raise AssertionError("Should not call Commons for wrong entity")
        with self.assertRaisesRegex(ValueError,"empty"):
            m.build_entries(seed,fetch=fetch)

    def test_reject_nonfree_missing_credit_and_unsafe_remote_hosts(self):
        for bad in [
            commons("https://example.com/prohibited"),
            commons(author=""),
            {"query":{"pages":{"12":{"imageinfo":[{
                "thumburl":"https://images.otherdomain.io/photo.jpg",
                "descriptionurl":"https://commons.wikimedia.org/wiki/File:x",
                "extmetadata":{
                    "LicenseUrl":{"value":"https://creativecommons.org/licenses/by/4.0/"},
                    "LicenseShortName":{"value":"CC BY 4.0"},
                    "Artist":{"value":"Someone"},
                },
            }]}}}},
        ]:
            self.assertIsNone(m.license_from_commons(bad))

    def test_reject_duplicate_or_unapproved_QIDs(self):
        row={"player":"A","teams":["Real Madrid"],"wikidata_qid":"Q1"}
        for rows in [[row,row],[{**row,"wikidata_qid":"not-a-QID"}]]:
            with self.assertRaises(ValueError):m.build_entries({"players":rows},fetch=lambda _:{})

    def test_html_artist_credit_is_plain_text(self):
        self.assertEqual(m.plain("<span><b>Bryan Berlin</b> / WikiPortraits</span>"),
                         "Bryan Berlin / WikiPortraits")
        self.assertEqual(m.norm("Vinícius Júnior"),m.norm("Vinicius Junior"))

if __name__=="__main__":
    unittest.main()
