import unittest
import stripe
from stripe_datev import customer


class MissingCustomerNameTests(unittest.TestCase):
    def test_missing_name_is_empty_not_an_invented_identity(self):
        obj = stripe.Customer.construct_from({'id': 'cus_nameless', 'name': None,
            'description': None, 'deleted': False}, None)
        self.assertEqual(customer.getCustomerName(obj), '')


if __name__ == '__main__':
    unittest.main()
