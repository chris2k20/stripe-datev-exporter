from datetime import datetime, timezone
import sys
import stripe

from stripe_datev import config, output

customers_cached = {}


def retrieveCustomer(id):
  if isinstance(id, str):
    if id in customers_cached:
      return customers_cached[id]
    cus = stripe.Customer.retrieve(id, expand=["tax_ids"])
    customers_cached[cus.id] = cus
    return cus
  elif isinstance(id, stripe.Customer):
    customers_cached[id.id] = id
    return id
  else:
    raise Exception("Unexpected retrieveCustomer() argument: {}".format(id))


def resolveCustomer(id, invoice=None, checkout_session=None, charge=None):
  if id is not None:
    return retrieveCustomer(id)

  address = getCustomerAddress(
    None, invoice=invoice, checkout_session=checkout_session)
  billing_details = _get_attr_or_key(charge, "billing_details")
  if not address:
    address = _get_attr_or_key(billing_details, "address")

  customer_details = _get_attr_or_key(checkout_session, "customer_details")
  email = _get_attr_or_key(customer_details, "email") or _get_attr_or_key(
    checkout_session, "customer_email") or _get_attr_or_key(billing_details, "email")
  name = _get_attr_or_key(customer_details, "name") or _get_attr_or_key(
    billing_details, "name") or email
  source_id = _get_attr_or_key(charge, "id") or _get_attr_or_key(
    invoice, "id") or _get_attr_or_key(checkout_session, "id") or "guest"

  return {
    "id": "guest_{}".format(source_id),
    "name": name or "Guest {}".format(source_id),
    "email": email,
    "address": address,
    "metadata": {},
    "tax_exempt": _get_attr_or_key(invoice, "customer_tax_exempt") or "none",
    "tax_ids": {"data": []},
    "synthetic": True,
  }


def getCustomerName(customer):
  if customer is None:
    return ""
  if _get_attr_or_key(customer, "deleted"):
    return _get_attr_or_key(customer, "id") or ""

  description = _get_attr_or_key(customer, "description")
  if description is not None:
    return description

  return _get_attr_or_key(customer, "name") or _get_attr_or_key(customer, "email") or _get_attr_or_key(customer, "id") or ""


tax_ids_cached = {}


def getCustomerTaxId(customer):
  if customer is None:
    return None

  tax_ids = _get_attr_or_key(customer, "tax_ids")
  if tax_ids is not None:
    tax_id_data = _get_attr_or_key(tax_ids, "data") or []
    tax_id = next((tax_id for tax_id in tax_id_data if _get_attr_or_key(tax_id, "type") ==
                  "eu_vat" and _get_attr_or_key(_get_attr_or_key(tax_id, "verification"), "status") in [None, "verified"]), None)
    tax_id = _get_attr_or_key(tax_id, "value") if tax_id is not None else None
  else:
    customer_id = _get_attr_or_key(customer, "id")
    if not customer_id or _get_attr_or_key(customer, "synthetic"):
      return None
    if customer_id in tax_ids_cached:
      return tax_ids_cached[customer_id]
    ids = stripe.Customer.list_tax_ids(customer_id, limit=10).data
    tax_id = ids[0].value if len(ids) > 0 else None
    tax_ids_cached[customer_id] = tax_id
  return tax_id


country_codes_eu = [
  "AT",
  "BE",
  "BG",
  "CY",
  "CZ",
  "DK",
  "EE",
  "FI",
  "FR",
  "DE",
  "GR",
  "HU",
  "IE",
  "IT",
  "LV",
  "LT",
  "LU",
  "MT",
  "NL",
  "PL",
  "PT",
  "RO",
  "SK",
  "SI",
  "ES",
  "SE",
]


def _get_attr_or_key(obj, key):
  if obj is None:
    return None
  if isinstance(obj, dict):
    return obj.get(key, None)
  value = getattr(obj, key, None)
  if value is not None:
    return value
  if hasattr(obj, "get"):
    try:
      return obj.get(key, None)
    except TypeError:
      try:
        return obj.get(key)
      except Exception:
        return None
  return None


def getCustomerAddress(customer, invoice=None, checkout_session=None):
  address = _get_attr_or_key(customer, "address")
  if not address:
    shipping = _get_attr_or_key(customer, "shipping")
    address = _get_attr_or_key(shipping, "address")
  if not address and invoice is not None:
    address = _get_attr_or_key(invoice, "customer_address")
    if not address:
      customer_shipping = _get_attr_or_key(invoice, "customer_shipping")
      address = _get_attr_or_key(customer_shipping, "address")
    if not address:
      shipping = _get_attr_or_key(invoice, "shipping")
      address = _get_attr_or_key(shipping, "address")
  if not address and checkout_session is not None:
    customer_details = _get_attr_or_key(checkout_session, "customer_details")
    address = _get_attr_or_key(customer_details, "address")
    if not address:
      shipping_details = _get_attr_or_key(checkout_session, "shipping_details")
      address = _get_attr_or_key(shipping_details, "address")
  return address


def getAddressField(address, field):
  return _get_attr_or_key(address, field)


