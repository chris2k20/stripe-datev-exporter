import unittest

from stripe_datev import references


class ReferencesTest(unittest.TestCase):

  def test_prefers_checkout_client_reference_id_for_order_reference(self):
    ref = references.get_order_reference(
      charge={"metadata": {"order_id": "charge-1"}},
      checkout_session={
        "client_reference_id": "order-42",
        "metadata": {"order_id": "session-1"},
      },
    )

    self.assertEqual(ref, "order-42")

  def test_sets_record_identifier_fields(self):
    record = {}

    references.set_record_identifiers(
      record,
      stripe_reference="ch_123",
      order_reference="order-42",
      extra_label="stripe_balance_txn_id",
      extra_value="txn_123",
    )

    self.assertEqual(record["Belegfeld 2"], "ch_123")
    self.assertEqual(record["Auftragsnummer"], "order-42")
    self.assertEqual(record["Zusatzinformation - Art 1"],
                     "stripe_balance_txn_id")
    self.assertEqual(record["Zusatzinformation- Inhalt 1"], "txn_123")
