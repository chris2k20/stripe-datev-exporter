import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest


class LocalAccountMappingTest(unittest.TestCase):

  def test_external_mapping_path_can_be_selected_without_stripe_write(self):
    with tempfile.TemporaryDirectory() as tmp:
      mapping = Path(tmp) / "debitorenkonten.json"
      mapping.write_text(json.dumps({"cus_test": "10999"}), encoding="utf-8")
      previous = os.environ.get("STRIPE_DATEV_LOCAL_ACCOUNT_NUMBERS_FILE")
      os.environ["STRIPE_DATEV_LOCAL_ACCOUNT_NUMBERS_FILE"] = str(mapping)
      try:
        from stripe_datev import customer
        importlib.reload(customer)
        self.assertEqual(Path(customer._LOCAL_ACCOUNT_NUMBERS_FILE), mapping)
        self.assertEqual(customer._load_local_account_numbers(), {"cus_test": "10999"})
      finally:
        if previous is None:
          os.environ.pop("STRIPE_DATEV_LOCAL_ACCOUNT_NUMBERS_FILE", None)
        else:
          os.environ["STRIPE_DATEV_LOCAL_ACCOUNT_NUMBERS_FILE"] = previous
        importlib.reload(customer)


if __name__ == "__main__":
  unittest.main()
