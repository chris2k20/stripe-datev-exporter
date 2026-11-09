"""Credit-note timing regression: real revenue/DATEV functions, only remote reads mocked."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from decimal import Decimal
import stripe
from stripe_datev import invoices, config


def obj(kind, data):
    return kind.construct_from(data, None)


def note(effective_at: int | None = 1787752718):
    return obj(stripe.CreditNote, {'id': 'cn_test', 'object': 'credit_note',
        'status': 'issued', 'number': 'TEST-0001-CN-01', 'currency': 'eur',
        'created': 1794257369, 'effective_at': effective_at,
        'total': 3927, 'post_payment_amount': 3927, 'invoice': 'in_test'})


def invoice():
    return obj(stripe.Invoice, {'id': 'in_test', 'object': 'invoice',
        'number': 'TEST-0001', 'status': 'paid', 'metadata': {},
        'created': 1787752718, 'total': 3927, 'tax': 627, 'currency': 'eur',
        'customer': 'cus_test', 'post_payment_credit_notes_amount': 3927,
        'pre_payment_credit_notes_amount': 0, 'total_tax_amounts': [{'tax_rate': 'txr_test'}],
        'status_transitions': {'finalized_at': 1787752718},
        'lines': {'object': 'list', 'has_more': False, 'data': [
            {'id': 'il_test', 'object': 'line_item', 'description': 'Monthly service',
             'amount': 3300, 'discount_amounts': [],
             'tax_amounts': [{'amount': 627, 'inclusive': False}],
             'period': {'start': 1787752717, 'end': 1790431117}}]}})


def page(notes):
    return obj(stripe.ListObject, {'object': 'list', 'data': notes, 'has_more': False})


class CreditNoteDateTests(unittest.TestCase):
    def revenue(self, credit, *, charges=None, notes=None, invo=None):
        source_invoice = invoice() if invo is None else invo
        cus = obj(stripe.Customer, {'id': 'cus_test', 'name': 'Test Company',
            'description': None, 'address': {'country': 'DE'}})
        props = {'customer_account': '10226', 'revenue_account': '8400',
            'datev_tax_key_invoice': '', 'vat_id': None}
        with patch.object(invoices.stripe.CreditNote, 'list', return_value=page([credit] if notes is None else notes)), \
             patch.object(invoices.stripe.Charge, 'list', return_value=page([] if charges is None else charges)), \
             patch.object(invoices, 'retrieveInvoice', return_value=source_invoice), \
             patch.object(invoices.customer, 'retrieveCustomer', return_value=cus), \
             patch.object(invoices.customer, 'getAccountingProps', return_value=props), \
             patch.object(invoices, 'retrieveTaxRate', return_value={'percentage': 19}):
            return invoices.createRevenueItems([source_invoice])[0]

    def test_effective_at_posts_credit_in_august_not_creation_month(self):
        item = self.revenue(note())
        self.assertEqual(item['credited_at'].date().isoformat(), '2026-08-26')
        records = invoices.createAccountingRecords(item)
        credit_rows = [r for r in records if r['Konto'] == '10226' and
                       r['Soll/Haben-Kennzeichen'] == 'H']
        self.assertEqual(len(credit_rows), 1)
        self.assertEqual(credit_rows[0]['date'].date().isoformat(), '2026-08-26')
        self.assertFalse(any(r['date'].month == 11 for r in records))


    def test_full_refund_without_credit_note_blocks_before_revenue(self):
        inv = invoice()
        inv.post_payment_credit_notes_amount = 0
        ch = obj(stripe.Charge, {'id': 'ch_test', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 3927, 'refunded': True})
        with self.assertRaisesRegex(ValueError,
                'Rechnung TEST-0001 erstattet, aber keine Gutschrift, bitte in Stripe anlegen'):
            self.revenue(note(), charges=[ch], notes=[], invo=inv)


    def test_credit_posting_references_the_actual_credit_note_document(self):
        item = self.revenue(note())
        credit_rows = [r for r in invoices.createAccountingRecords(item)
                       if r['Konto'] == '10226' and r['Soll/Haben-Kennzeichen'] == 'H']
        self.assertEqual(credit_rows[0]['Belegfeld 1'], 'TEST-0001-CN-01')

    def test_created_is_fallback_when_effective_at_is_null_or_absent(self):
        for absent in (False, True):
            cn = note(None)
            if absent:
                del cn['effective_at']
            with self.subTest(absent=absent):
                self.assertEqual(self.revenue(cn)['credited_at'].date().isoformat(), '2026-11-09')

    def test_explicit_zero_effective_timestamp_is_not_treated_as_missing(self):
        item = self.revenue(note(0))
        self.assertEqual(item['credited_at'].timestamp(), 0)

    def test_partial_refund_without_credit_note_also_blocks(self):
        inv = invoice()
        inv.post_payment_credit_notes_amount = 0
        ch = obj(stripe.Charge, {'id': 'ch_partial', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 1000, 'refunded': False})
        with self.assertRaisesRegex(ValueError, 'erstattet, aber keine Gutschrift'):
            self.revenue(note(), charges=[ch], notes=[], invo=inv)

    def test_void_credit_note_does_not_cover_refund(self):
        cn = note()
        cn.status = 'void'
        ch = obj(stripe.Charge, {'id': 'ch_test', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 3927, 'refunded': True})
        with self.assertRaisesRegex(ValueError, 'erstattet, aber keine Gutschrift'):
            self.revenue(cn, charges=[ch])

    def test_insufficient_credit_note_blocks(self):
        cn = note()
        cn.post_payment_amount = 500
        ch = obj(stripe.Charge, {'id': 'ch_test', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 1000, 'refunded': False})
        with self.assertRaisesRegex(ValueError, 'deckt die Erstattung nicht'):
            self.revenue(cn, charges=[ch])

    def test_multiple_refunded_charges_are_checked_once_per_invoice(self):
        cn = note()
        cn.post_payment_amount = 1000
        charges = [obj(stripe.Charge, {'id': 'ch_'+str(n), 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 800, 'refunded': False}) for n in (1, 2)]
        with self.assertRaisesRegex(ValueError, 'deckt die Erstattung nicht'):
            self.revenue(cn, charges=charges)

    def test_fully_documented_refund_does_not_block(self):
        ch = obj(stripe.Charge, {'id': 'ch_test', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 3927, 'refunded': True})
        self.assertEqual(self.revenue(note(), charges=[ch])['credited_amount'], Decimal('39.27'))


    def test_void_and_issued_notes_select_only_issued_document(self):
        active, void = note(), note()
        void.status = 'void'
        void.id = 'cn_void'
        self.assertEqual(self.revenue(active, notes=[void, active])['credited_amount'], Decimal('39.27'))

    def test_other_currency_credit_note_does_not_cover_refund(self):
        cn = note()
        cn.currency = 'usd'
        ch = obj(stripe.Charge, {'id': 'ch_test', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 3927, 'refunded': True})
        with self.assertRaisesRegex(ValueError, 'erstattet, aber keine Gutschrift'):
            self.revenue(cn, charges=[ch])

    def test_guard_checks_older_refunds_even_when_current_month_has_no_invoices(self):
        ch = obj(stripe.Charge, {'id': 'ch_old', 'invoice': 'in_test',
            'currency': 'eur', 'amount_refunded': 3927, 'refunded': True})
        with patch.object(invoices.stripe.Charge, 'list', return_value=page([ch])), \
             patch.object(invoices.stripe.CreditNote, 'list', return_value=page([])), \
             patch.object(invoices, 'retrieveInvoice', return_value=invoice()):
            with self.assertRaisesRegex(ValueError, 'erstattet, aber keine Gutschrift'):
                invoices.createRevenueItems([])


if __name__ == '__main__':
    unittest.main()
