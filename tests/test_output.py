import datetime
import io
import unittest

from stripe_datev import config, output


class OutputTest(unittest.TestCase):

  def test_print_records_treats_none_values_as_empty_strings(self):
    buffer = io.StringIO()

    output.printRecords(buffer, [{
      "date": config.accounting_tz.localize(datetime.datetime(2026, 3, 31)),
      "Umsatz (ohne Soll/Haben-Kz)": "10,00",
      "Soll/Haben-Kennzeichen": "S",
      "WKZ Umsatz": "EUR",
      "Konto": "1201",
      "Gegenkonto (ohne BU-Schlüssel)": "10001",
      "Belegfeld 1": None,
      "Buchungstext": "Testbuchung",
    }], bezeichung="Test")

    self.assertIn("Testbuchung", buffer.getvalue())