def getAccountingProps(customer, invoice=None, checkout_session=None):
  props = {
    "vat_region": "World",
  }

  metadata = _get_attr_or_key(customer, "metadata") or {}
  account_number = _get_attr_or_key(metadata, "accountNumber")
  is_synthetic = bool(_get_attr_or_key(customer, "synthetic"))

  if (invoice is None or datetime.fromtimestamp(invoice.status_transitions.finalized_at, timezone.utc) >= datetime(2022, 1, 1, 0, 0).astimezone(config.accounting_tz)):
    if not account_number and not is_synthetic:
      raise Exception("Expected 'accountNumber' in metadata")
    props["customer_account"] = account_number or str(
      config.accounts["sammel_debitor"])
  else:
    props["customer_account"] = str(config.accounts["sammel_debitor"])

  address = getCustomerAddress(
    customer, invoice=invoice, checkout_session=checkout_session)
  country = getAddressField(address, "country")

  invoice_tax = None
  invoice_total = None
  if invoice is not None:
    invoice_tax = invoice.get("tax", None)
    invoice_total = invoice.get("total", None)
  elif checkout_session is not None:
    invoice_tax = checkout_session.get(
      "total_details", {}).get("amount_tax", None)
    invoice_total = checkout_session.get("amount_total", None)

  # use tax status at time of invoice creation
  if invoice is not None and "customer_tax_exempt" in invoice and not invoice["automatic_tax"]["enabled"]:
    tax_exempt = invoice["customer_tax_exempt"]
  else:
    tax_exempt = _get_attr_or_key(customer, "tax_exempt")

  vat_id = getCustomerTaxId(customer)
  if not country and vat_id:
    country = vat_id[:2]
    print("Warning: customer without address, using VAT ID prefix as country",
          customer.id)
  if not country:
    print("Warning: customer without address", customer.id)

  props = dict(props, **{
    "country": country,
    "vat_id": vat_id,
    "tax_exempt": tax_exempt,
    "invoice_tax": invoice_tax,
    "datev_tax_key_invoice": "",
    "datev_tax_key_payment": "",
  })

  if country == "DE":
    if invoice is not None and invoice_tax is None:
      print("Warning: no tax in DE invoice", invoice["id"])
    if tax_exempt != "none":
      print("Warning: DE customer tax status is", tax_exempt, customer.id)
    props["revenue_account"] = str(config.accounts["revenue_german_vat"])
    props["datev_tax_key_invoice"] = str(config.accounts["datev_tax_key_germany_invoice"])
    props["datev_tax_key_payment"] = str(config.accounts["datev_tax_key_germany_payment"])
    props["vat_region"] = "DE"
    return props

  if country in country_codes_eu:
    props["vat_region"] = "EU"

  if tax_exempt == "reverse" or tax_exempt == "exempt" or invoice_tax is None or (invoice_tax == 0 and invoice_total is not None and invoice_total > 0):
    if invoice is not None:
      if tax_exempt == "exempt":
        print("Warning: tax exempt customer, treating like 'reverse'", customer.id)
        props["tax_exempt"] = "reverse"
      if tax_exempt == "none":
        print("Warning: taxable customer without tax on invoice, treating like 'reverse'",
              customer.id, invoice.get("id", "n/a") if invoice is not None else "n/a")
        props["tax_exempt"] = "reverse"
      if not (invoice_tax is None or invoice_tax == 0):
        print("Warning: tax on invoice of reverse charge customer",
              invoice.get("id", "n/a") if invoice is not None else "n/a")
      if country in country_codes_eu and vat_id is None:
        print("Warning: EU reverse charge customer without VAT ID", customer.id)

    if country in country_codes_eu and vat_id is not None:
      props["revenue_account"] = str(
        config.accounts["revenue_reverse_charge_eu"])
    else:
      props["revenue_account"] = str(
        config.accounts["account_reverse_charge_world"])

    props["datev_tax_key_invoice"] = str(
      config.accounts["datev_tax_key_reverse_invoice"])
    props["datev_tax_key_payment"] = str(
      config.accounts["datev_tax_key_reverse_payment"])
    return props

  elif tax_exempt == "none":
    # print("Warning: configure taxation for", country, "customer", customer.id)
    # Unter Bagtellgrenze MOSS
    pass

  else:
    print("Warning: unknown tax status for customer", customer.id)

  props["revenue_account"] = str(config.accounts["revenue_german_vat"])
  return props

def validate_customers():
  customer_count = 0
  for customer in stripe.Customer.list(expand=["data.tax_ids"]).auto_paging_iter():
    if not customer.address:
      print("Warning: customer without address", customer.id)

    if customer.tax_exempt == "exempt":
      print("Warning: exempt customer", customer.id)

    getAccountingProps(customer)

    customer_count += 1

  print("Validated {} customers".format(customer_count))


def fill_account_numbers():
  highest_account_number = None
  fill_customers = []
  for customer in stripe.Customer.list().auto_paging_iter():
    if "accountNumber" in customer.metadata:
      highest_account_number = int(customer.metadata["accountNumber"])
      break
    fill_customers.append(customer)

  if highest_account_number is None:
    highest_account_number = 10100 - 1

  print("{} customers without account number, highest number is {}".format(
    len(fill_customers), highest_account_number))

  for customer in reversed(fill_customers):
    # print(customer.id, customer.metadata)

    highest_account_number += 1
    metadata_new = {
      "accountNumber": str(highest_account_number)
    }

    for old_key in ["subscribedNetPrice", "subscribedProduct", "subscribedProductName", "subscribedTaxRate", "subscribedTotal"]:
      if old_key in customer.metadata:
        metadata_new[old_key] = ""

    # print("Update", metadata_new)
    stripe.Customer.modify(customer.id, metadata=metadata_new)

    print(customer.id, highest_account_number)


def list_account_numbers(file_path):
  customer_it = stripe.Customer.list(
    expand=["data.tax_ids"]).auto_paging_iter()
  if file_path is None:
    output.printAccounts(sys.stdout, customer_it)
  else:
    with open(file_path, "w", encoding="latin-1", errors="replace") as fp:
      output.printAccounts(fp, customer_it)
