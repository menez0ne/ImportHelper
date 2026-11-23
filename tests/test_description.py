"""Descrizione del venditore: estrazione dalle pagine e cache della traduzione (senza rete)."""
import json
import sqlite3
import unittest

from importhelper import description


class FakeResponse:
    status_code = 200

    def __init__(self, text="", data=None):
        self.text, self._data = text, data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, page):
        self.page, self.calls = page, 0

    def get(self, url, **kw):
        self.calls += 1
        return None if self.page is None else FakeResponse(self.page)


class FakeTranslator:
    """Finto Google Traduttore: riconosce il tedesco e "traduce" mettendo [it] davanti."""

    def __init__(self, lang="de", fail=False):
        self.lang, self.fail, self.calls = lang, fail, 0

    def post(self, url, params=None, data=None, **kw):
        self.calls += 1
        if self.fail:
            raise description.requests.ConnectionError("offline")
        q = data["q"]
        return FakeResponse(data=[[["[it] " + q, q]], None, self.lang])


def next_data(obj):
    return '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(obj) + "</script></html>"


class ExtractTests(unittest.TestCase):
    def test_autoscout24_next_data(self):
        page = next_data({"props": {"pageProps": {"listingDetails": {
            "description": "Scheckheftgepflegt, unfallfrei.<br />Garantie bis 2028.<br><br><ul><li>Pano</li><li>B&amp;O</li></ul>",
            "seller": {"type": "Dealer"}}}}})
        self.assertEqual(description.extract(page),
                         "Scheckheftgepflegt, unfallfrei.\nGarantie bis 2028.\n\n• Pano\n• B&O")

    def test_willhaben_attributes(self):
        page = next_data({"props": {"pageProps": {"advertDetails": {"attributes": {"attribute": [
            {"name": "DESCRIPTION", "values": ["Verkaufe meinen RS5, Service neu, Winterreifen dabei."]},
            {"name": "PRICE", "values": ["90000"]}]}}}}})
        self.assertEqual(description.extract(page), "Verkaufe meinen RS5, Service neu, Winterreifen dabei.")

    def test_inline_config_and_longest(self):
        page = ('<meta property="og:description" content="Audi RS5 te koop">'
                '<script>window.__CONFIG__ = {"listing": {"description": "Zeer nette RS5, dealer onderhouden,\\nnieuwe banden."},'
                '"seo": {"description": "Kort"}};</script>')
        self.assertEqual(description.extract(page), "Zeer nette RS5, dealer onderhouden,\nnieuwe banden.")

    def test_marktplaats_html_block(self):
        # nel JSON c'è solo l'inizio del testo: quello completo è nell'HTML, sotto il titolo "Beschrijving"
        page = ('<script>{"description":"Audi RS5 Avant 640 PK | BTW-auto"}</script>'
                '<div class="Description-module-root" data-collapse-target="description"><h2 class="Description-module-title">Beschrijving</h2>'
                '<div class="Description-module-description"><div data-collapsable="description">Audi RS5 Avant 640 PK | BTW-auto<br /><br />'
                'Een unieke verschijning.</div></div></div>')
        self.assertEqual(description.extract(page), "Audi RS5 Avant 640 PK | BTW-auto\n\nEen unieke verschijning.")

    def test_finn_heading_section(self):
        page = ('<section class="pt-40"><h2 class="t3 mb-0">Beskrivelse</h2><div data-testid="expandable-section">'
                '<div class="whitespace-pre-wrap"><br><strong>Audi RS 5 Avant PHEV</strong><p>Noen biler tar deg fra A til B.</p>'
                '</div></div><button>Vis mer</button></section><meta property="og:description" content="Audi RS5 2026">')
        self.assertEqual(description.extract(page), "Audi RS 5 Avant PHEV\nNoen biler tar deg fra A til B.")

    def test_html_block_and_meta_fallback(self):
        page = '<section data-testid="object-description"><h2>Beskrivelse</h2><p>Bilen er i meget god stand og har full servicehistorikk.</p></section>'
        self.assertIn("full servicehistorikk", description.extract(page))
        self.assertEqual(description.extract('<meta name="description" content="Tesla Model S Plaid, 2024">'),
                         "Tesla Model S Plaid, 2024")
        self.assertEqual(description.extract("<html></html>"), "")

    def test_chunks(self):
        text = ("parola " * 600).strip() + "\n" + "riga corta"
        parts = description._chunks(text)
        self.assertTrue(all(len(p) <= description.CHUNK for p in parts))
        self.assertEqual(" ".join(" ".join(parts).split()), " ".join(text.split()))


class CacheTests(unittest.TestCase):
    LISTING = {"source": "autoscout24", "source_id": "abc", "url": "https://example.invalid/a"}

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.page = next_data({"listingDetails": {"description": "Scheckheftgepflegt und unfallfrei, Garantie."}})

    def test_fetch_translate_then_cached(self):
        http, tr = FakeHttp(self.page), FakeTranslator("de")
        d = description.get(self.conn, self.LISTING, http, tr)
        self.assertEqual((d["lang"], d["lang_name"], d["error"]), ("de", "tedesco", ""))
        self.assertEqual(d["translation"], "[it] Scheckheftgepflegt und unfallfrei, Garantie.")
        self.assertTrue(d["needs_translation"])
        # seconda apertura: niente richieste né al sito né al traduttore
        again = description.get(self.conn, self.LISTING, http, tr)
        self.assertEqual(again, d)
        self.assertEqual((http.calls, tr.calls), (1, 1))

    def test_italian_not_translated(self):
        d = description.get(self.conn, self.LISTING, FakeHttp(self.page), FakeTranslator("it"))
        self.assertEqual((d["lang"], d["translation"], d["needs_translation"]), ("it", None, False))

    def test_translation_retried_after_failure(self):
        http = FakeHttp(self.page)
        d = description.get(self.conn, self.LISTING, http, FakeTranslator(fail=True))
        self.assertEqual(d["error"], "translate")
        self.assertIn("Scheckheftgepflegt", d["text"])
        d = description.get(self.conn, self.LISTING, http, FakeTranslator("de"))
        self.assertEqual(d["error"], "")
        self.assertTrue(d["translation"].startswith("[it]"))
        self.assertEqual(http.calls, 1)               # il testo era già salvato

    def test_site_unreachable_not_cached(self):
        d = description.get(self.conn, self.LISTING, FakeHttp(None), FakeTranslator())
        self.assertEqual(d["error"], "fetch")
        d = description.get(self.conn, self.LISTING, FakeHttp(self.page), FakeTranslator())
        self.assertEqual(d["error"], "")

    def test_no_description(self):
        d = description.get(self.conn, self.LISTING, FakeHttp("<html></html>"), FakeTranslator())
        self.assertEqual((d["text"], d["error"], d["needs_translation"]), ("", "", False))


if __name__ == "__main__":
    unittest.main()
