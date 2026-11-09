"""Do not turn unsupported numeric service dates into an annual period."""
import unittest
from datetime import datetime
from stripe_datev.dateparser import find_date_range


import io
from contextlib import redirect_stdout
from types import SimpleNamespace


class NumericServiceDateRegressionTests(unittest.TestCase):
    def test_separate_visit_dates_are_not_an_annual_service_period(self):
        description = (
            "Anfahrt zu den Terminen vor Ort am 17.08. und 20.10.2026 "
            "(Sankt Augustin und zurück, je 105,2 km à 0,50 €). "
            "Fahrzeit je ca. 1:50 Std. ohne Berechnung"
        )
        self.assertIsNone(find_date_range(description, ref_date=datetime(2026, 10, 22)))


    def test_invoice_fallback_is_explicit_and_creates_no_future_period(self):
        from stripe_datev.invoices import getLineItemRecognitionRange
        from stripe_datev import config
        created = 1792678236
        invoice = SimpleNamespace(created=created, id='in_regression')
        line = {'description': 'Anfahrt am 17.08. und 20.10.2026',
                'period': {'start': created, 'end': created}}
        log = io.StringIO()
        with redirect_stdout(log):
            start, end = getLineItemRecognitionRange(line, invoice)
        expected = datetime.fromtimestamp(created, config.accounting_tz)
        self.assertEqual((start, end), (expected, expected))
        self.assertIn('Warning: unknown period for line item -- in_regression', log.getvalue())

    def test_unsupported_numeric_date_variants_remain_unknown(self):
        for text in ['Leistung am 20.10.2026', 'Leistung 17.08. – 20.10.2026',
                     'Leistung 20.10.2026 und 17.08.2026', 'Leistung 31.02.2026',
                     'Leistung 20.10.2027', 'Leistung am 17.08.']:
            with self.subTest(text=text):
                self.assertIsNone(find_date_range(text, ref_date=datetime(2026, 10, 22)))


if __name__ == '__main__':
    unittest.main()
