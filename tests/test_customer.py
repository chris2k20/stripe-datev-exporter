import unittest

from stripe_datev import config, customer


class CustomerTest(unittest.TestCase):

  def test_resolve_customer_without_stripe_customer_uses_checkout_session_data(self):
    resolved = customer.resolveCustomer(
      None,
      checkout_session={
        "id": "cs_123",
        "customer_email": "guest@example.com",
        "customer_details": {
          "name": "Guest Customer",
          "email": "guest@example.com",
          "address": {
            "country": "DE",
            "city": "Berlin",
          },
        },
      },
      charge={
        "id": "ch_123",
        "billing_details": {
          "name": "Billing Name",
          "email": "billing@example.com",
        },
      },
    )

    self.assertTrue(resolved["synthetic"])
    self.assertEqual(resolved["id"], "guest_ch_123")
    self.assertEqual(customer.getCustomerName(resolved), "Guest Customer")
    self.assertEqual(customer.getAddressField(
      customer.getCustomerAddress(resolved), "country"), "DE")

  def test_get_accounting_props_for_synthetic_customer_uses_sammel_debitor(self):
    props = customer.getAccountingProps({
      "id": "guest_ch_123",
      "name": "Guest Customer",
      "address": {
        "country": "DE",
      },
      "metadata": {},
      "tax_exempt": "none",
      "tax_ids": {"data": []},
      "synthetic": True,
    })

    self.assertEqual(props["customer_account"],
                     str(config.accounts["sammel_debitor"]))
    self.assertEqual(props["revenue_account"],
                     str(config.accounts["revenue_german_vat"]))
