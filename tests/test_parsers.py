"""Test offline dei parser e del database: python -m unittest discover tests"""
import json
import tempfile
import unittest
from pathlib import Path

from importhelper.db import Database
from importhelper.models import below_min_price, excluded_word, matches
from importhelper.sources import autoscout24, tesla

AS24_ITEM = {
    "id": "abc-123",
    "url": "/annunci/tesla-model-s-plaid-abc-123",
    "images": ["https://prod.pictures.autoscout24.net/listing-images/abc_1.jpg/250x188.webp"],
    "price": {"priceFormatted": "€ 89.990", "priceRaw": 89990},
    "vehicle": {"make": "Tesla", "model": "Model S", "variant": None, "motorTypeName": "E 750 kW",
                "modelVersionInput": "Plaid AWD", "offerType": "U", "fuel": "Elettrica",
                "mileageInKm": "12.000 km"},
    "location": {"countryCode": "DE", "zip": "10115", "city": "Berlin"},
    "seller": {"id": "1", "type": "Dealer", "companyName": "Auto Berlin GmbH", "contactName": "Jan"},
    "tracking": {"firstRegistration": "03-2024", "fuelType": "e", "mileage": "12000", "price": "89990"},
    "vehicleDetails": [
        {"data": "12.000 km", "iconName": "mileage_odometer"},
        {"data": "03/2024", "iconName": "calendar"},
        {"data": "750 kW (1.020 CV)", "iconName": "speedometer"},
    ],
}


def as24_html(items, pages=1):
    data = {"props": {"pageProps": {"listings": items, "numberOfPages": pages}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


class ParserTests(unittest.TestCase):
    def test_autoscout24(self):
        listings, pages = autoscout24.parse_page(as24_html([AS24_ITEM], 3), "S Plaid", "https://www.autoscout24.it")
        self.assertEqual(pages, 3)
        l = listings[0]
        self.assertEqual(l.id, "autoscout24:abc-123@s-plaid")
        self.assertEqual((l.year, l.km, l.price, l.currency, l.country), (2024, 12000, 89990, "EUR", "DE"))
        self.assertEqual(l.url, "https://www.autoscout24.it/annunci/tesla-model-s-plaid-abc-123")
        self.assertTrue(l.photos[0].endswith("/1280x960.webp"))
        self.assertEqual((l.city, l.seller, l.seller_type, l.condition), ("Berlin", "Auto Berlin GmbH", "dealer", "used"))
        self.assertEqual((l.version, l.power_kw, l.first_registration), ("Plaid AWD", 750, "03/2024"))
        self.assertTrue(matches(l, {"must_contain": ["plaid"], "year_min": 2024, "year_max": 2026}))
        self.assertFalse(matches(l, {"must_contain": ["plaid"], "year_min": 2025}))

    def test_autoscout24_no_data(self):
        self.assertEqual(autoscout24.parse_page("<html></html>", "x", "https://x"), ([], 0))

    def test_tesla(self):
        data = {"results": [{
            "VIN": "5YJSA7E00PF000001", "TrimName": "Model S Plaid", "Year": 2024,
            "Odometer": 10000, "OdometerType": "Mi", "InventoryPrice": 95000,
            "CurrencyCode": "CHF", "CountryCode": "CH", "City": "Zürich",
            "VehiclePhotos": [{"imageUrl": "https://img/1.jpg"}],
        }], "total_matches_found": "1"}
        l = tesla.parse_results(data, "S Plaid", "ms", "CH", "used")[0]
        self.assertEqual(l.km, 16093)
        self.assertEqual((l.currency, l.country, l.year), ("CHF", "CH", 2024))
        self.assertEqual(l.url, "https://www.tesla.com/de_CH/ms/order/5YJSA7E00PF000001?titleStatus=used")
        self.assertEqual(l.photos, ["https://img/1.jpg"])
        self.assertTrue(matches(l, {"must_contain": ["plaid"]}))

    def test_min_price(self):
        l = autoscout24.parse_page(as24_html([AS24_ITEM]), "S", "https://x")[0][0]
        search = {"price_min_eur": 20000}
        l.price_eur = 2190  # rata di leasing
        self.assertTrue(below_min_price(l, search))
        l.price_eur = 89990
        self.assertFalse(below_min_price(l, search))
        l.price_eur = None  # prezzo sconosciuto: non scartare
        self.assertFalse(below_min_price(l, search))
        self.assertFalse(below_min_price(l, {}))
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            l.price_eur = 2190
            db.upsert(l, "2026-01-01")
            self.assertEqual(db.deactivate_below("S", 20000), 1)
            self.assertEqual(len(db.all()), 0)
            db.conn.close()

    def test_exclude_words(self):
        l = autoscout24.parse_page(as24_html([AS24_ITEM]), "S", "https://x")[0][0]
        s = {"exclude_words": ["noleggio", "LOA", "LLD", "lungo termine"]}
        for title, hit in [
            ("Audi RS5 2.9 TFSI quattro NOLEGGIO LUNGO TERMINE", True),
            ("Audi RS5 BERLINE 639 CH 879e LOA", True),
            ("Audi RS5 Avant (LLD)", True),
            ("Audi RS5 Avant leasingfähig Garantie", False),
            ("Audi RS5 *PROMO LEASING*", False),
            ("Audi RS5 Carloader Hyundai", False),  # "LOA" dentro una parola
        ]:
            l.title = title
            self.assertEqual(bool(excluded_word(l, s)), hit, title)

    def test_events_table(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            l = autoscout24.parse_page(as24_html([AS24_ITEM]), "S", "https://x")[0][0]
            l.price_eur = 89990
            db.record_new = False             # primo giro: nessun evento "new"
            db.upsert(l, "2026-01-01")
            self.assertEqual(db.events(), [])
            l.price, l.price_eur = 85000, 85000
            db.upsert(l, "2026-01-02")
            ev = db.events()[0]
            self.assertEqual((ev["type"], ev["listing_id"], ev["old_price_eur"], ev["new_price_eur"]),
                             ("price_drop", l.id, 89990, 85000))
            db.record_new = True
            l2 = autoscout24.parse_page(as24_html([{**AS24_ITEM, "id": "zz-9"}]), "S", "https://x")[0][0]
            db.upsert(l2, "2026-01-03")
            self.assertEqual(db.events()[0]["type"], "new")
            self.assertEqual(db.mark_inactive("autoscout24", "S", "2026-01-02T12"), 1)
            removed = [e for e in db.events() if e["type"] == "removed"]
            self.assertEqual([e["listing_id"] for e in removed], [l.id])
            db.commit()
            db.conn.close()
            # ricostruzione dei ribassi dalla cronologia prezzi su un database senza eventi
            db = Database(Path(d) / "t.db")
            db.conn.execute("DELETE FROM events"); db.conn.commit(); db.conn.close()
            db = Database(Path(d) / "t.db")
            self.assertEqual([e["type"] for e in db.events()], ["price_drop"])
            db.conn.close()

    def test_db_events(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            l = autoscout24.parse_page(as24_html([AS24_ITEM]), "S", "https://x")[0][0]
            self.assertEqual(db.upsert(l, "2026-01-01"), "new")
            self.assertEqual(db.upsert(l, "2026-01-02"), "same")
            l.price = 85000
            self.assertEqual(db.upsert(l, "2026-01-03"), "price_drop")
            self.assertEqual(db.mark_inactive("autoscout24", "S", "2026-01-04"), 1)
            self.assertEqual(len(db.all()), 0)
            db.conn.close()


if __name__ == "__main__":
    unittest.main()
