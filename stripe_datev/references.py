import stripe


ORDER_REFERENCE_KEYS = [
  "order_id",
  "orderId",
  "order_number",
  "orderNumber",
  "order_no",
  "orderNo",
  "bestellnummer",
  "bestellung",
  "geschaeftsvorgangsnummer",
  "geschäftsvorgangsnummer",
  "external_order_id",
]

checkout_sessions_by_payment_intent = {}
payment_intents_cached = {}


def get_attr_or_key(obj, key):
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


def get_metadata(obj):
  metadata = get_attr_or_key(obj, "metadata")
  if metadata is None:
    return {}
  if isinstance(metadata, dict):
    return metadata
  return dict(metadata)


def clean_string(value):
  if value is None:
    return None
  value = str(value).strip()
  return value or None


def get_payment_intent_cached(payment_intent):
  payment_intent_id = clean_string(get_attr_or_key(payment_intent, "id") or payment_intent)
  if not payment_intent_id:
    return None
  if payment_intent_id in payment_intents_cached:
    return payment_intents_cached[payment_intent_id]
  payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
  payment_intents_cached[payment_intent_id] = payment_intent
  return payment_intent


def get_checkout_session_via_payment_intent_cached(payment_intent):
  payment_intent_id = clean_string(get_attr_or_key(payment_intent, "id") or payment_intent)
  if not payment_intent_id:
    return None
  if payment_intent_id in checkout_sessions_by_payment_intent:
    return checkout_sessions_by_payment_intent[payment_intent_id]

  sessions = stripe.checkout.Session.list(
    payment_intent=payment_intent_id, expand=["data.line_items"]).data
  session = sessions[0] if len(sessions) > 0 else None
  checkout_sessions_by_payment_intent[payment_intent_id] = session
  return session


def get_order_reference(charge=None, invoice=None, payment_intent=None, checkout_session=None):
  payment_intent_id = clean_string(
    get_attr_or_key(payment_intent, "id")
    or payment_intent
    or get_attr_or_key(charge, "payment_intent")
    or get_attr_or_key(invoice, "payment_intent")
  )

  if checkout_session is None and payment_intent_id:
    checkout_session = get_checkout_session_via_payment_intent_cached(
      payment_intent_id)

  checkout_ref = clean_string(
    get_attr_or_key(checkout_session, "client_reference_id"))
  if checkout_ref:
    return checkout_ref

  for obj in [checkout_session, charge, invoice]:
    metadata = get_metadata(obj)
    for key in ORDER_REFERENCE_KEYS:
      reference = clean_string(metadata.get(key))
      if reference:
        return reference

  if payment_intent_id:
    payment_intent = get_payment_intent_cached(payment_intent_id)
    metadata = get_metadata(payment_intent)
    for key in ORDER_REFERENCE_KEYS:
      reference = clean_string(metadata.get(key))
      if reference:
        return reference

  return None


def set_record_identifiers(record, stripe_reference=None, order_reference=None, extra_label=None, extra_value=None):
  stripe_reference = clean_string(stripe_reference)
  order_reference = clean_string(order_reference)
  extra_label = clean_string(extra_label)
  extra_value = clean_string(extra_value)

  if stripe_reference:
    record["Belegfeld 2"] = stripe_reference
  if order_reference:
    record["Auftragsnummer"] = order_reference
  if extra_label and extra_value:
    record["Zusatzinformation - Art 1"] = extra_label
    record["Zusatzinformation- Inhalt 1"] = extra_value
