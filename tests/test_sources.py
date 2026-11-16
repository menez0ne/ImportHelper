"""Test delle fonti con pagine reali salvate (ridotte a pochi annunci) in tests/fixtures."""
import json
import unittest
from pathlib import Path

from importhelper.models import matches
from importhelper.sources import marktplaats, otomoto, schibsted, willhaben
from importhelper.sources.common import is_model, to_int

F = Path(__file__).with_name("fixtures")
RS5 = {"name": "Audi RS5", "make": "audi", "model": "rs5"}


def text(name):
    return (F / name).read_text(encoding="utf-8")


class SourceTests(unittest.TestCase):
    def test_common(self):
        self.assertEqual([to_int(x) for x in ("9500.0", "65000 km", "€ 9.500", 12.6, None, "")],
                         [9500, 65000, 9500, 13, None, None])
        self.assertTrue(is_model("Tesla Model S Plaid", {"make": "tesla", "model": "model-s"}))
        self.assertFalse(is_model("Tesla Model X Plaid", {"make": "tesla", "model": "model-s"}))
        self.assertFalse(is_model("Audi A5 Sportback", RS5))

    def test_marktplaats(self):
        l = marktplaats.parse(json.loads(text("marktplaats.json")), RS5,
                              {"domain": "https://www.marktplaats.nl", "country": "NL"}, "marktplaats")[0]
        self.assertEqual((l.id, l.year, l.km, l.price, l.currency, l.country, l.city),
                         ("marktplaats:m2459853749@audi-rs5", 2018, 125107, 48950.0, "EUR", "NL", "Harlingen"))
        self.assertEqual((l.seller, l.seller_type), ("Autocentrum Harlingen", "dealer"))
        self.assertTrue(l.url.startswith("https://www.marktplaats.nl/v/auto-s/audi/m2459853749"))
        self.assertTrue(l.photos[0].startswith("https://images.marktplaats.com/") and "$_85" in l.photos[0])

    def test_marktplaats_model_field(self):
        item = lambda i, title, model, **attrs: {"itemId": i, "title": title, "priceInfo": {"priceCents": 1}, "location": {},
                                                 "attributes": [{"key": "model", "value": model}] +
                                                 [{"key": k, "value": v} for k, v in attrs.items()]}
        data = {"listings": [
            item("a", "Audi RS4 Avant & Cabrio RS5 Cabrio", "RS4"),                                   # una RS4
            item("b", "Audi A5 Avant RS5 639Pk", "A5", constructionYear="2026", mileage="1050"),     # RS5 sotto "A5"
            item("c", "Audi RS5 Avant", "RS5"),
        ]}
        ids = [l.source_id for l in marktplaats.parse(data, RS5, {"domain": "https://x", "country": "NL"}, "marktplaats")]
        self.assertEqual(ids, ["b", "c"])

    def test_2dehands(self):
        data = json.loads(text("2dehands.json"))
        ls = marktplaats.parse(data, RS5, {"domain": "https://www.2dehands.be", "country": "BE"}, "2dehands")
        self.assertEqual(len(ls), 2)                     # il terzo annuncio non è una RS5
        self.assertEqual((ls[0].country, ls[0].city, ls[0].km), ("BE", "Eeklo", 87553))
        self.assertEqual((ls[1].country, ls[1].city), ("NL", "Groot-Ammers"))   # venditore olandese

    def test_otomoto(self):
        ls, pages = otomoto.parse(text("otomoto.html"), RS5)
        l = ls[0]
        self.assertEqual(pages, 1)
        self.assertEqual((l.id, l.year, l.km, l.price, l.currency, l.country, l.city),
                         ("otomoto:6151124885@audi-rs5", 2021, 65000, 249900.0, "PLN", "PL", "Warszawa"))
        self.assertEqual((l.power_kw, l.seller_type), (331, "dealer"))   # 450 CV
        self.assertTrue(l.photos[0].endswith(";s=1280x960"))

    def test_willhaben(self):
        ls, _ = willhaben.parse(text("willhaben.html"), RS5)
        self.assertEqual(len(ls), 2)                     # la terza auto (non RS5) è scartata
        l = ls[0]
        self.assertEqual((l.id, l.year, l.km, l.price, l.country, l.city, l.seller_type, l.power_kw),
                         ("willhaben:830137960@audi-rs5", 2008, 125000, 32500.0, "AT", "Kufstein", "private", 260))
        self.assertTrue(l.url.startswith("https://www.willhaben.at/iad/gebrauchtwagen/d/auto/"))
        self.assertTrue(l.photos[0].startswith("https://cache.willhaben.at/mmo/"))
        self.assertFalse(matches(l, {"year_min": 2026}))

    def test_blocket_finn(self):
        ls, pages = schibsted.parse(text("blocket.html"), RS5, "blocket", "SE")
        self.assertEqual((pages, ls[0].id, ls[0].currency, ls[0].country, ls[0].city, ls[0].seller),
                         (1, "blocket:28184998@audi-rs5", "SEK", "SE", "Vega", "GT Performance Cars AB"))
        self.assertEqual(ls[0].price, 1449900.0)
        ls, _ = schibsted.parse(text("finn.html"), RS5, "finn", "NO")
        self.assertEqual((ls[0].year, ls[0].km, ls[0].currency, ls[0].seller_type), (2011, 154100, "NOK", "private"))
        self.assertEqual(ls[1].seller_type, "dealer")


class DuplicateTests(unittest.TestCase):
    def test_merge(self):
        from importhelper.site import merge_duplicates
        car = lambda i, src, km, price, **kw: {"id": i, "source": src, "url": f"https://{src}/{i}", "search": "RS5",
                                               "country": "NL", "year": 2026, "km": km, "price_eur": price,
                                               "active": True, **kw}
        a = car("a", "marktplaats", 16000, 132500)
        b = car("b", "autoscout24", 16100, 131900)          # stessa auto: km +0,6%, prezzo -0,5%
        c = car("c", "2dehands", 16000, 140000)             # prezzo +5,7%: un'altra auto
        d = car("d", "willhaben", 16000, 132500, country="AT")
        e = car("e", "otomoto", 16000, 132500, active=False)
        f = car("f", "autoscout24", 10, 156750, city="ZWOLLE")      # auto nuove simili
        g = car("g", "marktplaats", 8, 156542, city="Drachten")     # ma in un'altra città
        h = car("h", "2dehands", 10, 156750, city="Zwolle")         # stessa auto di f
        self.assertEqual(merge_duplicates([a, b, c, d, e, f, g, h]), 2)
        self.assertNotIn("dup_of", g)
        self.assertEqual(h["dup_of"], "f")
        self.assertEqual(a["dup_of"], "b")                  # resta la scheda di AutoScout24
        self.assertEqual([x["source"] for x in b["also"]], ["marktplaats"])
        self.assertNotIn("dup_of", c)
        self.assertNotIn("dup_of", d)


if __name__ == "__main__":
    unittest.main()
