import stripe
import decimal
from datetime import datetime, timezone
from . import customer, output, config, references, csv


def listBalanceTransactions(fromTime, toTime):
  return stripe.BalanceTransaction.list(
    created={
        "lt": int(toTime.timestamp()),
        "gte": int(fromTime.timestamp()),
      },
      expand=["data.source", "data.source.customer",
              "data.source.customer.tax_ids", "data.source.invoice", "data.source.charge",
              "data.source.charge.customer", "data.source.charge.invoice",
              "data.source.source_transaction", "data.source.source_transaction.invoice",
              "data.source.destination", "data.source.destination_payment"]
  ).auto_paging_iter()


def createAccountingRecords(balance_transactions):
  records = []
  for tx in balance_transactions:
    created = datetime.fromtimestamp(
      tx.created, timezone.utc).astimezone(config.accounting_tz)
    amount = decimal.Decimal(tx.amount) / 100
    fee = decimal.Decimal(tx.fee) / 100

    if tx["reporting_category"] == "charge" or tx["reporting_category"] == "charge_failure":
      charge = tx.source
      cus = customer.resolveCustomer(charge.customer, charge=charge)
      accounting_props = customer.getAccountingProps(cus)
      order_reference = references.get_order_reference(charge=charge)
      if charge.invoice:
        number = charge.invoice.number
      else:
        number = charge.receipt_number
      fee_desc = tx.fee_details[0].description

      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(abs(amount)),
        "Soll/Haben-Kennzeichen": "S" if amount >= 0 else "H",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["bank"]),
        "Gegenkonto (ohne BU-Schlüssel)": accounting_props["customer_account"],
        "BU-Schlüssel": accounting_props["datev_tax_key_payment"],
        "Buchungstext": "Stripe Payment ({})".format(charge.id),
        "Belegfeld 1": number,
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=charge.id,
        order_reference=order_reference,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(abs(fee)),
        "Soll/Haben-Kennzeichen": "S" if fee >= 0 else "H",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["stripe_fees"]),
        "Gegenkonto (ohne BU-Schlüssel)": str(config.accounts["bank"]),
        "Buchungstext": "{} ({})".format(fee_desc or "Stripe Fee", charge.id),
        # Stripe invoices fees within the bounds of one UTC month,
        # this makes it easier to associate a fee with a montly invoice
        "Belegfeld 1": created.astimezone(timezone.utc).strftime("%Y-%m"),
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=charge.id,
        order_reference=order_reference,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

    elif tx["reporting_category"] == "payout":
      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(-amount),
        "Soll/Haben-Kennzeichen": "S",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["transit"]),
        "Gegenkonto (ohne BU-Schlüssel)": str(config.accounts["bank"]),
        "Buchungstext": "Stripe Payout {}".format(tx.source.id),
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=tx.source.id,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

    elif tx["reporting_category"] == "refund":
      charge = tx.source.charge
      cus = customer.resolveCustomer(charge.customer, charge=charge)
      accounting_props = customer.getAccountingProps(cus)
      order_reference = references.get_order_reference(charge=charge)
      if charge.invoice:
        number = charge.invoice.number
      else:
        number = charge.receipt_number

      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(-amount),
        "Soll/Haben-Kennzeichen": "H",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["bank"]),
        "Gegenkonto (ohne BU-Schlüssel)": accounting_props["customer_account"],
        "Buchungstext": "Stripe Payment Refund ({})".format(charge.id),
        "Belegfeld 1": number,
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=charge.id,
        order_reference=order_reference,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

    elif tx["reporting_category"] == "contribution":
      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(-amount),
        "Soll/Haben-Kennzeichen": "S",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["contributions"]),
        "Gegenkonto (ohne BU-Schlüssel)": str(config.accounts["bank"]),
        "Buchungstext": "Stripe {} {}".format(tx["description"] or "Contribution", tx["id"]),
        "Belegfeld 1": created.astimezone(timezone.utc).strftime("%Y-%m"),
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=tx.id,
      )

    elif tx["reporting_category"] == "transfer":
      transfer = tx.source
      net_amount = transfer.amount - \
          ((transfer.source_transaction.application_fee_amount if transfer.source_transaction else None) or 0)
      invoice = transfer.source_transaction.get(
        "invoice", None) if transfer.source_transaction else None
      invoiceNumber = invoice.number if invoice else None

      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(decimal.Decimal(net_amount) / 100),
        "Soll/Haben-Kennzeichen": "S",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["external_services"]),
        "Gegenkonto (ohne BU-Schlüssel)": transfer["destination"]["metadata"]["accountNumber"],
        "Buchungstext": "Fremdleistung {} anteilig".format(invoiceNumber or transfer.id),
        "Belegfeld 1": transfer.id,
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=transfer.id,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(decimal.Decimal(net_amount) / 100),
        "Soll/Haben-Kennzeichen": "S",
        "WKZ Umsatz": "EUR",
        "Konto": transfer["destination"]["metadata"]["accountNumber"],
        "Gegenkonto (ohne BU-Schlüssel)": str(config.accounts["bank"]),
        "Buchungstext": "Fremdleistung {} anteilig".format(invoiceNumber or transfer.id),
        "Belegfeld 1": transfer.id,
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=transfer.id,
        extra_label="stripe_balance_txn_id",
        extra_value=tx.id,
      )

    elif tx["reporting_category"] == "fee":
      records.append({
        "date": created,
        "Umsatz (ohne Soll/Haben-Kz)": output.formatDecimal(-amount),
        "Soll/Haben-Kennzeichen": "S",
        "WKZ Umsatz": "EUR",
        "Konto": str(config.accounts["stripe_fees"]),
        "Gegenkonto (ohne BU-Schlüssel)": str(config.accounts["bank"]),
        "Buchungstext": tx.description or "Stripe Fee",
        # Stripe invoices fees within the bounds of one UTC month,
        # this makes it easier to associate a fee with a montly invoice
        "Belegfeld 1": created.astimezone(timezone.utc).strftime("%Y-%m"),
      })
      references.set_record_identifiers(
        records[-1],
        stripe_reference=tx.id,
      )

    elif tx["reporting_category"] == "payout_minimum_balance_hold" or tx["reporting_category"] == "payout_minimum_balance_release":
      # Not relevant for accounting on the company side
      pass

    else:
      print(
        "Warning: unsupported balance transaction type:", tx["type"], "reporting_category:", tx["reporting_category"], tx["id"])

  return records


def to_fees_csv(balance_transactions):
  rows = [[
    "date",
    "balance_transaction_id",
    "source_id",
    "source_type",
    "reporting_category",
    "fee_type",
    "description",
    "fee_amount_eur",
    "currency",
    "invoice_number",
    "stripe_reference",
    "order_reference",
  ]]

  for tx in balance_transactions:
    created = datetime.fromtimestamp(
      tx.created, timezone.utc).astimezone(config.accounting_tz)

    if tx.fee and len(tx.fee_details) > 0:
      charge = tx.source if tx["reporting_category"] in ["charge", "charge_failure"] else tx.source.charge if tx["reporting_category"] == "refund" and tx.source and tx.source.charge else None
      invoice_number = charge.invoice.number if charge and charge.invoice else None
      stripe_reference = charge.id if charge else tx.id
      order_reference = references.get_order_reference(
        charge=charge) if charge else None

      for fee_detail in tx.fee_details:
        rows.append([
          created.strftime("%Y-%m-%d"),
          tx.id,
          charge.id if charge else "",
          charge.object if charge else "",
          tx["reporting_category"],
          fee_detail.type or "",
          fee_detail.description or tx.description or "",
          format(decimal.Decimal(fee_detail.amount) / 100, ".2f"),
          fee_detail.currency.upper() if fee_detail.currency else tx.currency.upper(),
          invoice_number,
          stripe_reference,
          order_reference,
        ])

    elif tx["reporting_category"] in ["fee", "contribution"]:
      source = tx.source
      rows.append([
        created.strftime("%Y-%m-%d"),
        tx.id,
        source.id if source else "",
        source.object if source else "",
        tx["reporting_category"],
        "",
        tx.description or "",
        format(abs(decimal.Decimal(tx.amount) / 100), ".2f"),
        tx.currency.upper(),
        "",
        tx.id,
        "",
      ])

  return csv.lines_to_csv(rows)


def extractCharges(balance_transactions):
  charges = []
  for tx in balance_transactions:
    if tx["type"] == "charge" or tx["type"] == "payment":
      charges.append(tx.source)

  return charges
